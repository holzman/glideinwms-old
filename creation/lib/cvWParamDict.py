#######################################################
#
# Frontend creation module
# Classes and functions needed to handle dictionary files
# created out of the parameter object
#
#######################################################

import os,os.path,shutil,string
import cWParams
import cvWDictFile,cWDictFile
import cvWConsts,cWConsts
import cvWCreate

################################################
#
# This Class contains the main dicts
#
################################################

class frontendMainDicts(cvWDictFile.frontendMainDicts):
    def __init__(self,params,workdir_name):
        cvWDictFile.frontendMainDicts.__init__(self,params.work_dir,params.stage_dir,workdir_name,simple_work_dir=False,assume_groups=True,log_dir=params.log_dir)
        self.monitor_dir=params.monitor_dir
        self.add_dir_obj(cWDictFile.monitorWLinkDirSupport(self.monitor_dir,self.work_dir))
        self.monitor_jslibs_dir=os.path.join(self.monitor_dir,'jslibs')
        self.add_dir_obj(cWDictFile.simpleDirSupport(self.monitor_jslibs_dir,"monitor"))
        self.params=params
        self.active_sub_list=[]
        self.monitor_jslibs=[]
        self.monitor_htmls=[]
        self.client_security={}

    def populate(self,params=None):
        if params==None:
            params=self.params

        # put default files in place first
        self.dicts['preentry_file_list'].add_placeholder(cWConsts.CONSTS_FILE,allow_overwrite=True)
        self.dicts['preentry_file_list'].add_placeholder(cWConsts.VARS_FILE,allow_overwrite=True)
        self.dicts['preentry_file_list'].add_placeholder(cWConsts.UNTAR_CFG_FILE,allow_overwrite=True) # this one must be loaded before any tarball
        self.dicts['preentry_file_list'].add_placeholder(cWConsts.GRIDMAP_FILE,allow_overwrite=True) # this one must be loaded before factory runs setup_x509.sh
        
        # follow by the blacklist file
        file_name=cWConsts.BLACKLIST_FILE
        self.dicts['preentry_file_list'].add_from_file(file_name,(file_name,"nocache","TRUE",'BLACKLIST_FILE'),os.path.join(params.src_dir,file_name))

        # Load initial system scripts
        # These should be executed before the other scripts
        for script_name in ('cat_consts.sh',"check_blacklist.sh"):
            self.dicts['preentry_file_list'].add_from_file(script_name,(cWConsts.insert_timestr(script_name),'exec','TRUE','FALSE'),os.path.join(params.src_dir,script_name))

        # put user files in stage
        for file in params.files:
            add_file_unparsed(file,self.dicts)

        # put user attributes into config files
        for attr_name in params.attrs.keys():
            add_attr_unparsed(attr_name, params,self.dicts,"main")

        # create GLIDEIN_Collector attribute
        self.dicts['params'].add_extended('GLIDEIN_Collector',False,str(calc_glidein_collectors(params.collectors)))
        populate_gridmap(params,self.dicts['gridmap'])

        if self.dicts['preentry_file_list'].is_placeholder(cWConsts.GRIDMAP_FILE): # gridmapfile is optional, so if not loaded, remove the placeholder
            self.dicts['preentry_file_list'].remove(cWConsts.GRIDMAP_FILE)

        # populate complex files
        populate_frontend_descript(self.work_dir,self.dicts['frontend_descript'],self.active_sub_list,params)
        populate_common_descript(self.dicts['frontend_descript'],params)

        # populate the monitor files
        javascriptrrd_dir=os.path.join(params.monitor.javascriptRRD_dir,'src/lib')
        for mfarr in ((params.src_dir,'frontend_support.js'),
                      (javascriptrrd_dir,'rrdFlot.js'),
                      (javascriptrrd_dir,'rrdFlotMatrix.js'),
                      (javascriptrrd_dir,'rrdFlotSupport.js'),
                      (javascriptrrd_dir,'rrdFile.js'),
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

        for mfarr in ((params.src_dir,'frontendRRDBrowse.html'),
                      (params.src_dir,'frontendRRDGroupMatrix.html'),
                      (params.src_dir,'frontendStatus.html')):
            mfdir,mfname=mfarr
            mfobj=cWDictFile.SimpleFile(mfdir,mfname)
            mfobj.load()
            self.monitor_htmls.append(mfobj)

        # populate security data
        populate_main_security(self.client_security,params)

    # reuse as much of the other as possible
    def reuse(self,other):             # other must be of the same class
        if self.monitor_dir!=other.monitor_dir:
            raise RuntimeError,"Cannot change main monitor base_dir! '%s'!='%s'"%(self.monitor_dir,other.monitor_dir)
        
        return cvWDictFile.frontendMainDicts.reuse(self,other)

    def save(self,set_readonly=True):
        cvWDictFile.frontendMainDicts.save(self,set_readonly)
        self.save_monitor()
        self.save_client_security()


    ########################################
    # INTERNAL
    ########################################
    
    def save_monitor(self):
        for fobj in self.monitor_jslibs:
            fobj.save(dir=self.monitor_jslibs_dir,save_only_if_changed=False)
        for fobj in self.monitor_htmls:
            fobj.save(dir=self.monitor_dir,save_only_if_changed=False)
        return

    def save_client_security(self):
        # create a dummy mapfile so we have a reasonable default
        cvWCreate.create_client_mapfile(os.path.join(self.work_dir,cvWConsts.FRONTEND_MAP_FILE),
                                        self.client_security['proxy_DN'],[],[],[])
        # but the real mapfile will be (potentially) different for each
        # group, so frontend daemons will need to point to the real one at runtime
        cvWCreate.create_client_condor_config(os.path.join(self.work_dir,cvWConsts.FRONTEND_CONDOR_CONFIG_FILE),
                                              os.path.join(self.work_dir,cvWConsts.FRONTEND_MAP_FILE),
                                              self.client_security['collector_nodes'])
        return

################################################
#
# This Class contains the group dicts
#
################################################

class frontendGroupDicts(cvWDictFile.frontendGroupDicts):
    def __init__(self,params,sub_name,
                 summary_signature,workdir_name):
        cvWDictFile.frontendGroupDicts.__init__(self,params.work_dir,params.stage_dir,sub_name,summary_signature,workdir_name,simple_work_dir=False,base_log_dir=params.log_dir)
        self.monitor_dir=cvWConsts.get_group_monitor_dir(params.monitor_dir,sub_name)
        self.add_dir_obj(cWDictFile.monitorWLinkDirSupport(self.monitor_dir,self.work_dir))
        self.params=params
        self.client_security={}

    def populate(self,params=None):
        if params==None:
            params=self.params

        sub_params=params.groups[self.sub_name]

        # put default files in place first
        self.dicts['preentry_file_list'].add_placeholder(cWConsts.CONSTS_FILE,allow_overwrite=True)
        self.dicts['preentry_file_list'].add_placeholder(cWConsts.VARS_FILE,allow_overwrite=True)
        self.dicts['preentry_file_list'].add_placeholder(cWConsts.UNTAR_CFG_FILE,allow_overwrite=True) # this one must be loaded before any tarball

        # follow by the blacklist file
        file_name=cWConsts.BLACKLIST_FILE
        self.dicts['preentry_file_list'].add_from_file(file_name,(file_name,"nocache","TRUE",'BLACKLIST_FILE'),os.path.join(params.src_dir,file_name))

        # Load initial system scripts
        # These should be executed before the other scripts
        for script_name in ('cat_consts.sh',"check_blacklist.sh"):
            self.dicts['preentry_file_list'].add_from_file(script_name,(cWConsts.insert_timestr(script_name),'exec','TRUE','FALSE'),os.path.join(params.src_dir,script_name))

        # put user files in stage
        for file in sub_params.files:
            add_file_unparsed(file,self.dicts)

        # put user attributes into config files
        for attr_name in sub_params.attrs.keys():
            add_attr_unparsed(attr_name, sub_params,self.dicts,self.sub_name)

        # populate complex files
        populate_group_descript(self.work_dir,self.dicts['group_descript'],
                                self.sub_name,sub_params)
        populate_common_descript(self.dicts['group_descript'],sub_params)

        # populate security data
        populate_main_security(self.client_security,params)
        populate_group_security(self.client_security,params,sub_params)

    # reuse as much of the other as possible
    def reuse(self,other):             # other must be of the same class
        if self.monitor_dir!=other.monitor_dir:
            raise RuntimeError,"Cannot change group monitor base_dir! '%s'!='%s'"%(self.monitor_dir,other.monitor_dir)
        
        return cvWDictFile.frontendGroupDicts.reuse(self,other)

    def save(self,set_readonly=True):
        cvWDictFile.frontendGroupDicts.save(self,set_readonly)
        self.save_client_security()

    ########################################
    # INTERNAL
    ########################################
    
    def save_client_security(self):
        # create the real mapfile
        cvWCreate.create_client_mapfile(os.path.join(self.work_dir,cvWConsts.GROUP_MAP_FILE),
                                        self.client_security['proxy_DN'],
                                        self.client_security['factory_DNs'],
                                        self.client_security['schedd_DNs'],
                                        self.client_security['collector_DNs'])
        return

        
################################################
#
# This Class contains both the main and
# the group dicts
#
################################################

class frontendDicts(cvWDictFile.frontendDicts):
    def __init__(self,params,
                 sub_list=None): # if None, get it from params
        if sub_list==None:
            sub_list=params.groups.keys()

        self.params=params
        cvWDictFile.frontendDicts.__init__(self,params.work_dir,params.stage_dir,sub_list,simple_work_dir=False,log_dir=params.log_dir)

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
        
        return cvWDictFile.frontendDicts.reuse(self,other)

    ###########
    # PRIVATE
    ###########

    def local_populate(self,params):
        return # nothing to do
        

    ######################################
    # Redefine methods needed by parent
    def new_MainDicts(self):
        return frontendMainDicts(self.params,self.workdir_name)

    def new_SubDicts(self,sub_name):
        return frontendGroupDicts(self.params,sub_name,
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

    if eval(file.after_entry,{},{}):
        file_list_idx='file_list'
    else:
        file_list_idx='preentry_file_list'

    if file.has_key('after_group'):
        if eval(file.after_group,{},{}):
            file_list_idx='aftergroup_%s'%file_list_idx

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

    is_parameter=eval(attr_obj.parameter,{},{})
    is_expr=(attr_obj.type=="expr")
    attr_val=params.extract_attr_val(attr_obj)
    
    if is_parameter:
        dicts['params'].add_extended(attr_name,is_expr,attr_val)
    else:
        if is_expr:
            RuntimeError, "Expression '%s' is not a parameter!"%attr_name
        else:
            dicts['consts'].add(attr_name,attr_val)

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
# Create the frontend descript file
def populate_frontend_descript(work_dir,
                               frontend_dict,active_sub_list,        # will be modified
                               params):
        # if a user does not provide a file name, use the default one
        down_fname=params.downtimes.absfname
        if down_fname==None:
            down_fname=os.path.join(work_dir,'frontend.downtimes')

        frontend_dict.add('FrontendName',params.frontend_name)
        frontend_dict.add('WebURL',params.web_url)

        if params.security.classad_proxy==None:
            raise RuntimeError, "Missing security.classad_proxy"
        params.subparams.data['security']['classad_proxy']=os.path.abspath(params.security.classad_proxy)
        if not os.path.isfile(params.security.classad_proxy):
            raise RuntimeError, "security.classad_proxy(%s) is not a file"%params.security.classad_proxy
        frontend_dict.add('ClassAdProxy',params.security.classad_proxy)
        
        frontend_dict.add('SymKeyType',params.security.sym_key)

        active_sub_list[:] # erase all
        for sub in params.groups.keys():
            if eval(params.groups[sub].enabled,{},{}):
                active_sub_list.append(sub)
        frontend_dict.add('Groups',string.join(active_sub_list,','))

        frontend_dict.add('LoopDelay',params.loop_delay)
        frontend_dict.add('AdvertiseDelay',params.advertise_delay)

        frontend_dict.add('CondorConfig',os.path.join(work_dir,cvWConsts.FRONTEND_CONDOR_CONFIG_FILE))

        frontend_dict.add('LogDir',params.log_dir)
        frontend_dict.add('DowntimesFile',down_fname)
        for tel in (("max_days",'MaxDays'),("min_days",'MinDays'),("max_mbytes",'MaxMBs')):
            param_tname,str_tname=tel
            frontend_dict.add('LogRetention%s'%str_tname,params.log_retention[param_tname])

#######################
# Populate group descript
def populate_group_descript(work_dir,group_descript_dict,        # will be modified
                            sub_name,sub_params):
    # if a user does not provide a file name, use the default one
    down_fname=sub_params.downtimes.absfname
    if down_fname==None:
        down_fname=os.path.join(work_dir,'group.downtimes')

    group_descript_dict.add('GroupName',sub_name)

    group_descript_dict.add('MapFile',os.path.join(work_dir,cvWConsts.GROUP_MAP_FILE))

    group_descript_dict.add('DowntimesFile',down_fname)
    group_descript_dict.add('MaxRunningPerEntry',sub_params.config.running_glideins_per_entry.max)
    group_descript_dict.add('FracRunningPerEntry',sub_params.config.running_glideins_per_entry.relative_to_queue)
    group_descript_dict.add('MaxIdlePerEntry',sub_params.config.idle_glideins_per_entry.max)
    group_descript_dict.add('ReserveIdlePerEntry',sub_params.config.idle_glideins_per_entry.reserve)
    group_descript_dict.add('MaxIdleVMsPerEntry',sub_params.config.idle_vms_per_entry.max)
    group_descript_dict.add('CurbIdleVMsPerEntry',sub_params.config.idle_vms_per_entry.curb)


#####################################################
# Populate values common to frontend and group dicts
MATCH_ATTR_CONV={'string':'s','int':'i','real':'r','bool':'b'}

def populate_common_descript(descript_dict,        # will be modified
                             params):
    for tel in (("factory","Factory"),("job","Job")):
        param_tname,str_tname=tel
        descript_dict.add('%sQueryExpr'%str_tname,params.match[param_tname]['query_expr'])
        match_attrs=params.match[param_tname]['match_attrs']
        ma_arr=[]
        for attr_name in match_attrs.keys():
            attr_type=match_attrs[attr_name]['type']
            if not (attr_type in MATCH_ATTR_CONV.keys()):
                raise RuntimeError, "match_attr type '%s' not one of %s"%(attr_type,MATCH_ATTR_CONV.keys())
            ma_arr.append((str(attr_name),MATCH_ATTR_CONV[attr_type]))
        descript_dict.add('%sMatchAttrs'%str_tname,repr(ma_arr))

    if params.security.security_name!=None:
        descript_dict.add('SecurityName',params.security.security_name)

    collectors=[]
    for el in params.match.factory.collectors:
        if el['factory_identity'][-9:]=='@fake.org':
            raise RuntimeError, "factory_identity for %s not set! (i.e. it is fake)"%el['node']
        if el['my_identity'][-9:]=='@fake.org':
            raise RuntimeError, "my_identity for %s not set! (i.e. it is fake)"%el['node']
        collectors.append((el['node'],el['factory_identity'],el['my_identity']))
    descript_dict.add('FactoryCollectors',repr(collectors))

    schedds=[]
    for el in params.match.job.schedds:
        schedds.append(el['fullname'])
    descript_dict.add('JobSchedds',string.join(schedds,','))

    if params.security.proxy_selection_plugin!=None:
        descript_dict.add('ProxySelectionPlugin',params.security.proxy_selection_plugin)

    if len(params.security.proxies)>0:
        proxies=[]
        proxy_refresh_scripts={}
        proxy_security_classes={}
        for pel in params.security.proxies:
            if pel['absfname']==None:
                raise RuntimeError,"All proxies need a absfname!"
            if pel['pool_count']==None:
                # only one
                proxies.append(pel['absfname'])
                if pel['proxy_refresh_script']!=None:
                    proxy_refresh_scripts[pel['absfname']]=pel['proxy_refresh_script']
                if pel['security_class']!=None:
                    proxy_security_classes[pel['absfname']]=pel['security_class']
            else: #pool
                pool_count=int(pel['pool_count'])
                for i in range(pool_count):
                    absfname=pel['absfname']%(i+1)
                    proxies.append(absfname)
                    if pel['proxy_refresh_script']!=None:
                        proxy_refresh_scripts[absfname]=pel['proxy_refresh_script']
                    if pel['security_class']!=None:
                        proxy_security_classes[absfname]=pel['security_class']

        descript_dict.add('Proxies',repr(proxies))
        if len(proxy_refresh_scripts.keys())>0:
             descript_dict.add('ProxyRefreshScripts',repr(proxy_refresh_scripts))
        if len(proxy_security_classes.keys())>0:
             descript_dict.add('ProxySecurityClasses',repr(proxy_security_classes))

    descript_dict.add('MatchExpr',params.match.match_expr)


#####################################################
# Returns a string usable for GLIDEIN_Collector
def calc_glidein_collectors(collectors):
    collector_nodes=[]
    for el in collectors:
        is_secondary=eval(el.secondary)
        if not is_secondary:
            continue # only consider secondary collectors here
        collector_nodes.append(el.node)
    if len(collector_nodes)!=0:
        return string.join(collector_nodes,",")

    # no secondard nodes, will have to use the primary ones
    for el in collectors:
        collector_nodes.append(el.node)
    return string.join(collector_nodes,",")

#####################################################
# Populate gridmap to be used by the glideins
def populate_gridmap(params,gridmap_dict):
    collector_dns=[]
    for el in params.collectors:
        dn=el.DN
        if dn==None:
            raise RuntimeError,"DN not defined for pool collector %s"%el.node
        if not (dn in collector_dns): #skip duplicates
            collector_dns.append(dn)
            gridmap_dict.add(dn,'collector%i'%len(collector_dns))

    # Add also the frontend DN, so it is easier to debug
    if params.security.proxy_DN!=None:
        gridmap_dict.add(params.security.proxy_DN,'frontend')

#####################################################
# Populate security values
def populate_main_security(client_security,params):
    if params.security.proxy_DN==None:
        raise RuntimeError,"DN not defined for classad_proxy"    
    client_security['proxy_DN']=params.security.proxy_DN
    
    collector_dns=[]
    collector_nodes=[]
    for el in params.collectors:
        dn=el.DN
        if dn==None:
            raise RuntimeError,"DN not defined for pool collector %s"%el.node
        is_secondary=eval(el.secondary)
        if is_secondary:
            continue # only consider primary collectors for the main security config
        collector_nodes.append(el.node)
        collector_dns.append(dn)
    if len(collector_nodes)==0:
        raise RuntimeError,"Need at least one non-secondary pool collector"
    client_security['collector_nodes']=collector_nodes
    client_security['collector_DNs']=collector_dns

def populate_group_security(client_security,params,sub_params):
    factory_dns=[]
    for el in params.match.factory.collectors:
        dn=el.DN
        if dn==None:
            raise RuntimeError,"DN not defined for factory %s"%el.node
        factory_dns.append(dn)
    for el in sub_params.match.factory.collectors:
        dn=el.DN
        if dn==None:
            raise RuntimeError,"DN not defined for factory %s"%el.node
        # don't worry about conflict... there is nothing wrong if the DN is listed twice
        factory_dns.append(dn)
    client_security['factory_DNs']=factory_dns
    
    schedd_dns=[]
    for el in params.match.job.schedds:
        dn=el.DN
        if dn==None:
            raise RuntimeError,"DN not defined for schedd %s"%el.fullname
        schedd_dns.append(dn)
    for el in sub_params.match.job.schedds:
        dn=el.DN
        if dn==None:
            raise RuntimeError,"DN not defined for schedd %s"%el.fullname
        # don't worry about conflict... there is nothing wrong if the DN is listed twice
        schedd_dns.append(dn)
    client_security['schedd_DNs']=schedd_dns

    
