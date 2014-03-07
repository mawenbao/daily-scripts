#!/bin/bash
# @author: mawenbao@hotmail.com
# @date: 2014-03-07
# @desc: list processes and their path
# @usage: ./show_proc_path.sh firefox

ind=0

ps -ef | grep -E "(PID|$1)" | grep -v grep | grep -v $0 | while read line
do
    if [ ${ind} -eq 0 ]; then
        echo "Num ${line} PATH"
    else
        cmdPid=`echo ${line} | awk '{print $2}'`
        cmdPath=`ls -l /proc/${cmdPid} | grep exe | awk '{print $11}'`
        echo "[${ind}] ${line} ${cmdPath}"
    fi
    ind=`expr ${ind} + 1`
done | column -t

