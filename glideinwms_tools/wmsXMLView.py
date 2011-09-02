#!/usr/bin/env python
#
# Project:
#   glideinWMS
#
# File Version: 
#   $Id: wmsXMLView.py,v 1.16.2.7 2010/09/24 15:30:37 parag Exp $
#
# Description:
#   This tool displays the status of the glideinWMS pool
#   in a XML format
#
# Arguments:
#   [-pool collector_node] [-condor-stats 1|0] [-internals 1|0]
#
# Author:
#   Igor Sfiligoi (May 9th 2007)
#

import sys

import glideinwms_factory.glideFactoryInterface
import glideinwms_factory.glideFactoryConfig
import glideinwms_frontend.glideinFrontendInterface
import glideinwms_libs.xmlFormat

pool_name = None
factory_name = None
frontend_name = None
remove_condor_stats = True
remove_internals = True

key_obj = None

# parse arguments
alen = len(sys.argv)
i = 1
while (i < alen):
    ael = sys.argv[i]
    if ael == '-pool':
        i = i + 1
        pool_name = sys.argv[i]
    elif ael == '-factory':
        i = i + 1
        factory_name = sys.argv[i]
    elif ael == '-frontend':
        i = i + 1
        frontend_name = sys.argv[i]
    elif ael == '-condor-stats':
        i = i + 1
        remove_condor_stats = not int(sys.argv[i])
    elif ael == '-internals':
        i = i + 1
        remove_internals = not int(sys.argv[i])
    elif ael == '-rsa_key':
        i = i + 1
        key_obj = glideinwms_factory.glideFactoryConfig.GlideinKey('RSA', sys.argv[i])
    elif ael == '-help':
        print "Usage:"
        print "wmsXMLView.py [-pool <node>[:<port>]] [-factory <factory>] [-frontend <frontend>] [-condor-stats 0|1] [-internals 0|1] [-rsa_key <fname>] [-help]"
        sys.exit(1)
    else:
        raise RuntimeError, "Unknown option '%s', try -help" % ael
    i = i + 1

# get data
factory_constraints = None
if factory_name != None:
    farr = factory_name.split('@')
    if len(farr) == 1:
        # just the generic factory name
        factory_constraints = 'FactoryName=?="%s"' % factory_name
    elif len(farr) == 2:
        factory_constraints = '(FactoryName=?="%s")&&(GlideinName=?="%s")' % (farr[1], farr[0])
    elif len(farr) == 3:
        factory_constraints = '(FactoryName=?="%s")&&(GlideinName=?="%s")&&(EntryName=?="%s")' % (farr[2], farr[1], farr[0])
    else:
        raise RuntimeError, "Invalid factory name; more than 2 @'s found"

glideins_obj = glideinwms_frontend.glideinFrontendInterface.findGlideins(pool_name, None, None, factory_constraints, get_only_matching=False)

factoryclient_constraints = None
if factory_name != None:
    farr = factory_name.split('@')
    if len(farr) == 1:
        # just the generic factory name
        factoryclient_constraints = 'ReqFactoryName=?="%s"' % factory_name
    elif len(farr) == 2:
        factoryclient_constraints = '(ReqFactoryName=?="%s")&&(ReqGlideinName=?="%s")' % (farr[1], farr[0])
    elif len(farr) == 3:
        factoryclient_constraints = '(ReqFactoryName=?="%s")&&(ReqGlideinName=?="%s")&&(ReqEntryName=?="%s")' % (farr[2], farr[1], farr[0])
    else:
        raise RuntimeError, "Invalid factory name; more than 2 @'s found"


clientsmon_obj = glideinwms_frontend.glideinFrontendInterface.findGlideinClientMonitoring(pool_name, None, factoryclient_constraints)

# extract data
glideins = glideins_obj.keys()
for glidein in glideins:
    glidein_el = glideins_obj[glidein]

    # Remove diagnostics attributes, if needed
    if remove_condor_stats:
        del glidein_el['attrs']['LastHeardFrom']

    #rename params into default_params
    glidein_el['default_params'] = glidein_el['params']
    del glidein_el['params']

    if remove_internals:
        for attr in ('EntryName', 'GlideinName', 'FactoryName'):
            del glidein_el['attrs'][attr]

    entry_name, glidein_name, factory_name = glidein.split("@")

    frontend_constraints = None
    if frontend_name != None:
        farr = frontend_name.split('.')
        if len(farr) == 1:
            # just the generic frontend name
            frontend_constraints = 'FrontendName=?="%s"' % frontend_name
        elif len(farr) == 2:
            frontend_constraints = '(FrontendName=?="%s")&&(GroupName=?="%s")' % (farr[0], farr[1])
        else:
            raise RuntimeError, "Invalid frontend name; more than one dot found"

    clients_obj = glideinwms_factory.glideFactoryInterface.findWork(factory_name, glidein_name, entry_name, None, key_obj, get_only_matching=False, additional_constraints=frontend_constraints)
    glidein_el['clients'] = clients_obj
    clients = clients_obj.keys()

    if (frontend_name != None) and (len(clients) == 0):
        # if user requested to see only one frontend
        # and this factory is not serving that frontend
        # do not show the frontend at all
        del glideins_obj[glidein]
        continue

    for client in clients:
        if remove_internals:
            del clients_obj[client]['internals']

        # rename monitor into client_monitor
        clients_obj[client]['client_monitor'] = clients_obj[client]['monitor']
        del clients_obj[client]['monitor']
        # add factory monitor
        if clientsmon_obj.has_key(client):
            clients_obj[client]['factory_monitor'] = clientsmon_obj[client]['monitor']

        for pd_key in clients_obj[client]["params_decrypted"].keys():
            if clients_obj[client]["params_decrypted"][pd_key] == None:
                clients_obj[client]["params_decrypted"][pd_key] = "ENCRYPTED"


#print data
sub_dict = {'clients':{'dict_name':'clients', 'el_name':'client', 'subtypes_params':{'class':{}}}}
print glideinwms_libs.xmlFormat.dict2string(glideins_obj, 'glideinWMS', 'factory', subtypes_params={'class':{'dicts_params':sub_dict}})

