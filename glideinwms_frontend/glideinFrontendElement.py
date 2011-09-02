#!/usr/bin/env python
#
# Project:
#   glideinWMS
#
# File Version: 
#   $Id: glideinFrontendElement.py,v 1.52.2.32 2011/07/05 23:11:06 sfiligoi Exp $
#
# Description:
#   This is the main of the glideinFrontend
#
# Arguments:
#   $1 = parent PID
#   $2 = work dir
#   $3 = group_name
#
# Author:
#   Igor Sfiligoi (was glideinFrontend.py until Nov 21, 2008)
#

import signal
import sys,os,os.path,copy
import fcntl
import traceback
import time,string,cPickle,signal
sys.path.append(os.path.join(sys.path[0],"../lib"))

import symCrypto,pubCrypto

import glideinFrontendConfig
import glideinFrontendInterface
import glideinFrontendLib
import glideinFrontendPidLib
import glideinFrontendMonitoring
import glideinFrontendPlugins
import glideinWMSVersion

############################################################
def check_parent(parent_pid):
    if os.path.exists('/proc/%s'%parent_pid):
        return # parent still exists, we are fine
    
    glideinFrontendLib.log_files.logWarning("Parent died, exit.")
    raise KeyboardInterrupt,"Parent died"

############################################################
def write_stats(stats):
    for k in stats.keys():
        stats[k].write_file();

############################################################
# Will log the factory_stat_arr (tuple composed of 13 numbers)
# and return a sum of factory_stat_arr+old_factory_stat_arr
def log_and_sum_factory_line(factory,is_down,factory_stat_arr,old_factory_stat_arr):
    # if numbers are too big, reduce them to either k or M for presentation
    form_arr=[]
    for i in factory_stat_arr:
        if i<100000:
            form_arr.append("%5i"%i)
        elif i<10000000:
            form_arr.append("%4ik"%(i/1000))
        else:
            form_arr.append("%4iM"%(i/1000000))

    if is_down:
        down_str="Down"
    else:
        down_str="Up  "

    glideinFrontendLib.log_files.logActivity(("%s(%s %s %s %s) %s(%s %s) | %s %s %s | %s %s "%tuple(form_arr))+
                                             ("%s %s"%(down_str,factory)))

    new_arr=[]
    for i in range(len(factory_stat_arr)):
        new_arr.append(factory_stat_arr[i]+old_factory_stat_arr[i])
    return new_arr

def init_factory_stats_arr():
    new_arr=[]
    for i in range(13):
        new_arr.append(0)
    return new_arr

def log_factory_header():
    glideinFrontendLib.log_files.logActivity("            Jobs in schedd queues                 |      Glideins     |   Request   ")
    glideinFrontendLib.log_files.logActivity("Idle (match  eff   old  uniq )  Run ( here  max ) | Total Idle   Run  | Idle MaxRun Down Factory")

###############################
# to be used with fork clients
# Args:
#  r    - input pipe
#  pid - pid of the child
def fetch_fork_result(r,pid):
    try:
        rin=""
        s=os.read(r,1024*1024)
        while (s!=""): # "" means EOF
            rin+=s
            s=os.read(r,1024*1024) 
    finally:
        os.close(r)
        os.waitpid(pid,0)

    out=cPickle.loads(rin)
    return out

# in: pipe_is - dictionary, each element is {'r':r,'pid':pid} - see above
# out: dictionary of fork_results
def fetch_fork_result_list(pipe_ids):
    out={}
    failures=0
    for k in pipe_ids.keys():
        try:
            # now collect the results
            rin=fetch_fork_result(pipe_ids[k]['r'],pipe_ids[k]['pid'])
            out[k]=rin
        except:
            # protect the loop, so we do all of them
            tb = traceback.format_exception(sys.exc_info()[0],sys.exc_info()[1],
                                            sys.exc_info()[2])
            glideinFrontendLib.log_files.logWarning("Exception in %s. See debug log for more details."%k)
            glideinFrontendLib.log_files.logDebug("Exception in %s occurred: %s" % (k,tb))
            failures+=1
        
    if failures>0:
        raise RuntimeError, "Found %i errors"%failures

    return out
        

############################################################
def iterate_one(client_name,elementDescript,paramsDescript,signatureDescript,x509_proxy_plugin,stats,history_obj):
    frontend_name=elementDescript.frontend_data['FrontendName']
    group_name=elementDescript.element_data['GroupName']
    security_name=elementDescript.merged_data['SecurityName']

    web_url=elementDescript.frontend_data['WebURL']

    # query condor
    glideinFrontendLib.log_files.logActivity("Query condor")

    pipe_ids={}
    r,w=os.pipe()
    pid=os.fork()
    if pid==0:
        # this is the child... return output as a pickled object via the pipe
        os.close(r)
        try:
            glidein_dict={}
            factory_constraint=elementDescript.merged_data['FactoryQueryExpr']
            factory_pools=elementDescript.merged_data['FactoryCollectors']
            for factory_pool in factory_pools:
                factory_pool_node=factory_pool[0]
                factory_identity=factory_pool[1]
                my_identity_at_factory_pool=factory_pool[2]
                try:
                    factory_glidein_dict=glideinFrontendInterface.findGlideins(factory_pool_node,None,signatureDescript.signature_type,factory_constraint,x509_proxy_plugin!=None,get_only_matching=True)
                except RuntimeError,e:
                    if factory_pool_node!=None:
                        glideinFrontendLib.log_files.logWarning("Failed to talk to factory_pool %s. See debug log for more details."%factory_pool_node)
                        glideinFrontendLib.log_files.logDebug("Failed to talk to factory_pool %s: %s"%(factory_pool_node, e))
                    else:
                        glideinFrontendLib.log_files.logWarning("Failed to talk to factory_pool. See debug log for more details.")
                        glideinFrontendLib.log_files.logDebug("Failed to talk to factory_pool: %s"%e)
                    # failed to talk, like empty... maybe the next factory will have something
                    factory_glidein_dict={}

                for glidename in factory_glidein_dict.keys():
                    if (not factory_glidein_dict[glidename]['attrs'].has_key('AuthenticatedIdentity')) or (factory_glidein_dict[glidename]['attrs']['AuthenticatedIdentity']!=factory_identity):
                        glideinFrontendLib.log_files.logWarning("Found an untrusted factory %s at %s; ignoring."%(glidename,factory_pool_node))
                        if factory_glidein_dict[glidename]['attrs'].has_key('AuthenticatedIdentity'):
                            glideinFrontendLib.log_files.logDebug("Found an untrusted factory %s at %s; identity mismatch '%s'!='%s'"%(glidename,factory_pool_node,factory_glidein_dict[glidename]['attrs']['AuthenticatedIdentity'],factory_identity))
                    else:
                        glidein_dict[(factory_pool_node,glidename,my_identity_at_factory_pool)]=factory_glidein_dict[glidename]

            os.write(w,cPickle.dumps(glidein_dict))
        finally:
            os.close(w)
            # hard kill myself... don't want any cleanup, since i was created just for this calculation
            os.kill(os.getpid(),signal.SIGKILL) 
    else:
        # this is the original
        # just remember what you did for now
        os.close(w)
        pipe_ids['entries']={'r':r,'pid':pid} 

    ## schedd
    r,w=os.pipe()
    pid=os.fork()
    if pid==0:
        # this is the child... return output as a pickled object via the pipe
        os.close(r)
        try:
            condorq_format_list=elementDescript.merged_data['JobMatchAttrs']
            if x509_proxy_plugin!=None:
                condorq_format_list=list(condorq_format_list)+list(x509_proxy_plugin.get_required_job_attributes())

            ### Add in elements to help in determining if jobs have voms creds
            condorq_format_list=list(condorq_format_list)+list((('x509UserProxyFirstFQAN','s'),))
            condorq_format_list=list(condorq_format_list)+list((('x509UserProxyFQAN','s'),))
            condorq_dict=glideinFrontendLib.getCondorQ(elementDescript.merged_data['JobSchedds'],
                                                       elementDescript.merged_data['JobQueryExpr'],
                                                       condorq_format_list)

            os.write(w,cPickle.dumps(condorq_dict))
        finally:
            os.close(w)
            # hard kill myself... don't want any cleanup, since i was created just for this calculation
            os.kill(os.getpid(),signal.SIGKILL) 
    else:
        # this is the original
        # just remember what you did for now
        os.close(w)
        pipe_ids['jobs']={'r':r,'pid':pid} 

    r,w=os.pipe()
    pid=os.fork()
    if pid==0:
        # this is the child... return output as a pickled object via the pipe
        os.close(r)
        try:
            status_format_list=[]
            if x509_proxy_plugin!=None:
                status_format_list=list(status_format_list)+list(x509_proxy_plugin.get_required_classad_attributes())

            # use the main collector... all adds must go there
            status_dict=glideinFrontendLib.getCondorStatus([None],
                                                           'GLIDECLIENT_Name=?="%s.%s"'%(frontend_name,group_name),
                                                           status_format_list)

            os.write(w,cPickle.dumps(status_dict))
        finally:
            os.close(w)
            # hard kill myself... don't want any cleanup, since i was created just for this calculation
            os.kill(os.getpid(),signal.SIGKILL) 
    else:
        # this is the original
        # just remember what you did for now
        os.close(w)
        pipe_ids['startds']={'r':r,'pid':pid} 
 
    glideinFrontendLib.log_files.logActivity("Child processes created")
    try:
        pipe_out=fetch_fork_result_list(pipe_ids)
    except RuntimeError, e:
        # expect all errors logged already
        glideinFrontendLib.log_files.logActivity("Terminating iteration due to errors")
        return
    glideinFrontendLib.log_files.logActivity("All children terminated")

    glidein_dict=pipe_out['entries']
    condorq_dict=pipe_out['jobs']
    status_dict=pipe_out['startds']

    condorq_dict_voms=glideinFrontendLib.getIdleVomsCondorQ(condorq_dict)
    condorq_dict_idle=glideinFrontendLib.getIdleCondorQ(condorq_dict)
    condorq_dict_old_idle=glideinFrontendLib.getOldCondorQ(condorq_dict_idle,600)
    condorq_dict_running=glideinFrontendLib.getRunningCondorQ(condorq_dict)
    
    condorq_dict_types={'Idle':{'dict':condorq_dict_idle,'abs':glideinFrontendLib.countCondorQ(condorq_dict_idle)},
                        'OldIdle':{'dict':condorq_dict_old_idle,'abs':glideinFrontendLib.countCondorQ(condorq_dict_old_idle)},
                        'VomsIdle':{'dict':condorq_dict_voms,'abs':glideinFrontendLib.countCondorQ(condorq_dict_voms)},
                        'Running':{'dict':condorq_dict_running,'abs':glideinFrontendLib.countCondorQ(condorq_dict_running)}}
    condorq_dict_abs=glideinFrontendLib.countCondorQ(condorq_dict);
    

    stats['group'].logJobs({'Total':condorq_dict_abs,
                            'Idle':condorq_dict_types['Idle']['abs'],
                            'OldIdle':condorq_dict_types['OldIdle']['abs'],
                            'Running':condorq_dict_types['Running']['abs']})

    glideinFrontendLib.log_files.logActivity("Jobs found total %i idle %i (old %i, voms %i) running %i"%(condorq_dict_abs,
                                                                                                condorq_dict_types['Idle']['abs'],
                                                                                                condorq_dict_types['VomsIdle']['abs'],
                                                                                                condorq_dict_types['OldIdle']['abs'],
                                                                                                condorq_dict_types['Running']['abs']))

    status_dict_idle=glideinFrontendLib.getIdleCondorStatus(status_dict)
    status_dict_running=glideinFrontendLib.getRunningCondorStatus(status_dict)

    #glideinFrontendLib.log_files.logDebug("condor stat: %s\n\n" % status_dict_running[None].fetchStored())

    glideinFrontendLib.appendRealRunning(condorq_dict_running, status_dict_running)

    #glideinFrontendLib.log_files.logDebug("condorq running: %s\n\n" % condorq_dict_running['devg-1.t2.ucsd.edu'].fetchStored())

    status_dict_types={'Total':{'dict':status_dict,'abs':glideinFrontendLib.countCondorStatus(status_dict)},
                       'Idle':{'dict':status_dict_idle,'abs':glideinFrontendLib.countCondorStatus(status_dict_idle)},
                       'Running':{'dict':status_dict_running,'abs':glideinFrontendLib.countCondorStatus(status_dict_running)}}

    stats['group'].logGlideins({'Total':status_dict_types['Total']['abs'],
                            'Idle':status_dict_types['Idle']['abs'],
                            'Running':status_dict_types['Running']['abs']})

    total_max_glideins=int(elementDescript.element_data['MaxRunningTotal'])
    total_curb_glideins=int(elementDescript.element_data['CurbRunningTotal'])
    total_glideins=status_dict_types['Total']['abs']
    
    glideinFrontendLib.log_files.logActivity("Glideins found total %i idle %i running %i limit %i curb %i"%
                                             (total_glideins,
                                              status_dict_types['Idle']['abs'],
                                              status_dict_types['Running']['abs'],
                                              total_max_glideins,total_curb_glideins)
                                             )

    # extract the public key, if present
    for glideid in glidein_dict.keys():
        glidein_el=glidein_dict[glideid]
        if not glidein_el['attrs'].has_key('PubKeyType'): # no pub key at all
            pass # no public key, nothing to do
        elif glidein_el['attrs']['PubKeyType']=='RSA': # only trust RSA for now
            try:
                glidein_el['attrs']['PubKeyObj']=pubCrypto.PubRSAKey(str(string.replace(glidein_el['attrs']['PubKeyValue'],'\\n','\n')))
            except:
                # if no valid key, just notify...
                # if key needed, will handle the error later on
                glideinFrontendLib.log_files.logWarning("Factory '%s@%s': invalid RSA key"%(glideid[1],glideid[0]))
        else:
            # don't know what to do with this key, notify the admin
            # if key needed, will handle the error later on
            glideinFrontendLib.log_files.logActivity("Factory '%s@%s': unsupported pub key type '%s'"%(glideid[1],glideid[0],glidein_el['attrs']['PubKeyType']))

    # get the proxy
    x509_proxies_data=None
    if x509_proxy_plugin!=None:
        proxy_security_classes=elementDescript.merged_data['ProxySecurityClasses']
        x509_proxy_list=x509_proxy_plugin.get_proxies(condorq_dict,condorq_dict_types,
                                                      status_dict,status_dict_types)
        glideinFrontendLib.log_files.logActivity("Using %i proxies"%len(x509_proxy_list))
        
        x509_proxies_data=[]
        for x509_proxy_list_el in x509_proxy_list:
            proxy_idx,proxy_fname=x509_proxy_list_el

            # should check if proxy has a refresh script, and call it
            # elementDescript.merged_data['ProxyRefreshScripts']
            # To be implemented

            try:
                proxy_fd=open(proxy_fname,'r')
                try:
                    proxy_data=proxy_fd.read()
                finally:
                    proxy_fd.close()
                if proxy_security_classes.has_key(proxy_fname):
                    proxy_security_class=proxy_security_classes[proxy_fname]
                else:
                    proxy_security_class=proxy_idx
                x509_proxies_data.append((proxy_idx,proxy_data,proxy_security_class))
            except:
                glideinFrontendLib.log_files.logWarning("Could not read proxy file '%s'"%proxy_fname)
                pass # do nothing else, just warn
        if len(x509_proxies_data)==0:
            glideinFrontendLib.log_files.logWarning("All proxies failed, not advertizing")
            return
        
        # ignore glidein factories that do not have a public key
        # have no way to give them the proxy
        for glideid in glidein_dict.keys():
            glidein_el=glidein_dict[glideid]
            if not glidein_el['attrs'].has_key('PubKeyObj'):
                glideinFrontendLib.log_files.logActivity("Ignoring factory '%s@%s': does not have a valid key, but x509_proxy specified"%(glideid[1],glideid[0]))
                del glidein_dict[glideid]


    # here we have all the data needed to build a GroupAdvertizeType object
    descript_obj=glideinFrontendInterface.FrontendDescript(client_name,frontend_name,group_name,
                                                           web_url,
                                                           signatureDescript.frontend_descript_fname, signatureDescript.group_descript_fname,
                                                           signatureDescript.signature_type, signatureDescript.frontend_descript_signature, signatureDescript.group_descript_signature,
                                                           x509_proxies_data)
    # reuse between loops might be a good idea, but this will work for now
    key_builder=glideinFrontendInterface.Key4AdvertizeBuilder()

    glideinFrontendLib.log_files.logActivity("Match")

    #glideinFrontendLib.log_files.logDebug("realcount: %s\n\n" % glideinFrontendLib.countRealRunning(elementDescript.merged_data['MatchExprCompiledObj'],condorq_dict_running,glidein_dict))

    glideinFrontendLib.log_files.logActivity("Counting")
    pipe_ids={}
    for dt in condorq_dict_types.keys()+['Real','Glidein']:
        # will make calculations in parallel,using multiple processes
        r,w=os.pipe()
        pid=os.fork()
        if pid==0:
            # this is the child... return output as a pickled object via the pipe
            os.close(r)
            try:
                if dt=='Real':
                    out=glideinFrontendLib.countRealRunning(elementDescript.merged_data['MatchExprCompiledObj'],condorq_dict_running,glidein_dict)
                elif dt=='Glidein':
                    count_status_multi={}
                    for glideid in glidein_dict.keys():
                        request_name=glideid[1]

                        count_status_multi[request_name]={}
                        for st in status_dict_types.keys():
                            c=glideinFrontendLib.getClientCondorStatus(status_dict_types[st]['dict'],frontend_name,group_name,request_name)
                            count_status_multi[request_name][st]=glideinFrontendLib.countCondorStatus(c)
                    out=count_status_multi
                else:
                    c,p,h=glideinFrontendLib.countMatch(elementDescript.merged_data['MatchExprCompiledObj'],condorq_dict_types[dt]['dict'],glidein_dict)
                    t=glideinFrontendLib.countCondorQ(condorq_dict_types[dt]['dict'])
                    out=(c,p,h,t)

                os.write(w,cPickle.dumps(out))
            finally:
                os.close(w)
                # hard kill myself... don't want any cleanup, since i was created just for this calculation
                os.kill(os.getpid(),signal.SIGKILL) 
        else:
            # this is the original
            # just remember what you did for now
            os.close(w)
            pipe_ids[dt]={'r':r,'pid':pid} 

    

    glideinFrontendLib.log_files.logActivity("Child processes created")
    try:
        pipe_out=fetch_fork_result_list(pipe_ids)
    except RuntimeError, e:
        # expect all errors logged already
        glideinFrontendLib.log_files.logActivity("Terminating iteration due to errors")
        return
    glideinFrontendLib.log_files.logActivity("All children terminated")

    for dt in condorq_dict_types.keys():
        el=condorq_dict_types[dt]
        (el['count'], el['prop'], el['hereonly'], el['total'])=pipe_out[dt]

    count_real=pipe_out['Real']
    count_status_multi=pipe_out['Glidein']

    max_running=int(elementDescript.element_data['MaxRunningPerEntry'])
    fraction_running=float(elementDescript.element_data['FracRunningPerEntry'])
    max_idle=int(elementDescript.element_data['MaxIdlePerEntry'])
    reserve_idle=int(elementDescript.element_data['ReserveIdlePerEntry'])
    max_vms_idle=int(elementDescript.element_data['MaxIdleVMsPerEntry'])
    curb_vms_idle=int(elementDescript.element_data['CurbIdleVMsPerEntry'])
    
    total_running=condorq_dict_types['Running']['total']
    glideinFrontendLib.log_files.logActivity("Total matching idle %i (old %i) running %i"%(condorq_dict_types['Idle']['total'],condorq_dict_types['OldIdle']['total'],total_running))


    glideid_list=glidein_dict.keys()
    glideid_list.sort() # sort for the sake of monitoring

    advertizer=glideinFrontendInterface.MultiAdvertizeWork(descript_obj)
    resource_advertiser = glideinFrontendInterface.ResourceClassadAdvertiser(multi_support=glideinFrontendInterface.frontendConfig.advertise_use_multi)
    
    log_factory_header()
    total_up_stats_arr=init_factory_stats_arr()
    total_down_stats_arr=init_factory_stats_arr()
    for glideid in glideid_list:
        if glideid==(None,None,None):
            continue # This is the special "Unmatched" entry
        factory_pool_node=glideid[0]
        request_name=glideid[1]
        my_identity=str(glideid[2]) # get rid of unicode
        glideid_str="%s@%s"%(request_name,factory_pool_node)
        glidein_el=glidein_dict[glideid]

        glidein_in_downtime=False
        if glidein_el['attrs'].has_key('GLIDEIN_In_Downtime'):
            glidein_in_downtime=(glidein_el['attrs']['GLIDEIN_In_Downtime']=='True')
            

        count_jobs={}     # straight match
        prop_jobs={}      # proportional subset for this entry
        hereonly_jobs={}  # can only run on this site
        for dt in condorq_dict_types.keys():
            count_jobs[dt]=condorq_dict_types[dt]['count'][glideid]
            prop_jobs[dt]=condorq_dict_types[dt]['prop'][glideid]
            hereonly_jobs[dt]=condorq_dict_types[dt]['hereonly'][glideid]

        count_status=count_status_multi[request_name]

        #If the glidein requires a voms proxy, only match voms idle jobs
        if glidein_el['attrs'].has_key('GLIDEIN_REQUIRE_VOMS'):
            #glideinFrontendLib.log_files.logActivity("Require VOMS found: %s" % glidein_el['attrs']['GLIDEIN_REQUIRE_VOMS'])
            if (glidein_el['attrs']['GLIDEIN_REQUIRE_VOMS']=="True"):
                prop_jobs['Idle']=prop_jobs['VomsIdle']
                glideinFrontendLib.log_files.logActivity("Voms proxy required, limiting idle glideins to: %i" % prop_jobs['Idle'])

        # effective idle is how much more we need
        # if there are idle slots, subtract them, they should match soon
        effective_idle=prop_jobs['Idle']-count_status['Idle']

        if effective_idle<0:
            effective_idle=0

        effective_oldidle=prop_jobs['OldIdle']-count_status['Idle']
        if effective_oldidle<0:
            effective_oldidle=0

        if count_status['Total']>=max_running:
            # have all the running jobs I wanted
            glidein_min_idle=0
        elif count_status['Idle']>=max_vms_idle:
            # enough idle vms, do not ask for more
            glidein_min_idle=0
        elif total_glideins>=total_max_glideins:
            # reached the system-wide limit
            glidein_min_idle=0
        elif (effective_idle>0):
            glidein_min_idle = effective_idle
            glidein_min_idle=glidein_min_idle/3 # since it takes a few cycles to stabilize, ask for only one third
            glidein_idle_reserve=effective_oldidle/3 # do not reserve any more than the number of old idles for reserve (/3)
            if glidein_idle_reserve>reserve_idle:
                glidein_idle_reserve=reserve_idle

            glidein_min_idle+=glidein_idle_reserve
            
            if glidein_min_idle>max_idle:
                glidein_min_idle=max_idle # but never go above max
            if glidein_min_idle>(max_running-count_status['Total']+glidein_idle_reserve):
                glidein_min_idle=(max_running-count_status['Total']+glidein_idle_reserve) # don't go over the max_running
            if glidein_min_idle>(total_max_glideins-total_glideins+glidein_idle_reserve):
                # don't go over the system-wide max
                # not perfect, given te number of entries, but better than nothing
                glidein_min_idle=(total_max_glideins-total_glideins+glidein_idle_reserve)
            if count_status['Idle']>=curb_vms_idle:
                glidein_min_idle/=2 # above first treshold, reduce
            if total_glideins>=total_curb_glideins:
                glidein_min_idle/=2 # above global treshold, reduce
            if glidein_min_idle<1:
                glidein_min_idle=1
        else:
            # no idle, make sure the glideins know it
            glidein_min_idle=0 

        glidein_min_idle=int(glidein_min_idle)

        # we don't need more slots than number of jobs in the queue (unless the fraction is positive)
        if (prop_jobs['Idle']+count_jobs['Running'])>0:
            glidein_max_run=int((prop_jobs['Idle']+count_jobs['Running'])*fraction_running+1)
        else:
            # the above calculation is always >0, but should be 0 if nothing in the user queue
            glidein_max_run=0

        remove_excess_wait=False # do not remove excessive glideins by default
        # keep track of how often idle was 0
        if not history_obj.has_key('idle0'):
            history_obj['idle0']={}
        history_idle0=history_obj['idle0']
        if not history_idle0.has_key(glideid):
            history_idle0[glideid]=0
        if count_jobs['Idle']==0:
            # no idle jobs in the queue left
            # consider asking for unsubmitted idle glideins to be removed
            history_idle0[glideid]+=1
            if history_idle0[glideid]>5:
                # nobody asked for anything more for some time, so
                remove_excess_wait=True
        else:
            history_idle0[glideid]=0

        remove_excess_idle=False # do not remove excessive glideins by default

        # keep track of how often glideidle was 0
        if not history_obj.has_key('glideempty'):
            history_obj['glideempty']={}
        history_glideempty=history_obj['glideempty']
        if not history_glideempty.has_key(glideid):
            history_glideempty[glideid]=0
        if count_status['Idle']>=count_status['Total']:
            # no glideins being used
            # consider asking for all idle glideins to be removed
            history_glideempty[glideid]+=1
            if remove_excess_wait and (history_glideempty[glideid]>10):
                # no requests and no glideins being used
                # no harm getting rid of everything
                remove_excess_idle=True
        else:
            history_glideempty[glideid]=0

        remove_excess_running=False # do not remove excessive glideins by default

        # keep track of how often glidetotal was 0
        if not history_obj.has_key('glidetotal0'):
            history_obj['glidetotal0']={}
        history_glidetotal0=history_obj['glidetotal0']
        if not history_glidetotal0.has_key(glideid):
            history_glidetotal0[glideid]=0
        if count_status['Total']==0:
            # no glideins registered
            # consider asking for all idle glideins to be removed
            history_glidetotal0[glideid]+=1
            if remove_excess_wait and (history_glidetotal0[glideid]>10):
                # no requests and no glidein registered
                # no harm getting rid of everything
                remove_excess_running=True
        else:
            history_glidetotal0[glideid]=0

        if remove_excess_running:
            remove_excess_str="ALL"
        elif remove_excess_idle:
            remove_excess_str="IDLE"
        elif remove_excess_wait:
            remove_excess_str="WAIT"
        else:
            remove_excess_str="NO"

        this_stats_arr=(prop_jobs['Idle'],count_jobs['Idle'],effective_idle,prop_jobs['OldIdle'],hereonly_jobs['Idle'],count_jobs['Running'],count_real[glideid],max_running,
                        count_status['Total'],count_status['Idle'],count_status['Running'],
                        glidein_min_idle,glidein_max_run)

        stats['group'].logMatchedJobs(
            glideid_str, prop_jobs['Idle'],effective_idle, prop_jobs['OldIdle'],
            count_jobs['Running'], count_real[glideid])

        stats['group'].logMatchedGlideins(
            glideid_str, count_status['Total'],count_status['Idle'],
            count_status['Running'])

        stats['group'].logFactAttrs(glideid_str, glidein_el['attrs'], ('PubKeyValue','PubKeyObj'))

        stats['group'].logFactDown(glideid_str, glidein_in_downtime)

        if glidein_in_downtime:
            total_down_stats_arr=log_and_sum_factory_line(glideid_str,glidein_in_downtime,this_stats_arr,total_down_stats_arr)
        else:
            total_up_stats_arr=log_and_sum_factory_line(glideid_str,glidein_in_downtime,this_stats_arr,total_up_stats_arr)

        # get the parameters
        glidein_params=copy.deepcopy(paramsDescript.const_data)
        for k in paramsDescript.expr_data.keys():
            kexpr=paramsDescript.expr_objs[k]
            # convert kexpr -> kval
            glidein_params[k]=glideinFrontendLib.evalParamExpr(kexpr,paramsDescript.const_data,glidein_el)

        stats['group'].logFactReq(
            glideid_str, glidein_min_idle, glidein_max_run, glidein_params)

        glidein_monitors={}
        for t in count_jobs.keys():
            glidein_monitors[t]=count_jobs[t]
        
        glidein_monitors['RunningHere'] = count_real[glideid]
        
        for t in count_status.keys():
            glidein_monitors['Glideins%s'%t]=count_status[t]
        if descript_obj.need_encryption():
            key_obj=key_builder.get_key_obj(my_identity,
                                            glidein_el['attrs']['PubKeyID'],glidein_el['attrs']['PubKeyObj'])
        else:
            if (glidein_el['attrs'].has_key('PubKeyObj') and glidein_el['attrs'].has_key('PubKeyID')):
                # still want to encript the security_name
                key_obj=key_builder.get_key_obj(my_identity,
                                                glidein_el['attrs']['PubKeyID'],glidein_el['attrs']['PubKeyObj'])
            else:
                # if no proxies, encryption is not required
                key_obj=None

        advertizer.add(factory_pool_node,
                       request_name,request_name,
                       glidein_min_idle,glidein_max_run,glidein_params,glidein_monitors,
                       remove_excess_str=remove_excess_str,
                       key_obj=key_obj,glidein_params_to_encrypt=None,security_name=security_name)

        
        # Create the resource classad and populate the required information
        resource_classad = glideinFrontendInterface.ResourceClassad(request_name, client_name)
        resource_classad.setInDownTime(glidein_in_downtime)
        resource_classad.setEntryInfo(glidein_el['attrs'])
        resource_classad.setGlideFactoryMonitorInfo(glidein_el['monitor'])
        try:
            resource_classad.setGlideClientMonitorInfo(this_stats_arr)
        except RuntimeError, e:
            glideinFrontendLib.log_files.logWarning("Error populating GlideClientMonitor info in the resource classad. See debug log for more details.")
            glideinFrontendLib.log_files.logDebug("Populating GlideClientMonitor info in resource classad failed: %s"%e)
                    
        resource_advertiser.addClassad(resource_classad.adParams['Name'], resource_classad)

    # end for glideid in condorq_dict_types['Idle']['count'].keys()

    # Print the totals
    # Ignore the resulting sum
    log_factory_header()
    log_and_sum_factory_line('Sum of useful factories',False,tuple(total_up_stats_arr),total_down_stats_arr)
    log_and_sum_factory_line('Sum of down factories',True,tuple(total_down_stats_arr),total_up_stats_arr)

    # Print unmatched... Ignore the resulting sum
    unmatched_idle=condorq_dict_types['Idle']['count'][(None,None,None)]
    unmatched_oldidle=condorq_dict_types['OldIdle']['count'][(None,None,None)]
    unmatched_running=condorq_dict_types['Running']['count'][(None,None,None)]

    stats['group'].logMatchedJobs(
        'Unmatched', unmatched_idle, unmatched_idle, unmatched_oldidle,
        unmatched_running, 0)
    
    stats['group'].logMatchedGlideins('Unmatched', 0,0,0) # Nothing running
    stats['group'].logFactAttrs('Unmatched', [], ()) # just for completeness
    stats['group'].logFactDown('Unmatched', True)
    stats['group'].logFactReq('Unmatched', 0, 0, {})

    this_stats_arr=(unmatched_idle,unmatched_idle,unmatched_idle,unmatched_oldidle,unmatched_idle,unmatched_running,0,0,
                    0,0,0, # glideins... none, since no matching
                    0,0)   # requested... none, since not matching
    log_and_sum_factory_line('Unmatched',True,this_stats_arr,total_down_stats_arr)
        
    # Advertise glideclient classads
    try:
        glideinFrontendLib.log_files.logActivity("Advertizing %i requests"%advertizer.get_queue_len())
        advertizer.do_advertize()
        glideinFrontendLib.log_files.logActivity("Done advertizing")
    except glideinFrontendInterface.MultiExeError, e:
        glideinFrontendLib.log_files.logWarning("Advertizing failed for %i requests. See debug log for more details."%len(e.arr))
        for ee in e.arr:
            glideinFrontendLib.log_files.logDebug("Advertizing failed: %s"%ee)
    except RuntimeError, e:
        glideinFrontendLib.log_files.logWarning("Advertizing failed. See debug log for more details.")
        glideinFrontendLib.log_files.logDebug("Advertizing failed: %s"%e)
    except:
        glideinFrontendLib.log_files.logWarning("Advertizing failed: Reason unknown")
        tb = traceback.format_exception(sys.exc_info()[0],sys.exc_info()[1],
                                        sys.exc_info()[2])
        glideinFrontendLib.log_files.logDebug("Advertizing failed: %s" % tb)


    # Advertise glideresource classads
    try:
        glideinFrontendLib.log_files.logActivity("Advertising %i glideresource classads to the user pool" %  len(resource_advertiser.classads))
        #glideinFrontendLib.log_files.logActivity("glideresource classads to advertise -\n%s" % resource_advertiser.getAllClassads())
        resource_advertiser.advertiseAllClassads()
        glideinFrontendLib.log_files.logActivity("Done advertising glideresource classads")
    except RuntimeError, e:
        glideinFrontendLib.log_files.logWarning("Advertising failed. See debug log for more details.")
        glideinFrontendLib.log_files.logDebug("Advertising failed: %s"%e)
    except:
        glideinFrontendLib.log_files.logWarning("Advertising failed: Reason unknown")
        tb = traceback.format_exception(sys.exc_info()[0],sys.exc_info()[1],
                                      sys.exc_info()[2])
        glideinFrontendLib.log_files.logDebug("Advertising failed: %s" % tb)

    return

############################################################
def iterate(parent_pid,elementDescript,paramsDescript,signatureDescript,x509_proxy_plugin):
    sleep_time=int(elementDescript.frontend_data['LoopDelay'])
    
    factory_pools=elementDescript.merged_data['FactoryCollectors']

    frontend_name=elementDescript.frontend_data['FrontendName']
    group_name=elementDescript.element_data['GroupName']

    stats={}
    history_obj={}

    if not elementDescript.frontend_data.has_key('X509Proxy'):
        published_frontend_name='%s.%s'%(frontend_name,group_name)
    else:
        # if using a VO proxy, label it as such
        # this way we don't risk of using the wrong proxy on the other side
        # if/when we decide to stop using the proxy
        published_frontend_name='%s.XPVO_%s'%(frontend_name,group_name)

    try:
        is_first=1
        while 1: # will exit by exception
            check_parent(parent_pid)
            glideinFrontendLib.log_files.logActivity("Iteration at %s" % time.ctime())
            try:
                # recreate every time (an easy way to start from a clean state)
                stats['group']=glideinFrontendMonitoring.groupStats()
                
                done_something=iterate_one(published_frontend_name,elementDescript,paramsDescript,signatureDescript,x509_proxy_plugin,stats,history_obj)
                
                glideinFrontendLib.log_files.logActivity("Writing stats")
                try:
                    write_stats(stats)
                except KeyboardInterrupt:
                    raise # this is an exit signal, pass through
                except:
                    # never fail for stats reasons!
                    tb = traceback.format_exception(sys.exc_info()[0],sys.exc_info()[1],
                                                    sys.exc_info()[2])
                    glideinFrontendLib.log_files.logWarning("Unhandled exception, ignoring. See debug log for more details.")
                    glideinFrontendLib.log_files.logDebug("Exception occurred: %s" % tb)
            except KeyboardInterrupt:
                raise # this is an exit signal, pass trough
            except:
                if is_first:
                    raise
                else:
                    # if not the first pass, just warn
                    tb = traceback.format_exception(sys.exc_info()[0],sys.exc_info()[1],
                                                    sys.exc_info()[2])
                    glideinFrontendLib.log_files.logWarning("Unhandled exception, ignoring. See debug log for more details.")
                    glideinFrontendLib.log_files.logDebug("Exception occurred: %s" % tb)
            is_first=0
            
            # do it just before the sleep
            glideinFrontendLib.log_files.cleanup()

            glideinFrontendLib.log_files.logActivity("Sleep")
            time.sleep(sleep_time)
    finally:
        glideinFrontendLib.log_files.logActivity("Deadvertize my ads")
        for factory_pool in factory_pools:
            factory_pool_node=factory_pool[0]
            try:
                glideinFrontendInterface.deadvertizeAllWork(factory_pool_node,published_frontend_name)
            except:
                pass # just ignore errors... this was cleanup

        # Invalidate all resource classads
        try:
            resource_advertiser = glideinFrontendInterface.ResourceClassadAdvertiser()
            resource_advertiser.invalidateConstrainedClassads('GlideClientName == "%s"' % published_frontend_name)
        except:
            # Ignore all errors
            pass
            

############################################################
def main(parent_pid, work_dir, group_name):
    startup_time=time.time()

    elementDescript=glideinFrontendConfig.ElementMergedDescript(work_dir,group_name)

    # the log dir is shared between the frontend main and the groups, so use a subdir
    log_dir=os.path.join(elementDescript.frontend_data['LogDir'],"group_%s"%group_name)

    # Configure the process to use the proper LogDir as soon as you get the info
    glideinFrontendLib.log_files=glideinFrontendLib.LogFiles(log_dir,
                                                             float(elementDescript.frontend_data['LogRetentionMaxDays']),
                                                             float(elementDescript.frontend_data['LogRetentionMinDays']),
                                                             float(elementDescript.frontend_data['LogRetentionMaxMBs']))

    paramsDescript=glideinFrontendConfig.ParamsDescript(work_dir,group_name)
    signatureDescript=glideinFrontendConfig.GroupSignatureDescript(work_dir,group_name)

    glideinFrontendMonitoring.monitoringConfig.monitor_dir=os.path.join(work_dir,"monitor/group_%s"%group_name)

    glideinFrontendInterface.frontendConfig.advertise_use_tcp=(elementDescript.frontend_data['AdvertiseWithTCP'] in ('True','1'))
    glideinFrontendInterface.frontendConfig.advertise_use_multi=(elementDescript.frontend_data['AdvertiseWithMultiple'] in ('True','1'))

    try:
        dir = os.path.dirname(os.path.dirname(sys.argv[0]))
        glideinFrontendInterface.frontendConfig.glideinwms_version = glideinWMSVersion.GlideinWMSDistro(dir, os.path.join(dir,'etc/checksum.frontend')).version()
    except:
        tb = traceback.format_exception(sys.exc_info()[0],sys.exc_info()[1],
                                        sys.exc_info()[2])
        glideinFrontendLib.log_files.logWarning("Exception occured while trying to retrieve the glideinwms version. See debug log for more details.")
        glideinFrontendLib.log_files.logDebug("Exception occurred: %s" % tb)    

    if len(elementDescript.merged_data['Proxies'])>0:
        if not glideinFrontendPlugins.proxy_plugins.has_key(elementDescript.merged_data['ProxySelectionPlugin']):
            glideinFrontendLib.log_files.logWarning("Invalid ProxySelectionPlugin '%s', supported plugins are %s"%(elementDescript.merged_data['ProxySelectionPlugin']),glideinFrontendPlugins.proxy_plugins.keys())
            return 1
        x509_proxy_plugin=glideinFrontendPlugins.proxy_plugins[elementDescript.merged_data['ProxySelectionPlugin']](os.path.join(work_dir,"group_%s"%group_name),elementDescript.merged_data['Proxies'])
    else:
        # no proxies, will try to use the factory one
        x509_proxy_plugin=None

    # set the condor configuration and GSI setup globally, so I don't need to worry about it later on
    os.environ['CONDOR_CONFIG']=elementDescript.frontend_data['CondorConfig']
    os.environ['_CONDOR_CERTIFICATE_MAPFILE']=elementDescript.element_data['MapFile']
    os.environ['X509_USER_PROXY']=elementDescript.frontend_data['ClassAdProxy']

    # create lock file
    pid_obj=glideinFrontendPidLib.ElementPidSupport(work_dir,group_name)

    pid_obj.register(parent_pid)
    try:
        try:
            glideinFrontendLib.log_files.logActivity("Starting up")
            iterate(parent_pid,elementDescript,paramsDescript,signatureDescript,x509_proxy_plugin)
        except KeyboardInterrupt:
            glideinFrontendLib.log_files.logActivity("Received signal...exit")
        except:
            tb = traceback.format_exception(sys.exc_info()[0],sys.exc_info()[1],
                                            sys.exc_info()[2])
            glideinFrontendLib.log_files.logWarning("Unhandled exception, dying. See debug log for more details.")
            glideinFrontendLib.log_files.logDebug("Exception occurred: %s" % tb)
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
    signal.signal(signal.SIGTERM,termsignal)
    signal.signal(signal.SIGQUIT,termsignal)
    main(sys.argv[1],sys.argv[2],sys.argv[3])
 
