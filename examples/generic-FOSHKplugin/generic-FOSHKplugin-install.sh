#!/bin/bash
# installs the FOSHKplugin to connect a weather station from Fine Offset (FOSHK)
# Oliver Engel, 01.12.19, 28.12.19, 18.01.20, 22.05.20, 20.07.20, 10.10.20, 19.02.21, 08.05.21, 27.06.21
# https://foshkplugin.phantasoft.de
#
# contains foshkplugin.py and foshkplugin.service as well as generic-FOSHKplugin-install.sh (this script)
#
# Preliminary work:
# Create directory
# sudo mkdir /opt/FOSHKplugin
#
# Change to the created directory
# cd /opt/FOSHKplugin
#
# Get the current version of the plugin via wget or curl
# wget -N https://foshkplugin.phantasoft.de/files/generic-FOSHKplugin.zip
# or
# curl -O https://foshkplugin.phantasoft.de/files/generic-FOSHKplugin.zip
#
# Unzip the ZIP file
# unzip -o generic-FOSHKplugin.zip
#
# Grant execute right for generic-FOSHKplugin-install.sh (this script)
# chmod u+x generic-FOSHKplugin-install.sh
#
# Run generic-FOSHKplugin-install.sh (this script)
# sudo ./generic-FOSHKplugin-install.sh --install
#
#
# for a later update of FOSHKplugin:
# sudo ./generic-FOSHKplugin-install.sh --update
# or to directly install a certain version generic-FOSHKplugin-0.0.8Beta.zip:
# sudo ./generic-FOSHKplugin-install.sh --update generic-FOSHKplugin-0.0.8Beta.zip

PRGNAME=FOSHKplugin
PRGVER=v0.08d
MYDIR=`pwd`
REPLY=n
ISTR="+++ $PRGNAME +++"
setWSConfig="not written"
zipname=generic-FOSHKplugin.zip
SVCNAME=foshkplugin

# check current user context
if [ "${SUDO_USER}" = "" ]; then
  ISUSR=${USER}
else
  ISUSR=${SUDO_USER}
fi

aptInstall() {
  apt-get -y install --no-upgrade python3 python3-setuptools python3-pip
}

pipInstall() {
  pip3 install --upgrade requests paho-mqtt influxdb
}

adjustLogs() {
  # Adjust the rights of the log files if necessary
  echo
  echo $ISTR change owner of *.log to "${ISUSR}:${ISUSR}"
  f=(*.log)
  if [[ -f "${f[0]}" ]]; then
    chown -vf "${ISUSR}:${ISUSR}" *.log
  fi
  echo
}

listSVC() {
  # show currently installed services containing "foshk"
  echo current services containing \"foshk\":
  systemctl list-unit-files|grep foshk
  echo
}

checkWrite() {
  # check if dir is writable for current user
  ISDIR=`pwd`
  ME=`whoami`
  OWNER=`stat -c %U $ISDIR`
  echo
  if [ -w ${ISDIR} ]; then
    # writable
    echo "running in ${ISDIR} as user ${ME} - owner: ${OWNER}, USR: ${ISUSR}"
  else
    # permission denied
    echo "write permission to ${ISDIR} denied!"
    echo "you have to run this script as user ${OWNER} (given: ${ME}/${ISUSR}) or change owner"
    echo "of ${ISDIR} to ${ME} with chown -R ${ME} ${ISDIR} and try again"
    echo
    echo "nothing done"
    exit
  fi
  echo
}

clear
echo
echo Phantasoft install-Script for $PRGNAME $PRGVER
echo ------------------------------------------------
echo

if [ "$1" = "-update" ] || [ "$1" = "--update" ] || [ "$1" = "-upgrade" ] || [ "$1" = "--upgrade" ]; then
  echo $ISTR going to update $PRGNAME

  # check write permission
  checkWrite

  echo $ISTR save the current configuration
  sudo -u "${ISUSR}" cp -v foshkplugin.conf foshkplugin.save

  # if you want to upgrade to a specific FOSHKplugin-version
  #if [ "$2" != "" ]; then zipname=$2; fi
  if [ "$2" != "" ]; then 
    zipname=$2
    zipname="${zipname##*/}"
  fi

  # download new version from web
  echo $ISTR get new $PRGNAME $zipname from the web
  sudo -u "${ISUSR}" wget -N https://foshkplugin.phantasoft.de/files/$zipname 2>/dev/null || curl -O https://foshkplugin.phantasoft.de/files/$zipname

  echo $ISTR unzipping the new file
  sudo -u "${ISUSR}" unzip -o $zipname

  echo $ISTR recover saved Config
  sudo -u "${ISUSR}" cp -v foshkplugin.conf foshkplugin.new
  sudo -u "${ISUSR}" cp -v foshkplugin.save foshkplugin.conf

  echo $ISTR set executable to foshkplugin.py
  chmod 711 -v foshkplugin.py
  chmod 711 -v generic-FOSHKplugin-install.sh

  # which servicename to use?
  mySVCNAME=$SVCNAME
  read -p "$ISTR Define the name of the running service to restart: [$mySVCNAME]: " SVCNAME
  SVCNAME=${SVCNAME:-$mySVCNAME}

  # retain old configuration in case of updating a not running FOSHKplugin
  if diff -q foshkplugin.save foshkplugin.conf >/dev/null && test -f foshkplugin.conf.foshkbackup; then
    cp -p foshkplugin.conf.foshkbackup foshkplugin.conf
    echo old configuration file foshkplugin.conf.foshkbackup retained as foshkplugin.conf
  fi

  echo $ISTR restarting $PRGNAME-service $SVCNAME if running
  systemctl is-active --quiet $SVCNAME && systemctl restart $SVCNAME

  echo
  echo $ISTR upgrade-installation complete
elif [ "$1" = "-uninstall" ] || [ "$1" = "--uninstall" ]; then
  # uninstall service
  echo $ISTR uninstalling $PRGNAME as service $SVCNAME
  echo

  # which servicename to use?
  listSVC
  mySVCNAME=$SVCNAME
  read -p "$ISTR Define the name of current service to uninstall: [$mySVCNAME]: " SVCNAME
  SVCNAME=${SVCNAME:-$mySVCNAME}

  echo $ISTR disable system-service foshkplugin
  systemctl stop $SVCNAME
  systemctl disable $SVCNAME
  systemctl daemon-reload

  echo $ISTR remove system-service foshkplugin from auto-start
  rm -f /etc/systemd/system/$SVCNAME.service

  echo
  echo $ISTR system-service $SVCNAME should be uninstalled
  echo $ISTR all files are still in $MYDIR
  echo
elif [ "$1" = "-install" ] || [ "$1" = "--install" ]; then
  echo $ISTR install and configure $PRGNAME

  # check write permission
  checkWrite

  # install required packages
  read -t 1 -n 10000 discard
  echo
  echo $ISTR we will now install Python3 via apt
  aptInstall

  # install required Python packages
  echo
  echo $ISTR now we have to install the python-libs
  pipInstall

  # Adjust file rights
  echo
  echo $ISTR set executable to foshkplugin.py
  chmod 711 -v foshkplugin.py
  # Adjust path names for log in the config
  if test -f foshkplugin.conf; then
    /bin/sed -i "s#REPLACEFOSHKPLUGINLOGDIR#$MYDIR#" foshkplugin.conf
  fi

  # Adjust the rights of the log files if necessary
  adjustLogs

  # gather weather station for details
  ./foshkplugin.py -autoConfig

  # Configuration
  until [[ $REPLY =~ ^[YyJj]$ ]]; do
    echo
    # query Target-IP
    myLOX_IP=""
    read -p "$ISTR ip address of target system to send UDP-messages to (leave blank if no UDP needed) [$myLOX_IP]: " LOX_IP
    LOX_IP=${LOX_IP:-$myLOX_IP}
    # query Target-Port
    myLOX_PORT=""
    read -p "$ISTR udp port on target system  (leave blank if no UDP needed) [$myLOX_PORT]: " LOX_PORT
    LOX_PORT=${LOX_PORT:-$myLOX_PORT}
    # query local IP-Adress
    myLB_IP=`hostname -I | cut -d' ' -f1`
    read -p "$ISTR ip address of local system [$myLB_IP]: " LB_IP
    LB_IP=${LB_IP:-$myLB_IP}
    # query the local HTTP port; default: 8080
    myLBH_PORT=8080
    while [ "`./foshkplugin.py -checkLBHPort $myLBH_PORT`" != "ok" ]; do
      echo The port is $myLBH_PORT
      let myLBH_PORT=$myLBH_PORT+1
    done
    read -p "$ISTR http port on local system [$myLBH_PORT]: " LBH_PORT
    LBH_PORT=${LBH_PORT:-$myLBH_PORT}
    # inform about all found weather stations
    ./foshkplugin.py -scanWS
    # query the IP address of the weather station
    myWS_IP=`./foshkplugin.py -getWSIP`
    read -p "$ISTR ip address of weather station [$myWS_IP]: " WS_IP
    WS_IP=${WS_IP:-$myWS_IP}
    # query the command port of the weather station
    myWS_PORT=`./foshkplugin.py -getWSPORT`
    read -p "$ISTR command port of weather station [$myWS_PORT]: " WS_PORT
    WS_PORT=${WS_PORT:-$myWS_PORT}
    # query the interval of the weather station
    myWS_INTERVAL=`./foshkplugin.py -getWSINTERVAL`
    read -p "$ISTR message-interval of weather station [$myWS_INTERVAL]: " WS_INTERVAL
    WS_INTERVAL=${WS_INTERVAL:-$myWS_INTERVAL}
    echo
    read -p "$ISTR are these settings ok? (Y/N) " -n 1 -r
  done

  # Create / update config file
  read -t 1 -n 10000 discard
  echo
  read -p "$ISTR do you want to write settings into the config-file? (Y/N) " -n 1 -r
  if [[ $REPLY =~ ^[YyJj]$ ]]; then
    echo
    echo $ISTR configuring $PRGNAME
    if [ "${LOX_IP}" = "" ]; then LOX_IP="none"; fi
    if [ "${LOX_PORT}" = "" ]; then LOX_PORT="none"; fi
    createConfig=`./foshkplugin.py -createConfig $WS_IP $WS_PORT $LB_IP $LBH_PORT $WS_INTERVAL $LOX_IP $LOX_PORT`
  fi
  echo

  # Write settings in the weather station
  read -t 1 -n 10000 discard
  echo
  read -p "$ISTR do you want to write settings into the weather station? (Y/N) " -n 1 -r
  if [[ $REPLY =~ ^[YyJj]$ ]]; then
    echo
    echo $ISTR configuring weather station
    setWSConfig=`./foshkplugin.py -setWSconfig $WS_IP $WS_PORT $LB_IP $LBH_PORT $WS_INTERVAL`
  fi
  echo

  # Set up and start the service
  read -t 1 -n 10000 discard
  echo
  read -p "$ISTR do you want to enable and start the service? (Y/N) " -n 1 -r
  if [[ $REPLY =~ ^[YyJj]$ ]]; then
    echo
    # which servicename to use?
    listSVC
    mySVCNAME=$SVCNAME
    read -p "$ISTR Define a name of the service: [$mySVCNAME]: " SVCNAME
    SVCNAME=${SVCNAME:-$mySVCNAME}

    echo $ISTR installing system-service via systemd
    cp -f foshkplugin.service $SVCNAME.service.tmp
    /bin/sed -i "s#REPLACEFOSHKPLUGINDATADIR#$MYDIR#" $SVCNAME.service.tmp
    # replace SyslogIdentifier in service.tmp
    /bin/sed -i "s#SyslogIdentifier=foshkplugin#SyslogIdentifier=$SVCNAME#" $SVCNAME.service.tmp
    cp -f $SVCNAME.service.tmp /etc/systemd/system/$SVCNAME.service
    chown -v "${ISUSR}:${ISUSR}" $SVCNAME.service.tmp
    systemctl import-environment
    systemctl daemon-reload && systemctl enable $SVCNAME && systemctl start $SVCNAME --no-block
  fi

  # Adjust the rights of the log files if necessary
  adjustLogs

  # ready
  # now add the missing settings with an editor if necessary
  echo
  echo
  echo $ISTR everything should be ok now, $PRGNAME should be up and ready
  ps ax|grep foshkplugin|grep -v grep
  echo
  echo $ISTR current configuration is:
  cat foshkplugin.conf
  echo
  echo createConfig: $createConfig
  echo setWSConfig: $setWSConfig
elif [ "$1" = "-repair" ] || [ "$1" = "--repair" ]; then
  echo $ISTR repair installation of $PRGNAME
  # install required packages
  aptInstall
  # install required Python packages
  pipInstall
  # Rechte der Log-Dateien ggf. anpassen
  adjustLogs
  # restart the service
  systemctl restart $SVCNAME
  echo
  echo $ISTR repairing installation complete
elif [ "$1" = "-enable" ] || [ "$1" = "--enable" ]; then
  echo
  # which servicename to use?
  listSVC
  mySVCNAME=$SVCNAME
  read -p "$ISTR Define the name of service to enable: [$mySVCNAME]: " SVCNAME
  SVCNAME=${SVCNAME:-$mySVCNAME}
  echo $ISTR installing $PRGNAME as a system-service $SVCNAME via systemd
  cp -f foshkplugin.service $SVCNAME.service.tmp
  /bin/sed -i "s#REPLACEFOSHKPLUGINDATADIR#$MYDIR#" $SVCNAME.service.tmp
  # replace SyslogIdentifier in service.tmp
  /bin/sed -i "s#SyslogIdentifier=foshkplugin#SyslogIdentifier=$SVCNAME#" $SVCNAME.service.tmp
  cp -f $SVCNAME.service.tmp /etc/systemd/system/$SVCNAME.service
  chown -v "${ISUSR}:${ISUSR}" $SVCNAME.service.tmp
  systemctl import-environment
  systemctl daemon-reload && systemctl enable $SVCNAME && systemctl start $SVCNAME --no-block
else
  echo you have to use parameter -install, -uninstall, -upgrade, -repair or -enable
  echo as a 2. parameter you may specify a specific ZIP-file for upgrading
  echo
  echo nothing done
fi
echo

