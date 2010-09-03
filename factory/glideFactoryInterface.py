#
# Project:
#   glideinWMS
#
# File Version: 
#   $Id: glideFactoryInterface.py,v 1.44.20.2.4.3 2010/09/03 00:56:12 sfiligoi Exp $
#
# Description:
#   This module implements the functions needed to advertize
#   and get commands from the Collector
#
# Author:
#   Igor Sfiligoi (Sept 7th 2006)
#

import condorExe
import condorMonitor
import os
import time
import string

############################################################
#
# Configuration
#
############################################################

class FakeLog:
    def write(self,str):
        pass

class FactoryConfig:
    def __init__(self):
        # set default values
        # user should modify if needed

        # The name of the attribute that identifies the glidein
        self.factory_id = "glidefactory"
        self.client_id = "glideclient"
        self.factoryclient_id = "glidefactoryclient"

        # String to prefix for the attributes
        self.glidein_attr_prefix = ""

        # String to prefix for the parameters
        self.glidein_param_prefix = "GlideinParam"
        self.encrypted_param_prefix = "GlideinEncParam"

        # String to prefix for the monitoring
        self.glidein_monitor_prefix = "GlideinMonitor"

        # String to prefix for the requests
        self.client_req_prefix = "Req"

        # String to prefix for the web passing
        self.client_web_prefix = "Web"

        # The name of the signtype
        self.factory_signtype_id = "SupportedSignTypes"
        self.client_web_signtype_suffix = "SignType"

        # Should we use TCP for condor_advertise?
        self.advertise_use_tcp=False

        # warning log files
        # default is FakeLog, any other value must implement the write(str) method
        self.warning_log = FakeLog()


# global configuration of the module
factoryConfig=FactoryConfig()

############################################################
#
# User functions
#
############################################################


def findWork(factory_name,glidein_name,entry_name,
             supported_signtypes,
             pub_key_obj=None,allowed_proxy_source=('factory','frontend'),
             get_only_matching=True,  # if this is false, return also glideins I cannot use)
             additional_constraints=None):
    """
    Look for requests.
    Look for classAds that have my (factory, glidein name, entry name).

    Return:
      Dictionary, each key is the name of a frontend.
      Each value has a 'requests' and a 'params' key.
        Both refer to classAd dictionaries.
    """

    global factoryConfig
    
    status_constraint='(GlideinMyType=?="%s") && (ReqGlidein=?="%s@%s@%s")'%(factoryConfig.client_id,entry_name,glidein_name,factory_name)

    if supported_signtypes!=None:
        status_constraint+=' && stringListMember(%s%s,"%s")'%(factoryConfig.client_web_prefix,factoryConfig.client_web_signtype_suffix,string.join(supported_signtypes,","))

    if get_only_matching:
        if pub_key_obj!=None:
            # get only classads that have my key or no key at all
            # any other key will not work
            status_constraint+=' && (((ReqPubKeyID=?="%s") && (ReqEncKeyCode=!=Undefined) && (ReqEncIdentity=!=Undefined)) || (ReqPubKeyID=?=Undefined))'%pub_key_obj.get_pub_key_id()
            if not ('factory' in allowed_proxy_source):
                # the proxy is required, so look for it 
                status_constraint+=' && ((GlideinEncParamx509_proxy =!= UNDEFINED) || (GlideinEncParamx509_proxy_0 =!= UNDEFINED))'
            if not ('frontend' in allowed_proxy_source):
                # the proxy is not allowed, so ignore such requests 
                status_constraint+=' && (GlideinEncParamx509_proxy =?= UNDEFINED) && (GlideinEncParamx509_proxy_0 =?= UNDEFINED)'

    if additional_constraints!=None:
        status_constraint="(%s)&&(%s)"%(status_constraint,additional_constraints)

    status=condorMonitor.CondorStatus("any")
    status.require_integrity(True) #important, this dictates what gets submitted
    status.glidein_name=glidein_name
    status.entry_name=entry_name
    status.load(status_constraint)

    data=status.fetchStored()

    reserved_names=("ReqName","ReqGlidein","ClientName","FrontendName","GroupName","ReqPubKeyID","ReqEncKeyCode","ReqEncIdentity","AuthenticatedIdentity")

    out={}

    # copy over requests and parameters
    for k in data.keys():
        kel=data[k]
        el={"requests":{},"web":{},"params":{},"params_decrypted":{},"monitor":{},"internals":{}}
        for (key,prefix) in (("requests",factoryConfig.client_req_prefix),
                             ("web",factoryConfig.client_web_prefix),
                             ("params",factoryConfig.glidein_param_prefix),
                             ("monitor",factoryConfig.glidein_monitor_prefix)):
            plen=len(prefix)
            for attr in kel.keys():
                if attr in reserved_names:
                    continue # skip reserved names
                if attr[:plen]==prefix:
                    el[key][attr[plen:]]=kel[attr]
        if pub_key_obj!=None:
            if kel.has_key('ReqPubKeyID'):
                try:
                    sym_key_obj=pub_key_obj.extract_sym_key(kel['ReqEncKeyCode'])
                except:
                    if get_only_matching:
                        continue # bad key, ignore entry
                    else:
                        sym_key_obj=None # leave it encrypted
            else:
                sym_key_obj=None # no key used, will not decrypt
        else:
            sym_key_obj=None # have no key, will not decrypt

        if sym_key_obj!=None:
            try:
                enc_identity=sym_key_obj.decrypt_hex(kel['ReqEncIdentity'])
            except:
                factoryConfig.warning_log.write("Client %s provided invalid ReqEncIdentity, could not decode. Skipping for security reasons."%k)
                continue # corrupted classad
            if enc_identity!=kel['AuthenticatedIdentity']:
                factoryConfig.warning_log.write("Client %s provided invalid ReqEncIdentity(%s!=%s). Skipping for security reasons."%(k,enc_identity,kel['AuthenticatedIdentity']))
                continue # uh oh... either the client is misconfigured, or someone is trying to cheat
            

        invalid_classad=False
        for (key,prefix) in (("params_decrypted",factoryConfig.encrypted_param_prefix),):
            plen=len(prefix)
            for attr in kel.keys():
                if attr in reserved_names:
                    continue # skip reserved names
                if attr[:plen]==prefix:
                    el[key][attr[plen:]]=None # define it even if I don't understand the content
                    if sym_key_obj!=None:
                        try:
                            el[key][attr[plen:]]=sym_key_obj.decrypt_hex(kel[attr])
                        except:
                            invalid_classad=True
                            break # I don't understand it -> invalid
        if invalid_classad:
            factoryConfig.warning_log.write("At least one of the encrypted parameters for client %s cannot be decoded. Skipping for security reasons."%k)
            continue # need to go this way as I may have problems in an inner loop


        for attr in kel.keys():
            if attr in ("ClientName","FrontendName","GroupName","ReqName","LastHeardFrom","ReqPubKeyID","AuthenticatedIdentity"):
                el["internals"][attr]=kel[attr]
        
        out[k]=el

    return out

start_time=time.time()
advertizeGlideinCounter=0
# glidein_attrs is a dictionary of values to publish
#  like {"Arch":"INTEL","MinDisk":200000}
# similar for glidein_params and glidein_monitor_monitors
def advertizeGlidein(factory_name,glidein_name,entry_name,
                     supported_signtypes,
                     glidein_attrs={},glidein_params={},glidein_monitors={},
                     pub_key_obj=None,allowed_proxy_source=None):
    global factoryConfig,advertizeGlideinCounter

    # get a 9 digit number that will stay 9 digit for the next 25 years
    short_time = time.time()-1.05e9
    tmpnam="/tmp/gfi_ag_%li_%li"%(short_time,os.getpid())
    fd=file(tmpnam,"w")
    try:
        try:
            fd.write('MyType = "%s"\n'%factoryConfig.factory_id)
            fd.write('GlideinMyType = "%s"\n'%factoryConfig.factory_id)
            fd.write('Name = "%s@%s@%s"\n'%(entry_name,glidein_name,factory_name))
            fd.write('FactoryName = "%s"\n'%factory_name)
            fd.write('GlideinName = "%s"\n'%glidein_name)
            fd.write('EntryName = "%s"\n'%entry_name)
            fd.write('%s = "%s"\n'%(factoryConfig.factory_signtype_id,string.join(supported_signtypes,',')))
            if pub_key_obj!=None:
                fd.write('PubKeyID = "%s"\n'%pub_key_obj.get_pub_key_id())
                fd.write('PubKeyType = "%s"\n'%pub_key_obj.get_pub_key_type())
                fd.write('PubKeyValue = "%s"\n'%string.replace(pub_key_obj.get_pub_key_value(),'\n','\\n'))
                if allowed_proxy_source!=None:
                    fd.write('GlideinAllowx509_Proxy = %s\n'%('frontend' in allowed_proxy_source))
                    fd.write('GlideinRequirex509_Proxy = %s\n'%(not ('factory' in allowed_proxy_source)))
            fd.write('DaemonStartTime = %li\n'%start_time)
            fd.write('UpdateSequenceNumber = %i\n'%advertizeGlideinCounter)
            advertizeGlideinCounter+=1

            # write out both the attributes, params and monitors
            for (prefix,data) in ((factoryConfig.glidein_attr_prefix,glidein_attrs),
                                  (factoryConfig.glidein_param_prefix,glidein_params),
                                  (factoryConfig.glidein_monitor_prefix,glidein_monitors)):
                for attr in data.keys():
                    el=data[attr]
                    if type(el)==type(1):
                        # don't quote ints
                        fd.write('%s%s = %s\n'%(prefix,attr,el))
                    else:
                        escaped_el=string.replace(string.replace(str(el),'"','\\"'),'\n','\\n')
                        fd.write('%s%s = "%s"\n'%(prefix,attr,escaped_el))
        finally:
            fd.close()

        exe_condor_advertise(tmpnam,"UPDATE_MASTER_AD")
    finally:
        os.remove(tmpnam)

# remove add from Collector
def deadvertizeGlidein(factory_name,glidein_name,entry_name):
    # get a 9 digit number that will stay 9 digit for the next 25 years
    short_time = time.time()-1.05e9
    tmpnam="/tmp/gfi_ag_%li_%li"%(short_time,os.getpid())
    fd=file(tmpnam,"w")
    try:
        try:
            fd.write('MyType = "Query"\n')
            fd.write('TargetType = "%s"\n'%factoryConfig.factory_id)
            fd.write('Requirements = Name == "%s@%s@%s"\n'%(entry_name,glidein_name,factory_name))
        finally:
            fd.close()

        exe_condor_advertise(tmpnam,"INVALIDATE_MASTER_ADS")
    finally:
        os.remove(tmpnam)
    

# glidein_attrs is a dictionary of values to publish
#  like {"Arch":"INTEL","MinDisk":200000}
# similar for glidein_params and glidein_monitor_monitors
def advertizeGlideinClientMonitoring(factory_name,glidein_name,entry_name,
                                     client_name,client_int_name,client_int_req,
                                     glidein_attrs={},client_params={},client_monitors={}):
    #global factoryConfig,advertizeGlideinCounter

    # get a 9 digit number that will stay 9 digit for the next 25 years
    short_time = time.time()-1.05e9
    tmpnam="/tmp/gfi_ag_%li_%li"%(short_time,os.getpid())
    fd=file(tmpnam,"w")
    try:
        try:
            fd.write('MyType = "%s"\n'%factoryConfig.factoryclient_id)
            fd.write('GlideinMyType = "%s"\n'%factoryConfig.factoryclient_id)
            fd.write('Name = "%s"\n'%client_name)
            fd.write('ReqGlidein = "%s@%s@%s"\n'%(entry_name,glidein_name,factory_name))
            fd.write('ReqFactoryName = "%s"\n'%factory_name)
            fd.write('ReqGlideinName = "%s"\n'%glidein_name)
            fd.write('ReqEntryName = "%s"\n'%entry_name)
            fd.write('ReqClientName = "%s"\n'%client_int_name)
            fd.write('ReqClientReqName = "%s"\n'%client_int_req)
            #fd.write('DaemonStartTime = %li\n'%start_time)
            #fd.write('UpdateSequenceNumber = %i\n'%advertizeGlideinCounter)
            #advertizeGlideinCounter+=1

            # write out both the attributes, params and monitors
            for (prefix,data) in ((factoryConfig.glidein_attr_prefix,glidein_attrs),
                                  (factoryConfig.glidein_param_prefix,client_params),
                                  (factoryConfig.glidein_monitor_prefix,client_monitors)):
                for attr in data.keys():
                    el=data[attr]
                    if type(el)==type(1):
                        # don't quote ints
                        fd.write('%s%s = %s\n'%(prefix,attr,el))
                    else:
                        escaped_el=string.replace(str(el),'"','\\"')
                        fd.write('%s%s = "%s"\n'%(prefix,attr,escaped_el))
        finally:
            fd.close()

        exe_condor_advertise(tmpnam,"UPDATE_LICENSE_AD") # must use a different AD that the frontend
    finally:
        os.remove(tmpnam)

# remove add from Collector
def deadvertizeGlideinClientMonitoring(factory_name,glidein_name,entry_name,client_name):
    # get a 9 digit number that will stay 9 digit for the next 25 years
    short_time = time.time()-1.05e9
    tmpnam="/tmp/gfi_ag_%li_%li"%(short_time,os.getpid())
    fd=file(tmpnam,"w")
    try:
        try:
            fd.write('MyType = "Query"\n')
            fd.write('TargetType = "%s"\n'%factoryConfig.factoryclient_id)
            fd.write('Requirements = Name == "%s"\n'%client_name)
        finally:
            fd.close()

        exe_condor_advertise(tmpnam,"INVALIDATE_LICENSE_ADS")
    finally:
        os.remove(tmpnam)

# remove adds from Collector
def deadvertizeAllGlideinClientMonitoring(factory_name,glidein_name,entry_name):
    # get a 9 digit number that will stay 9 digit for the next 25 years
    short_time = time.time()-1.05e9
    tmpnam="/tmp/gfi_ag_%li_%li"%(short_time,os.getpid())
    fd=file(tmpnam,"w")
    try:
        try:
            fd.write('MyType = "Query"\n')
            fd.write('TargetType = "%s"\n'%factoryConfig.factoryclient_id)
            fd.write('Requirements = ReqGlidein == "%s@%s@%s"\n'%(entry_name,glidein_name,factory_name))
        finally:
            fd.close()

        exe_condor_advertise(tmpnam,"INVALIDATE_LICENSE_ADS")
    finally:
        os.remove(tmpnam)


############################################################
#
# I N T E R N A L - Do not use
#
############################################################

def usetcp2str(use_tcp):
    if use_tcp:
        return "-tcp "
    else:
        return ""


def exe_condor_advertise(fname,command):
    return condorExe.exe_cmd("../sbin/condor_advertise","%s%s %s"%(usetcp2str(factoryConfig.advertise_use_tcp),command,fname))
    
