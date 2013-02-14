#!/usr/bin/env python
#
# Project:
#   glideinWMS
#
# File Version: 
#
# Description:
#   Stop a running glideinFrontend
# 
# Arguments:
#   $1 = work_dir
#
# Author:
#   Igor Sfiligoi
#

import signal
import sys
import os
import os.path
import fcntl
import string
import time

sys.path.append(os.path.join(sys.path[0],"../.."))

from glideinwms.frontend import glideinFrontendPidLib
from glideinwms.frontend import glideinFrontendConfig

# this one should  never throw an exeption
def get_element_pids(work_dir,frontend_pid):
    # get element pids
    frontendDescript=glideinFrontendConfig.FrontendDescript(work_dir)
    groups=string.split(frontendDescript.data['Groups'],',')
    groups.sort()

    element_pids={}
    for group in groups:
        try:
            element_pid,element_ppid=glideinFrontendPidLib.get_element_pid(work_dir,group)
        except RuntimeError,e:
            print e
            continue # report error and go to next group
        if element_ppid!=frontend_pid:
            print "Group '%s' has an unexpected Parent PID: %s!=%s"%(group,element_ppid,frontend_pid)
            continue # report error and go to next group
        element_pids[group]=element_pid

    return element_pids

def main(work_dir, force=False):
    retries_count = 100
    sleep_in_retries = 0.2
    # get the pids
    try:
        frontend_pid=glideinFrontendPidLib.get_frontend_pid(work_dir)
    except RuntimeError, e:
        print e
        return 1
    #print frontend_pid

    if not glideinFrontendPidLib.pidSupport.check_pid(frontend_pid):
        # Frontend already dead
        return 0

    # kill processes
    # first soft kill the frontend (20s timeout)
    try:
        os.kill(frontend_pid, signal.SIGTERM)
    except OSError:
        pass # frontend likely already dead

    for retries in range(retries_count):
        if glideinFrontendPidLib.pidSupport.check_pid(frontend_pid):
            time.sleep(sleep_in_retries)
        else:
            return 0 # frontend dead

    if not force:
        print "Frontend did not die after the timeout of %s sec" % (retries_count * sleep_in_retries)
        return 1

    # Retry soft kill the frontend ... should exit now
    print "Frontend still alive ... retrying soft kill"
    try:
        os.kill(frontend_pid, signal.SIGTERM)
    except OSError:
        pass # frontend likely already dead

    for retries in range(retries_count):
        if glideinFrontendPidLib.pidSupport.check_pid(frontend_pid):
            time.sleep(sleep_in_retries)
        else:
            return 0 # frontend dead

    print "Frontend still alive ... sending hard kill"

    element_pids = get_element_pids(work_dir, frontend_pid)
    #print element_pids

    element_keys = element_pids.keys()
    element_keys.sort()

    for element in element_keys:
        if glideinFrontendPidLib.pidSupport.check_pid(element_pids[element]):
            print "Hard killing element %s" % element
            try:
                os.kill(element_pids[element], signal.SIGKILL)
            except OSError:
                pass # ignore already dead processes

    if not glideinFrontendPidLib.pidSupport.check_pid(frontend_pid):
        return 0 # Frontend died

    try:
        os.kill(frontend_pid, signal.SIGKILL)
    except OSError:
        pass # ignore problems
    return 0

if __name__ == '__main__':
    if len(sys.argv)<2:
        print "Usage: stopFrontend.py work_dir"
        sys.exit(1)

    sys.exit(main(sys.argv[1], force=True))
