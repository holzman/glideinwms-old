#!/bin/bash
#
# Project:
#   glideinWMS
#
# File Version: 
#   $Id: condor_startup.sh,v 1.48.2.12 2011/06/16 19:08:29 parag Exp $
#
# Description:
# This script starts the condor daemons expects a config file as a parameter
#

#function to handle passing signals to the child processes
function on_die {
echo "Condor startup received kill signal... shutting down condor processes"
$CONDOR_DIR/sbin/condor_master -k $PWD/condor_master2.pid
ON_DIE=1
}

function ignore_signal {
        echo "Condor startup received SIGHUP signal, ignoring..."
}



# first of all, clean up any CONDOR variable
condor_vars=`env |awk '/^_[Cc][Oo][Nn][Dd][Oo][Rr]_/{split($1,a,"=");print a[1]}'`
for v in $condor_vars; do
 unset $v
done
echo "Removed condor variables $condor_vars" 1>&2

# Condor 7.5.6 and above will use the system's gsi-authz.conf.  We don't want that.
export GSI_AUTHZ_CONF=/dev/null

# pstr = variable representing an appendix
pstr='"'

config_file=$1

# find out whether user wants to run job or run test
operation_mode=`grep -i "^DEBUG_MODE " $config_file | awk '{print $2}'`

if [ "$operation_mode" == "1" ] || [ "$operation_mode" == "2" ]; then
    echo "-------- $config_file in condor_startup.sh ----------" 1>&2
    cat $config_file 1>&2
    echo "-----------------------------------------------------" 1>&2
fi

main_stage_dir=`grep -i "^GLIDEIN_WORK_DIR " $config_file | awk '{print $2}'`

description_file=`grep -i "^DESCRIPTION_FILE " $config_file | awk '{print $2}'`

# grab user proxy so we can authenticate ourselves to run condor_fetchlog
X509_USER_PROXY=`grep -i "^X509_USER_PROXY " $config_file | awk '{print $2}'`

in_condor_config="${main_stage_dir}/`grep -i '^condor_config ' ${main_stage_dir}/${description_file} | awk '{print $2}'`"

export CONDOR_CONFIG="${PWD}/condor_config"

cp "$in_condor_config" $CONDOR_CONFIG

echo "# ---- start of condor_startup generated part ----" >> $CONDOR_CONFIG

wrapper_list=`grep -i "^WRAPPER_LIST " $config_file | awk '{print $2}'`

#
# Create the job wrapper
#
condor_job_wrapper="condor_job_wrapper.sh"
cat > $condor_job_wrapper <<EOF
#!/bin/bash

# This script is started just before the user job
# It is referenced by the USER_JOB_WRAPPER

EOF

for fname in `cat $wrapper_list`; 
do 
  cat "$fname" >> $condor_job_wrapper
done

cat >> $condor_job_wrapper <<EOF

# Condor job wrappers must replace its own image
exec "\$@"
EOF

chmod a+x $condor_job_wrapper
echo "USER_JOB_WRAPPER = \$(LOCAL_DIR)/$condor_job_wrapper" >> $CONDOR_CONFIG


# glidein_variables = list of additional variables startd is to publish
glidein_variables=""

# job_env = environment to pass to the job
job_env=""


#
# Set a variable read from a file
#
function set_var {
    var_name=$1
    var_type=$2
    var_def=$3
    var_condor=$4
    var_req=$5
    var_exportcondor=$6
    var_user=$7

    if [ -z "$var_name" ]; then
	# empty line
	return 0
    fi

    var_val=`grep "^$var_name " $config_file | awk '{print substr($0,index($0,$2))}'`
    if [ -z "$var_val" ]; then
	if [ "$var_req" == "Y" ]; then
	    # needed var, exit with error
	    echo "Cannot extract $var_name from '$config_file'" 1>&2
	    exit 1
	elif [ "$var_def" == "-" ]; then
	    # no default, do not set
	    return 0
	else
	    eval var_val=$var_def
	fi
    fi
    
    if [ "$var_condor" == "+" ]; then
	var_condor=$var_name
    fi
    if [ "$var_type" == "S" ]; then
	var_val_str="${pstr}${var_val}${pstr}"
    else
	var_val_str="$var_val"
    fi

    # insert into condor_config
    echo "$var_condor=$var_val_str" >> $CONDOR_CONFIG

    if [ "$var_exportcondor" == "Y" ]; then
	# register var_condor for export
	if [ -z "$glidein_variables" ]; then
	   glidein_variables="$var_condor"
	else
	   glidein_variables="$glidein_variables,$var_condor"
	fi
    fi

    if [ "$var_user" != "-" ]; then
	# - means do not export
	if [ "$var_user" == "+" ]; then
	    var_user=$var_name
	elif [ "$var_user" == "@" ]; then
	    var_user=$var_condor
	fi

	if [ -z "$job_env" ]; then
	   job_env="$var_user=$var_val"
	else
	   job_env="$job_env;$var_user=$var_val"
	fi
    fi

    # define it for future use
    eval "$var_name='$var_val'"
    return 0
}

function python_b64uuencode {
    echo "begin-base64 644 -"
    python -c 'import binascii,sys;fd=sys.stdin;buf=fd.read();size=len(buf);idx=0
while size>57:
 print binascii.b2a_base64(buf[idx:idx+57]),;
 idx+=57;
 size-=57;
print binascii.b2a_base64(buf[idx:]),'
    echo "===="
}

function base64_b64uuencode {
    echo "begin-base64 644 -"
    base64 -
    echo "===="
}

# not all WNs have all the tools installed
function b64uuencode {
    which uuencode >/dev/null 2>&1
    if [ $? -eq 0 ]; then
	uuencode -m -
    else
	which base64 >/dev/null 2>&1
	if [ $? -eq 0 ]; then
	    base64_b64uuencode
	else
	    python_b64uuencode
	fi
    fi
}

function cond_print_log {
    # $1 = fname
    # $2 = fpath
    if [ -f  "$2" ]; then
	echo "$1" 1>&2
	echo "======== gzip | uuencode =============" 1>&2
	gzip --stdout "$2" | b64uuencode 1>&2
	echo
    fi
}

# interpret the variables
touch condor_vars.lst.tmp
for vid in GLIDECLIENT_GROUP_CONDOR_VARS_FILE GLIDECLIENT_CONDOR_VARS_FILE ENTRY_CONDOR_VARS_FILE CONDOR_VARS_FILE
do
 condor_vars=`grep -i "^$vid " $config_file | awk '{print $2}'`
 if [ -n "$condor_vars" ]; then
     grep -v "^#" "$condor_vars" >> condor_vars.lst.tmp 
 fi
done

while read line
do
    set_var $line
done < condor_vars.lst.tmp

#let "max_job_time=$job_max_hours * 3600"

# calculate retire time if wall time is defined (undefined=-1)
max_walltime=`grep -i "^GLIDEIN_Max_Walltime " $config_file | awk '{print $2}'`
if [ -z "$max_walltime" ]; then
  retire_time=`grep -i "^GLIDEIN_Retire_Time " $config_file | awk '{print $2}'`
  if [ -z "$retire_time" ]; then
    retire_time=21600
    echo "used default retire time, $retire_time" 1>&2
  else
    echo "used param defined retire time, $retire_time" 1>&2
  fi
else
  echo "max wall time, $max_walltime" 1>&2
  job_maxtime=`grep -i "^GLIDEIN_Job_Max_Time " $config_file | awk '{print $2}'`
  echo "job max time, $job_maxtime" 1>&2
  let "retire_time=$max_walltime - $job_maxtime"
  GLIDEIN_Retire_Time=$retire_time
  echo "calculated retire time, $retire_time" 1>&2
fi
org_GLIDEIN_Retire_Time=$retire_time
# randomize the retire time, to smooth starts and terminations
retire_spread=`grep -i "^GLIDEIN_Retire_Time_Spread " $config_file | awk '{print $2}'`
if [ -z "$retire_spread" ]; then
  let "retire_spread=$retire_time / 10"
  echo "using default retire spread, $retire_spread" 1>&2
else
  echo "used param retire spead, $retire_spread" 1>&2
fi

let "random100=$RANDOM%100"
let "retire_time=$retire_time - $retire_spread * $random100 / 100"

# but protect from going too low
if [ "$retire_time" -lt "600" ]; then
  retire_time=600
fi
echo "Retire time set to $retire_time" 1>&2

now=`date +%s`
let "x509_duration=$X509_EXPIRE - $now - 1"

#if [ $max_proxy_time -lt $max_job_time ]; then
#    max_job_time=$max_proxy_time
#    glidein_expire=$x509_expire
#else
#    let "glidein_expire=$now + $max_job_time"
#fi

let "glidein_toretire=$now + $retire_time"

# put some safety margin
let "session_duration=$x509_duration + 300"

# if in test mode, don't ever start any jobs
START_JOBS="TRUE"
if [ "$operation_mode" == "2" ]; then
	START_JOBS="FALSE"
  # need to know which startd to fetch against
  STARTD_NAME=glidein_$$
fi

cat >> "$CONDOR_CONFIG" <<EOF
# ---- start of condor_startup fixed part ----

SEC_DEFAULT_SESSION_DURATION = $session_duration

LOCAL_DIR = $PWD

#GLIDEIN_EXPIRE = $glidein_expire
GLIDEIN_TORETIRE = $glidein_toretire
GLIDEIN_START_TIME = $now

STARTER_JOB_ENVIRONMENT = $job_env
GLIDEIN_VARIABLES = $glidein_variables

MASTER_NAME = glidein_$$
STARTD_NAME = glidein_$$

#This can be used for locating the proper PID for monitoring
GLIDEIN_PARENT_PID = $$

START = $START_JOBS 

EOF
####################################
if [ $? -ne 0 ]; then
    echo "Error customizing the condor_config" 1>&2
    exit 1
fi

monitor_mode=`grep -i "^MONITOR_MODE " $config_file | awk '{print $2}'`

if [ "$monitor_mode" == "MULTI" ] || [ "$operation_mode" -eq 2 ]; then
    use_multi_monitor=1
else
    use_multi_monitor=0
fi

# get check_include file for testing
if [ "$operation_mode" == "2" ]; then
	condor_config_check_include="${main_stage_dir}/`grep -i '^condor_config_check_include ' ${main_stage_dir}/${description_file} | awk '{print $2}'`"
    echo "# ---- start of include part ----" >> "$CONDOR_CONFIG"
    cat "$condor_config_check_include" >> "$CONDOR_CONFIG"
    if [ $? -ne 0 ]; then
	echo "Error appending check_include to condor_config" 1>&2
	exit 1
    fi
fi

if [ "$use_multi_monitor" -eq 1 ]; then
    condor_config_multi_include="${main_stage_dir}/`grep -i '^condor_config_multi_include ' ${main_stage_dir}/${description_file} | awk '{print $2}'`"
    echo "# ---- start of include part ----" >> "$CONDOR_CONFIG"
    cat "$condor_config_multi_include" >> "$CONDOR_CONFIG"
    if [ $? -ne 0 ]; then
	echo "Error appending multi_include to condor_config" 1>&2
	exit 1
    fi
else
    condor_config_main_include="${main_stage_dir}/`grep -i '^condor_config_main_include ' ${main_stage_dir}/${description_file} | awk '{print $2}'`"
    echo "# ---- start of include part ----" >> "$CONDOR_CONFIG"

    # using two different configs... one for monitor and one for main
    # don't create the monitoring configs and dirs if monitoring is disabled
    if [ "$GLIDEIN_Monitoring_Enabled" == "True" ]; then
      condor_config_monitor_include="${main_stage_dir}/`grep -i '^condor_config_monitor_include ' ${main_stage_dir}/${description_file} | awk '{print $2}'`"
      condor_config_monitor=${CONDOR_CONFIG}.monitor
      cp "$CONDOR_CONFIG" "$condor_config_monitor"
      if [ $? -ne 0 ]; then
	  echo "Error copying condor_config into condor_config.monitor" 1>&2
	  exit 1
      fi
      cat "$condor_config_monitor_include" >> "$condor_config_monitor"
      if [ $? -ne 0 ]; then
	  echo "Error appending monitor_include to condor_config.monitor" 1>&2
	  exit 1
      fi

      cat >> "$condor_config_monitor" <<EOF
# use a different name for monitor
MASTER_NAME = monitor_$$
STARTD_NAME = monitor_$$

# use plural names, since there may be more than one if multiple job VMs
Monitored_Names = "glidein_$$@\$(FULL_HOSTNAME)"
EOF
    fi
    
    cat $condor_config_main_include >> "$CONDOR_CONFIG"
    if [ $? -ne 0 ]; then
	echo "Error appending main_include to condor_config" 1>&2
	exit 1
    fi

    if [ "$GLIDEIN_Monitoring_Enabled" == "True" ]; then
      cat >> "$CONDOR_CONFIG" <<EOF

Monitoring_Name = "monitor_$$@\$(FULL_HOSTNAME)"
EOF

      # also needs to create "monitor" dir for log and execute dirs
      mkdir monitor monitor/log monitor/execute 
      if [ $? -ne 0 ]; then
	  echo "Error creating monitor dirs" 1>&2
	  exit 1
      fi
    fi
fi


mkdir log execute 
if [ $? -ne 0 ]; then
    echo "Error creating condor dirs" 1>&2
    exit 1
fi

####################################

if [ "$operation_mode" == "1" ] || [ "$operation_mode" == "2" ]; then
  echo "--- condor_config ---" 1>&2
  cat $CONDOR_CONFIG 1>&2
  echo "--- ============= ---" 1>&2
  env 1>&2
  echo "--- ============= ---" 1>&2
  echo 1>&2
  #env 1>&2
fi

##	start the condor master
if [ "$use_multi_monitor" -ne 1 ]; then
    # don't start if monitoring is disabled
    if [ "$GLIDEIN_Monitoring_Enabled" == "True" ]; then
      # start monitoring startd
      # use the appropriate configuration file
      tmp_condor_config=$CONDOR_CONFIG
      export CONDOR_CONFIG=$condor_config_monitor

      monitor_start_time=`date +%s`
      echo "Starting monitoring condor at `date` (`date +%s`)" 1>&2

      # set the worst case limit
      # should never hit it, but let's be safe and shutdown automatically at some point
      let "monretmins=( $retire_time + $GLIDEIN_Job_Max_Time ) / 60 - 1"
      $CONDOR_DIR/sbin/condor_master -f -r $monretmins -pidfile $PWD/monitor/condor_master.pid  >/dev/null 2>&1 </dev/null &
      ret=$?
      if [ "$ret" -ne 0 ]; then
	  echo 'Failed to start monitoring condor... still going ahead' 1>&2
      fi

      # clean back
      export CONDOR_CONFIG=$tmp_condor_config

      monitor_starter_log='monitor/log/StarterLog'
    fi
      main_starter_log='log/StarterLog'
else
    main_starter_log='log/StarterLog.vm2'
    monitor_starter_log='log/StarterLog.vm1'
fi

start_time=`date +%s`
echo "=== Condor starting `date` (`date +%s`) ==="
ON_DIE=0
trap 'ignore_signal' HUP
trap 'on_die' TERM
trap 'on_die' INT


#### STARTS CONDOR ####
if [ "$operation_mode" == "2" ]; then
	echo "=== Condor started in test mode ==="
	$CONDOR_DIR/sbin/condor_master -pidfile $PWD/condor_master.pid
else
	$CONDOR_DIR/sbin/condor_master -f -pidfile $PWD/condor_master2.pid &
	# Wait for a few seconds to make sure the pid file is created, 
	# then wait on it for completion
	sleep 5
	if [ -e "$PWD/condor_master2.pid" ]; then
		echo "=== Condor started in background, now waiting on process `cat $PWD/condor_master2.pid` ==="
		wait `cat $PWD/condor_master2.pid`
	fi
fi

condor_ret=$?


end_time=`date +%s`
let elapsed_time=$end_time-$start_time
echo "=== Condor ended `date` (`date +%s`) after $elapsed_time ==="
echo

## perform a condor_fetchlog against the condor_startd
##    if fetch fails, sleep for 'fetch_sleeptime' amount
##    of seconds, then try again.  Repeat until
##    'timeout' amount of time has been reached.
if [ $operation_mode -eq 2 ]; then

  HOST=`uname -n`

  # debug statement
  # echo "CONDOR_CONFIG ENV VAR= `env | grep CONDOR_CONFIG | awk '{split($0,a,"="); print a[2]}'`" 1>&2
  #echo "running condor_fetchlog with the following:" 1>&2
  #echo "\t$CONDOR_DIR/sbin/condor_fetchlog -startd $STARTD_NAME@$HOST STARTD" 1>&2

  fetch_sleeptime=30      # can be dynamically set
  fetch_timeout=500       # can be dynamically set
  fetch_curTime=0         
  fetch_exit_code=1       
  let fetch_attemptsLeft="$fetch_timeout / $fetch_sleeptime"
  while [ "$fetch_curTime" -lt "$fetch_timeout" ]; do	
    sleep $fetch_sleeptime

    let "fetch_curTime  += $fetch_sleeptime" 
	  FETCH_RESULTS=`$CONDOR_DIR/sbin/condor_fetchlog -startd $STARTD_NAME@$HOST STARTD`
    fetch_exit_code=$?
    if [ $fetch_exit_code -eq 0 ]; then
      break
    fi
    echo "fetch exit code=$fetch_exit_code" 1>&2
    echo "fetch failed in this iteration...will try $fetch_attemptsLeft more times."  >&2
    let "fetch_attemptsLeft -= 1" 
  done

  if [ $fetch_exit_code -ne 0 ]; then 
    echo "Able to talk to startd? FALSE" 1>&1 1>&2
		echo "Failed to talk to startd $STARTD_NAME on host $HOST" >&2
    echo "Reason for failing: Condor_fetchlog took too long to talk to host" >&2
    echo "time spent trying to fetch : $fetch_curTime" >&2 
	else
    echo "Able to talk to startd? TRUE" 1>&1 1>&2
		echo "Successfully talked to startd $STARTD_NAME on host $HOST" >&2
		echo "Fetch Results from condor_fetchlog: $FETCH_RESULTS" >&2
	fi

	## KILL CONDOR
	KILL_RES=`$CONDOR_DIR/sbin/condor_master -k $PWD/condor_master.pid`
fi

# log dir is always different
# get the real name
log_dir='log'

echo ===   Stats of main   ===
if [ -f "${main_starter_log}" ]; then
  awk -f "${main_stage_dir}/parse_starterlog.awk" ${main_starter_log}
fi
echo === End Stats of main ===

if [ "$operation_mode" == "0" ] || [ "$operation_mode" == "1" ] || [ "$operation_mode" == "2" ]; then
    ls -l log 1>&2
    echo
    cond_print_log MasterLog log/MasterLog
    cond_print_log StartdLog log/StartdLog
    cond_print_log StarterLog ${main_starter_log}
    if [ "$use_multi_monitor" -ne 1 ]; then
      if [ "$GLIDEIN_Monitoring_Enabled" == "True" ]; then 
	    cond_print_log MasterLog.monitor monitor/log/MasterLog
	    cond_print_log StartdLog.monitor monitor/log/StartdLog
        cond_print_log StarterLog.monitor ${monitor_starter_log}
	  fi
	else
      cond_print_log StarterLog.monitor ${monitor_starter_log}
    fi
fi

## kill the master (which will kill the startd)
if [ "$use_multi_monitor" -ne 1 ]; then
    # terminate monitoring startd
    if [ "$GLIDEIN_Monitoring_Enabled" == "True" ]; then
      # use the appropriate configuration file
      tmp_condor_config=$CONDOR_CONFIG
      export CONDOR_CONFIG=$condor_config_monitor

      monitor_start_time=`date +%s`
      echo "Terminating monitoring condor at `date` (`date +%s`)" 1>&2

		#### KILL CONDOR ####
      $CONDOR_DIR/sbin/condor_master -k $PWD/monitor/condor_master.pid 
		####

      ret=$?
      if [ "$ret" -ne 0 ]; then
			echo 'Failed to terminate monitoring condor... still going ahead' 1>&2
      fi

      # clean back
      export CONDOR_CONFIG=$tmp_condor_config
    fi
fi

if [ "$ON_DIE" -eq 1 ]; then
	
	#If we are explicitly killed, do not wait required time
	echo "Explicitly killed, exiting with return code 0 instead of $condor_ret";
	exit 0;
fi

##
##########################################################

exit $condor_ret
