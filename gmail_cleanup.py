#!/usr/bin/env python
# -*- coding: UTF-8 -*-
# author: mwenbao@gmail.com
# date: 2015.06.03 - 2015.06.09
# desc: Move old gmails with given labels to trash.
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


class MyBackupEmail(object):
    def __init__(self):
        self.mid = ''
        self.subject = u''
        self.sender = u''
        self.datetime = None  # represented in the email date's tz

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
            if header['name'] == u'Subject':
                self.subject = header['value']
            if header['name'] == u'From':
                self.sender = header['value']
            if header['name'] == u'Date':
                datestr = header['value']
            if self.subject and self.sender and datestr:
                break
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
        help="Treat different senders' emails within the same label seperately.")
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
        print 'Storing credentials to ' + credential_path
    return credentials

def lookup_label_id(service, labels):
    """Lookup gmail label id according to their names.
    """
    if not labels:
        return

    labelids = []
    def cb(reqid, resp, exception):
        if exception is not None:
            logging.error('Got error when requesting email label id: %s', exception)
            return
        mylabs = resp.get('labels', [])
        if not mylabs:
            logging.error('Label not found: %s', labels[int(reqid)])
            return
        for lab in mylabs:
            if lab['name'] in labels:
                labelids.append(lab['id'])

    batchreq = BatchHttpRequest(callback=cb)
    for i in range(len(labels)):
        batchreq.add(service.users().labels().list(userId='me'), request_id=str(i))
    batchreq.execute()
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
        1. (7) sent in this month.
        2. (*) sent in the last months(one mail per month).
        3. (*) sent in the last years(one mail per year).
    """
    today = datetime.now().date()
    reserv_mails = {} # year|month|date => mail.mid
    num_month_mails = 0 # number of mails sent this month
    def reserv_m(key, mail):
        if not reserv_mails.has_key(key):
            reserv_mails[key] = mail.mid

    # get a copy of mails sort by datetime in desc order first
    for mail in sorted(mails, key=lambda m:m.datetime, reverse=True):
        if mail.datetime.year != today.year:
            # mails sent in the last years, keep the newest mail per year
            reserv_m(mail.datetime.year, mail)
        elif mail.datetime.month != today.month:
            # mails sent in the last months, keep the newest mail per month
            reserv_m(mail.datetime.month, mail)
        elif num_month_mails < 7:
            # mails sent in this month, keep the newest 7 mails
            date = mail.datetime.date()
            if not reserv_mails.has_key(date):
                num_month_mails += 1
            reserv_m(date, mail)

    reserv_mids = dict.fromkeys(reserv_mails.values())
    return [m for m in mails if m.mid not in reserv_mids]

def get_email_detail(service, mailobjs):
    '''Get mail details using batch http request and return as MyBackupEmail.
    '''
    if not mailobjs:
        return

    mymails = []
    def cb(reqid, resp, exception):
        if exception is not None:
            logging.error('Got error when requesting mail details: %s', exception)
        else:
            myml = MyBackupEmail()
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
            logging.warn('Successfully trashed mail: %s, received at UTC %s',
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

    for label in flags.label:
        # lookup label id first
        labelids = lookup_label_id(service, [label])
        if not labelids:
            logging.error('Label not found: %s', label)
            return 1

        # find emails with given labels
        mailobjs = lookup_email_id(service, labelids)
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

if __name__ == '__main__':
    ret = 0
    try:
        ret = main(parse_cmd_args())
    except errors.HttpError, error:
        logging.error('Error: %s', error)
        sys.exit(1)
    except:
        logging.exception('Unknown error')
        sys.exit(1)
    sys.exit(ret)

