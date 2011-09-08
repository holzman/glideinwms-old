#
# Project:
#   glideinWMS
#
# File Version: 
#   $Id: create_mapfile.sh,v 1.1.8.2 2010/09/08 03:30:00 parag Exp $
#
# Description:
#   This is an include file for glidein_startup.sh
#   It has the routins to create grid and condor mapfiles
#

# add the current DN to the list of allowed DNs
# create a new file if none exist
function create_gridmapfile {
    id=`grid-proxy-info -identity`
    if [ $? -ne 0 ]; then
	id=`voms-proxy-info -identity`
	if [ $? -ne 0 ]; then
	    echo "Cannot get user identity!" 1>&2
	    echo "Tried both grid-proxy-info and voms-proxy-info." 1>&2
	    exit 1
	fi
    fi

    idp=`echo $id |awk '{split($0,a,"/CN=proxy"); print a[1]}'`
    if [ $? -ne 0 ]; then
	echo "Cannot remove proxy part from user identity!" 1>&2
	exit 1
    fi

    touch "$X509_GRIDMAP"
    if [ -e "$GLIDEIN_WORK_DIR/$EXPECTED_GRIDMAP_FNAME" ]; then
	lines=`wc -l "$GLIDEIN_WORK_DIR/$EXPECTED_GRIDMAP_FNAME" |awk '{print $1}'`
	cat "$GLIDEIN_WORK_DIR/$EXPECTED_GRIDMAP_FNAME" >> "$X509_GRIDMAP"
	echo "Using factory main grid-mapfile ($lines)" 1>&2
    fi
    if [ -e "$GLIDEIN_ENTRY_WORK_DIR/$EXPECTED_GRIDMAP_FNAME" ]; then
	lines=`wc -l "$GLIDEIN_ENTRY_WORK_DIR/$EXPECTED_GRIDMAP_FNAME" |awk '{print $1}'`
	cat "$GLIDEIN_ENTRY_WORK_DIR/$EXPECTED_GRIDMAP_FNAME" >> "$X509_GRIDMAP"
	echo "Using factory entry grid-mapfile ($lines)" 1>&2
    fi
    if [ -e "$GLIDECLIENT_WORK_DIR/$EXPECTED_GRIDMAP_FNAME" ]; then
	lines=`wc -l "$GLIDECLIENT_WORK_DIR/$EXPECTED_GRIDMAP_FNAME" |awk '{print $1}'`
	cat "$GLIDECLIENT_WORK_DIR/$EXPECTED_GRIDMAP_FNAME" >> "$X509_GRIDMAP"
	echo "Using client main grid-mapfile ($lines)" 1>&2
    fi
    if [ -e "$GLIDECLIENT_GROUP_WORK_DIR/$EXPECTED_GRIDMAP_FNAME" ]; then
	lines=`wc -l "$GLIDECLIENT_GROUP_WORK_DIR/$EXPECTED_GRIDMAP_FNAME" |awk '{print $1}'`
	cat "$GLIDECLIENT_GROUP_WORK_DIR/$EXPECTED_GRIDMAP_FNAME" >> "$X509_GRIDMAP"
	echo "Using client group grid-mapfile ($lines)" 1>&2
    fi
    echo "\"$idp\"" condor >> "$X509_GRIDMAP"
    if [ $? -ne 0 ]; then
	echo "Cannot add user identity to $X509_GRIDMAP!" 1>&2
	exit 1
    fi

    return 0
}


function extract_gridmap_DNs {
    awk -F '"' '/CN/{dn=$2;if (dns=="") {dns=dn;} else {dns=dns "," dn}}END{print dns}' $X509_GRIDMAP
}

# create a condor_mapfile starting from a grid-mapfile
function create_condormapfile {
    id=`id -un`

    # make sure there is nothing in place already
    rm -f "$X509_CONDORMAP"
    touch "$X509_CONDORMAP"
    chmod go-wx "$X509_CONDORMAP"

    # copy with formatting the glide-mapfile into condor_mapfile
    # fileter out lines starting with the comment (#)
    grep -v "^[ ]*#"  "$X509_GRIDMAP" | while read file
    do
      if [ -n "$file" ]; then # ignore empty lines
        # split between DN and UID
        # keep the quotes in DN to not loose trailing spaces
        udn=`echo "$file" |awk '{print substr($0,1,length($0)-length($NF)-1)}'`
        uid=`echo "$file" |awk '{print $NF}'`
        
        # encode for regexp
        edn_wq=`echo "$udn" | sed 's/[^[:alnum:]]/\\\&/g'`
        # remove backslashes from the first and last quote
        # and add begin and end matching chars
        edn=`echo "$edn_wq" | awk '{print "\"^" substr(substr($0,3,length($0)-2),1,length($0)-4) "$\"" }'`
        
        echo "GSI $edn $uid" >> "$X509_CONDORMAP"
      fi
    done

    # add local user
    echo "FS $id localuser" >> "$X509_CONDORMAP"

    # deny any other type of traffic 
    echo "GSI (.*) anonymous" >> "$X509_CONDORMAP"
    echo "FS (.*) anonymous" >> "$X509_CONDORMAP"

    return 0
}

############################################################
#
# Main
#
############################################################

# Assume all functions exit on error
config_file="$1"

EXPECTED_GRIDMAP_FNAME="grid-mapfile"

X509_GRIDMAP="$PWD/$EXPECTED_GRIDMAP_FNAME"
X509_CONDORMAP="$PWD/condor_mapfile"

GLIDEIN_WORK_DIR=`grep -i "^GLIDEIN_WORK_DIR " $config_file | awk '{print $2}'`
GLIDEIN_ENTRY_WORK_DIR=`grep -i "^GLIDEIN_ENTRY_WORK_DIR " $config_file | awk '{print $2}'`
GLIDECLIENT_WORK_DIR=`grep -i "^GLIDECLIENT_WORK_DIR " $config_file | awk '{print $2}'`
GLIDECLIENT_GROUP_WORK_DIR=`grep -i "^GLIDECLIENT_GROUP_WORK_DIR " $config_file | awk '{print $2}'`

X509_CERT_DIR=`grep -i "^X509_CERT_DIR " $config_file | awk '{print $2}'`
X509_USER_PROXY=`grep -i "^X509_USER_PROXY " $config_file | awk '{print $2}'`

create_gridmapfile
X509_GRIDMAP_DNS=`extract_gridmap_DNs`
create_condormapfile

cat >> "$config_file" <<EOF
######## create_mapfile ###########
X509_CONDORMAP           $X509_CONDORMAP
X509_GRIDMAP_DNS         $X509_GRIDMAP_DNS
X509_GRIDMAP_TRUSTED_DNS $X509_GRIDMAP_DNS
###############################
EOF

exit 0
