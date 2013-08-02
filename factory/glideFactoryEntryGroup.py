#!/usr/bin/env python
#
# Project:
#   glideinWMS
#
# File Version:
#
# Description:
#   This is the glideinFactoryEntryGroup. Common Tasks like querying collector
#   and advertizing the work done by group are done here
#
# Arguments:
#   $1 = poll period (in seconds)
#   $2 = advertize rate (every $2 loops)
#   $3 = glidein submit_dir
#   $4 = entry name
#
# Author:
#   Parag Mhashilkar (October 2012)
#

import signal
import os
import os.path
import sys
import fcntl
import traceback
import time
import string
import math
import copy
import random
import cPickle
import select

STARTUP_DIR=sys.path[0]
sys.path.append(os.path.join(STARTUP_DIR,"../../"))

from glideinwms.lib import logSupport
from glideinwms.lib import glideinWMSVersion
from glideinwms.factory import glideFactoryLogParser
from glideinwms.factory import glideFactoryEntry
from glideinwms.factory import glideFactoryConfig as gfc
from glideinwms.factory import glideFactoryLib as gfl
from glideinwms.factory import glideFactoryInterface as gfi
from glideinwms.factory import glideFactoryPidLib
from glideinwms.factory import glideFactoryMonitorAggregator
from glideinwms.factory import glideFactoryMonitoring
from glideinwms.factory import glideFactoryDowntimeLib

# Memory foot print of a entry process when forked for check_and_perform_work
# Set a conservative limit of 500 MB (based on USCD 2.6 factory Pss of 115 MB)
#   plus a safety factor of 2

ENTRY_MEM_REQ_BYTES = 500000000 * 2
############################################################
class EntryGroup:

    def __init__(self):
        pass

############################################################
def check_parent(parent_pid, glideinDescript, my_entries):
    """
    Check to make sure that we aren't an orphaned process.  If Factory
    daemon has died, then clean up after ourselves and kill ourselves off.

    @type parent_pid: int
    @param parent_pid: pid for the Factory daemon process

    @type glideinDescript: glideFactoryConfig.GlideinDescript
    @param glideinDescript: Object that encapsulates glidein.descript in the Factory root directory

    @type my_entries: dict
    @param my_entries: Dictionary of entry objects keyed on entry name

    @raise KeyboardInterrupt: Raised when the Factory daemon cannot be found
    """

    if os.path.exists('/proc/%s'%parent_pid):
        return # parent still exists, we are fine
    
    gfl.log_files.logActivity("Parent died, exit.")    

    # there is nobody to clean up after ourselves... do it here
    gfl.log_files.logActivity("Deadvertize myself")
    
    for entry in my_entries.values():
        # Deadvertise glidefactory classad
        try:
            gfi.deadvertizeGlidein(
                glideinDescript.data['FactoryName'],	 
                glideinDescript.data['GlideinName'],	 
                entry.name)	 
        except:
            gfl.log_files.logWarning("Failed to deadvertize entry '%s'" % entry.name)

        # Deadvertise glidefactoryclient classad
        try:
            gfi.deadvertizeAllGlideinClientMonitoring(
                glideinDescript.data['FactoryName'],	 
                glideinDescript.data['GlideinName'],	 
                entry.name)	 
        except:
            gfl.log_files.logWarning("Failed to deadvertize monitoring for entry '%s'" % entry.name)

    raise KeyboardInterrupt,"Parent died. Quiting."


############################################################
def find_work(factory_in_downtime, glideinDescript,
              frontendDescript, group_name, my_entries):
    """
    Find work for all the entries in the group

    @type factory_in_downtime:  boolean
    @param factory_in_downtime:  True if factory is in downtime

    @type glideinDescript: dict
    @param glideinDescript: Factory glidein config values

    @type frontendDescript: dict 
    @param frontendDescript: Security mappings for frontend identities, security classes, and usernames for privsep

    @type group_name: string
    @param group_name: Name of the group

    @type my_entries: dict
    @param my_entries: Dictionary of entry objects keyed on entry name
    
    @return: Dictionary of work to do keyed on entry name
    @rtype: dict
    """

    pub_key_obj = glideinDescript.data['PubKeyObj']
    old_pub_key_obj = glideinDescript.data['OldPubKeyObj']

    allowed_proxy_source = glideinDescript.data['AllowedJobProxySource'].split(',')

    gfl.log_files.logActivity("Finding work")
    work = gfi.findGroupWork(gfl.factoryConfig.factory_name,
                             gfl.factoryConfig.glidein_name,
                             my_entries.keys(),
                             gfl.factoryConfig.supported_signtypes,
                             pub_key_obj, allowed_proxy_source)
    log_work_info(work, key='existing')



    # If old key is valid, find the work using old key as well and append it
    # to existing work dictionary
    if (old_pub_key_obj != None):
        work_oldkey = {}
        # still using the old key in this cycle
        gfl.log_files.logActivity("Old factory key is still valid. Trying to find work using old factory key.")
        work_oldkey = gfi.findGroupWork(gfl.factoryConfig.factory_name,
                                        gfl.factoryConfig.glidein_name,
                                        my_entries.keys(),
                                        gfl.factoryConfig.supported_signtypes,
                                        old_pub_key_obj, allowed_proxy_source)
        log_work_info(work, key='old')

        # Merge the work_oldkey with work
        for w in work_oldkey:
            if w in work:
                # This should not happen but still as a safegaurd warn
                gfl.log_files.logActivity("Work task for %s exists using existing key and old key. Ignoring the work from old key." % w)
                gfl.log_files.logWarning("Work task for %s exists using existing key and old key. Ignoring the work from old key." % w)
                continue
            work[w] = work_oldkey[w]

    # Append empty work item for entries that do not have work
    # This is required to trigger glidein sanitization further in the code
    for ent in my_entries:
        if ent not in work:
            work[ent] = {}

    return work


def log_work_info(work, key=''):
    keylogstr = ''
    if key.strip() != '':
        gfl.log_files.logActivity('Work tasks grouped by entries using %s factory key' % (key))
    else:
        gfl.log_files.logActivity('Work tasks grouped by entries')

    for entry in work:
        # Only log if there is work to do
        if len(work[entry]) > 0:
            gfl.log_files.logActivity("Entry: %s (Tasks: %s)" % (entry, len(work[entry])))


def get_work_count(work):
    """
    Get total work to do i.e. sum of work to do for every entry

    @type work: dict
    @param work: Dictionary of work to do keyed on entry name

    @rtype: int
    @return: Total work to do.
    """

    count = 0
    for entry in work:
        count += len(work[entry])
    return count

###############################
def fetch_fork_result(r, pid):
    """
    Used with fork clients
   
    @type r: pipe
    @param r: Input pipe

    @type pid: int
    @param pid: pid of the child

    @rtype: Object
    @return: Unpickled object
    """

    try:
        rin = ""
        s = os.read(r, 1024*1024)
        while (s != ""): # "" means EOF
            rin += s
            s = os.read(r,1024*1024)
    finally:
        os.close(r)
        os.waitpid(pid, 0)

    out = cPickle.loads(rin)
    return out

def fetch_fork_result_list(pipe_ids):
    """
    Read the output pipe of the children, used after forking to perform work
    and after forking to entry.writeStats()
 
    @type pipe_ids: dict
    @param pipe_ids: Dictinary of pipe and pid 

    @rtype: dict
    @return: Dictionary of fork_results
    """

    out = {}
    failures = 0
    for key in pipe_ids:
        try:
            # Collect the results
            out[key] = fetch_fork_result(pipe_ids[key]['r'],
                                         pipe_ids[key]['pid'])
        except Exception, e:
            tb = traceback.format_exception(sys.exc_info()[0],
                                            sys.exc_info()[1],
                                            sys.exc_info()[2])
            gfl.log_files.logWarning("Failed to extract info from child '%s'" % key)
            gfl.log_files.logDebug("Failed to extract info from child '%s': %s" % (key, tb))
            failures += 1

    if failures>0:
        raise RuntimeError, "Found %i errors" % failures

    return out


###############################

def process_finished_children(pipe_ids):
    """
    Read the output pipe of the children, used after forking. If there is data
    on the pipes to consume, read the data and close the pipe.
    and after forking to entry.writeStats()

    @type pipe_ids: dict
    @param pipe_ids: Dictinary of pipe and pid

    @rtype: dict
    @return: Dictionary of work_done
    """

    work_info = {}
    failures = 0
    fds_to_entry = dict((pipe_ids[x]['r'], x) for x in pipe_ids)

    readable_fds = select.select(fds_to_entry.keys(), [], [], 0)[0]
    for fd in readable_fds:
        try:
            key = fds_to_entry[fd]
            pid = pipe_ids[key]['pid']
            out = fetch_fork_result(fd, pid)
            work_info[key] = out
        except Exception, e:
            tb = traceback.format_exception(sys.exc_info()[0],
                                            sys.exc_info()[1],
                                            sys.exc_info()[2])
            gfl.log_files.logWarning("Failed to extract info from child '%s'" % key)
            gfl.log_files.logDebug("Failed to extract info from child '%s': %s" % (key, tb))
            failures += 1

    if failures:
        raise RuntimeError, "Found %i errors" % failures

    return work_info

###############################

def find_and_perform_work(factory_in_downtime, glideinDescript,
                          frontendDescript, group_name, my_entries):
    """
    For all entries in this group, find work requests from the WMS collector, 
    validates credentials, and requests glideins. If an entry is in downtime,
    requested glideins is zero.
    
    @type factory_in_downtime: boolean
    @param factory_in_downtime: True if factory is in downtime

    @type glideinDescript: dict
    @param glideinDescript: Factory glidein config values

    @type frontendDescript: dict 
    @param frontendDescript: Security mappings for frontend identities, security classes, and usernames for privsep

    @type group_name: string
    @param group_name: Name of the group

    @type my_entries: dict
    @param my_entries: Dictionary of entry objects keyed on entry name
    
    @return: Dictionary of work to do keyed on entry name
    @rtype: dict
    """
    
    # Work done by group keyed by entry name. This will be returned back
    groupwork_done = {}

    # Step 1:
    # Find work to perform. Work is a dict work[entry_name][frontend]
    # We may or may not be able to perform all the work but that will be
    # checked later per entry

    work = {}
    work = find_work(factory_in_downtime, glideinDescript,
                     frontendDescript, group_name, my_entries)   

    work_count = get_work_count(work)
    if (work_count == 0):
        gfl.log_files.logActivity("No work found")
        return groupwork_done

    gfl.log_files.logActivity("Found %s total tasks to work on" % work_count)

    # Got the work items grouped by entries
    # Now fork a process per entry and wait for certain duration to get back
    # the results. Kill processes if they take too long to get back with result

    # ids keyed by entry name
    pipe_ids = {}

    # Max number of children to fork at a time
    # Each child currently takes ~50 MB
    # Leaving 3GB for system, max number of children to fork is
    # (Memory - 3000)/50 = 100 (RAM: 8GB) & 250 (RAM: 16GB)
    parallel_workers = 0
    try:
        parallel_workers = int(glideinDescript.data['EntryParallelWorkers'])
    except KeyError:
        gfl.log_files.logDebug("EntryParallelWorkers not set -- factory probably needs a reconfig; setting to 0 for dynamic limits.")

    post_work_info = {}
    work_info_read_err = False

    if parallel_workers <= 0:
        gfl.log_files.logDebug("Setting parallel_workers limit dynamically based on the available free memory")
        free_mem = os.sysconf('SC_AVPHYS_PAGES')*os.sysconf('SC_PAGE_SIZE')
        parallel_workers = int(free_mem / float(ENTRY_MEM_REQ_BYTES))
        if parallel_workers < 1: parallel_workers = 1

    gfl.log_files.logDebug("Setting parallel_workers limit of %s" % parallel_workers)
    forks_remaining = parallel_workers

    # Only fork of child processes for entries that have corresponding
    # work todo, ie glideclient classads.
    for ent in work:
        # Check if we can fork more
        while (forks_remaining == 0):
            # Give some time for the processes to finsh the work
            #gfl.log_files.logDebug("Reached parallel_workers limit of %s" % parallel_workers)
            time.sleep(1)

            post_work_info_subset = {}
            # Wait and gather results for work done so far before forking more
            try:
                #post_work_info_subset = fetch_fork_result_list(pipe_ids)
                #gfl.log_files.logDebug("Checking finished workers")
                post_work_info_subset = process_finished_children(pipe_ids)
                post_work_info.update(post_work_info_subset)
            except RuntimeError:
                # Expect all errors logged already
                work_info_read_err = True

            forks_remaining += len(post_work_info_subset)

            for en in post_work_info_subset:
                del pipe_ids[en]


        entry = my_entries[ent]
        r,w = os.pipe()
        pid = os.fork()
        forks_remaining -= 1

        if pid != 0:
            # This is the parent process
            os.close(w)
            pipe_ids[entry.name] = {'r': r, 'pid': pid}
        else:
            # This is the child process
            os.close(r)
            try:
                work_done = glideFactoryEntry.check_and_perform_work(
                                factory_in_downtime, group_name,
                                entry, work[entry.name])
                # entry object now has updated info in the child process
                # This info is required for monitoring and advertising
                # Compile the return info from th  updated entry object 
                # Can't dumps the entry object directly, so need to extract
                # the info required.
                return_dict = compile_pickle_data(entry, work_done)
                os.write(w,cPickle.dumps(return_dict))
            except Exception, ex:
                tb = traceback.format_exception(sys.exc_info()[0],
                                                sys.exc_info()[1],
                                                sys.exc_info()[2])
                entry.logFiles.logDebug("Error in talking to the factory pool: %s" % tb)

            os.close(w)
            # Hard kill myself. Don't want any cleanup, since I was created
            # just for doing check and perform work for each entry
            os.kill(os.getpid(),signal.SIGKILL)

    # Gather info from rest of the entries
    try:
        post_work_info_subset = fetch_fork_result_list(pipe_ids)
        post_work_info.update(post_work_info_subset)
    except RuntimeError:
        # Expect all errors logged already
        work_info_read_err = True


    # Gather results from the forked children
    gfl.log_files.logActivity("All children forked for glideFactoryEntry.check_and_perform_work terminated. Loading post work state for the entry.")
    gfl.log_files.logDebug("All children forked for glideFactoryEntry.check_and_perform_work terminated. Loading post work state for the entry.")

    for entry in my_entries:
        # Update the entry object from the post_work_info
        if ((entry in post_work_info) and (len(post_work_info[entry]) > 0)):
            groupwork_done[entry] = {'work_done': post_work_info[entry]['work_done']}
            (my_entries[entry]).setState(post_work_info[entry])

        else:
            gfl.log_files.logDebug("Entry %s not used by any frontends, i.e no corresponding glideclient classads" % entry)

    if work_info_read_err:
        gfl.log_files.logDebug("Unable to process response from one or more children for check_and_perform_work. One or more forked processes may have failed and may not have client_stats updated")
        gfl.log_files.logWarning("Unable to process response from one or more children for check_and_perform_work. One or more forked processes may have failed and may not have client_stats updated")
    
    return groupwork_done

############################################################

def iterate_one(do_advertize, factory_in_downtime, glideinDescript,
                frontendDescript, group_name, my_entries, need_cleanup):
    
    """
    One iteration of the entry group

    @type do_advertize: boolean
    @param do_advertize: True if glidefactory classads should be advertised

    @type factory_in_downtime: boolean
    @param factory_in_downtime: True if factory is in downtime

    @type glideinDescript: dict
    @param glideinDescript: Factory glidein config values

    @type frontendDescript: dict 
    @param frontendDescript: Security mappings for frontend identities, security classes, and usernames for privsep

    @type group_name: string
    @param group_name: Name of the group

    @type my_entries: dict
    @param my_entries: Dictionary of entry objects keyed on entry name
    """

    groupwork_done = {}
    done_something = 0

    for entry in my_entries.values():
        entry.initIteration(factory_in_downtime)

    cl_pids=[]
    if need_cleanup:
        # IS: Fix the number of forks to 4 for now
        #     Would be a good idea making it configurable, though
        elist=my_entries.values()
        elistSize=len(elist)
        elistForks=4
        elistChunk=elistSize/elistForks+1*((elistSize%elistForks)!=0) #round up
        for i in range(elistForks):
            cl_pid = os.fork()
            if cl_pid != 0:
                # This is the parent process
                cl_pids.append(cl_pid)
            else:
                # This is the child process
                try:
                    for entry in elist[i*elistChunk:(i+1)*elistChunk]:
                        entry.doCleanup()
                finally:
                    # Hard kill myself. Don't want any cleanup, since I was created
                    # just for doing the cleanup
                    os.kill(os.getpid(),signal.SIGKILL)
        del elist 
        gfl.log_files.logActivity("Cleanup forked pids:%s"%str(cl_pids))
    else:
        gfl.log_files.logActivity("No cleanup this round")

    try:
        groupwork_done = find_and_perform_work(factory_in_downtime, 
                                               glideinDescript,
                                               frontendDescript,
                                               group_name, my_entries)
    except:
        tb = traceback.format_exception(sys.exc_info()[0],
                                        sys.exc_info()[1],
                                        sys.exc_info()[2])
        gfl.log_files.logWarning("Error occurred while trying to find and do work.")
        gfl.log_files.logWarning("Exception: %s" % tb)

    gfl.log_files.logDebug("Group Work done: %s" % groupwork_done)

    # Classad files to use
    # Get a 9 digit number that will stay 9 digit for the next 25 years
    short_time = time.time() - 1.05e9
    gf_filename = "/tmp/gfi_gf_multi_%li_%li" % (short_time, os.getpid())
    gfc_filename = "/tmp/gfi_gfc_multi_%li_%li" % (short_time, os.getpid())

    gfl.log_files.logActivity("Generating glidefactory (%s) and glidefactoryclient (%s) classads files" % (gf_filename, gfc_filename))

    for entry in my_entries.values():
        # Write classads to file if work was done or if advertise flag is set
        # Actual advertise is done using multi classad advertisement
        entrywork_done = 0
        if ( (entry.name in groupwork_done) and 
             ('work_done' in groupwork_done[entry.name]) ):
            entrywork_done = groupwork_done[entry.name]['work_done']
            done_something += entrywork_done

        if ( (do_advertize) or (entrywork_done > 0) ):
            gfl.log_files.logDebug("Generating glidefactory and glidefactoryclient classads for entry: %s" % entry.name)
            entry.writeClassadsToFile(factory_in_downtime, gf_filename,
                                      gfc_filename)

        entry.unsetInDowntime()

    if ( (do_advertize) or (done_something > 0) ):
        # ADVERTISE: glidefactory classads
        if os.path.exists(gf_filename):
            try:
                gfl.log_files.logActivity("Advertising glidefactory classads")
                gfi.advertizeGlideinFromFile(gf_filename,
                                             remove_file=True,
                                             is_multi=True)
            except:
                tb = traceback.format_exception(sys.exc_info()[0],
                                                sys.exc_info()[1],
                                                sys.exc_info()[2])
                gfl.log_files.logWarning("Advertising glidefactory classads failed")
                gfl.log_files.logDebug("Advertising glidefactory classads failed: %s" % tb)
        else:
            gfl.log_files.logWarning("glidefactory classad file %s does not exist. Check if you have atleast one entry enabled" % gf_filename)

        # ADVERTISE: glidefactoryclient classads
        if os.path.exists(gfc_filename):
            try:
                gfl.log_files.logActivity("Advertising glidefactoryclient classads")
                gfi.advertizeGlideinClientMonitoringFromFile(
                    gfc_filename, remove_file=True, is_multi=True)
            except:
                tb = traceback.format_exception(sys.exc_info()[0],
                                                sys.exc_info()[1],
                                                sys.exc_info()[2])
                gfl.log_files.logWarning("Advertising glidefactoryclient classads failed")
                gfl.log_files.logDebug("Advertising glidefactoryclient classads failed: %s" % tb)
        else:
            gfl.log_files.logWarning("glidefactoryclient classad file %s does not exist. Check if frontends are allowed to submit to entry" % gfc_filename)


    if need_cleanup:
        for cl_pid in cl_pids:
            gfl.log_files.logActivity("Collectoring cleanup pid:%s"%cl_pid)
            os.waitpid(cl_pid, 0)
        gfl.log_files.logActivity("All cleanups collected")
        del cl_pids

    return done_something

############################################################
def iterate(parent_pid, sleep_time, advertize_rate, glideinDescript,
            frontendDescript, group_name, my_entries):
    """
    Iterate over set of tasks until its time to quit or die. The main "worker" 
    function for the Factory Entry Group.
    @todo: More description to come

    @type parent_pid: int
    @param parent_pid: the pid for the Factory daemon

    @type sleep_time: int
    @param sleep_time: The number of seconds to sleep between iterations

    @type advertize_rate: int
    @param advertize_rate: The rate at which advertising should occur

    @type glideinDescript: glideFactoryConfig.GlideinDescript
    @param glideinDescript: glidein.descript object in the Factory root dir

    @type frontendDescript: glideFactoryConfig.FrontendDescript
    @param frontendDescript: frontend.descript object in the Factory root dir

    @type group_name: string
    @param group_name: Name of the group

    @type my_entries: dict
    @param my_entries: Dictionary of entry objects keyed on entry name
    """

    is_first=1
    count=0;

    # Record the starttime so we know when to disable the use of old pub key
    starttime = time.time()
    # The grace period should be in the factory config. Use it to determine
    # the end of lifetime for the old key object. Hardcoded for now to 30 mins.
    oldkey_gracetime = int(glideinDescript.data['OldPubKeyGraceTime'])
    oldkey_eoltime = starttime + oldkey_gracetime

    factory_downtimes = glideFactoryDowntimeLib.DowntimeFile(glideinDescript.data['DowntimesFile'])

    last_cleanup=None
    while 1:

        # Check if parent is still active. If not cleanup and die.
        check_parent(parent_pid, glideinDescript, my_entries)

        # Check if its time to invalidate factory's old key
        if ( (time.time() > oldkey_eoltime) and 
             (glideinDescript.data['OldPubKeyObj'] != None) ):
            # Invalidate the use of factory's old key
            gfl.log_files.logActivity("Retiring use of old key.")
            gfl.log_files.logActivity("Old key was valid from %s to %s ie grace of ~%s sec" % (starttime,oldkey_eoltime,oldkey_gracetime))
            glideinDescript.data['OldPubKeyType'] = None
            glideinDescript.data['OldPubKeyObj'] = None

        # Check if the factory is in downtime. Group is in downtime only if the
        # factory is in downtime. Entry specific downtime is handled in entry
        factory_in_downtime = factory_downtimes.checkDowntime(entry="factory")

        iteration_stime = time.time()
        iteration_stime_str = time.ctime()

        if factory_in_downtime:
            gfl.log_files.logActivity("Iteration at (in downtime) %s" % iteration_stime_str)
        else:
            gfl.log_files.logActivity("Iteration at %s" % iteration_stime_str)

        try:
            if last_cleanup is None:
                need_cleanup=True
            else:
                # IS: Fix it to half hour for now
                #     Making it a prameter is likely be a good idea, though
                need_cleanup=(time.time()-last_cleanup)>1800

            done_something = iterate_one(count==0, factory_in_downtime,
                                         glideinDescript, frontendDescript,
                                         group_name, my_entries, need_cleanup)
            if need_cleanup:
                last_cleanup=time.time()

            gfl.log_files.logActivity("Writing stats for all entries")

            try:
                pids = []
                # generate a list of entries for each CPU
                cpuCount = int(glideinDescript.data['MonitorUpdateThreadCount'])
                gfl.log_files.logActivity("Number of parallel writes for stats: %i" % cpuCount)

                entrylists = [my_entries.values()[cpu::cpuCount] for cpu in xrange(cpuCount)]

                # Fork's keyed by cpu number. Actual key is irrelevant
                pipe_ids = {}

                post_writestats_info = {}

                for cpu in xrange(cpuCount):
                    r,w = os.pipe()
                    pid = os.fork()
                    if pid:
                        # I am the parent
                        pids.append(pid)
                        os.close(w)
                        pipe_ids[cpu] = {'r': r, 'pid': pid}
                    else:
                        # I am the child
                        signal.signal(signal.SIGTERM, signal.SIG_DFL)
                        signal.signal(signal.SIGQUIT, signal.SIG_DFL)
                        os.close(r)
                        # Return the pickled entry object in form of dict
                        # return_dict[entry.name][entry.getState()]
                        return_dict = {}
                        for entry in entrylists[cpu]:
                            try:
                                entry.writeStats()
                                return_dict[entry.name] = entry.getState()
                            except:
                                tb = traceback.format_exception(
                                         sys.exc_info()[0],
                                         sys.exc_info()[1],
                                         sys.exc_info()[2])
                                gfl.log_files.logWarning("Error writing stats for entry '%s'" % (entry.name))
                                gfl.log_files.logDebug("Error writing stats for entry '%s': %s" % (entry.name, tb))

                        os.write(w, cPickle.dumps(return_dict))
                        os.close(w)
                        # Exit without triggering SystemExit exception
                        os._exit(0)

                try:
                    gfl.log_files.logActivity("Processing response from children after write stats")
                    post_writestats_info = fetch_fork_result_list(pipe_ids)
                except:
                    gfl.log_files.logWarning("Error processing response from one or more children after write stats")

                for i in post_writestats_info:
                    for ent in post_writestats_info[i]:
                        (my_entries[ent]).setState(post_writestats_info[i][ent])
            except KeyboardInterrupt:
                raise # this is an exit signal, pass through
            except:
                # never fail for stats reasons!
                tb = traceback.format_exception(sys.exc_info()[0],
                                                sys.exc_info()[1],
                                                sys.exc_info()[2])
                gfl.log_files.logWarning("Error writing stats: %s" % tb)
        except KeyboardInterrupt:
            raise # this is an exit signal, pass through
        except:
            if is_first:
                raise
            else:
                # if not the first pass, just warn
                tb = traceback.format_exception(sys.exc_info()[0],
                                                sys.exc_info()[1],
                                                sys.exc_info()[2])
                gfl.log_files.logWarning("Exception occurred: %s" % tb)

        gfl.log_files.cleanup()

        iteration_etime = time.time()
        iteration_sleep_time = sleep_time - (iteration_etime - iteration_stime)
        if (iteration_sleep_time < 0):
            iteration_sleep_time = 0

        gfl.log_files.logActivity("Sleep %is" % iteration_sleep_time)
        time.sleep(iteration_sleep_time)
        count = (count+1) % advertize_rate
        is_first = 0


############################################################
# Initialize log_files for entries and groups
# TODO: init_logs,init_group_logs,init_entry_logs maybe removed later

def init_logs(name, entity, log_dir, glideinDescript):
    gfl.log_files_dict[entity][name] = gfl.LogFiles(
        log_dir,
        float(glideinDescript.data['LogRetentionMaxDays']),
        float(glideinDescript.data['LogRetentionMinDays']),
        float(glideinDescript.data['LogRetentionMaxMBs']))

    # TODO: What to do with warning_log.
    #       Is this correct? Or do we need warning logs for every entry?
    #       If so how to we instantiate it?
    gfi.factoryConfig.warning_log = gfl.log_files_dict[entity][name].warning_log

def init_group_logs(name, glideinDescript):
    log_dir = os.path.join(glideinDescript.data['LogDir'], 'factory')
    init_logs(name, 'group', log_dir, glideinDescript)

def init_entry_logs(name, glideinDescript):
    log_dir = os.path.join(glideinDescript.data['LogDir'], "entry_%s"%name)
    init_logs(name, 'entry', log_dir, glideinDescript)
    glideFactoryMonitoring.monitoringConfig.config_log(
        log_dir,
        float(glideinDescript.data['SummaryLogRetentionMaxDays']),
        float(glideinDescript.data['SummaryLogRetentionMinDays']),
        float(glideinDescript.data['SummaryLogRetentionMaxMBs']))



############################################################

def main(parent_pid, sleep_time, advertize_rate,
         startup_dir, entry_names, group_id):
    """
    GlideinFactoryEntryGroup main function

    Setup logging, monitoring, and configuration information. Starts the Entry
    group main loop and handles cleanup at shutdown.

    @type parent_pid: int
    @param parent_pid: The pid for the Factory daemon

    @type sleep_time: int
    @param sleep_time: The number of seconds to sleep between iterations

    @type advertize_rate: int
    @param advertize_rate: The rate at which advertising should occur

    @type startup_dir: string
    @param startup_dir: The "home" directory for the entry.

    @type entry_names: string
    @param entry_names: The CVS name of the entries this process should work on 

    @type group_id: string
    @param group_id: Group id
    """

    # Assume name to be group_[0,1,2] etc. Only required to create log_dir
    # where tasks common to the group will be stored. There is no other 
    # significance to the group_name and number of entries supported by a group
    # can change between factory reconfigs

    group_name = "group_%s" % group_id

    os.chdir(startup_dir)

    # Setup the lock_dir
    gfi.factoryConfig.lock_dir = os.path.join(startup_dir, "lock")

    # Read information about the glidein and frontends
    glideinDescript = gfc.GlideinDescript()
    frontendDescript = gfc.FrontendDescript()

    # Load factory keys
    glideinDescript.load_pub_key()
    glideinDescript.load_old_rsa_key()

    # Dictionary of Entry objects this group will process
    my_entries = {}

    glidein_entries = glideinDescript.data['Entries']


    # Initiate the log_files
    log_dir = os.path.join(glideinDescript.data['LogDir'], 'factory')
    gfl.log_files = gfl.LogFiles(
        log_dir,
        float(glideinDescript.data['LogRetentionMaxDays']),
        float(glideinDescript.data['LogRetentionMinDays']),
        float(glideinDescript.data['LogRetentionMaxMBs']),
        file_name=group_name)
    gfi.factoryConfig.warning_log = gfl.log_files.warning_log

     
    gfl.log_files.logActivity("Starting up")
    gfl.log_files.logActivity("Entries processed by %s: %s " % (group_name, entry_names))


    # Check if all the entries in this group are valid
    for entry in string.split(entry_names, ':'):
        if not (entry in string.split(glidein_entries, ',')):
            msg = "Entry '%s' not configured: %s" % (entry, glidein_entries)
            gfl.log_files.logWarning(msg)
            raise RuntimeError, msg

        # Create entry objects
        my_entries[entry] = glideFactoryEntry.Entry(entry, startup_dir,
                                                    glideinDescript,
                                                    frontendDescript)

    # Create lock file for this group and register its parent
    pid_obj = glideFactoryPidLib.EntryGroupPidSupport(startup_dir, group_name)
    pid_obj.register(parent_pid)

    try:
        try:
            try:
                iterate(parent_pid, sleep_time, advertize_rate,
                        glideinDescript, frontendDescript,
                        group_name, my_entries)
            except KeyboardInterrupt:
                gfl.log_files.logActivity("Received signal...exit")
            except:
                tb = traceback.format_exception(sys.exc_info()[0],
                                                sys.exc_info()[1],
                                                sys.exc_info()[2])
                gfl.log_files.logWarning("Exception occurred: %s" % tb)
                raise
        finally:
            # No need to cleanup. The parent should be doing it
            gfl.log_files.logActivity("Dying")
    finally:
        pid_obj.relinquish()


################################################################################
# Pickle Friendly data
################################################################################

def compile_pickle_data(entry, work_done):
    """
    Extract the state of the entry after doing work

    @type entry: Entry
    @param entry: Entry object

    @type work_done: int
    @param work_done: Work done info
    """

    return_dict = entry.getState()
    return_dict['work_done'] = work_done

    return return_dict

############################################################
#
# S T A R T U P
#
############################################################

def termsignal(signr,frame):
    raise KeyboardInterrupt, "Received signal %s"%signr

if __name__ == '__main__':
    signal.signal(signal.SIGTERM, termsignal)
    signal.signal(signal.SIGQUIT, termsignal)

    # Force integrity checks on all condor operations
    gfl.set_condor_integrity_checks()

    main(sys.argv[1], int(sys.argv[2]), int(sys.argv[3]), 
         sys.argv[4], sys.argv[5], sys.argv[6])
