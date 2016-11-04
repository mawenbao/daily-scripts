#!/usr/bin/env python
# -*- coding: utf-8 -*-
# pip install tornado

import tornado
import tornado.iostream
import tornado.httpclient
import signal
import multiprocessing
import os
import sys
import struct
import functools
try:
    import cPickle as pickle
except ImportError:
    import pickle
import time
import argparse

class SubCmd(object):
    CmdInvalid = -1
    CmdResult = 0
    CmdExit = 1
    CmdWillExit = 2

    def __init__(self, cmd, result=None):
        self.cmd = cmd
        self.result = result

    def msg(self):
        objstr = pickle.dumps(self, 2)
        strlen = len(objstr)
        return struct.pack('<I%ds' % (strlen), strlen, objstr)

    @classmethod
    def load(cls, msg):
        return pickle.loads(msg)

class LoadResult(object):
    def __init__(self):
        self.num_requests = 0
        self.num_errors = 0
        self.status_map = {}
        self.total_resp_time = 0
        self.avg_resp_time = 0
        self.max_resp_time = 0
        self.min_resp_time = 999999

    def new_status(self, code):
        if code in self.status_map:
            self.status_map[code] += 1
        else:
            self.status_map[code] = 1

    def update(self, other):
        if other is None:
            return
        self.num_requests += other.num_requests
        self.num_errors += other.num_errors
        for k, v in other.status_map.items():
            if k not in self.status_map:
                self.status_map[k] = v
            else:
                self.status_map[k] += v
        self.total_resp_time += other.total_resp_time
        self.avg_resp_time = self.total_resp_time / self.num_requests
        self.max_resp_time = max(self.max_resp_time, other.max_resp_time)
        self.min_resp_time = min(self.min_resp_time, other.min_resp_time)

good_size = 400
now_exit = False
first_show = True
sub_cmd_pipes = []
sub_result_pipes = {}
sub_procs = []
result = LoadResult()
begin_time = time.time()

def stdout_erase_lines(num=1):
    # cursor up + line erase + column 0
    sys.stdout.write('\x1b[1A\x1b[2K' * num + '\r')
    sys.stdout.flush()

def readable_elaps_time(begin_time):
    elaps_time = time.time() - begin_time
    if elaps_time > 24 * 3600:
        return '{:.2f}d'.format(elaps_time / 24 * 3600)
    elif elaps_time > 3600:
        return '{:.2f}h'.format(elaps_time / 3600)
    elif elaps_time > 60:
        return '{:.2f}m'.format(elaps_time / 60)
    else:
        return '{:.2f}s'.format(elaps_time)

def show_result():
    global now_exit, begin_time, result, first_show
    if now_exit:
        return
    if not first_show:
        stdout_erase_lines(3)
    req_rate = result.num_requests / (time.time() - begin_time)
    status_line = ''
    for k, v in result.status_map.items():
        status_line += ('{} ({}) | '.format(k, v))
    print('{:<25}total {} | rate: {:.2f} #/s | errors: {}'.format(
        'requests (elaps {}):'.format(readable_elaps_time(begin_time)),
        result.num_requests,
        req_rate,
        result.num_errors))
    print('{:<25}{}'.format('response status:', status_line[:-3]))
    print('{:<25}min {:4.2f} | max {:4.2f} | avg {:4.2f}'.format(
        'response time(ms):',
        result.min_resp_time,
        result.max_resp_time,
        result.avg_resp_time))
    first_show = False

class Request(object):
    def __init__(self, url, output):
        self.url = url
        self.output = output
        self.client = None

    def handle_response(self, response):
        global now_exit, good_size, result
        result.num_requests += 1
        if response.body is None or len(response.body) < good_size:
            result.num_errors += 1
        result.new_status(response.code)
        resp_time = response.request_time * 1000
        result.total_resp_time += resp_time
        result.avg_resp_time = result.total_resp_time / result.num_requests
        result.min_resp_time = min(result.min_resp_time, resp_time)
        result.max_resp_time = max(result.max_resp_time, resp_time)

        if result.num_requests % 10 == 0:
            self.output.write(SubCmd(SubCmd.CmdResult, result).msg())

        self.client.close()
        if not now_exit:
            self.run()

    def run(self):
        self.client = tornado.httpclient.AsyncHTTPClient(force_instance=True)
        self.client.fetch(self.url, self.handle_response)

def parse_cmd_args():
    parser = argparse.ArgumentParser(description=u'Http压力测试工具')
    parser.add_argument('url', help=u'目标URL')
    parser.add_argument('-f', dest='procs', type=int, default=1, help=u'进程数目，默认1')
    parser.add_argument('-c', dest='coroutines', type=int, default=10, help=u'每个进程(单线程)的并发数目，默认10')
    if len(sys.argv) == 1:
        parser.print_help()
        sys.exit(2)
    args = parser.parse_args()
    urlstr = u'{:<15}{}'.format('URL:', args.url)
    procstr = u'{:<15}{}'.format('Processes:', args.procs)
    corstr = u'{:<15}{}'.format('Coroutines:', args.coroutines)
    numdeli = max(len(urlstr), len(procstr), len(corstr))
    print('\n{0}\n{1}\n{2}\n{3}\n{0}\n'.format(numdeli * '=', urlstr, procstr, corstr))
    return args

def exit_handler(signum, frame):
    global now_exit
    now_exit = True

def try_exit():
    global now_exit, sub_procs
    if now_exit:
        print('\nWaiting for children to exit...')
        for p in sub_cmd_pipes:
            p.write(SubCmd(SubCmd.CmdExit).msg())
        for p in sub_procs:
            p.join()
        tornado.ioloop.IOLoop.current().stop()
        print('Bye')

def start_worker(url, num_coroutines, pipe_in, pipe_out):
    # clear loop instance inited in parent process
    tornado.ioloop.IOLoop.clear_instance()
    loop = tornado.ioloop.IOLoop.instance()
    loop.make_current()

    cmd_stream = tornado.iostream.PipeIOStream(pipe_in)
    def process_cmd(data):
        cmd = SubCmd.load(data)
        if cmd.cmd == SubCmd.CmdExit:
            global now_exit
            now_exit = True
            tornado.ioloop.IOLoop.current().stop()
            sys.exit(0)

    def process_cmd_len(data):
        strlen = struct.unpack('<I', data)[0]
        cmd_stream.read_bytes(strlen, process_cmd)

    def on_cmd_read(fd, evs):
        cmd_stream.read_bytes(4, process_cmd_len)

    loop.add_handler(pipe_in, on_cmd_read, tornado.ioloop.IOLoop.READ)
    output = tornado.iostream.PipeIOStream(pipe_out)
    requests = [Request(url, output) for n in range(num_coroutines)]

    for r in requests:
        r.run()
    loop.start()

if __name__ == '__main__':
    signal.signal(signal.SIGINT, exit_handler)

    args = parse_cmd_args()

    for n in range(args.procs):
        cmd_pipe_r, cmd_pipe_w = os.pipe()
        res_pipe_r, res_pipe_w = os.pipe()
        proc = multiprocessing.Process(target=start_worker, args=(args.url, args.coroutines, cmd_pipe_r, res_pipe_w))
        proc.start()
        os.close(cmd_pipe_r)
        os.close(res_pipe_w)
        sub_procs.append(proc)

        sub_cmd_pipes.append(tornado.iostream.PipeIOStream(cmd_pipe_w))
        sub_result_pipes[res_pipe_r] = tornado.iostream.PipeIOStream(res_pipe_r)

        def process_cmd(data):
            cmd = SubCmd.load(data)
            if cmd.cmd == SubCmd.CmdResult:
                global result
                result.update(cmd.result)
                show_result()

        def process_cmd_len(stream, data):
            strlen = struct.unpack('<I', data)[0]
            stream.read_bytes(strlen, process_cmd)

        def on_cmd_read(fd, evs):
            stream = sub_result_pipes[fd]
            stream.read_bytes(4, functools.partial(process_cmd_len, stream))

    loop = tornado.ioloop.IOLoop.instance()
    for fd in sub_result_pipes.keys():
        loop.add_handler(fd, on_cmd_read, tornado.ioloop.IOLoop.READ)

    tornado.ioloop.PeriodicCallback(try_exit, 1000).start()
    loop.start()