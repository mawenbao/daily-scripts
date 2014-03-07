# -*- encoding: UTF-8 -*-
# @author: mawenbao@hotmail.com
# @date: 2014-03-04
# @desc: 执行外部命令相关的辅助函数

import sys, subprocess, string

def exit_with_error(errorMsg):
    """ 按照spider/README.txt中的约定规则输出错误信息然后退出进程。
    """

    sys.stdout.write("#ERROR: " + replace_newline(errorMsg) + "\n")
    sys.exit(1)

def run_cmd(cmdStr):
    """ 用shell运行命令，并检查命令返回值。

    仔细检查cmdStr，以避免可能存在的安全问题。
    """

    cmdProc = subprocess.Popen(
        cmdStr,
        shell=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
    )

    stdout, stderr = cmdProc.communicate()
    # check command return
    if (0 != cmdProc.returncode or stderr):
        err = ""
        if stdout:
            err += stdout + " "
        if stderr:
            err += stderr
        exit_with_error(err)
    return stdout

