#!/usr/bin/env python

#
# Project:
#   glideinWMS
#
# File Version: 
#
# Description:
#  This program clones (a subset of) entries
#  from a remote xml config into a local one
#

import os
import sys

STARTUP_DIR=sys.path[0]

import os.path
import copy
import re
import string
import shutil
import traceback
sys.path.append(os.path.join(STARTUP_DIR,"../.."))
from glideinwms.creation.lib import cgWParams


################################################################################

def run_attr_regexp(params,entry_name,attr,ro):
    if not params.entries[entry_name].attrs.has_key(attr):
        return False
    return re.search(ro,params.entries[entry_name].attrs[attr].value)!=None

def run_descr_regexp(params,entry_name,attr,ro):
    if not params.subparams.data['entries'][entry_name].has_key(attr):
        return False
    return re.search(ro,params.subparams.data['entries'][entry_name][attr])!=None

def run_name_regexp(params,entry_name,ro):
    return re.search(ro,entry_name)!=None


def create_filter(attr,regexp):
    ro=re.compile(regexp)
    if attr=="name":
        return lambda params,entry_name:run_name_regexp(params,entry_name,ro)
    elif attr in ("gatekeeper","gridtype","rsl",'schedd_name',"work_dir",'proxy_url','verbosity',"enabled"):
        return lambda params,entry_name:run_descr_regexp(params,entry_name,attr,ro)
    else:
        return lambda params,entry_name:run_attr_regexp(params,entry_name,attr,ro)
    
def match_list(params,entry_name,include_list,exclude_list):
    if len(include_list)!=0: # if empty, include all
        found=False
        for f in include_list:
            if f(params,entry_name):
                found=True
                break
        if not found: # not in whitelist
            return False

    for f in exclude_list:
        if f(params,entry_name):
            return False

    return True #not in blacklist


################################################################################

def add_entry(params,other_params, entry_name):
    params.subparams.data['entries'][entry_name]=copy.deepcopy(other_params.subparams.data['entries'][entry_name])
    for e in ('schedd_name','allow_frontends'):
        # these are likely different between installations
        if params.subparams.data['entries'][entry_name].has_key(e):
            if type(params.entry_defaults[e])==type(()):
                params.subparams.data['entries'][entry_name][e]=copy.deepcopy(params.entry_defaults[e][0])
            else:
                params.subparams.data['entries'][entry_name][e]=copy.deepcopy(params.entry_defaults[e])

def merge_entry(params,other_params, entry_name,preserve_enable):
    org_entry=params.subparams.data['entries'][entry_name]
    params.subparams.data['entries'][entry_name]=copy.deepcopy(other_params.subparams.data['entries'][entry_name])
    preserve_els=['schedd_name','allow_frontends','downtimes']
    if preserve_enable:
        preserve_els.append('enable')
    for e in preserve_els:
        # preserve these, since they are instance specific
        if org_entry.has_key(e):
            params.subparams.data['entries'][entry_name][e]=org_entry[e]

def disable_entry(params,entry_name):
    eel=params.subparams.data['entries'][entry_name]
    eel['enabled']='False'
    if eel.has_key('comment') and (eel['comment']!=None):
        base_comment=eel['comment']+" "
    else:
        base_comment=""
    eel['comment']=base_comment+"Disabled because obsoleted during cloning."
    
################################################################################
def main(params,other_params,
         merge_opt,preserve_enable,disable_old,
         include_list,exlude_list):
    other_entry_list=[]
    for e in other_params.entries.keys():
        if not match_list(other_params,e,include_list,exlude_list):
            continue # filtered out
        other_entry_list.append(e)

        if params.entries.has_key(e):
            if merge_opt in ('yes','only'):
                print "Merging %s"%e
                merge_entry(params,other_params,e,preserve_enable)
        else:
            if merge_opt in ('yes','no'):
                print "Adding %s"%e
                add_entry(params, other_params,e)

    if disable_old:
        for e in params.entries.keys():
            if not match_list(params,e,include_list,exlude_list):
                continue # filtered out
            if not (e in other_entry_list):
                if params.entries[e].enabled=="True":
                    print "Disabling %s"%e
                    disable_entry(params,e)


############################################################
#
# S T A R T U P
# 
############################################################
def start():
    load(sys.argv)

def load(argv):
    usage_prefix="clone_glidein -other config [-out fname] [-debug] [-include attr regexp] [-exclude attr regexp] [-merge yes|no|only] [-preserve_enable] [-disable_old]"

    other_fname=None
    out_fname="out.xml"
    debug=False
    include_list=[]
    exclude_list=[]
    merge_opt="no"
    disable_old=False
    preserve_enable=False
    while len(argv)>2:
        if argv[1]=='-other':
            other_fname=argv[2]
            argv=argv[0:1]+argv[3:]
        elif argv[1]=='-out':
            out_fname=argv[2]
            argv=argv[0:1]+argv[3:]
        elif argv[1]=='-include':
            include_list.append(create_filter(argv[2],argv[3]))
            argv=argv[0:1]+argv[4:]
        elif argv[1]=='-exclude':
            exclude_list.append(create_filter(argv[2],argv[3]))
            argv=argv[0:1]+argv[4:]
        elif argv[1]=='-merge':
            merge_opt=argv[2]
            if not (merge_opt in ('yes','no','only')):
                print "Merge must be yes, no or only, got %s"%merge_opt
                sys.exit(1)
            argv=argv[0:1]+argv[3:]
        elif argv[1]=='-debug':
            debug=True
            argv=argv[0:1]+argv[2:]
        elif argv[1]=='-disable_old':
            disable_old=True
            argv=argv[0:1]+argv[2:]
        elif argv[1]=='-preserve_enable':
            preserve_enable=True
            argv=argv[0:1]+argv[2:]
        else:
            break
            
    if other_fname==None:
        print "Missing -other"
        print
        print "Usage:"
        print "%s local_config"%usage_prefix
        sys.exit(1)

    try:
        params=cgWParams.GlideinParams(usage_prefix,os.path.join(STARTUP_DIR,"web_base"),argv)
    except RuntimeError,e:
        if debug:
            import traceback
            tb = traceback.format_exception(sys.exc_info()[0],sys.exc_info()[1],
                                            sys.exc_info()[2])
            print string.join(tb,'\n')
        print e
        sys.exit(1)

    try:
        other_argv=copy.deepcopy(argv)
        other_argv[1]=other_fname
        other_params=cgWParams.GlideinParams(usage_prefix,os.path.join(STARTUP_DIR,"web_base"),other_argv)
    except RuntimeError,e:
        if debug:
            import traceback
            tb = traceback.format_exception(sys.exc_info()[0],sys.exc_info()[1],
                                            sys.exc_info()[2])
            print string.join(tb,'\n')
        print e
        sys.exit(1)

    main(params,other_params,
         merge_opt,preserve_enable,disable_old,
         include_list,exclude_list)

    print
    print "Writing out %s"%out_fname
    params.save_into_file(out_fname)
    
if __name__ == '__main__':
    start()
