#
# Description:
#   This module implements the basic functions needed
#   to interface to rrdtool
#
# Author:
#   Igor Sfiligoi
#

import string,time

class BaseRRDSupport:
    #############################################################
    def __init__(self,rrd_obj):
        self.rrd_obj=rrd_obj

    def isDummy(self):
        return (self.rrd_obj==None)

    #############################################################
    # The default will do nothing
    # Children should overwrite it, if needed
    def get_disk_lock(self,fname):
        return dummy_disk_lock()

    #############################################################
    # The default will do nothing
    # Children should overwrite it, if needed
    def get_graph_lock(self,fname):
        return dummy_disk_lock()

    #############################################################
    def create_rrd(self,
                   rrdfname,
                   rrd_step,rrd_archives,
                   rrd_ds):
        """
        Create a new RRD archive

        Arguments:
          rrdfname     - File path name of the RRD archive
          rrd_step     - base interval in seconds
          rrd_archives - list of tuples, each containing the following fileds (in order)
            CF    - consolidation function (usually AVERAGE)
            xff   - xfiles factor (fraction that can be unknown)
            steps - how many of these primary data points are used to build a consolidated data point
            rows  - how many generations of data values are kept
          rrd_ds       - a tuple containing the following fields (in order)
            ds-name   - attribute name
            DST       - Data Source Type (usually GAUGE)
            heartbeat - the maximum number of seconds that may pass between two updates before it becomes unknown
            min       - min value
            max       - max value
          
        For more details see
          http://oss.oetiker.ch/rrdtool/doc/rrdcreate.en.html
        """
        self.create_rrd_multi(rrdfname,
                              rrd_step,rrd_archives,
                              (rrd_ds,))
        return

    #############################################################
    def create_rrd_multi(self,
                         rrdfname,
                         rrd_step,rrd_archives,
                         rrd_ds_arr):
        """
        Create a new RRD archive

        Arguments:
          rrdfname     - File path name of the RRD archive
          rrd_step     - base interval in seconds
          rrd_archives - list of tuples, each containing the following fileds (in order)
            CF    - consolidation function (usually AVERAGE)
            xff   - xfiles factor (fraction that can be unknown)
            steps - how many of these primary data points are used to build a consolidated data point
            rows  - how many generations of data values are kept
          rrd_ds_arr   - list of tuples, each containing the following fields (in order)
            ds-name   - attribute name
            DST       - Data Source Type (usually GAUGE)
            heartbeat - the maximum number of seconds that may pass between two updates before it becomes unknown
            min       - min value
            max       - max value
          
        For more details see
          http://oss.oetiker.ch/rrdtool/doc/rrdcreate.en.html
        """
        if None==self.rrd_obj:
            return # nothing to do in this case

        start_time=(long(time.time()-1)/rrd_step)*rrd_step # make the start time to be aligned on the rrd_step boundary - needed for optimal resoultion selection 
        #print (rrdfname,start_time,rrd_step)+rrd_ds
        args=[str(rrdfname),'-b','%li'%start_time,'-s','%i'%rrd_step]
        for rrd_ds in rrd_ds_arr:
            args.append('DS:%s:%s:%i:%s:%s'%rrd_ds)
        for archive in rrd_archives:
            args.append("RRA:%s:%g:%i:%i"%archive)

        lck=self.get_disk_lock(rrdfname)
        try:
            self.rrd_obj.create(*args)
        finally:
            lck.close()
        return

    #############################################################
    def update_rrd(self,
                   rrdfname,
                   time,val):
        """
        Create an RRD archive with a new value

        Arguments:
          rrdfname - File path name of the RRD archive
          time     - When was the value taken
          val      - What vas the value
        """
        if None==self.rrd_obj:
            return # nothing to do in this case

        lck=self.get_disk_lock(rrdfname)
        try:
            self.rrd_obj.update(str(rrdfname),'%li:%i'%(time,val))
        finally:
            lck.close()

        return

    #############################################################
    def update_rrd_multi(self,
                         rrdfname,
                         time,val_dict):
        """
        Create an RRD archive with a set of values (possibly all of the supported)

        Arguments:
          rrdfname - File path name of the RRD archive
          time     - When was the value taken
          val_dict - What was the value
        """
        if None==self.rrd_obj:
            return # nothing to do in this case

        args=[str(rrdfname)]
        ds_names=val_dict.keys()
        ds_names.sort()

        ds_names_real=[]
        ds_vals=[]
        for ds_name in ds_names:
            if val_dict[ds_name]!=None:
                ds_vals.append("%i"%val_dict[ds_name])
                ds_names_real.append(ds_name)

        if len(ds_names_real)==0:
            return

        args.append('-t')
        args.append(string.join(ds_names_real,':'))
        args.append(('%li:'%time)+string.join(ds_vals,':'))
    
        lck=self.get_disk_lock(rrdfname)
        try:
            #print args
            self.rrd_obj.update(*args)
        finally:
            lck.close()
            
        return

    #############################################################
    def rrd2graph(self,fname,
                  rrd_step,ds_name,ds_type,
                  start,end,
                  width,height,
                  title,rrd_files,cdef_arr=None,trend=None,
                  img_format='PNG'):
        """
        Create a graph file out of a set of RRD files

        Arguments:
          fname         - File path name of the graph file
          rrd_step      - Which step should I use in the RRD files
          ds_name       - Which attribute should I use in the RRD files
          ds_type       - Which type should I use in the RRD files
          start,end     - Time points in utime format
          width,height  - Size of the graph
          title         - Title to put in the graph
          rrd_files     - list of RRD files, each being a tuple of (in order)
                rrd_id      - logical name of the RRD file (will be the graph label)
                rrd_fname   - name of the RRD file
                graph_type  - Graph type (LINE, STACK, AREA)
                grpah_color - Graph color in rrdtool format
          cdef_arr      - list of derived RRD values
                          if present, only the cdefs will be plotted
                          each elsement is a tuple of (in order)
                rrd_id        - logical name of the RRD file (will be the graph label)
                cdef_formula  - Derived formula in rrdtool format
                graph_type    - Graph type (LINE, STACK, AREA)
                grpah_color   - Graph color in rrdtool format
          trend         - Trend value in seconds (if desired, None else)
          
        For more details see
          http://oss.oetiker.ch/rrdtool/doc/rrdcreate.en.html
        """
        if None==self.rrd_obj:
            return # nothing to do in this case

        multi_rrd_files=[]
        for rrd_file in rrd_files:
            multi_rrd_files.append((rrd_file[0],rrd_file[1],ds_name,ds_type,rrd_file[2],rrd_file[3]))
        return self.rrd2graph_multi(fname,rrd_step,start,end,width,height,title,multi_rrd_files,cdef_arr,trend,img_format)

    #############################################################
    def rrd2graph_now(self,fname,
                      rrd_step,ds_name,ds_type,
                      period,width,height,
                      title,rrd_files,cdef_arr=None,trend=None,
                      img_format='PNG'):
        """
        Create a graph file out of a set of RRD files

        Arguments:
          fname         - File path name of the graph file
          rrd_step      - Which step should I use in the RRD files
          ds_name       - Which attribute should I use in the RRD files
          ds_type       - Which type should I use in the RRD files
          period        - start=now-period, end=now
          width,height  - Size of the graph
          title         - Title to put in the graph
          rrd_files     - list of RRD files, each being a tuple of (in order)
                rrd_id      - logical name of the RRD file (will be the graph label)
                rrd_fname   - name of the RRD file
                graph_type  - Graph type (LINE, STACK, AREA)
                grpah_color - Graph color in rrdtool format
          cdef_arr      - list of derived RRD values
                          if present, only the cdefs will be plotted
                          each elsement is a tuple of (in order)
                rrd_id        - logical name of the RRD file (will be the graph label)
                cdef_formula  - Derived formula in rrdtool format
                graph_type    - Graph type (LINE, STACK, AREA)
                grpah_color   - Graph color in rrdtool format
          trend         - Trend value in seconds (if desired, None else)
          
        For more details see
          http://oss.oetiker.ch/rrdtool/doc/rrdcreate.en.html
        """
        now=long(time.time())
        start=((now-period)/rrd_step)*rrd_step
        end=((now-1)/rrd_step)*rrd_step
        return self.rrd2graph(fname,rrd_step,ds_name,ds_type,start,end,width,height,title,rrd_files,cdef_arr,trend,img_format)

    #############################################################
    def rrd2graph_multi(self,fname,
                        rrd_step,
                        start,end,
                        width,height,
                        title,rrd_files,cdef_arr=None,trend=None,
                        img_format='PNG'):
        """
        Create a graph file out of a set of RRD files

        Arguments:
          fname         - File path name of the graph file
          rrd_step      - Which step should I use in the RRD files
          start,end     - Time points in utime format
          width,height  - Size of the graph
          title         - Title to put in the graph
          rrd_files     - list of RRD files, each being a tuple of (in order)
                rrd_id      - logical name of the RRD file (will be the graph label)
                rrd_fname   - name of the RRD file
                ds_name     - Which attribute should I use in the RRD files
                ds_type     - Which type should I use in the RRD files
                graph_type  - Graph type (LINE, STACK, AREA)
                graph_color - Graph color in rrdtool format
          cdef_arr      - list of derived RRD values
                          if present, only the cdefs will be plotted
                          each elsement is a tuple of (in order)
                rrd_id        - logical name of the RRD file (will be the graph label)
                cdef_formula  - Derived formula in rrdtool format
                graph_type    - Graph type (LINE, STACK, AREA)
                grpah_color   - Graph color in rrdtool format
          trend         - Trend value in seconds (if desired, None else)
          img_format    - format of the graph file (default PNG)
          
        For more details see
          http://oss.oetiker.ch/rrdtool/doc/rrdcreate.en.html
        """
        if None==self.rrd_obj:
            return # nothing to do in this case

        args=[str(fname),'-s','%li'%start,'-e','%li'%end,'--step','%i'%rrd_step,'-l','0','-w','%i'%width,'-h','%i'%height,'--imgformat',str(img_format),'--title',str(title)]
        for rrd_file in rrd_files:
            ds_id=rrd_file[0]
            ds_fname=rrd_file[1]
            ds_name=rrd_file[2]
            ds_type=rrd_file[3]
            if trend==None:
                args.append(str("DEF:%s=%s:%s:%s"%(ds_id,ds_fname,ds_name,ds_type)))
            else:
                args.append(str("DEF:%s_inst=%s:%s:%s"%(ds_id,ds_fname,ds_name,ds_type)))
                args.append(str("CDEF:%s=%s_inst,%i,TREND"%(ds_id,ds_id,trend)))

        plot_arr=rrd_files
        if cdef_arr!=None:
            plot_arr=cdef_arr # plot the cdefs not the files themselves, when we have them
            for cdef_el in cdef_arr:
                ds_id=cdef_el[0]
                cdef_formula=cdef_el[1]
                ds_graph_type=rrd_file[2]
                ds_color=rrd_file[3]
                args.append(str("CDEF:%s=%s"%(ds_id,cdef_formula)))
        else:
            plot_arr=[]
            for rrd_file in rrd_files:
                plot_arr.append((rrd_file[0],None,rrd_file[4],rrd_file[5]))


        if plot_arr[0][2]=="STACK":
            # add an invisible baseline to stack upon
            args.append("AREA:0")

        for plot_el in plot_arr:
            ds_id=plot_el[0]
            ds_graph_type=plot_el[2]
            ds_color=plot_el[3]
            args.append("%s:%s#%s:%s"%(ds_graph_type,ds_id,ds_color,ds_id))
            

        args.append("COMMENT:Created on %s"%time.strftime("%b %d %H\:%M\:%S %Z %Y"))

    
        try:
            lck=self.get_graph_lock(fname)
            try:
                self.rrd_obj.graph(*args)
            finally:
                lck.close()
        except:
            print "Failed graph: %s"%str(args)

        return args

    #############################################################
    def rrd2graph_multi_now(self,fname,
                            rrd_step,
                            period,width,height,
                            title,rrd_files,cdef_arr=None,trend=None,
                            img_format='PNG'):
        """
        Create a graph file out of a set of RRD files

        Arguments:
          fname         - File path name of the graph file
          rrd_step      - Which step should I use in the RRD files
          period        - start=now-period, end=now
          width,height  - Size of the graph
          title         - Title to put in the graph
          rrd_files     - list of RRD files, each being a tuple of (in order)
                rrd_id      - logical name of the RRD file (will be the graph label)
                rrd_fname   - name of the RRD file
                ds_name     - Which attribute should I use in the RRD files
                ds_type     - Which type should I use in the RRD files
                graph_type  - Graph type (LINE, STACK, AREA)
                graph_color - Graph color in rrdtool format
          cdef_arr      - list of derived RRD values
                          if present, only the cdefs will be plotted
                          each elsement is a tuple of (in order)
                rrd_id        - logical name of the RRD file (will be the graph label)
                cdef_formula  - Derived formula in rrdtool format
                graph_type    - Graph type (LINE, STACK, AREA)
                grpah_color   - Graph color in rrdtool format
          trend         - Trend value in seconds (if desired, None else)
          img_format    - format of the graph file (default PNG)
          
        For more details see
          http://oss.oetiker.ch/rrdtool/doc/rrdcreate.en.html
        """
        now=long(time.time())
        start=((now-period)/rrd_step)*rrd_step
        end=((now-1)/rrd_step)*rrd_step
        return self.rrd2graph_multi(fname,rrd_step,start,end,width,height,title,rrd_files,cdef_arr,trend,img_format)

# This class uses the rrdtool module for rrd_obj
class ModuleRRDSupport(BaseRRDSupport):
    def __init__(self):
        import rrdtool
        BaseRRDSupport.__init__(self,rrdtool)

# This class uses rrdtool cmdline for rrd_obj
class ExeRRDSupport(BaseRRDSupport):
    def __init__(self):
        BaseRRDSupport.__init__(self,rrdtool_exe())

# This class tries to use the rrdtool module for rrd_obj
# then tries the rrdtool cmdline
# will use None if needed
class rrdSupport(BaseRRDSupport):
    def __init__(self):
        try:
            import rrdtool
            rrd_obj=rrdtool
        except ImportError,e:
            try:
                rrd_obj=rrdtool_exe()
            except:
                rrd_obj=None
        BaseRRDSupport.__init__(self,rrd_obj)


##################################################################
# INTERNAL, do not use directly
##################################################################


##################################
# Dummy, do nothing
# Used just to get a object
class DummyDiskLock:
    def close(self):
        return

def dummy_disk_lock():
    return DummyDiskLock()

#################################
def string_quote_join(arglist):
    l2=[]
    for e in arglist:
        l2.append('"%s"'%e)
    return string.join(l2)

#################################
# this class is used in place of the rrdtool
# python module, if that one is not available
class rrdtool_exe:
    def __init__(self):
        import popen2
        self.popen2_obj=popen2
        self.rrd_bin=self.iexe_cmd("which rrdtool")[0][:-1]

    def create(self,*args):
        cmdline='%s create %s'%(self.rrd_bin,string_quote_join(args))
        outstr=self.iexe_cmd(cmdline)
        return

    def update(self,*args):
        cmdline='%s update %s'%(self.rrd_bin,string_quote_join(args))
        outstr=self.iexe_cmd(cmdline)
        return

    def graph(self,*args):
        cmdline='%s graph %s'%(self.rrd_bin,string_quote_join(args))
        outstr=self.iexe_cmd(cmdline)
        return

    ##########################################
    def iexe_cmd(cmd):
        child=self.popen2_obj.Popen3(cmd,True)
        child.tochild.close()
        tempOut = child.fromchild.readlines()
        child.fromchild.close()
        tempErr = child.childerr.readlines()
        child.childerr.close()
        try:
            errcode=child.wait()
        except OSError, e:
            if len(tempOut)!=0:
                # if there was some output, it is probably just a problem of timing
                # have seen a lot of those when running very short processes
                errcode=0
            else:
                raise RuntimeError, "Error running '%s'\nStdout:%s\nStderr:%s\nException OSError: %s"%(cmd,tempOut,tempErr,e)
        if (errcode!=0):
            raise RuntimeError, "Error running '%s'\ncode %i:%s"%(cmd,errcode,tempErr)
        return tempOut


#
#
# Chris's hacked support for fetching
#
#
import rrdtool, time

#Defaults for rrdtool fetch
resDefault = 300
endDefault = int(time.time() / resDefault) * resDefault
startDefault = endDefault - 86400
	
def fetchData(file, pathway, res = resDefault, start = startDefault, end = endDefault):
	"""Uses rrdtool to fetch data from the clients.  Returns a dictionary of lists of data.  There is a list for each element.

	rrdtool fetch returns 3 tuples: a[0], a[1], & a[2].
	[0] lists the resolution, start and end time, which can be specified as arugments of fetchData.
	[1] returns the names of the datasets.  These names are listed in the key.
	[2] is a list of tuples. each tuple contains data from every dataset.  There is a tuple for each time data was collected."""

	#use rrdtool to fetch data
	fetched = rrdtool.fetch(pathway + file, 'AVERAGE', '-r', str(res), '-s', str(start), '-e', str(end))
        
	#sometimes rrdtool returns extra tuples that don't contain data
        actual_res = fetched[0][2]
        actual_start = fetched[0][0]
        actual_end = fetched[0][1]
        num2slice = ((actual_end - end) - (actual_start - start)) / actual_res
        if num2slice > 0:
            fetched_data_raw = fetched[2][:-num2slice]
        else:
            fetched_data_raw = fetched[2]
        #converts fetched from tuples to lists
	fetched_names = list(fetched[1])
	fetched_data = []
	for data in fetched_data_raw:
		fetched_data.append(list(data))
	
	#creates a dictionary to be filled with lists of data
	data_sets = {}
	for name in fetched_names:
		data_sets[name] = []	

	#check to make sure the data exists
	for data_set in data_sets:
		index = fetched_names.index(data_set)	
		for data in fetched_data:
			if isinstance(data[index], (int, float)):
				data_sets[data_set].append(data[index])
	
	return data_sets

