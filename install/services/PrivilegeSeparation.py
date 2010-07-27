#!/bin/env python

import traceback
import sys,os,os.path,string,time
import pwd,grp
import stat
import optparse

import common
os.environ["PYTHONPATH"] = "."
#-------------------------

class PrivilegeSeparation:

  def __init__(self,condor_location,factory_obj,frontend_objs,frontend_users_dict):

    self.condor_location = condor_location
    self.factory        = factory_obj
    self.frontends      = frontend_objs
    #-- dictionary of frontends and local unix account --
    self.frontend_users_dict = frontend_users_dict 

    # -- config file is hard-coded in Condor.  It cannot be changed --
    self.config_file = "/etc/condor/privsep_config"

    # -- condor switchboard that must have setuid ----
    self.switchboard_bin = os.path.join(self.condor_location,'sbin/condor_root_switchboard')
    # -- users and groups ----
    self.factory_user    = self.factory.unix_acct()
    self.factory_groups  = None
    self.frontend_groups = {}
    self.frontend_users  = []

    self.validate_before_condor_install()

  #--------------------------------
  def validate_before_condor_install(self):
    common.logit(".. privilege separation validation prior to condor install")
    if os.getuid() != 0:
      common.logerr("You must install as root user to use privilege separation.")
    self.validate_frontends()       
    self.validate_users()       
    if self.validate_client_files() == False:
      common.logerr("Privilege separation requires root-only write permissions (drwxr-xr-x) for full path to client files: %s" % os.path.dirname(self.factory.client_files()))
    common.logit(".. privilege separation validation prior to condor install complete")

  #--------------------------------
  def validate_client_files(self):
    dir = os.path.dirname(self.factory.client_files())
    if not os.path.exists(dir):
      return False
    while dir <> "/":
      if not os.path.isdir(dir):
        return False
      if os.stat(dir)[4] <> 0:
        return False
      if os.stat(dir)[5] <> 0:
        return False
      if not common.has_permissions(dir,"USR",["R","W","X",]):
        return False
      if not common.has_permissions(dir,"GRP",["R","X",]) or common.has_permissions(dir,"GRP",["W",]):
        return False
      if not common.has_permissions(dir,"OTH",["R","X",]) or common.has_permissions(dir,"OTH",["W",]):
        return False
      dir = os.path.dirname(dir)
    return True


  #--------------------------------
  def config_data(self):
    data = """
valid-caller-uids = %s 
valid-caller-gids = %s 
valid-target-uids = %s 
valid-target-gids = %s 
valid-dirs = %s 
valid-dirs = %s 
procd-executable = %s
""" % (self.factory_user,
       self.factory_groups,
       string.join(self.frontend_users," : "),
       string.join(self.frontend_groups.keys()," : "),
       self.factory.client_logs(),
       self.factory.client_proxies(),
       os.path.join(self.condor_location,'sbin/condor_procd'))
    return data

  #--------------------------------
  def condor_config_data(self):
    data = """
#########################################################
## Make the factory user a condor superuser.
## This is needed by the factory damemons in privsep mode
## and it also makes the administration easier.
#########################################################
QUEUE_SUPER_USERS = $(QUEUE_SUPER_USERS), %s
""" % self.factory_user
    return data

  #--------------------------------
  def validate_frontends(self):
    #--- frontend check to insure they are in ini file(s) ---
    frontend_inis = []
    service_names = self.frontend_users_dict.keys()
    for obj in self.frontends:
      frontend_inis.append(obj.service_name())
    service_names.sort() 
    frontend_inis.sort()
    if service_names <> frontend_inis:
      msg = """The service_names of VOFrontends in your ini file do not match 
those in your frontend_users attribute of the WMSCollector ini file:  
  frontend_users = %s 
  frontend inis  = %s""" % (self.frontend_users_dict,frontend_inis)
      common.logerr(msg)

  #--------------------------------
  def validate_users(self):
    #--- factory ---
    user_valid = True
    try:
      self.factory_groups = self.get_groups(self.factory_user)
    except Exception,e:
      user_valid = False
      common.logit("ERROR: Factory user (%s) account not created" % self.factory_user)
    #--- frontends user check ---
    for service_name in self.frontend_users_dict.keys():
      user = self.frontend_users_dict[service_name]
      self.frontend_users.append(user)
      try:
        group = self.get_groups(user)
      except:
        user_valid = False
        common.logit("ERROR: for frontend(%s), user (%s) account not created" % (service_name,user))
        continue
      if not self.frontend_groups.has_key(group):
        self.frontend_groups[group] = []
      # multiple users may share  the same group, so group them together
      self.frontend_groups[group].append(user)
    if user_valid == False:
      common.logerr("One or more errors have occurred. Please correct them.")

  #--------------------------------
  def get_groups(self,user):
    try:
      groups = grp.getgrgid(pwd.getpwnam(user)[3])[0]
    except Exception,e:
      raise
    return groups

  #--------------------------------
  def update(self):
    common.logit("\n--- Privilege Separation is in effect ---\nThe following directories/files are being created to support this.")
    #-- some validation on the condor install ---
    if not os.path.isdir(self.condor_location):
      common.logerr("The CONDOR_LOCATION specified does not exist: %s" % self.condor_location)
    #--- check for Condor switchboard ---
    if not os.path.isfile(self.switchboard_bin):
      common.logerr("Privilege separation binary (%s) does not exist. Do you have the right version of Condor?" % self.switchboard_bin)
    if os.stat(self.switchboard_bin)[stat.ST_UID] != 0:
      common.logerr("Privilege separation binary (%s) must be owned by root!" % self.switchboard_bin)
    #-- create the config file ---
    if not os.path.isdir(os.path.dirname(self.config_file)):
      os.mkdir(os.path.dirname(self.config_file))
    common.write_file("w",0644,self.config_file,self.config_data())
    #-- setuid on swtichboard ---
    os.chmod(self.switchboard_bin,04755)
    #-- create factory directories ---
    #-- factory dirs done in Factory install --
    # self.factory.create_factory_dirs(self.factory.unix_acct(),0755)
    self.factory.create_factory_client_dirs('root',0755)
    common.logit("--- End of updates for Privilege Separation.--- ")

  #--------------------------------
  def remove(self):
    if not os.path.isfile(self.config_file()):
      return 
    if os.getuid() != 0:
      common.logit("\nA privilege separation config file exists but you are not root user\n so we cannot remove it at this time.")
      yn = common.ask_yn("Do you want to proceed")
      if yn == "n":
        common.logerr("Terminating at your request")

#--- end of class ---

##########################################
def main(argv):
  try:
    import WMSCollector
    import Factory
    import VOFrontend
    wms      = WMSCollector.WMSCollector("../weigand.ini")
    factory  = Factory.Factory("../weigand.ini")
    frontend = VOFrontend.VOFrontend("../weigand.ini")
#    privsep = PrivilegeSeparation(wms.condor_location(),factory,[frontend,],{"zzz":"xxxx",})
#    privsep = PrivilegeSeparation(wms.condor_location(),factory,[frontend,],{"vo_cms":"vo_cms"})
    #privsep = PrivilegeSeparation(wms.condor_location(),factory,[frontend,],{"vo_cms":"o_cms"})
    privsep = PrivilegeSeparation(wms.condor_location(),factory,[frontend,],{"vo_cms":"vo_cms"})
    privsep.validate_frontends()

    #privsep = PrivilegeSeparation("/home/weigand/condor-wms",factory,[frontend,]) 
    #privsep.update()
    #privsep.validate_after_condor_install()
  except KeyboardInterrupt, e:
    common.logit("\n... looks like you aborted this script... bye.")
    return 1
  except EOFError:
    common.logit("\n... looks like you aborted this script... bye.");
    return 1
  except common.WMSerror:
    print;return 1
  return 0


#--------------------------
if __name__ == '__main__':
  sys.exit(main(sys.argv))
