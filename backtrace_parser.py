#!/usr/bin/env python
# -*- coding: UTF-8 -*-
# @author: mawenbao@hotmail.com
# @date: 2014.04.25
# @desc: parse backtrace output
 
import re
import os
import sys
import subprocess
 
_bt_line_regex = re.compile(r'.*? - (?P<path>.+)\((?P<func>.*?)(\+0x[0-9a-f]+)?\) \[(?P<addr>0x[0-9a-f]+)\]')
 
def _run_cmd(cmd):
    """run cmd(string) and return it's stdout"""
    cmdProc = subprocess.Popen(
        cmd,
        shell=True,
        stdout=subprocess.PIPE
    )
    return cmdProc.communicate()[0]
 
def main(object_file):
    for line in sys.stdin:
        # extract function name and return address
        # from backtrace's output
        match = _bt_line_regex.match(line)
        if not match:
            continue
        groups = match.groupdict()
        path = groups['path']
        func = groups['func']
        addr = groups['addr']
        # demangle function name
        func = _run_cmd('c++filt {}'.format(func)).strip()
        # translate return address to file path and line number
        addr = _run_cmd('addr2line -e {} {}'.format(object_file, addr)).strip()
        print('[{}]  {}  {}'.format(path, addr, func))
    return 0
 
def usage():
    return'usage: python {} <object_file>'.format(sys.argv[0])
 
if __name__ == '__main__':
    if len(sys.argv) != 2:
        print(usage())
        sys.exit(2)
    objFile = sys.argv[1]
 
    if not os.path.exists(objFile):
        print('object file does not exists: {}'.format(objFile))
        sys.exit(2)
    sys.exit(main(objFile))
