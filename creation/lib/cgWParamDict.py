#######################################################
#
# Glidein creation module
# Classes and functions needed to handle dictionary files
# created out of the parameter object
#
#######################################################

import os,os.path,shutil,string
import cWParams
import cgWDictFile,cWDictFile
import cgWCreate
import cgWConsts,cWConsts

################################################
#
# This Class contains the main dicts
#
################################################

class glideinMainDicts(cgWDictFile.glideinMainDicts):
    def __init__(self,params,workdir_name):
        cgWDictFile.glideinMainDicts.__init__(self,params.submit_dir,params.stage_dir,workdir_name,
                                              params.log_dir,
                                              params.client_log_dirs,params.client_proxies_dirs)
        self.monitor_dir=params.monitor_dir
        self.add_dir_obj(cWDictFile.monitorWLinkDirSupport(self.monitor_dir,self.work_dir))
        self.monitor_jslibs_dir=os.path.join(self.monitor_dir,'jslibs')
        self.add_dir_obj(cWDictFile.simpleDirSupport(self.monitor_jslibs_dir,"monitor"))
        self.params=params
        self.active_sub_list=[]
        self.monitor_jslibs=[]
        self.monitor_htmls=[]

    def populate(self,params=None):
        if params==None:
            params=self.params

        # put default files in place first
        self.dicts['file_list'].add_placeholder(cWConsts.CONSTS_FILE,allow_overwrite=True)
        self.dicts['file_list'].add_placeholder(cWConsts.VARS_FILE,allow_overwrite=True)
        self.dicts['file_list'].add_placeholder(cWConsts.UNTAR_CFG_FILE,allow_overwrite=True) # this one must be loaded before any tarball
        
        # Load initial system scripts
        # These should be executed before the other scripts
        for script_name in ('cat_consts.sh','setup_x509.sh'):
            self.dicts['file_list'].add_from_file(script_name,(cWConsts.insert_timestr(script_name),'exec','TRUE','FALSE'),os.path.join(params.src_dir,script_name))

        #load system files
        for file_name in ('parse_starterlog.awk', "condor_config", "condor_config.multi_schedd.include", "condor_config.dedicated_starter.include", "condor_config.monitor.include" ):
            self.dicts['file_list'].add_from_file(file_name,(cWConsts.insert_timestr(file_name),"regular","TRUE",'FALSE'),os.path.join(params.src_dir,file_name))
        self.dicts['description'].add("condor_config","condor_config")
        self.dicts['description'].add("condor_config.multi_schedd.include","condor_config_multi_include")
        self.dicts['description'].add("condor_config.dedicated_starter.include","condor_config_main_include")
        self.dicts['description'].add("condor_config.monitor.include","condor_config_monitor_include")
        self.dicts['vars'].load(params.src_dir,'condor_vars.lst',change_self=False,set_not_changed=False)

        # put user files in stage
        for file in params.files:
            add_file_unparsed(file,self.dicts)

        # put user attributes into config files
        for attr_name in params.attrs.keys():
            add_attr_unparsed(attr_name, params,self.dicts,"main")

        # add the basic standard params
        self.dicts['params'].add("GLIDEIN_Collector",'Fake')

        # Prepare to load condor tarballs (after entry, as I may need data from there)
        for script_name in ('validate_node.sh','condor_platform_select.sh'):
            self.dicts['after_file_list'].add_from_file(script_name,(cWConsts.insert_timestr(script_name),'exec','TRUE','FALSE'),os.path.join(params.src_dir,script_name))
                
        #load condor tarballs
        for condor_idx in range(len(params.condor_tarballs)):
            condor_el=params.condor_tarballs[condor_idx]
            condor_platform="%s-%s-%s"%(condor_el.version,condor_el.os,condor_el.arch)
            cond_name="CONDOR_PLATFORM_%s"%condor_platform
            condor_fname=cgWConsts.CONDOR_FILE%condor_platform
            # register the tarball, but make the download conditional to cond_name
            if condor_el.tar_file!=None: # condor tarball available
                self.dicts['after_file_list'].add_from_file(condor_fname,(cWConsts.insert_timestr(condor_fname),"untar",cond_name,cgWConsts.CONDOR_ATTR),condor_el.tar_file)
            else: # create a new tarball
                condor_fd=cgWCreate.create_condor_tar_fd(condor_el.base_dir)
                condor_fname=cWConsts.insert_timestr(condor_fname)
                self.dicts['after_file_list'].add_from_fd(condor_fname,(condor_fname,"untar",cond_name,cgWConsts.CONDOR_ATTR),condor_fd)
                condor_fd.close()
                # insert the newly created tarball fname back into the config
                params.subparams.data['condor_tarballs'][condor_idx]['tar_file']=os.path.join(self.dicts['file_list'].dir,condor_fname)
            # add cond_name in the config, so that it is known it is there
            # but leave it disabled by default
            self.dicts['consts'].add(cond_name,"0",allow_overwrite=False)
            self.dicts['untar_cfg'].add(condor_fname,cgWConsts.CONDOR_DIR)

        # add additional system scripts
        for script_name in ('create_mapfile.sh','collector_setup.sh','gcb_setup.sh','glexec_setup.sh'):
            self.dicts['after_file_list'].add_from_file(script_name,(cWConsts.insert_timestr(script_name),'exec','TRUE','FALSE'),os.path.join(params.src_dir,script_name))
                
        # this must be the last script in the list
        for script_name in (cgWConsts.CONDOR_STARTUP_FILE,):
            self.dicts['after_file_list'].add_from_file(script_name,(cWConsts.insert_timestr(script_name),'exec','TRUE','FALSE'),os.path.join(params.src_dir,script_name))
        self.dicts['description'].add(cgWConsts.CONDOR_STARTUP_FILE,"last_script")

        # populate complex files
        populate_factory_descript(self.work_dir,self.dicts['glidein'],self.active_sub_list,params)
        populate_frontend_descript(self.dicts['frontend_descript'],params)


        # populate the monitor files
        javascriptrrd_dir=os.path.join(params.monitor.javascriptRRD_dir,'src/lib')
        for mfarr in ((params.src_dir,'factory_support.js'),
                      (javascriptrrd_dir,'rrdFlot.js'),
                      (javascriptrrd_dir,'rrdFlotMatrix.js'),
                      (javascriptrrd_dir,'rrdFlotSupport.js'),
                      (javascriptrrd_dir,'rrdFile.js'),
                      (javascriptrrd_dir,'rrdMultiFile.js'),
                      (javascriptrrd_dir,'rrdFilter.js'),
                      (javascriptrrd_dir,'binaryXHR.js'),
                      (params.monitor.flot_dir,'jquery.flot.js'),
                      (params.monitor.flot_dir,'jquery.flot.selection.js'),
                      (params.monitor.flot_dir,'excanvas.js'),
                      (params.monitor.jquery_dir,'jquery.js')):
            mfdir,mfname=mfarr
            mfobj=cWDictFile.SimpleFile(mfdir,mfname)
            mfobj.load()
            self.monitor_jslibs.append(mfobj)

        for mfarr in ((params.src_dir,'factoryRRDBrowse.html'),
                      (params.src_dir,'factoryRRDEntryMatrix.html'),
                      (params.src_dir,'factoryStatus.html'),
                      (params.src_dir,'factoryLogStatus.html'),
                      (params.src_dir,'factoryCompletedStats.html')):
            mfdir,mfname=mfarr
            mfobj=cWDictFile.SimpleFile(mfdir,mfname)
            mfobj.load()
            self.monitor_htmls.append(mfobj)

        # populate the monitor configuration file
        #populate_monitor_config(self.work_dir,self.dicts['glidein'],params)

    # reuse as much of the other as possible
    def reuse(self,other):             # other must be of the same class
        if self.monitor_dir!=other.monitor_dir:
            raise RuntimeError,"Cannot change main monitor base_dir! '%s'!='%s'"%(self.monitor_dir,other.monitor_dir)
        
        return cgWDictFile.glideinMainDicts.reuse(self,other)

    def save(self,set_readonly=True):
        cgWDictFile.glideinMainDicts.save(self,set_readonly)
        self.save_pub_key()
        self.save_monitor()
        self.save_monitor_config(self.work_dir,self.dicts['glidein'],self.params)


    ########################################
    # INTERNAL
    ########################################
    
    def save_pub_key(self):
        if self.params.security.pub_key=='None':
            pass # nothing to do
        elif self.params.security.pub_key=='RSA':
            import pubCrypto
            rsa_key_fname=os.path.join(self.work_dir,cgWConsts.RSA_KEY)

            if not os.path.isfile(rsa_key_fname):
                # create the key only once

                # touch the file with correct flags first
                # I have no way to do it in  RSAKey class
                fd=os.open(rsa_key_fname,os.O_CREAT,0600)
                os.close(fd)
                
                key_obj=pubCrypto.RSAKey()
                key_obj.new(int(self.params.security.key_length))
                key_obj.save(rsa_key_fname)            
        else:
            raise RuntimeError,"Invalid value for security.pub_key(%s), must be either None or RSA"%self.params.security.pub_key

    def save_monitor(self):
        for fobj in self.monitor_jslibs:
            fobj.save(dir=self.monitor_jslibs_dir,save_only_if_changed=False)
        for fobj in self.monitor_htmls:
            fobj.save(dir=self.monitor_dir,save_only_if_changed=False)
        return

    ###################################
    # Create the monitor config file
    def save_monitor_config(self, work_dir, glidein_dict, params):
        monitor_config_file = os.path.join(params.monitor_dir, cgWConsts.MONITOR_CONFIG_FILE)
        monitor_config_line = []
        
        monitor_config_fd = open(monitor_config_file,'w')
        monitor_config_line.append("<monitor_config>")
        monitor_config_line.append("  <entries>")
        try:
          try:
            for sub in params.entries.keys():
                if eval(params.entries[sub].enabled,{},{}):
                    monitor_config_line.append("    <entry name=\"%s\">" % sub)
                    monitor_config_line.append("      <monitorgroups>")                
                    for group in params.entries[sub].monitorgroups:
                        monitor_config_line.append("        <monitorgroup group_name=\"%s\">" % group['group_name'])
                        monitor_config_line.append("        </monitorgroup>")
                    
                    monitor_config_line.append("      </monitorgroups>")
                    monitor_config_line.append("    </entry>")
    
            monitor_config_line.append("  </entries>")
            monitor_config_line.append("</monitor_config>")
    
            for line in monitor_config_line:
                monitor_config_fd.write(line + "\n")
          except IOError,e:
            raise RuntimeError,"Error writing into file %s"%filepath
        finally:
            monitor_config_fd.close()
    
################################################
#
# This Class contains the entry dicts
#
################################################

class glideinEntryDicts(cgWDictFile.glideinEntryDicts):
    def __init__(self,params,sub_name,
                 summary_signature,workdir_name):
        cgWDictFile.glideinEntryDicts.__init__(self,params.submit_dir,params.stage_dir,sub_name,summary_signature,workdir_name,
                                               params.log_dir,params.client_log_dirs,params.client_proxies_dirs)
                                               
        self.monitor_dir=cgWConsts.get_entry_monitor_dir(params.monitor_dir,sub_name)
        self.add_dir_obj(cWDictFile.monitorWLinkDirSupport(self.monitor_dir,self.work_dir))
        self.params=params

    def erase(self):
        cgWDictFile.glideinEntryDicts.erase(self)
        self.dicts['condor_jdl']=cgWCreate.GlideinSubmitDictFile(self.work_dir,cgWConsts.SUBMIT_FILE)
        
    def load(self):
        cgWDictFile.glideinEntryDicts.load(self)
        self.dicts['condor_jdl'].load()

    def save_final(self,set_readonly=True):
        sub_stage_dir=cgWConsts.get_entry_stage_dir("",self.sub_name)
        
        self.dicts['condor_jdl'].finalize(self.summary_signature['main'][0],self.summary_signature[sub_stage_dir][0],
                                          self.summary_signature['main'][1],self.summary_signature[sub_stage_dir][1])
        self.dicts['condor_jdl'].save(set_readonly=set_readonly)
        
    
    def populate(self,params=None):
        if params==None:
            params=self.params

        sub_params=params.entries[self.sub_name]

        # put default files in place first
        self.dicts['file_list'].add_placeholder(cWConsts.CONSTS_FILE,allow_overwrite=True)
        self.dicts['file_list'].add_placeholder(cWConsts.VARS_FILE,allow_overwrite=True)
        self.dicts['file_list'].add_placeholder(cWConsts.UNTAR_CFG_FILE,allow_overwrite=True) # this one must be loaded before any tarball

        # follow by the blacklist file
        file_name=cWConsts.BLACKLIST_FILE
        self.dicts['file_list'].add_from_file(file_name,(file_name,"nocache","TRUE",'BLACKLIST_FILE'),os.path.join(params.src_dir,file_name))

        # Load initial system scripts
        # These should be executed before the other scripts
        for script_name in ('cat_consts.sh',"check_blacklist.sh"):
            self.dicts['file_list'].add_from_file(script_name,(cWConsts.insert_timestr(script_name),'exec','TRUE','FALSE'),os.path.join(params.src_dir,script_name))

        #load system files
        self.dicts['vars'].load(params.src_dir,'condor_vars.lst.entry',change_self=False,set_not_changed=False)
        
        # put user files in stage
        for file in sub_params.files:
            add_file_unparsed(file,self.dicts)

        # put user attributes into config files
        for attr_name in sub_params.attrs.keys():
            add_attr_unparsed(attr_name, sub_params,self.dicts,self.sub_name)

        # put standard attributes into config file
        # override anything the user set
        for dtype in ('attrs','consts'):
            self.dicts[dtype].add("GLIDEIN_Gatekeeper",sub_params.gatekeeper,allow_overwrite=True)
            self.dicts[dtype].add("GLIDEIN_GridType",sub_params.gridtype,allow_overwrite=True)
            if sub_params.rsl!=None:
                self.dicts[dtype].add('GLIDEIN_GlobusRSL',sub_params.rsl,allow_overwrite=True)

        # populate infosys
        for infosys_ref in sub_params.infosys_refs:
            self.dicts['infosys'].add_extended(infosys_ref['type'],infosys_ref['server'],infosys_ref['ref'],allow_overwrite=True)

        # populate monitorgroups
        for monitorgroup in sub_params.monitorgroups:
            self.dicts['mongroup'].add_extended(monitorgroup['group_name'],allow_overwrite=True)

        # populate complex files
        populate_job_descript(self.work_dir,self.dicts['job_descript'],
                              self.sub_name,sub_params)

        self.dicts['condor_jdl'].populate(cgWConsts.STARTUP_FILE,
                                          params.factory_name,params.glidein_name,self.sub_name,
                                          sub_params.gridtype,sub_params.gatekeeper,sub_params.rsl,
                                          params.web_url,sub_params.proxy_url,sub_params.work_dir,
                                          params.submit.base_client_log_dir)

    # reuse as much of the other as possible
    def reuse(self,other):             # other must be of the same class
        if self.monitor_dir!=other.monitor_dir:
            raise RuntimeError,"Cannot change entry monitor base_dir! '%s'!='%s'"%(self.monitor_dir,other.monitor_dir)
        
        return cgWDictFile.glideinEntryDicts.reuse(self,other)

################################################
#
# This Class contains both the main and
# the entry dicts
#
################################################

class glideinDicts(cgWDictFile.glideinDicts):
    def __init__(self,params,
                 sub_list=None): # if None, get it from params
        if sub_list==None:
            sub_list=params.entries.keys()

        self.params=params
        cgWDictFile.glideinDicts.__init__(self,params.submit_dir,params.stage_dir,params.log_dir,params.client_log_dirs,params.client_proxies_dirs,sub_list)

        self.monitor_dir=params.monitor_dir
        self.active_sub_list=[]
        return

    def populate(self,params=None): # will update params (or self.params)
        if params==None:
            params=self.params
        
        self.main_dicts.populate(params)
        self.active_sub_list=self.main_dicts.active_sub_list

        self.local_populate(params)
        for sub_name in self.sub_list:
            self.sub_dicts[sub_name].populate(params)

    # reuse as much of the other as possible
    def reuse(self,other):             # other must be of the same class
        if self.monitor_dir!=other.monitor_dir:
            raise RuntimeError,"Cannot change monitor base_dir! '%s'!='%s'"%(self.monitor_dir,other.monitor_dir)
        
        return cgWDictFile.glideinDicts.reuse(self,other)

    ###########
    # PRIVATE
    ###########

    def local_populate(self,params):
        # make sure all the schedds are defined
        # if not, define them, in place, so thet it get recorded
        global_schedd_names=string.split(params.schedd_name,',')
        global_schedd_idx=0
        for sub_name in self.sub_list:
            if params.entries[sub_name].schedd_name==None:
                # use one of the global ones if specific not provided
                schedd_name=global_schedd_names[global_schedd_idx%len(global_schedd_names)]
                global_schedd_idx=global_schedd_idx+1
                params.subparams.data['entries'][sub_name]['schedd_name']=schedd_name
        return
        

    ######################################
    # Redefine methods needed by parent
    def new_MainDicts(self):
        return glideinMainDicts(self.params,self.workdir_name)

    def new_SubDicts(self,sub_name):
        return glideinEntryDicts(self.params,sub_name,
                                 self.main_dicts.get_summary_signature(),self.workdir_name)

############################################################
#
# P R I V A T E - Do not use
# 
############################################################

#############################################
# Add a user file residing in the stage area
# file as described by Params.file_defaults
def add_file_unparsed(file,dicts):
    absfname=file.absfname
    if absfname==None:
        raise RuntimeError, "Found a file element without an absname: %s"%file
    
    relfname=file.relfname
    if relfname==None:
        relfname=os.path.basename(absfname) # defualt is the final part of absfname
    if len(relfname)<1:
        raise RuntimeError, "Found a file element with an empty relfname: %s"%file

    is_const=eval(file.const,{},{})
    is_executable=eval(file.executable,{},{})
    is_wrapper=eval(file.wrapper,{},{})
    do_untar=eval(file.untar,{},{})

    file_list_idx='file_list'
    if file.has_key('after_entry'):
        if eval(file.after_entry,{},{}):
            file_list_idx='after_file_list'

    if is_executable: # a script
        if not is_const:
            raise RuntimeError, "A file cannot be executable if it is not constant: %s"%file
    
        if do_untar:
            raise RuntimeError, "A tar file cannot be executable: %s"%file

        if is_wrapper:
            raise RuntimeError, "A wrapper file cannot be executable: %s"%file

        dicts[file_list_idx].add_from_file(relfname,(cWConsts.insert_timestr(relfname),"exec","TRUE",'FALSE'),absfname)
    elif is_wrapper: # a sourceable script for the wrapper
        if not is_const:
            raise RuntimeError, "A file cannot be a wrapper if it is not constant: %s"%file
    
        if do_untar:
            raise RuntimeError, "A tar file cannot be a wrapper: %s"%file

        dicts[file_list_idx].add_from_file(relfname,(cWConsts.insert_timestr(relfname),"wrapper","TRUE",'FALSE'),absfname)
    elif do_untar: # a tarball
        if not is_const:
            raise RuntimeError, "A file cannot be untarred if it is not constant: %s"%file

        wnsubdir=file.untar_options.dir
        if wnsubdir==None:
            wnsubdir=string.split(relfname,'.',1)[0] # deafult is relfname up to the first .

        config_out=file.untar_options.absdir_outattr
        if config_out==None:
            config_out="FALSE"
        cond_attr=file.untar_options.cond_attr


        dicts[file_list_idx].add_from_file(relfname,(cWConsts.insert_timestr(relfname),"untar",cond_attr,config_out),absfname)
        dicts['untar_cfg'].add(relfname,wnsubdir)
    else: # not executable nor tarball => simple file
        if is_const:
            val='regular'
            dicts[file_list_idx].add_from_file(relfname,(cWConsts.insert_timestr(relfname),val,'TRUE','FALSE'),absfname)
        else:
            val='nocache'
            dicts[file_list_idx].add_from_file(relfname,(relfname,val,'TRUE','FALSE'),absfname) # no timestamp if it can be modified

#######################
# Register an attribute
# attr_obj as described by Params.attr_defaults
def add_attr_unparsed(attr_name,params,dicts,description):
    try:
        add_attr_unparsed_real(attr_name,params,dicts)
    except RuntimeError,e:
        raise RuntimeError, "Error parsing attr %s[%s]: %s"%(description,attr_name,str(e))

def add_attr_unparsed_real(attr_name,params,dicts):
    attr_obj=params.attrs[attr_name]
    
    if attr_obj.value==None:
        raise RuntimeError, "Attribute '%s' does not have a value: %s"%(attr_name,attr_obj)
    
    do_publish=eval(attr_obj.publish,{},{})
    is_parameter=eval(attr_obj.parameter,{},{})
    is_const=eval(attr_obj.const,{},{})
    attr_val=params.extract_attr_val(attr_obj)
    
    if do_publish: # publish in factory ClassAd
        if is_parameter: # but also push to glidein
            if is_const:
                dicts['attrs'].add(attr_name,attr_val)
                dicts['consts'].add(attr_name,attr_val)
            else:
                dicts['params'].add(attr_name,attr_val)
        else: # only publish
            if (not is_const):
                raise RuntimeError, "Published attribute '%s' must be either a parameter or constant: %s"%(attr_name,attr_obj)
            
            dicts['attrs'].add(attr_name,attr_val)
    else: # do not publish, only to glidein
        if is_parameter:
            if is_const:
                dicts['consts'].add(attr_name,attr_val)
            else:
                raise RuntimeError, "Parameter attributes '%s' must be either a published or constant: %s"%(attr_name,attr_obj)
        else:
            raise RuntimeError, "Attributes '%s' must be either a published or parameters: %s"%(attr_name,attr_obj) 

    do_glidein_publish=eval(attr_obj.glidein_publish,{},{})
    do_job_publish=eval(attr_obj.job_publish,{},{})

    if do_glidein_publish or do_job_publish:
            # need to add a line only if will be published
            if dicts['vars'].has_key(attr_name):
                # already in the var file, check if compatible
                attr_var_el=dicts['vars'][attr_name]
                attr_var_type=attr_var_el[0]
                if (((attr_obj.type=="int") and (attr_var_type!='I')) or
                    ((attr_obj.type=="expr") and (attr_var_type=='I')) or
                    ((attr_obj.type=="string") and (attr_var_type=='I'))):
                    raise RuntimeError, "Types not compatible (%s,%s)"%(attr_obj.type,attr_var_type)
                attr_var_export=attr_var_el[4]
                if do_glidein_publish and (attr_var_export=='N'):
                    raise RuntimeError, "Cannot force glidein publishing"
                attr_var_job_publish=attr_var_el[5]
                if do_job_publish and (attr_var_job_publish=='-'):
                    raise RuntimeError, "Cannot force job publishing"
            else:
                dicts['vars'].add_extended(attr_name,attr_obj.type,None,None,False,do_glidein_publish,do_job_publish)

###################################
# Create the glidein descript file
def populate_factory_descript(work_dir,
                              glidein_dict,active_sub_list,        # will be modified
                              params):
        # if a user does not provide a file name, use the default one
        down_fname=params.downtimes.absfname
        if down_fname==None:
            down_fname=os.path.join(work_dir,'factory.downtimes')

        glidein_dict.add('FactoryName',params.factory_name)
        glidein_dict.add('GlideinName',params.glidein_name)
        glidein_dict.add('WebURL',params.web_url)
        glidein_dict.add('PubKeyType',params.security.pub_key)
        del active_sub_list[:] # clean

        for sub in params.entries.keys():
            if eval(params.entries[sub].enabled,{},{}):
                active_sub_list.append(sub)

        glidein_dict.add('Entries',string.join(active_sub_list,','))
        glidein_dict.add('LoopDelay',params.loop_delay)
        glidein_dict.add('AdvertiseDelay',params.advertise_delay)
        glidein_dict.add('RestartAttempts',params.restart_attempts)
        glidein_dict.add('RestartInterval',params.restart_interval)
        glidein_dict.add('AdvertiseDelay',params.advertise_delay)
        validate_job_proxy_source(params.security.allow_proxy)
        glidein_dict.add('AllowedJobProxySource',params.security.allow_proxy)
        glidein_dict.add('LogDir',params.log_dir)
        glidein_dict.add('ClientLogBaseDir',params.submit.base_client_log_dir)
        glidein_dict.add('ClientProxiesBaseDir',params.submit.base_client_proxies_dir)
        glidein_dict.add('DowntimesFile',down_fname)
        for lel in (("logs",'Log'),("job_logs",'JobLog'),("summary_logs",'SummaryLog'),("condor_logs",'CondorLog')):
            param_lname,str_lname=lel
            for tel in (("max_days",'MaxDays'),("min_days",'MinDays'),("max_mbytes",'MaxMBs')):
                param_tname,str_tname=tel
                glidein_dict.add('%sRetention%s'%(str_lname,str_tname),params.log_retention[param_lname][param_tname])


#######################
# Populate job_descript
def populate_job_descript(work_dir,job_descript_dict,        # will be modified
                          sub_name,sub_params):
    # if a user does not provide a file name, use the default one
    down_fname=sub_params.downtimes.absfname
    if down_fname==None:
        down_fname=os.path.join(work_dir,'entry.downtimes')

    job_descript_dict.add('EntryName',sub_name)
    job_descript_dict.add('GridType',sub_params.gridtype)
    job_descript_dict.add('Gatekeeper',sub_params.gatekeeper)
    if sub_params.rsl!=None:
        job_descript_dict.add('GlobusRSL',sub_params.rsl)
    job_descript_dict.add('Schedd',sub_params.schedd_name)
    job_descript_dict.add('StartupDir',sub_params.work_dir)
    if sub_params.proxy_url!=None:
        job_descript_dict.add('ProxyURL',sub_params.proxy_url)
    job_descript_dict.add('Verbosity',sub_params.verbosity)
    job_descript_dict.add('DowntimesFile',down_fname)
    job_descript_dict.add('MaxRunning',sub_params.config.max_jobs.running)
    job_descript_dict.add('MaxIdle',sub_params.config.max_jobs.idle)
    job_descript_dict.add('MaxHeld',sub_params.config.max_jobs.held)
    job_descript_dict.add('MaxSubmitRate',sub_params.config.submit.max_per_cycle)
    job_descript_dict.add('SubmitCluster',sub_params.config.submit.cluster_size)
    job_descript_dict.add('SubmitSleep',sub_params.config.submit.sleep)
    job_descript_dict.add('MaxRemoveRate',sub_params.config.remove.max_per_cycle)
    job_descript_dict.add('RemoveSleep',sub_params.config.remove.sleep)
    job_descript_dict.add('MaxReleaseRate',sub_params.config.release.max_per_cycle)
    job_descript_dict.add('ReleaseSleep',sub_params.config.release.sleep)

###################################
# Create the frontend descript file
def populate_frontend_descript(frontend_dict,     # will be modified
                               params):
    for fe in params.security.frontends.keys():
        fe_el=params.security.frontends[fe]

        ident=fe_el['identity']
        if ident==None:
            raise RuntimeError, 'security.frontends[%s][identity] not defined, but required'%fe

        maps={}
        for sc in fe_el['security_classes'].keys():
            sc_el=fe_el['security_classes'][sc]
            username=sc_el['username']
            if username==None:
                raise RuntimeError, 'security.frontends[%s].security_sclasses[%s][username] not defined, but required'%(fe,sc)
            maps[sc]=username
        
        frontend_dict.add(fe,{'ident':ident,'usermap':maps})

    
#################################
# Check that it is a string list
# containing only valid entries
def validate_job_proxy_source(allow_proxy):
    recognized_sources=('factory','frontend')
    ap_list=allow_proxy.split(',')
    for source in ap_list:
        if not (source in recognized_sources):
            raise RuntimeError, "'%s' not a valid proxy source (valid list = %s)"%(source,recognized_sources)
    return

#####################
# Simply copy a file
def copy_file(infile,outfile):
    try:
        shutil.copy2(infile,outfile)
    except IOError, e:
        raise RuntimeError, "Error copying %s in %s: %s"%(infile,outfile,e)
        
