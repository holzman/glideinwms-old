#!/bin/bash

#
# Project:
#   glideinWMS
#
# File Version: 
#   $Id: java_setup.sh,v 1.1 2010/12/22 22:22:05 sfiligoi Exp $
#
# Description:
#   This script will setup the java parameters
#

glidein_config=$1
tmp_fname=${glidein_config}.$$.tmp

condor_vars_file=`grep -i "^CONDOR_VARS_FILE " $glidein_config | awk '{print $2}'`

# import add_config_line and add_condor_vars_line functions
add_config_line_source=`grep '^ADD_CONFIG_LINE_SOURCE ' $glidein_config | awk '{print $2}'`
source $add_config_line_source

# Is site configured with glexec?
need_java=`grep '^GLIDEIN_Java_Use ' $glidein_config | awk '{print $2}'`
if [ -z "$need_java" ]; then
    echo "`date` GLIDEIN_Java_Use not configured. Defaulting it to NEVER"
    need_java="NEVER"
fi

if [ "$need_java" == "NEVER" ]; then
  echo "`date` VO does not want to use Java"
  exit 0
fi

java_bin=`which java`

if [ -z "$java_bin" ]; then
   if [ "$need_java" == "REQUIRED" ]; then
     echo "`date` VO mandates the use of Java but java not in the path." 1>&2
     exit 1
   fi
   echo "`date` Java not found, but it was OPTIONAL"
   exit 0
fi

echo "`date` Using Java in $java_bin"

add_config_line "JAVA" "$java_bin"
add_condor_vars_line "JAVA" "C" "-" "+" "Y" "N" "-"

add_config_line "JAVA_MAXHEAP_ARGUMENT" "-Xmx"
add_condor_vars_line "JAVA_MAXHEAP_ARGUMENT" "C" "-" "+" "Y" "N" "-"

add_config_line "JAVA_CLASSPATH_ARGUMENT" "-classpath"
add_condor_vars_line "JAVA_CLASSPATH_ARGUMENT" "C" "-" "+" "Y" "N" "-"

add_config_line "JAVA_CLASSPATH_DEFAULT" '$(LIB),$(LIB)/scimark2lib.jar,.'
add_condor_vars_line "JAVA_CLASSPATH_DEFAULT" "C" "-" "+" "Y" "N" "-"

