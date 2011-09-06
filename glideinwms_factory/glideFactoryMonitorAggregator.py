#
# Project:
#   glideinWMS
#
# File Version: 
#   $Id: glideFactoryMonitorAggregator.py,v 1.84.8.9 2011/05/01 17:14:51 sfiligoi Exp $
#
# Description:
#   This module implements the functions needed
#   to aggregate the monitoring fo the glidein factory
#
# Author:
#   Igor Sfiligoi (May 23rd 2007)
#

import os
import time
import sets

import glideFactoryLib
import glideFactoryMonitoring

import glideinwms_libs.xmlParse
import glideinwms_libs.xmlFormat

############################################################
#
# Configuration
#
############################################################

class MonitorAggregatorConfig:
    def __init__(self):
        # The name of the attribute that identifies the glidein
        self.monitor_dir = "monitor/"

        # list of entries
        self.entries = []

        # name of the status files
        self.status_relname = "schedd_status.xml"
        self.logsummary_relname = "log_summary.xml"

    def config_factory(self, monitor_dir, entries):
        self.monitor_dir = monitor_dir
        self.entries = entries
        glideFactoryMonitoring.monitoringConfig.monitor_dir = monitor_dir


# global configuration of the module
monitorAggregatorConfig = MonitorAggregatorConfig()

def rrd_site(name):
    sname = name.split(".")[0]
    return "rrd_%s.xml" % sname

###########################################################
#
# Functions
#
###########################################################

status_attributes = {'Status':("Idle", "Running", "Held", "Wait", "Pending", "StageIn", "IdleOther", "StageOut"),
                   'Requested':("Idle", "MaxRun"),
                   'ClientMonitor':("InfoAge", "JobsIdle", "JobsRunning", "JobsRunHere", "GlideIdle", "GlideRunning", "GlideTotal")}

##############################################################################
# create an aggregate of status files, write it in an aggregate status file
# end return the values
def aggregateStatus(in_downtime):
    global monitorAggregatorConfig

    avgEntries = ('InfoAge',)

    type_strings = {'Status':'Status', 'Requested':'Req', 'ClientMonitor':'Client'}
    global_total = {'Status':None, 'Requested':None, 'ClientMonitor':None}
    status = {'entries':{}, 'total':global_total}
    status_fe = {'frontends':{}} #analogous to above but for frontend totals

    # initialize the RRD dictionary, so it gets created properly
    val_dict = {}
    for tp in global_total.keys():
        # type - status or requested
        if not (tp in status_attributes.keys()):
            continue

        tp_str = type_strings[tp]

        attributes_tp = status_attributes[tp]
        for a in attributes_tp:
            val_dict["%s%s" % (tp_str, a)] = None

    nr_entries = 0
    nr_feentries = {} #dictionary for nr entries per fe
    for entry in monitorAggregatorConfig.entries:
        # load entry status file
        status_fname = os.path.join(os.path.join(monitorAggregatorConfig.monitor_dir, 'entry_' + entry),
                                  monitorAggregatorConfig.status_relname)
        try:
            entry_data = glideinwms_libs.xmlParse.xmlfile2dict(status_fname)
        except IOError:
            continue # file not found, ignore

        # update entry 
        status['entries'][entry] = {'downtime':entry_data['downtime'], 'frontends':entry_data['frontends']}

        # update total
        if entry_data.has_key('total'):
            nr_entries += 1
            status['entries'][entry]['total'] = entry_data['total']

            for w in global_total.keys():
                tel = global_total[w]
                if not entry_data['total'].has_key(w):
                    continue
                el = entry_data['total'][w]
                if tel == None:
                    # new one, just copy over
                    global_total[w] = {}
                    tel = global_total[w]
                    for a in el.keys():
                        tel[a] = int(el[a]) #coming from XML, everything is a string
                else:
                    # successive, sum 
                    for a in el.keys():
                        if tel.has_key(a):
                            tel[a] += int(el[a])

                        # if any attribute from prev. frontends are not in the current one, remove from total
                        for a in tel.keys():
                            if not el.has_key(a):
                                del tel[a]

        # update frontends
        if entry_data.has_key('frontends'):
            #loop on fe's in this entry
            for fe in entry_data['frontends'].keys():
                #compare each to the list of fe's accumulated so far
                if not status_fe['frontends'].has_key(fe):
                    status_fe['frontends'][fe] = {}
                if not nr_feentries.has_key(fe):
                    nr_feentries[fe] = 1 #already found one
                else:
                    nr_feentries[fe] += 1
                for w in entry_data['frontends'][fe].keys():
                    if not status_fe['frontends'][fe].has_key(w):
                        status_fe['frontends'][fe][w] = {}
                    tela = status_fe['frontends'][fe][w]
                    ela = entry_data['frontends'][fe][w]
                    for a in ela.keys():
                        #for the 'Downtime' field (only bool), do logical AND of all site downtimes
                        # 'w' is frontend attribute name, ie 'ClientMonitor' or 'Downtime'
                        # 'a' is sub-field, such as 'GlideIdle' or 'status'
                        if w == 'Downtime' and a == 'status':
                            ela_val = (ela[a] != 'False') # Check if 'True' or 'False' but default to True if neither
                            if tela.has_key(a):
                                try:
                                    tela[a] = tela[a] and ela_val
                                except:
                                    pass # just protect
                            else:
                                tela[a] = ela_val
                        else:
                            try:
                                #if there already, sum
                                if tela.has_key(a):
                                    tela[a] += int(ela[a])
                                else:
                                    tela[a] = int(ela[a])
                            except:
                                pass #not an int, not Downtime, so do nothing

                        # if any attribute from prev. frontends are not in the current one, remove from total
                        for a in tela.keys():
                            if not ela.has_key(a):
                                del tela[a]


    for w in global_total.keys():
        if global_total[w] == None:
            del global_total[w] # remove entry if not defined
        else:
            tel = global_total[w]
            for a in tel.keys():
                if a in avgEntries:
                    tel[a] = tel[a] / nr_entries # since all entries must have this attr to be here, just divide by nr of entries

    #do average for per-fe stat--'InfoAge' only
    for fe in status_fe['frontends'].keys():
        for w in status_fe['frontends'][fe].keys():
            tel = status_fe['frontends'][fe][w]
            for a in tel.keys():
                if a in avgEntries and nr_feentries.has_key(fe):
                    tel[a] = tel[a] / nr_feentries[fe] # divide per fe


    xml_downtime = glideinwms_libs.xmlFormat.dict2string({}, dict_name='downtime', el_name='', params={'status':str(in_downtime)}, leading_tab=glideinwms_libs.xmlFormat.DEFAULT_TAB)

    # Write xml files
    updated = time.time()
    xml_str = ('<?xml version="1.0" encoding="ISO-8859-1"?>\n\n' +
             '<glideFactoryQStats>\n' +
             get_xml_updated(updated, indent_tab=glideinwms_libs.xmlFormat.DEFAULT_TAB, leading_tab=glideinwms_libs.xmlFormat.DEFAULT_TAB) + "\n" +
             xml_downtime + "\n" +
             glideinwms_libs.xmlFormat.dict2string(status["entries"], dict_name="entries", el_name="entry",
                                   subtypes_params={"class":{"dicts_params":{"frontends":{"el_name":"frontend",
                                                                                          "subtypes_params":{"class":{"subclass_params":{"Requested":{"dicts_params":{"Parameters":{"el_name":"Parameter",
                                                                                                                                                                                    "subtypes_params":{"class":{}}}}}}}}}}}},
                                   leading_tab=glideinwms_libs.xmlFormat.DEFAULT_TAB) + "\n" +
             glideinwms_libs.xmlFormat.class2string(status["total"], inst_name="total", leading_tab=glideinwms_libs.xmlFormat.DEFAULT_TAB) + "\n" +
             glideinwms_libs.xmlFormat.dict2string(status_fe["frontends"], dict_name="frontends", el_name="frontend",
                                   subtypes_params={"class":{"subclass_params":{"Requested":{"dicts_params":{"Parameters":{"el_name":"Parameter",
                                                                                                                           "subtypes_params":{"class":{}}}}}}}},
                                   leading_tab=glideinwms_libs.xmlFormat.DEFAULT_TAB) + "\n" +
             "</glideFactoryQStats>\n")
    glideFactoryMonitoring.monitoringConfig.write_file(monitorAggregatorConfig.status_relname, xml_str)

    # Write rrds
    glideFactoryMonitoring.monitoringConfig.establish_dir("total")

    for tp in global_total.keys():
        # type - status or requested
        if not (tp in status_attributes.keys()):
            continue

        tp_str = type_strings[tp]
        attributes_tp = status_attributes[tp]

        tp_el = global_total[tp]

        for a in tp_el.keys():
            if a in attributes_tp:
                a_el = int(tp_el[a])
                val_dict["%s%s" % (tp_str, a)] = a_el

    glideFactoryMonitoring.monitoringConfig.write_rrd_multi("total/Status_Attributes",
                                                            "GAUGE", updated, val_dict)

    return status

######################################################################################
# create an aggregate of log summary files, write it in an aggregate log summary file
# end return the values
def aggregateLogSummary():
    global monitorAggregatorConfig

    # initialize global counters
    global_total = {'Current':{}, 'Entered':{}, 'Exited':{}, 'CompletedCounts':{'Sum':{}, 'Waste':{}, 'WasteTime':{}, 'Lasted':{}, 'JobsNr':{}, 'JobsDuration':{}}}

    for s in ('Wait', 'Idle', 'Running', 'Held'):
        for k in ['Current', 'Entered', 'Exited']:
            global_total[k][s] = 0

    for s in ('Completed', 'Removed'):
        for k in ['Entered']:
            global_total[k][s] = 0

    for k in ['idle', 'validation', 'badput', 'nosuccess']:
        for w in ("Waste", "WasteTime"):
            el = {}
            for t in glideFactoryMonitoring.getAllMillRanges():
                el[t] = 0
            global_total['CompletedCounts'][w][k] = el

    el = {}
    for t in glideFactoryMonitoring.getAllTimeRanges():
        el[t] = 0
    global_total['CompletedCounts']['Lasted'] = el

    el = {}
    for t in glideFactoryMonitoring.getAllJobRanges():
        el[t] = 0
    global_total['CompletedCounts']['JobsNr'] = el

    el = {}
    for t in glideFactoryMonitoring.getAllTimeRanges():
        el[t] = 0
    global_total['CompletedCounts']['JobsDuration'] = el

    global_total['CompletedCounts']['Sum'] = {'Glideins':0,
                                            'Lasted':0,
                                            'FailedNr':0,
                                            'JobsNr':0,
                                            'JobsLasted':0,
                                            'JobsGoodput':0,
                                            'JobsTerminated':0,
                                            'CondorLasted':0}

    #
    status = {'entries':{}, 'total':global_total}
    nr_entries = 0
    for entry in monitorAggregatorConfig.entries:
        # load entry log summary file
        status_fname = os.path.join(os.path.join(monitorAggregatorConfig.monitor_dir, 'entry_' + entry),
                                  monitorAggregatorConfig.logsummary_relname)
        try:
            entry_data = glideinwms_libs.xmlParse.xmlfile2dict(status_fname, always_singular_list=['Fraction', 'TimeRange', 'Range'])
        except IOError:
            continue # file not found, ignore

        # update entry
        out_data = {}
        for frontend in entry_data['frontends'].keys():
            fe_el = entry_data['frontends'][frontend]
            out_fe_el = {}
            for k in ['Current', 'Entered', 'Exited']:
                out_fe_el[k] = {}
                for s in fe_el[k].keys():
                    out_fe_el[k][s] = int(fe_el[k][s])
            out_fe_el['CompletedCounts'] = {'Waste':{}, 'WasteTime':{}, 'Lasted':{}, 'JobsNr':{}, 'JobsDuration':{}, 'Sum':{}}
            for tkey in fe_el['CompletedCounts']['Sum'].keys():
                out_fe_el['CompletedCounts']['Sum'][tkey] = int(fe_el['CompletedCounts']['Sum'][tkey])
            for k in ['idle', 'validation', 'badput', 'nosuccess']:
                for w in ("Waste", "WasteTime"):
                    out_fe_el['CompletedCounts'][w][k] = {}
                    for t in glideFactoryMonitoring.getAllMillRanges():
                        out_fe_el['CompletedCounts'][w][k][t] = int(fe_el['CompletedCounts'][w][k][t]['val'])
            for t in glideFactoryMonitoring.getAllTimeRanges():
                out_fe_el['CompletedCounts']['Lasted'][t] = int(fe_el['CompletedCounts']['Lasted'][t]['val'])
            out_fe_el['CompletedCounts']['JobsDuration'] = {}
            for t in glideFactoryMonitoring.getAllTimeRanges():
                out_fe_el['CompletedCounts']['JobsDuration'][t] = int(fe_el['CompletedCounts']['JobsDuration'][t]['val'])
            for t in glideFactoryMonitoring.getAllJobRanges():
                out_fe_el['CompletedCounts']['JobsNr'][t] = int(fe_el['CompletedCounts']['JobsNr'][t]['val'])
            out_data[frontend] = out_fe_el

        status['entries'][entry] = {'frontends':out_data}

        # update total
        if entry_data.has_key('total'):
            nr_entries += 1
            local_total = {}

            for k in ['Current', 'Entered', 'Exited']:
                local_total[k] = {}
                for s in global_total[k].keys():
                    local_total[k][s] = int(entry_data['total'][k][s])
                    global_total[k][s] += int(entry_data['total'][k][s])
            local_total['CompletedCounts'] = {'Sum':{}, 'Waste':{}, 'WasteTime':{}, 'Lasted':{}, 'JobsNr':{}, 'JobsDuration':{}}
            for tkey in entry_data['total']['CompletedCounts']['Sum'].keys():
                local_total['CompletedCounts']['Sum'][tkey] = int(entry_data['total']['CompletedCounts']['Sum'][tkey])
                global_total['CompletedCounts']['Sum'][tkey] += int(entry_data['total']['CompletedCounts']['Sum'][tkey])
            for k in ['idle', 'validation', 'badput', 'nosuccess']:
                for w in ("Waste", "WasteTime"):
                    local_total['CompletedCounts'][w][k] = {}
                    for t in glideFactoryMonitoring.getAllMillRanges():
                        local_total['CompletedCounts'][w][k][t] = int(entry_data['total']['CompletedCounts'][w][k][t]['val'])
                        global_total['CompletedCounts'][w][k][t] += int(entry_data['total']['CompletedCounts'][w][k][t]['val'])

            for t in glideFactoryMonitoring.getAllTimeRanges():
                local_total['CompletedCounts']['Lasted'][t] = int(entry_data['total']['CompletedCounts']['Lasted'][t]['val'])
                global_total['CompletedCounts']['Lasted'][t] += int(entry_data['total']['CompletedCounts']['Lasted'][t]['val'])
            local_total['CompletedCounts']['JobsDuration'] = {}
            for t in glideFactoryMonitoring.getAllTimeRanges():
                local_total['CompletedCounts']['JobsDuration'][t] = int(entry_data['total']['CompletedCounts']['JobsDuration'][t]['val'])
                global_total['CompletedCounts']['JobsDuration'][t] += int(entry_data['total']['CompletedCounts']['JobsDuration'][t]['val'])

            for t in glideFactoryMonitoring.getAllJobRanges():
                local_total['CompletedCounts']['JobsNr'][t] = int(entry_data['total']['CompletedCounts']['JobsNr'][t]['val'])
                global_total['CompletedCounts']['JobsNr'][t] += int(entry_data['total']['CompletedCounts']['JobsNr'][t]['val'])

            status['entries'][entry]['total'] = local_total

    # Write xml files
    updated = time.time()
    xml_str = ('<?xml version="1.0" encoding="ISO-8859-1"?>\n\n' +
             '<glideFactoryLogSummary>\n' +
             get_xml_updated(updated, indent_tab=glideinwms_libs.xmlFormat.DEFAULT_TAB, leading_tab=glideinwms_libs.xmlFormat.DEFAULT_TAB) + "\n" +
             glideinwms_libs.xmlFormat.dict2string(status["entries"], dict_name="entries", el_name="entry",
                                   subtypes_params={"class":{"dicts_params":{"frontends":{"el_name":"frontend",
                                                                                          "subtypes_params":{"class":{'subclass_params':{'CompletedCounts':glideFactoryMonitoring.get_completed_stats_xml_desc()}}}}},
                                                             "subclass_params":{"total":{"subclass_params":{'CompletedCounts':glideFactoryMonitoring.get_completed_stats_xml_desc()}}}
                                                             }
                                                    },
                                   leading_tab=glideinwms_libs.xmlFormat.DEFAULT_TAB) + "\n" +
             glideinwms_libs.xmlFormat.class2string(status["total"], inst_name="total", subclass_params={'CompletedCounts':glideFactoryMonitoring.get_completed_stats_xml_desc()}, leading_tab=glideinwms_libs.xmlFormat.DEFAULT_TAB) + "\n" +
             "</glideFactoryLogSummary>\n")
    glideFactoryMonitoring.monitoringConfig.write_file(monitorAggregatorConfig.logsummary_relname, xml_str)

    # Write rrds
    fe_dir = "total"
    sdata = status["total"]['Current']
    # AT Unused??
    #sdiff = status["total"]

    glideFactoryMonitoring.monitoringConfig.establish_dir(fe_dir)
    val_dict_counts = {}
    val_dict_counts_desc = {}
    val_dict_completed = {}
    val_dict_stats = {}
    val_dict_waste = {}
    val_dict_wastetime = {}
    for s in ('Wait', 'Idle', 'Running', 'Held', 'Completed', 'Removed'):
        if not (s in ('Completed', 'Removed')): # I don't have their numbers from inactive logs
            count = sdata[s]
            val_dict_counts["Status%s" % s] = count
            val_dict_counts_desc["Status%s" % s] = {'ds_type':'GAUGE'}

            exited = -status["total"]['Exited'][s]
            val_dict_counts["Exited%s" % s] = exited
            val_dict_counts_desc["Exited%s" % s] = {'ds_type':'ABSOLUTE'}

        entered = status["total"]['Entered'][s]
        val_dict_counts["Entered%s" % s] = entered
        val_dict_counts_desc["Entered%s" % s] = {'ds_type':'ABSOLUTE'}

        if s == 'Completed':
            completed_counts = status["total"]['CompletedCounts']
            count_entered_times = completed_counts['Lasted']
            count_jobnrs = completed_counts['JobsNr']
            count_jobs_duration = completed_counts['JobsDuration']
            count_waste_mill = completed_counts['Waste']
            time_waste_mill = completed_counts['WasteTime']
            # save run times
            for timerange in count_entered_times.keys():
                val_dict_stats['Lasted_%s' % timerange] = count_entered_times[timerange]
                # they all use the same indexes
                val_dict_stats['JobsLasted_%s' % timerange] = count_jobs_duration[timerange]

            # save jobsnr
            for jobrange in count_jobnrs.keys():
                val_dict_stats['JobsNr_%s' % jobrange] = count_jobnrs[jobrange]

            # save simple vals
            for tkey in completed_counts['Sum'].keys():
                val_dict_completed[tkey] = completed_counts['Sum'][tkey]

            # save waste_mill
            for w in count_waste_mill.keys():
                count_waste_mill_w = count_waste_mill[w]
                for p in count_waste_mill_w.keys():
                    val_dict_waste['%s_%s' % (w, p)] = count_waste_mill_w[p]

            for w in time_waste_mill.keys():
                time_waste_mill_w = time_waste_mill[w]
                for p in time_waste_mill_w.keys():
                    val_dict_wastetime['%s_%s' % (w, p)] = time_waste_mill_w[p]

    # write the data to disk
    glideFactoryMonitoring.monitoringConfig.write_rrd_multi_hetero("%s/Log_Counts" % fe_dir,
                                                            val_dict_counts_desc, updated, val_dict_counts)
    glideFactoryMonitoring.monitoringConfig.write_rrd_multi("%s/Log_Completed" % fe_dir,
                                                            "ABSOLUTE", updated, val_dict_completed)
    glideFactoryMonitoring.monitoringConfig.write_rrd_multi("%s/Log_Completed_Stats" % fe_dir,
                                                            "ABSOLUTE", updated, val_dict_stats)
    # Disable Waste RRDs... WasteTime much more useful 
    #glideFactoryMonitoring.monitoringConfig.write_rrd_multi("%s/Log_Completed_Waste"%fe_dir,
    #                                                        "ABSOLUTE",updated,val_dict_waste)
    glideFactoryMonitoring.monitoringConfig.write_rrd_multi("%s/Log_Completed_WasteTime" % fe_dir,
                                                            "ABSOLUTE", updated, val_dict_wastetime)

    return status

def aggregateRRDStats():
    global monitorAggregatorConfig
    # AT Unused??
    #factoryStatusData = glideFactoryMonitoring.FactoryStatusData()
    rrdstats_relname = glideFactoryMonitoring.rrd_list
    tab = glideinwms_libs.xmlFormat.DEFAULT_TAB

    for rrd in rrdstats_relname:

        # assigns the data from every site to 'stats'
        stats = {}
        for entry in monitorAggregatorConfig.entries:
            rrd_fname = os.path.join(os.path.join(monitorAggregatorConfig.monitor_dir, 'entry_' + entry), rrd_site(rrd))
            try:
                stats[entry] = glideinwms_libs.xmlParse.xmlfile2dict(rrd_fname, always_singular_list={'timezone':{}})
            except IOError:
                glideFactoryLib.log_files.logDebug("aggregateRRDStats %s exception: parse_xml, IOError" % rrd_fname)

        stats_entries = stats.keys()
        if len(stats_entries) == 0:
            continue # skip this RRD... nothing to aggregate
        stats_entries.sort()

        # Get all the resolutions, data_sets and frontends... for totals
        resolution = sets.Set([])
        frontends = sets.Set([])
        data_sets = sets.Set([])
        for entry in stats_entries:
            entry_resolution = stats[entry]['total']['periods'].keys()
            if len(entry_resolution) == 0:
                continue # not an interesting entry
            resolution = resolution.union(entry_resolution)
            entry_data_sets = stats[entry]['total']['periods'][entry_resolution[0]]
            data_sets = data_sets.union(entry_data_sets)
            entry_frontends = stats[entry]['frontends'].keys()
            frontends = frontends.union(entry_frontends)
            entry_data_sets = stats[entry]['total']['periods'][entry_resolution[0]]

        resolution = list(resolution)
        frontends = list(frontends)
        data_sets = list(data_sets)

        # create a dictionary that will hold the aggregate data
        clients = frontends + ['total']
        aggregate_output = {}
        for client in clients:
            aggregate_output[client] = {}
            for res in resolution:
                aggregate_output[client][res] = {}
                for data_set in data_sets:
                    aggregate_output[client][res][data_set] = 0

        # assign the aggregate data to 'aggregate_output'
        for client in aggregate_output:
            for res in aggregate_output[client]:
                for data_set in aggregate_output[client][res]:
                    for entry in stats_entries:
                        if client == 'total':
                            try:
                                aggregate_output[client][res][data_set] += float(stats[entry][client]['periods'][res][data_set])
                            except KeyError:
                                # well, some may be just missing.. can happen
                                glideFactoryLib.log_files.logDebug("aggregate_data, KeyError stats[%s][%s][%s][%s][%s]" % (entry, client, 'periods', res, data_set))

                        else:
                            if stats[entry]['frontends'].has_key(client):
                                # not all the entries have all the frontends
                                try:
                                    aggregate_output[client][res][data_set] += float(stats[entry]['frontends'][client]['periods'][res][data_set])
                                except KeyError:
                                    # well, some may be just missing.. can happen
                                    glideFactoryLib.log_files.logDebug("aggregate_data, KeyError stats[%s][%s][%s][%s][%s][%s]" % (entry, 'frontends', client, 'periods', res, data_set))

        # write an aggregate XML file

        # data from indivdual entries
        entry_str = tab + "<entries>\n"
        for entry in stats_entries:
            entry_name = entry.split("/")[-1]
            entry_str += 2 * tab + "<entry name = \"" + entry_name + "\">\n"
            entry_str += 3 * tab + '<total>\n'
            try:
                entry_str += (glideinwms_libs.xmlFormat.dict2string(stats[entry]['total']['periods'], dict_name='periods', el_name='period', subtypes_params={"class":{}}, indent_tab=tab, leading_tab=4 * tab) + "\n")
            except UnboundLocalError:
                glideFactoryLib.log_files.logDebug("total_data, NameError or TypeError")
            except NameError:
                glideFactoryLib.log_files.logDebug("total_data, NameError or TypeError")
            entry_str += 3 * tab + '</total>\n'

            entry_str += (3 * tab + '<frontends>\n')
            try:
                entry_frontends = stats[entry]['frontends'].keys()
                entry_frontends.sort()
                for frontend in entry_frontends:
                    entry_str += (4 * tab + '<frontend name=\"' +
                                  frontend + '\">\n')
                    try:
                        entry_str += (glideinwms_libs.xmlFormat.dict2string(stats[entry]['frontends'][frontend]['periods'], dict_name='periods', el_name='period', subtypes_params={"class":{}}, indent_tab=tab, leading_tab=5 * tab) + "\n")
                    except KeyError:
                        glideFactoryLib.log_files.logDebug("frontend_data, KeyError")
                    entry_str += 4 * tab + '</frontend>\n'
            except TypeError:
                glideFactoryLib.log_files.logDebug("frontend_data, TypeError")
            entry_str += (3 * tab + '</frontends>\n')
            entry_str += 2 * tab + "</entry>\n"
        entry_str += tab + "</entries>\n"

        # aggregated data
        total_xml_str = 2 * tab + '<total>\n'
        total_data = aggregate_output['total']
        try:
            total_xml_str += (glideinwms_libs.xmlFormat.dict2string(total_data, dict_name='periods', el_name='period', subtypes_params={"class":{}}, indent_tab=tab, leading_tab=4 * tab) + "\n")
        except UnboundLocalError:
            glideFactoryLib.log_files.logDebug("total_data, NameError or TypeError")
        except NameError:
            glideFactoryLib.log_files.logDebug("total_data, NameError or TypeError")
        total_xml_str += 2 * tab + '</total>\n'

        frontend_xml_str = (2 * tab + '<frontends>\n')
        try:
            for frontend in frontends:
                frontend_xml_str += (3 * tab + '<frontend name=\"' +
                                     frontend + '\">\n')
                frontend_data = aggregate_output[frontend]
                frontend_xml_str += (glideinwms_libs.xmlFormat.dict2string(frontend_data, dict_name='periods', el_name='period', subtypes_params={"class":{}}, indent_tab=tab, leading_tab=4 * tab) + "\n")
                frontend_xml_str += 3 * tab + '</frontend>\n'
        except TypeError:
            glideFactoryLib.log_files.logDebug("frontend_data, TypeError")
        frontend_xml_str += (2 * tab + '</frontends>\n')

        data_str = (tab + "<total>\n" + total_xml_str + frontend_xml_str +
                     tab + "</total>\n")

        # putting it all together
        updated = time.time()
        xml_str = ('<?xml version="1.0" encoding="ISO-8859-1"?>\n\n' +
                   '<glideFactoryRRDStats>\n' +
                   get_xml_updated(updated, indent_tab=glideinwms_libs.xmlFormat.DEFAULT_TAB, leading_tab=glideinwms_libs.xmlFormat.DEFAULT_TAB) + "\n" + entry_str +
                   data_str + '</glideFactoryRRDStats>')

        try:
            glideFactoryMonitoring.monitoringConfig.write_file(rrd_site(rrd), xml_str)
        except IOError:
            glideFactoryLib.log_files.logDebug("write_file %s, IOError" % rrd_site(rrd))

    return


#################        PRIVATE      #####################

def get_xml_updated(when, indent_tab=glideinwms_libs.xmlFormat.DEFAULT_TAB, leading_tab=""):
    return glideFactoryMonitoring.time2xml(when, "updated", indent_tab, leading_tab)



