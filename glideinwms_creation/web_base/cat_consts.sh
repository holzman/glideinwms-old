#!/bin/bash
#
# Project:
#   glideinWMS
#
# File Version: 
#   $Id: cat_consts.sh,v 1.9.8.1 2010/09/08 03:30:00 parag Exp $
#

glidein_config=$1
tmp_fname=${glidein_config}.$$.tmp

dir_id=$2

function warn {
 echo `date` $@ 1>&2
}

# import add_config_line function
add_config_line_source=`grep '^ADD_CONFIG_LINE_SOURCE ' $glidein_config | awk '{print $2}'`
source $add_config_line_source

# import get_prefix function
get_id_selectors_source=`grep '^GET_ID_SELECTORS_SOURCE ' $glidein_config | awk '{print $2}'`
source $get_id_selectors_source

id_prefix=`get_prefix $dir_id`

###################################
# Find file names
consts_file=`grep "^${id_prefix}CONSTS_FILE " $glidein_config | awk '{print $2}'`
if [ -z "$consts_file" ]; then
    warn "Cannot find ${id_prefix}CONSTS_FILE in $glidein_config!"
    exit 1
fi

##################################
# Merge constants with config file
if [ -n "$consts_file" ]; then
    echo "# --- Provided $dir_id constants  ---" >> $glidein_config
    # merge constants
    while read line
    do
	add_config_line $line
    done < "$consts_file"
    echo "# --- End $dir_id constants       ---" >> $glidein_config
fi
