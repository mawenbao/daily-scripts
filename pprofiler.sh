#!/bin/bash
# @date: 2014-05-12
# poor man's profiler, got from http://poormansprofiler.org/

function usage {
    echo "usage: bash pprofiler.sh <pid> [sample count] [sleep time]"
    echo "    pid:          pid of the process to profile"
    echo "    sample count: collect samples with gdb for this count of times, default is 1"
    echo "    sleep time:   sleep for some seconds before next profiling, default is 0"
}

if [[ 0 == $# ]];then
    usage
    exit 2
fi

pid=$1

nsamples=1
if [[ $# > 1 ]]; then
    nsamples=$2
fi

sleeptime=0
if [[ $# > 2 ]]; then
    sleeptime=$2
fi

for x in $(seq 1 $nsamples)
  do
    gdb -ex "set pagination 0" -ex "thread apply all bt" -batch -p $pid
    sleep $sleeptime
  done | \
awk '
  BEGIN { s = ""; }
  /^Thread/ { print s; s = ""; }
  /^\#/ { if (s != "" ) { s = s "," $4} else { s = $4 } }
  END { print s }' | \
sort | uniq -c | sort -r -n -k 1,1

