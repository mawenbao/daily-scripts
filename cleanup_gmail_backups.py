#!/usr/bin/env python
# -*- coding: UTF-8 -*-
# author: mwenbao@gmail.com
# date: 2015.06.03
# desc: Move old backup gmails to trash.
# depend: python2.7
#         gmail python api: pip install --upgrade google-api-python-client

import os
import sys
import re
import argparse
import logging
from datetime import datetime

from apiclient.discovery import build
from apiclient import errors
from httplib2 import Http
import oauth2client
from oauth2client import client
from oauth2client import tools

LOGGING_FORMAT = '[%(levelname)s] [%(asctime)-15s] %(message)s'
TRASH_LABEL = 'TRASH'
BACKUP_LABEL = 'host-backup'
DATE_FORMAT = '%Y-%m-%d %H:%M:%S'
MAIL_DATE_REG = re.compile(r'[1-9][0-9]{3}-[0-9]{2}-[0-9]{2} [0-2][0-9]:[0-6][0-9]:[0-6][0-9]')

SCOPES = 'https://www.googleapis.com/auth/gmail.modify'
APPLICATION_NAME = 'Cleanup Gmail Backups'


class MyBackupEmail(object):
    def __init__(self):
        self.mid = ''
        self.subject = u''
        self.datetime = None

    def __str__(self):
        return '{} {} {}'.format(self.datetime, self.mid, self.subject)

    def __repr__(self):
        return self.__str__()

    def __parse_datetime(self):
        '''Parse date and time from mail subject.
        '''
        try:
            datels = MAIL_DATE_REG.findall(self.subject)
            if not datels:
                logging.error('Failed to match datetime string in mail subject: %s', self.subject)
                return False
            self.datetime = datetime.strptime(datels[0], DATE_FORMAT)
        except ValueError, e:
            logging.error('Failed to parse datetime string: %s', e)
            return False
        return True

    def update(self, msg):
        '''Set mail id, subject and datetime.
        '''
        self.mid = msg['id']
        for header in msg['payload']['headers']:
            if header['name'] == u'Subject':
                self.subject = header['value']
                break
        if not self.subject:
            logging.error("No subject found in email %s's headers", self.mid)
            return False
        if not self.__parse_datetime():
            return False
        return True

def parse_cmd_args():
    parser = argparse.ArgumentParser(parents=[tools.argparser])
    parser.add_argument('--logging_file', default='',
            help='Location of the log file.')
    parser.add_argument('--secret_file', default='client_secret.json',
            help='Location of the secret file.')
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
                                   'cleanup-gmail-backups.json')

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

def find_label_id(service, name):
    """Find label id according to its name.
    """

    label_id = ''
    results = service.users().labels().list(userId='me').execute()
    labels = results.get('labels', [])
    if not labels:
        logging.error('No lables found')
        return ''
    for label in labels:
        if label['name'] == name:
            label_id = label['id']
            break
    return label_id

def find_emails_by_labelid(service, labelids):
    """Find all the emails tagged with labels(id).

    Results are sort by date desc.
    """

    results = service.users().messages().list(
        userId='me', labelIds=labelids).execute()
    return results.get('messages', [])

def find_expired_emails(mails):
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

def main(flags):
    # setup logging
    logging.basicConfig(filename=flags.logging_file, format=LOGGING_FORMAT, level=flags.logging_level)

    # init api service
    credentials = get_credentials(flags)
    service = build('gmail', 'v1', http=credentials.authorize(Http()))

    # find label id
    labelid = find_label_id(service, BACKUP_LABEL)
    if not labelid:
        logging.error('Label %s not found', BACKUP_LABEL)
        return 1

    # find all emails tagged with label(id)
    mailobjs = find_emails_by_labelid(service, [labelid])
    if not mailobjs:
        logging.error('No mails found for label(id): %s', labelid)
        return 1
    mymails = []
    for mail in mailobjs:
        msg = service.users().messages().get(userId='me', id=mail['id']).execute()
        myml = MyBackupEmail()
        if not myml.update(msg):
            continue
        mymails.append(myml)

    # moved expired mails to trash
    for mail in find_expired_emails(mymails):
        msg = service.users().messages().trash(userId='me', id=mail.mid).execute()
        if msg['id'] == mail.mid and TRASH_LABEL in msg['labelIds']:
            logging.warn('Successfully trashed mail: %s', mail.subject)
        else:
            logging.error('Failed to trash mail: %s', mail.subject)
    return 0

if __name__ == '__main__':
    try:
        sys.exit(main(parse_cmd_args()))
    except errors.HttpError, error:
        logging.error('Error: %s', error)
        sys.exit(1)

