/*
 * Project:
 *   glideinWMS
 * 
 * File Version: 
 *   $Id: frontend_support.js,v 1.2.8.3 2011/07/05 19:25:55 sfiligoi Exp $
 *
 * Support javascript module for the frontend monitoring
 * Part of the gldieinWMS package
 *
 * Original repository: http://www.uscms.org/SoftwareComputing/Grid/WMS/glideinWMS/
 *
 */


// Load FrontendStats XML file and return the object
function loadFrontendStats() {
  var request =  new XMLHttpRequest();
  request.open("GET", "frontend_status.xml",false);
  request.send(null);
  
  var frontendStats=request.responseXML.firstChild;
  return frontendStats;
}

// Extract group names from a frontendStats XML object
function getFrontendGroups(frontendStats) {
  groups=new Array();
  for (var elc=0; elc<frontendStats.childNodes.length; elc++) {
    var el=frontendStats.childNodes[elc];
    if ((el.nodeType==1) && (el.nodeName=="groups")) {
      for (var etc=0; etc<el.childNodes.length; etc++) {
	var group=el.childNodes[etc];
	if ((group.nodeType==1)&&(group.nodeName=="group")) {
	  var group_name=group.attributes.getNamedItem("name");
	  groups.push(group_name.value);
	}
      }
    }
  }
  return groups;
}

//Extract factory names from frontendStats XML obj
function getFrontendGroupFactories(frontendStats, group_name) {
  factories=new Array();

  if(group_name=="total") {
    for (var i=0; i<frontendStats.childNodes.length; i++) {
      var el=frontendStats.childNodes[i];
      if ((el.nodeType==1) && (el.nodeName=="factories")) {
        for (var j=0; j<el.childNodes.length; j++) {
  	  var group=el.childNodes[j];
            if ((group.nodeType==1)&&(group.nodeName=="factory")) {
              var group_name=group.attributes.getNamedItem("name");
	      factories.push(group_name.value);
	    }
          }
       }
    } 
    return factories;
  }

  for (var i=0; i<frontendStats.childNodes.length; i++) {
    var el=frontendStats.childNodes[i];
    if ((el.nodeType==1) && (el.nodeName=="groups")) {
      for (var j=0; j<el.childNodes.length; j++) {
	var group=el.childNodes[j];
	if ((group.nodeType==1)&&(group.nodeName=="group")) {
	  var group_name1=group.attributes.getNamedItem("name").value;
          if(group_name1==group_name) {
             for(var k=0; k<group.childNodes.length; k++) { 
               var el2 = group.childNodes[k];
               if (el2.nodeName=="factories") {
                  for(var m=0; m<el2.childNodes.length; m++) { 
                     var factory = el2.childNodes[m];
                     if(factory.nodeName=="factory") {
                        factory_name=factory.attributes.getNamedItem("name");
	                factories.push(factory_name.value);
                     }
                  }
               }               
             }
          }
	}
      }
    }
  }
  return factories;
}

function sanitize(name) {
 var out="";
 for (var i=0; i<name.length; i++) {
  var c=name.charAt(i);
  if (c.search('[A-z0-9\-.]')==-1) {
    out=out.concat('_');
  } else {
    out=out.concat(c);
  }
 }
 return out; 
}
