#!/usr/bin/env python
# -*- coding: UTF-8 -*-
# author: mwenbao@gmail.com
# date: 2015.06.03 - 2015.06.09
# desc: Move old gmails tagged with given labels to trash.
#       Old gmails are defined by the function `find_expired_email'
# depends: python2.7
#          gmail python api: pip install --upgrade google-api-python-client

import os
import sys
import argparse
import logging
import time
from datetime import datetime
import email.utils

from apiclient.discovery import build
from apiclient import errors
from apiclient.http import BatchHttpRequest
from httplib2 import Http
import oauth2client
from oauth2client import client
from oauth2client import tools

LOGGING_FORMAT = '[%(levelname)s] [%(asctime)-15s] %(message)s'
TRASH_LABEL = 'TRASH'
SCOPES = 'https://www.googleapis.com/auth/gmail.modify'
APPLICATION_NAME = 'gmail-cleanup'


class MyEmail(object):
    def __init__(self, mid='', subject=u'', sender='', dt=None):
        self.mid = mid
        self.subject = subject
        self.sender = sender
        self.datetime = dt  # represented in the email date's tz

    def __str__(self):
        return '{} {} {}'.format(self.datetime, self.mid, self.subject)

    def __repr__(self):
        return self.__str__()

    def _parse_datetime(self, datestr):
        '''Parse email's date.
        '''
        datetuple = email.utils.parsedate(datestr)
        if datetuple is None:
            logging.error('Failed to parse email date: %s', datestr)
            return False
        self.datetime = datetime.fromtimestamp(time.mktime(datetuple))
        return True

    def update(self, msg):
        '''Set mail id, subject and datetime.
        '''
        self.mid = msg['id']
        datestr = u''
        for header in msg['payload']['headers']:
            if self.subject and self.sender and datestr:
                break
            if header['name'] == u'Subject':
                self.subject = header['value']
            if header['name'] == u'From':
                self.sender = header['value']
            if header['name'] == u'Date':
                datestr = header['value']
        if not self.subject:
            logging.error("No subject found in email %s's headers", self.mid)
            return False
        if not self.sender:
            logging.error("No sender address in email %s's headers", self.mid)
            return False
        if not datestr:
            logging.error("No date found in email %s's headers", self.mid)
            return False
        if not self._parse_datetime(datestr):
            return False
        return True

def parse_cmd_args():
    parser = argparse.ArgumentParser(parents=[tools.argparser])
    parser.add_argument('--logging_file', default='',
        help='Location of the log file.')
    parser.add_argument('--secret_file', default='client_secret.json',
        help='Location of the secret file.')
    parser.add_argument('--sender_sensitive', action='store_true',
        help="Treat different senders' emails within the same label separately.")
    parser.add_argument('label', nargs='+', help='Gmail labels')
    return parser.parse_args()

def get_credentials(flags):
    """Gets valid user credentials from storage.

    If nothing has been stored, or if the stored credentials are invalid,
    the OAuth2 flow is completed to obtain the new credentials.

    Returns:
        Credentials, the obtained credential.
    """
    home_dir = os.path.expanduser('~')
    credential_dir = os.path.join(home_dir, '.google-credentials')
    if not os.path.exists(credential_dir):
        os.makedirs(credential_dir)
    credential_path = os.path.join(credential_dir,
                                   'gmail-cleanup.json')

    store = oauth2client.file.Storage(credential_path)
    credentials = store.get()
    if not credentials or credentials.invalid:
        flow = client.flow_from_clientsecrets(flags.secret_file, SCOPES)
        flow.user_agent = APPLICATION_NAME
        if flags:
            credentials = tools.run_flow(flow, store, flags)
        else: # Needed only for compatability with Python 2.6
            credentials = tools.run(flow, store)
        print('Storing credentials to ' + credential_path)
    return credentials

def lookup_label_id(service, labels):
    """Lookup gmail label id according to their names.
    """
    if not labels:
        return

    labelids = {}  # label name => label id
    results = service.users().labels().list(userId='me').execute()
    mylabs = results.get('labels', [])
    for lab in mylabs:
        if len(labelids) == len(labels):
            break
        if lab['name'] in labels:
            labelids[lab['name']] = lab['id']
    return labelids

def lookup_email_id(service, labelids):
    '''Lookup gmail message id according to their label(id)s.
    '''
    if not labelids:
        return

    results = service.users().messages().list(userId='me', labelIds=labelids).execute()
    return results.get('messages', [])

def find_expired_email(mails):
    """Find all the emails which should be moved to gmail trash.

    Reserved mails:
        1. (7) last 7 mails.
        2. (*) sent in the last months(one mail per month).
        3. (*) sent in the last years(one mail per year).
    """
    if not mails:
        return []

    # get a copy of mails sort by datetime in desc order first
    mails_date = sorted(mails, key=lambda m:m.datetime, reverse=True)
    last7mails = mails_date[:7]
    bmail = last7mails[-1]
    # year|month|date => mail.mid
    reserv_mails = { m.datetime:m.mid for m in last7mails }
    def reserv_m(key, mail):
        if not reserv_mails.has_key(key):
            reserv_mails[key] = mail.mid

    for mail in mails_date[7:]:
        if mail.datetime.year < bmail.datetime.year:
            # mails sent in the last years, keep the newest mail per year
            reserv_m(mail.datetime.year, mail)
        elif mail.datetime.year == bmail.datetime.year and \
                mail.datetime.month < bmail.datetime.month:
            # mails sent in the last months, keep the newest mail per month
            reserv_m(mail.datetime.month, mail)

    reserv_mids = dict.fromkeys(reserv_mails.values())
    return [m for m in mails if m.mid not in reserv_mids]

def get_email_detail(service, mailobjs):
    '''Get mail details using batch http request and return as MyEmail.
    '''
    if not mailobjs:
        return

    mymails = []
    def cb(reqid, resp, exception):
        if exception is not None:
            logging.error('Got error when requesting mail details: %s', exception)
        else:
            myml = MyEmail()
            if myml.update(resp):
                mymails.append(myml)

    batchreq = BatchHttpRequest(callback=cb)
    for mail in mailobjs:
        batchreq.add(service.users().messages().get(userId='me', id=mail['id']))
    batchreq.execute()
    return mymails

def trash_expired_email(service, mymails):
    '''Move expired gmails to trash using batch http request.
    '''
    if not mymails:
        return

    exmails = find_expired_email(mymails)
    if not exmails:
        return

    def cb(reqid, resp, exception):
        i = int(reqid)
        if exception is not None:
            logging.error('Got error when trashing gmails: %s', exception)
        elif exmails[i].mid == resp['id'] and TRASH_LABEL in resp['labelIds']:
            logging.warn('Successfully trashed mail: %s, received at %s',
                exmails[i].subject, exmails[i].datetime)
        else:
            logging.error('Failed to trash mail: %s', exmails[i].subject)

    batchreq = BatchHttpRequest(callback=cb)
    for i in range(len(exmails)):
        batchreq.add(service.users().messages().trash(userId='me', id=exmails[i].mid), request_id=str(i))
    batchreq.execute()

def main(flags):
    # setup logging
    logging.basicConfig(filename=flags.logging_file, format=LOGGING_FORMAT, level=flags.logging_level)

    # init api service
    credentials = get_credentials(flags)
    service = build('gmail', 'v1', http=credentials.authorize(Http()))

    # lookup label id first
    labmap = lookup_label_id(service, flags.label)
    if len(labmap) != len(flags.label):
        logging.error('Label(s) do not exist: %s', ' '.join([lab for lab in flags.label if lab not in labmap]))
        return 1

    for labid in labmap.values():
        # find emails with given labels
        mailobjs = lookup_email_id(service, [labid])
        if not mailobjs:
            logging.error('No email was tagged with any of the labels: %s', ' '.join(flags.label))
            return 1
        mymails = get_email_detail(service, mailobjs)

        # trash expired emails
        if not flags.sender_sensitive:
            trash_expired_email(service, mymails)
        else:
            # group emails according to sender's email address
            grpmails = {}
            for m in mymails:
                if m.sender not in grpmails:
                    grpmails[m.sender] = []
                grpmails[m.sender].append(m)
            for submails in grpmails.values():
                trash_expired_email(service, submails)

    return 0

def test_find_expired_email():
    inputs = [
        MyEmail('0', 's', 'a', datetime(2015, 1, 6)),
        MyEmail('1', 's', 'a', datetime(2015, 1, 5)),
        MyEmail('2', 's', 'a', datetime(2015, 1, 4)),
        MyEmail('3', 's', 'a', datetime(2015, 1, 3)),
        MyEmail('4', 's', 'a', datetime(2015, 1, 2)),
        MyEmail('5', 's', 'a', datetime(2015, 1, 1)),
        MyEmail('6', 's', 'a', datetime(2014, 12, 9)),
        MyEmail('7', 's', 'a', datetime(2014, 12, 6)),
        MyEmail('8', 's', 'a', datetime(2014, 11, 11)),
        MyEmail('9', 's', 'a', datetime(2014, 10, 10)),
        MyEmail('10', 's', 'a', datetime(2014, 10, 9)),
        MyEmail('11', 's', 'a', datetime(2014, 8, 1)),
        MyEmail('12', 's', 'a', datetime(2013, 8, 1)),
        MyEmail('13', 's', 'a', datetime(2013, 2, 1)),
        MyEmail('14', 's', 'a', datetime(2012, 1, 1)),
    ]
    expect_outputs = [
        MyEmail('7', 's', 'a', datetime(2014, 12, 6)),
        MyEmail('10', 's', 'a', datetime(2014, 10, 9)),
        MyEmail('13', 's', 'a', datetime(2013, 2, 1)),
    ]
    outputs = find_expired_email(inputs)
    if len(outputs) != len(expect_outputs):
        return False
    for i in range(len(outputs)):
        if outputs[i].mid != expect_outputs[i].mid:
            return False
    return True

def run_tests():
    if not test_find_expired_email():
        print('Test find_expired_email error.')
        sys.exit(1)
    sys.exit(0)

if __name__ == '__main__':
    #run_tests()

    try:
        sys.exit(main(parse_cmd_args()))
    except errors.HttpError as e:
        logging.error('Error: %s', e)
        sys.exit(1)
    except Exception:
        logging.exception('Unknown error')
        sys.exit(1)

