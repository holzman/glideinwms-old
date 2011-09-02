#!/usr/bin/env python
#
# Project:
#   glideinWMS
#
# File Version: 
#   $Id: find_StartdLogs.py,v 1.4.8.2 2010/09/24 15:30:36 parag Exp $
#
# Description:
#   Print out the StartdLogs for a certain date
#
# Usage: find_StartdLogs.py <factory> YY/MM/DD [hh:mm:ss]
#

import sys
import os
import gWftArgsHelper
import gWftLogParser
import glideinwms_factory.glideFactoryConfig

USAGE = "Usage: find_StartdLogs.py <factory> YY/MM/DD [hh:mm:ss]"

# return a GlideinDescript with
# factory_dir, date_arr and time_arr
def parse_args():
    if len(sys.argv) < 3:
        raise ValueError, "Not enough arguments!"

    factory_dir = sys.argv[1]
    try:
        glideinwms_factory.glideFactoryConfig.factoryConfig.glidein_descript_file = os.path.join(factory_dir, glideinwms_factory.glideFactoryConfig.factoryConfig.glidein_descript_file)
        glideinDescript = glideinwms_factory.glideFactoryConfig.GlideinDescript()
    except:
        raise ValueError, "%s is not a factory!" % factory_dir

    glideinDescript.factory_dir = factory_dir
    glideinDescript.date_arr = gWftArgsHelper.parse_date(sys.argv[2])
    if len(sys.argv) >= 4:
        glideinDescript.time_arr = gWftArgsHelper.parse_time(sys.argv[3])
    else:
        glideinDescript.time_arr = (0, 0, 0)

    return glideinDescript

def main():
    try:
        glideinDescript = parse_args()
    except ValueError, e:
        sys.stderr.write("%s\n\n%s\n" % (e, USAGE))
        sys.exit(1)
    entries = glideinDescript.data['Entries'].split(',')

    log_list = gWftLogParser.get_glidein_logs(glideinDescript.factory_dir, entries, glideinDescript.date_arr, glideinDescript.time_arr, "err")
    for fname in log_list:
        sys.stdout.write("%s\n" % fname)
        sys.stdout.write("===========================================================\n")
        sys.stdout.write("%s\n" % gWftLogParser.get_CondorLog(fname, 'CondorLog'))



if __name__ == '__main__':
    main()

