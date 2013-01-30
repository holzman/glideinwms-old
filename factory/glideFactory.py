#!/usr/bin/env python
#
# Project:
#   glideinWMS
#
# File Version: 
#
# Description:
#   This is the main of the glideinFactory
#
# Arguments:
#   $1 = glidein submit_dir
#
# Author:
#   Igor Sfiligoi (Apr 9th 2007 - moved old glideFactory to glideFactoryEntry)
#

import os
import sys
import resource

STARTUP_DIR=sys.path[0]

import math
import fcntl
import subprocess
import traceback
import signal
import time
import string
import copy

sys.path.append(os.path.join(STARTUP_DIR,"../lib"))

import glideFactoryPidLib
import glideFactoryConfig
import glideFactoryLib
import glideFactoryInterface
import glideFactoryMonitorAggregator
import glideFactoryMonitoring
import glideFactoryDowntimeLib

############################################################
def aggregate_stats(in_downtime):
    try:
        _ = glideFactoryMonitorAggregator.aggregateStatus(in_downtime)
    except:
        # protect and report
        tb = traceback.format_exception(sys.exc_info()[0],sys.exc_info()[1],
                                        sys.exc_info()[2])
        glideFactoryLib.log_files.logDebug("aggregateStatus failed: %s" % string.join(tb,''))
    
    try:
        _ = glideFactoryMonitorAggregator.aggregateLogSummary()
    except:
        # protect and report
        tb = traceback.format_exception(sys.exc_info()[0],sys.exc_info()[1],
                                        sys.exc_info()[2])
        glideFactoryLib.log_files.logDebug("aggregateLogStatus failed: %s" % string.join(tb,''))
    
    try:
        _ = glideFactoryMonitorAggregator.aggregateRRDStats(logfiles=glideFactoryLib.log_files)
    except:
        # protect and report
        tb = traceback.format_exception(sys.exc_info()[0],sys.exc_info()[1],
                                        sys.exc_info()[2])
        glideFactoryLib.log_files.logDebug("aggregateRRDStats failed: %s" % string.join(tb,''))
    
    return

# added by C.W. Murphy to make descript.xml
def write_descript(glideinDescript,frontendDescript,monitor_dir):
    glidein_data = copy.deepcopy(glideinDescript.data)
    frontend_data = copy.deepcopy(frontendDescript.data)
    entry_data = {}
    for entry in glidein_data['Entries'].split(","):
        entry_data[entry] = {}

        entryDescript = glideFactoryConfig.JobDescript(entry)
        entry_data[entry]['descript'] = entryDescript.data

        entryAttributes = glideFactoryConfig.JobAttributes(entry)
        entry_data[entry]['attributes'] = entryAttributes.data

        entryParams = glideFactoryConfig.JobParams(entry)
        entry_data[entry]['params'] = entryParams.data

    descript2XML = glideFactoryMonitoring.Descript2XML()
    xml_str = (descript2XML.glideinDescript(glidein_data) +
               descript2XML.frontendDescript(frontend_data) +
               descript2XML.entryDescript(entry_data))

    try:
        descript2XML.writeFile(monitor_dir, xml_str)
    except IOError:
        glideFactoryLib.log_files.logDebug("IOError in writeFile in descript2XML")
    # end add


############################################################

def entry_grouper(size, entries):
    """
    Group the entries into n smaller groups
    KNOWN ISSUE: Needs improvement to do better grouping in certain cases
    TODO: Migrate to itertools when only supporting python 2.6 and higher

    @type size: long
    @param size: Size of each subgroup
    @type entries: list
    @param size: List of entries
    
    @rtype: list
    @return: List of grouped entries. Each group is a list
    """

    list = []

    if size == 0: 
        return list

    if len(entries) <= size:
        list.insert(0,entries)
    else:
        for group in range(len(entries)/size):
            list.insert(group, entries[group*size:(group+1)*size])
    
        if (size*len(list) < len(entries)):
            list.insert(group+1, entries[(group+1)*size:])

    return list


############################################################
def is_crashing_often(startup_time, restart_interval, restart_attempts):
    crashing_often = True

    if (len(startup_time) < restart_attempts):
        # We haven't exhausted restart attempts
        crashing_often = False
    else:
        # Check if the service has been restarted often
        if restart_attempts == 1:
            crashing_often = True
        elif (time.time() - startup_time[0]) >= restart_interval:
            crashing_often = False
        else:
            crashing_often = True

    return crashing_often

def is_file_old(filename, allowed_time):
    """
    Check if the file is older than given time

    @type filename: String 
    @param filename: Full path to the file
    @type allowed_time: long
    @param allowed_time: Time is second
    
    @rtype: bool
    @return: True if file is older than the given time, else False 
    """
    if (time.time() > (os.path.getmtime(filename) + allowed_time)):
        return True
    return False

############################################################
def clean_exit(childs):
    count=100000000 # set it high, so it is triggered at the first iteration
    sleep_time=0.1 # start with very little sleep
    while len(childs)>0:
        count+=1
        if count>4:
            # Send a term signal to the childs
            # May need to do it several times, in case there are in the middle of something
            count = 0
            glideFactoryLib.log_files.logActivity("Killing EntryGroups %s" % childs.keys())
            for group in childs:
                try:
                    os.kill(childs[group].pid,signal.SIGTERM)
                except OSError:
                    glideFactoryLib.log_files.logActivity("Already dead EntryGroup %s: %s" % (group,childs[group]))
                    del childs[group] # already dead
            
        glideFactoryLib.log_files.logActivity("Sleep")
        time.sleep(sleep_time)
        # exponentially increase, up to 5 secs
        sleep_time=sleep_time*2
        if sleep_time>5:
            sleep_time=5
        
        glideFactoryLib.log_files.logActivity("Checking dying EntryGroups %s" % childs.keys())
        dead_entries=[]
        for group in childs:
            child=childs[group]

            # empty stdout and stderr
            try:
                tempOut = child.stdout.read()
                if len(tempOut)!=0:
                    glideFactoryLib.log_files.logWarning("EntryGroup %s STDOUT: %s"%(group, tempOut))
            except IOError:
                pass # ignore
            try:
                tempErr = child.stderr.read()
                if len(tempErr)!=0:
                    glideFactoryLib.log_files.logWarning("EntryGroup %s STDERR: %s"%(group, tempErr))
            except IOError:
                pass # ignore

            # look for exited child
            if child.poll() is not None:
                # the child exited
                dead_entries.append(group)
                del childs[group]
                tempOut = child.stdout.readlines()
                tempErr = child.stderr.readlines()
        if len(dead_entries)>0:
            glideFactoryLib.log_files.logActivity("These EntryGroups died: %s"%dead_entries)

    glideFactoryLib.log_files.logActivity("All EntryGroups dead")


############################################################
def spawn(sleep_time, advertize_rate, startup_dir, glideinDescript,
          entries, restart_attempts, restart_interval):

    global STARTUP_DIR
    childs={}

    # Number of glideFactoryEntry processes to spawn and directly relates to 
    # number of concurrent condor_status processess
    # 
    # NOTE: If number of entries gets too big, we may excede the shell args 
    #       limit. If that becomes an issue, move the logic to identify the 
    #       entries to serve to the group itself.
    #
    # Each process will handle multiple entries split as follows
    #   - Sort the entries alphabetically. Already done
    #   - Divide the list into equal chunks as possible
    #   - Last chunk may get fewer entries
    entry_process_count = 1

    starttime = time.time()
    oldkey_gracetime = int(glideinDescript.data['OldPubKeyGraceTime'])
    oldkey_eoltime = starttime + oldkey_gracetime
    
    childs_uptime={}

    factory_downtimes = glideFactoryDowntimeLib.DowntimeFile(glideinDescript.data['DowntimesFile'])

    glideFactoryLib.log_files.logActivity("Starting entries %s" % entries)

    group_size = long(math.ceil(float(len(entries))/entry_process_count))
    entry_groups = entry_grouper(group_size, entries)
    def _set_rlimit():
        resource.setrlimit(resource.RLIMIT_NOFILE, [1024, 1024])

    try:
        for group in range(len(entry_groups)):
            entry_names = string.join(entry_groups[group], ':')
            glideFactoryLib.log_files.logActivity("Starting EntryGroup %s: %s" % (group, entry_groups[group]))
            
            # Converted to using the subprocess module
            command_list = [sys.executable, 
                            os.path.join(STARTUP_DIR,"glideFactoryEntryGroup.py"),
                            str(os.getpid()),
                            str(sleep_time),
                            str(advertize_rate),
                            startup_dir,
                            entry_names,
                            str(group)]
            childs[group] = subprocess.Popen(command_list, shell=False,
                                             stdout=subprocess.PIPE,
                                             stderr=subprocess.PIPE,
                                             close_fds=True,
                                             preexec_fn=_set_rlimit)

            # Get the startup time. Used to check if the entry is crashing
            # periodically and needs to be restarted.
            childs_uptime[group] = list()
            childs_uptime[group].insert(0, time.time())

        glideFactoryLib.log_files.logActivity("EntryGroup startup times: %s"%childs_uptime)

        for group in childs:
            #childs[group].tochild.close()
            # set it in non blocking mode
            # since we will run for a long time, we do not want to block
            for fd  in (childs[group].stdout.fileno(),
                        childs[group].stderr.fileno()):
                fl = fcntl.fcntl(fd, fcntl.F_GETFL)
                fcntl.fcntl(fd, fcntl.F_SETFL, fl | os.O_NONBLOCK)

        while 1:
            # THIS IS FOR SECURITY
            # Make sure you delete the old key when its grace is up.
            # If a compromised key is left around and if attacker can somehow 
            # trigger FactoryEntry process crash, we do not want the entry to pick up 
            # the old key again when factory auto restarts it.  
            if ( (time.time() > oldkey_eoltime) and 
             (glideinDescript.data['OldPubKeyObj'] is not None) ):
                glideinDescript.data['OldPubKeyObj'] = None
                glideinDescript.data['OldPubKeyType'] = None
                try:
                    glideinDescript.remove_old_key()
                    glideFactoryLib.log_files.logActivity("Removed the old public key after its grace time of %s seconds" % oldkey_gracetime)
                except:
                    # Do not crash if delete fails. Just log it.
                    glideFactoryLib.log_files.logActivity("Failed to remove the old public key after its grace time")
                    glideFactoryLib.log_files.logWarning("Failed to remove the old public key after its grace time")

            glideFactoryLib.log_files.logActivity("Checking EntryGroups %s" % (group))
            for group in childs:
                entry_names = string.join(entry_groups[group], ':')
                child=childs[group]

                # empty stdout and stderr
                try:
                    tempOut = child.stdout.read()
                    if len(tempOut)!=0:
                        glideFactoryLib.log_files.logWarning("EntryGroup %s STDOUT: %s"%(group, tempOut))
                except IOError:
                    pass # ignore
                try:
                    tempErr = child.stderr.read()
                    if len(tempErr)!=0:
                        glideFactoryLib.log_files.logWarning("EntryGroup %s STDERR: %s"%(group, tempErr))
                except IOError:
                    pass # ignore
                
                # look for exited child
                if child.poll() is not None:
                    # the child exited
                    glideFactoryLib.log_files.logWarning("EntryGroup %s exited. Checking if it should be restarted."%(group))
                    tempOut = child.stdout.readlines()
                    tempErr = child.stderr.readlines()

                    if is_crashing_often(childs_uptime[group],
                                         restart_interval, restart_attempts):
                        del childs[group]
                        raise RuntimeError,"EntryGroup '%s' has been crashing too often, quit the whole factory:\n%s\n%s"%(group,tempOut,tempErr)
                    else:
                        # Restart the entry setting its restart time
                        glideFactoryLib.log_files.logWarning("Restarting EntryGroup %s."%(group))
                        del childs[group]

                        command_list = [sys.executable,
                                        os.path.join(STARTUP_DIR,
                                                     "glideFactoryEntryGroup.py"),
                                        str(os.getpid()),
                                        str(sleep_time),
                                        str(advertize_rate),
                                        startup_dir,
                                        entry_names,
                                        str(group)]
                        childs[group] = subprocess.Popen(
                                                 command_list, shell=False,
                                                 stdout=subprocess.PIPE,
                                                 stderr=subprocess.PIPE)
                        if len(childs_uptime[group]) == restart_attempts:
                            childs_uptime[group].pop(0)
                        childs_uptime[group].append(time.time())
                        childs[group].tochild.close()
                        for fd  in (childs[group].stdout.fileno(),
                                    childs[group].stderr.fileno()):
                            fl = fcntl.fcntl(fd, fcntl.F_GETFL)
                            fcntl.fcntl(fd, fcntl.F_SETFL, fl | os.O_NONBLOCK)
                        glideFactoryLib.log_files.logWarning("EntryGroup startup/restart times: %s"%childs_uptime)

            # Aggregate Monitoring data periodically
            glideFactoryLib.log_files.logActivity("Aggregate monitoring data")
            aggregate_stats(factory_downtimes.checkDowntime())
            
            # do it just before the sleep
            glideFactoryLib.log_files.cleanup()

            glideFactoryLib.log_files.logActivity("Sleep %s secs" % sleep_time)
            time.sleep(sleep_time)
    finally:        
        # cleanup at exit
        glideFactoryLib.log_files.logActivity("Received signal...exit")
        try:
            try:
                clean_exit(childs)
            except:
                # if anything goes wrong, hardkill the rest
                for group in childs:
                    glideFactoryLib.log_files.logActivity("Hard killing entry %s"%group)
                    try:
                        os.kill(childs[group].pid,signal.SIGKILL)
                    except OSError:
                        pass # ignore dead clients
        finally:
            glideFactoryLib.log_files.logActivity("Deadvertize myself")
            try:
                glideFactoryInterface.deadvertizeFactory(glideinDescript.data['FactoryName'],
                                                         glideinDescript.data['GlideinName'])
            except:
                glideFactoryLib.log_files.logWarning("Factory deadvertize failed!")
                pass # just warn
            try:
                glideFactoryInterface.deadvertizeFactoryClientMonitoring(glideinDescript.data['FactoryName'],
                                                                         glideinDescript.data['GlideinName'])
            except:
                glideFactoryLib.log_files.logWarning("Factory Monitoring deadvertize failed!")
                pass # just warn
        glideFactoryLib.log_files.logActivity("All entries should be terminated")
        
        
############################################################
def main(startup_dir):
    """
    Reads in the configuration file and starts up the factory
    
    @type startup_dir: String 
    @param startup_dir: Path to glideinsubmit directory
    """

    # We don't use this anywhere?
    #startup_time = time.time()

    # Force integrity checks on all condor operations
    glideFactoryLib.set_condor_integrity_checks()

    glideFactoryInterface.factoryConfig.lock_dir=os.path.join(startup_dir,"lock")

    glideFactoryConfig.factoryConfig.glidein_descript_file=os.path.join(startup_dir,glideFactoryConfig.factoryConfig.glidein_descript_file)
    glideinDescript=glideFactoryConfig.GlideinDescript()
    frontendDescript = glideFactoryConfig.FrontendDescript()

    write_descript(glideinDescript,frontendDescript,os.path.join(startup_dir, 'monitor/'))

    # the log dir is shared between the factory main and the entries, so use a subdir
    log_dir=os.path.join(glideinDescript.data['LogDir'],"factory")

    # Configure the process to use the proper LogDir as soon as you get the info
    glideFactoryLib.log_files=glideFactoryLib.LogFiles(
        log_dir,
        float(glideinDescript.data['LogRetentionMaxDays']),
        float(glideinDescript.data['LogRetentionMinDays']),
        float(glideinDescript.data['LogRetentionMaxMBs']))

    try:
        os.chdir(startup_dir)
    except:
        tb = traceback.format_exception(sys.exc_info()[0],sys.exc_info()[1],
                                        sys.exc_info()[2])
        glideFactoryLib.log_files.logWarning("Unable to change to startup_dir %s: %s" % (startup_dir,tb))
        raise

    try:
        
        if (is_file_old(glideinDescript.default_rsakey_fname, 
                        int(glideinDescript.data['OldPubKeyGraceTime']))):
            # First back and load any existing key
            glideFactoryLib.log_files.logActivity("Backing up and loading old key")
            glideinDescript.backup_and_load_old_key()
            # Create a new key for this run
            glideFactoryLib.log_files.logActivity("Recreating and loading new key")
            glideinDescript.load_pub_key(recreate=True)
        else:
            # Key is recent enough. Just reuse them.
            glideFactoryLib.log_files.logActivity("Key is recent enough")
            glideFactoryLib.log_files.logActivity("Reusing key for this run")
            glideinDescript.load_pub_key(recreate=False)
            glideFactoryLib.log_files.logActivity("Loading old key")
            glideinDescript.load_old_rsa_key()
        
        glideFactoryMonitorAggregator.glideFactoryMonitoring.monitoringConfig.my_name="%s@%s"%(glideinDescript.data['GlideinName'],glideinDescript.data['FactoryName'])

        # check that the GSI environment is properly set
        if not os.environ.has_key('X509_CERT_DIR'):
            if os.path.isdir('/etc/grid-security/certificates'):
                os.environ['X509_CERT_DIR']='/etc/grid-security/certificates'
                glideFactoryLib.log_files.logActivity("Environment variable X509_CERT_DIR not set, defaulting to /etc/grid-security/certificates")
            else:  
                glideFactoryLib.log_files.logWarning("Environment variable X509_CERT_DIR not set and /etc/grid-security/certificates does not exist. Need X509_CERT_DIR to work!")
                raise RuntimeError, "Need X509_CERT_DIR to work!"

        allowed_proxy_source=glideinDescript.data['AllowedJobProxySource'].split(',')
        if 'factory' in allowed_proxy_source:
            if not os.environ.has_key('X509_USER_PROXY'):
                glideFactoryLib.log_files.logWarning("Factory is supposed to allow provide a proxy, but environment variable X509_USER_PROXY not set. Need X509_USER_PROXY to work!")
                raise RuntimeError, "Factory is supposed to allow provide a proxy. Need X509_USER_PROXY to work!"
            


        glideFactoryInterface.factoryConfig.advertise_use_tcp=(glideinDescript.data['AdvertiseWithTCP'] in ('True','1'))
        glideFactoryInterface.factoryConfig.advertise_use_multi=(glideinDescript.data['AdvertiseWithMultiple'] in ('True','1'))
        sleep_time=int(glideinDescript.data['LoopDelay'])
        advertize_rate=int(glideinDescript.data['AdvertiseDelay'])
        restart_attempts=int(glideinDescript.data['RestartAttempts'])
        restart_interval=int(glideinDescript.data['RestartInterval'])
        
        entries=string.split(glideinDescript.data['Entries'],',')
        entries.sort()

        glideFactoryMonitorAggregator.monitorAggregatorConfig.config_factory(os.path.join(startup_dir,"monitor"),entries)
    except:
        tb = traceback.format_exception(sys.exc_info()[0],sys.exc_info()[1],
                                        sys.exc_info()[2])
        glideFactoryLib.log_files.logWarning("Exception occurred: %s" % tb)
        raise

    # create lock file
    pid_obj=glideFactoryPidLib.FactoryPidSupport(startup_dir)
    
    # start
    pid_obj.register()
    try:
        try:
            spawn(sleep_time, advertize_rate, startup_dir, glideinDescript,
                  entries, restart_attempts, restart_interval)
        except KeyboardInterrupt,e:
            raise e
        except:
            tb = traceback.format_exception(sys.exc_info()[0],sys.exc_info()[1],
                                            sys.exc_info()[2])
            glideFactoryLib.log_files.logWarning("Exception occurred: %s" % tb)
    finally:
        pid_obj.relinquish()
    
############################################################
#
# S T A R T U P
#
############################################################

def termsignal(signr,frame):
    raise KeyboardInterrupt, "Received signal %s"%signr

if __name__ == '__main__':
    os.setpgid(os.getpid(), os.getpid())
    signal.signal(signal.SIGTERM,termsignal)
    signal.signal(signal.SIGQUIT,termsignal)

    try:
        main(sys.argv[1])
    except KeyboardInterrupt,e:
        glideFactoryLib.log_files.logActivity("Terminating: %s"%e)
