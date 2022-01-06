#!/usr/bin/env python3
# vim: set encoding=utf-8 tabstop=4 softtabstop=4 shiftwidth=4 expandtab
#########################################################################
#  Copyright 2020-      <AUTHOR>                                  <EMAIL>
#########################################################################
#  This file is part of SmartHomeNG.
#  https://www.smarthomeNG.de
#  https://knx-user-forum.de/forum/supportforen/smarthome-py
#
#  Sample plugin for new plugins to run with SmartHomeNG version 1.8 and
#  upwards.
#
#  SmartHomeNG is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.
#
#  SmartHomeNG is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with SmartHomeNG. If not, see <http://www.gnu.org/licenses/>.
#
#########################################################################

from lib.model.smartplugin import SmartPlugin
from lib.item import Items

from .webif import WebInterface

import socket
import sys
import math
import struct
import time
import json
from datetime import datetime
from os import path

class Foshk(SmartPlugin):

    PLUGIN_VERSION = '1.0.0'    # (must match the version specified in plugin.yaml), use '1.0.0' for your initial plugin Release
    
    ip = 'auto discover'
    port = 45000
    cmd_discover     = "\xff\xff\x12\x00\x04\x16"
    cmd_reboot       = "\xff\xff\x40\x03\x43"
    cmd_get_customC  = "\xff\xff\x51\x03\x54"        # ff ff 51 03 54 (last byte: CRC)
    cmd_get_customE  = "\xff\xff\x2a\x03\x2d"        # ff ff 2a 03 2d (last byte: CRC)
    cmd_set_customC  = "\xff\xff\x52"                # ff ff 52 Len [Laenge Path Ecowitt][Path Ecowitt][Laenge Path WU][Path WU][crc]
    cmd_set_customE  = "\xff\xff\x2b"                # ff ff 2b Len [Laenge ID][ID][Laenge Key][Key][Laenge IP][IP][Port][Intervall][ecowitt][enable][crc]
    cmd_get_FWver    = "\xff\xff\x50\x03\x53"        # ff ff 50 03 53 (last byte: CRC)
    ok_set_customE   = "\xff\xff\x2b\x04\x00\x2f"
    ok_set_customC   = "\xff\xff\x52\x04\x00\x56"
    ok_cmd_reboot    = "\xff\xff\x40\x04\x00\x44"
    
    cmd_discover2 = '\xff\xff\x12\x03\x15'           # Packet Format: HEADER, CMD_BROADCAST, SIZE, CHECKSUM
    
    data_dict = {}

    def __init__(self, sh):
        """
        Initalizes the plugin.

        If you need the sh object at all, use the method self.get_sh() to get it. There should be almost no need for
        a reference to the sh object any more.

        Plugins have to use the new way of getting parameter values:
        use the SmartPlugin method get_parameter_value(parameter_name). Anywhere within the Plugin you can get
        the configured (and checked) value for a parameter by calling self.get_parameter_value(parameter_name). It
        returns the value in the datatype that is defined in the metadata.
        """

        self.logger.info(f'Init of Plugin {self.get_shortname()} started')

        # Call init code of parent class (SmartPlugin)
        super().__init__()

        # get the parameters for the plugin (as defined in metadata plugin.yaml):
        self._socket_addr = self.get_parameter_value('Server_IP')
        self._socket_port = self.get_parameter_value('Port')
        self._cycle = self.get_parameter_value('Cycle')

        # Initialization code goes here
        self.data_dict_im = {}                             # dict to hold all information gotten from weatherstation gateway in imperial units
        self.data_dict_me = {}                             # dict to hold all information gotten from weatherstation gateway in metric units

        self._socket = None
        self.connection = None
        self.adress = None
        
        # Current execution start of day timestamp
        currentTimestamp = 0
        startOfDayTimestamp = 0
        observation_counter = 0

        self.alive = None
        self.is_connected = 'False'
        self.battery_warning = False
        self._altitude = 435

        # On initialization error use:
        #   self._init_complete = False
        #   return

        # if plugin should start even without web interface
        self.init_webinterface(WebInterface)
        # if plugin should not start without web interface
        # if not self.init_webinterface():
        #     self._init_complete = False

        return

    def run(self):
        """
        Run method for the plugin
        """
        self.logger.debug(f"{self.get_shortname()}: Run method called")
        # setup scheduler for device poll loop   (disable the following line, if you don't need to poll the device. Rember to comment the self_cycle statement in __init__ as well)
        self.scheduler_add('poll_device', self.perform, cycle=self._cycle)

        self.alive = True
        # if you need to create child threads, do not make them daemon = True!
        # They will not shutdown properly. (It's a python bug)
        self.getWSconfig()
        self.scanWS()
        self.perform()

    def stop(self):
        """
        Stop method for the plugin
        """
        self.logger.debug(f"{self.get_shortname()}: Stop method called")
        # self.scheduler_remove('poll_device')
        self.alive = False

        try:
            self._sh.scheduler.remove('Foshk')
        except:
            self.logger.error(f"{self.get_shortname()}: Removing plugin scheduler failed: {sys.exc_info()}")
    
    def connect(self):
    # Connect to the GW1000 device on the local network

        try:
            # Check if the current ip is valid
            socket.inet_aton(self.ip)
        except socket.error:
            # The current ip is invalid, we need to try to discover the device.
            return False
        try:
            # Create a client to connect to the local network device
            self.connection = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.connection.settimeout(10)
            self.connection.connect((self.ip, self.port))
            return True
        except socket.error:
            self.logger.debug('Error: unable to connect to the GW1000 local network device')
            self.connection.close()
            return False
    
    def discover(self):
    # Discover the GW1000 device on the local network.
        try:
            # Create a socket to send and receive the CMD_BROADCAST command.
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            sock.settimeout(2)
            sock.bind(('', 59387))
        except socket.error:
            self.logger.debug('Error: unable to listening for discover packet')
            return False
        # Try to find the device within 5 retries
        for n in range(5):
            try:
                # Sent a CMD_BROADCAST command
                sock.sendto(bytearray(self.cmd_discover2,'latin-1'), ('255.255.255.255', 46000) )
                packet = sock.recv(1024)
                # Check device name to avoid detection of other local Ecowiit/Ambient consoles
                device_name = packet[18:len(packet) - 1].decode()
                self.logger.debug(device_name)
                if device_name.startswith('GW'):
                    self.ip = '%d.%d.%d.%d' % struct.unpack('>BBBB', packet[11:15])
                    self.port = struct.unpack('>H', packet[15: 17])[0]
                    self.logger.debug(f"Weather device {device_name} discovered at {self.ip}:{self.port}")
                    return self.connect()
                else:
                    self.lastKnownError = 'Error: Unsupported local console: {}'.format(device_name)
            except socket.error:
                self.lastKnownError = 'Error: unable to find GW1000 device on local network'
        self.logger.debug(self.lastKnownError)
        return False
        
    def getWSconfig(self):
        tries = 5                                      # Anzahl der Versuche
        v = 0
        ip = None
        port = None
        wsCONFIG = "not found - try again!"
        while wsCONFIG == "not found - try again!" and v <= tries:
            # Set up UDP socket
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            s.settimeout(2)
            s.bind(('',43210))
            s.sendto(bytearray(self.cmd_discover,'latin-1'), ('255.255.255.255', 46000) )
            found = False
            try:
                while not found :
                    data, addr = s.recvfrom(11200)
                    if len(data) > 15:
                        ip = str(data[11]) + "." + str(data[12]) + "." + str(data[13]) + "." + str(data[14])
                        port = wsCONFIG = str(data[15]*256 + data[16])
                        found = True
                s.close()
            except socket.error:
                pass
            v +=1
            self.logger.debug(f"getWSconfig: {ip}:{port} mit {v} Versuchen")
        return
        
    def scanWS(self) :
        devices = []
        # Set up UDP socket
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        s.settimeout(2)  # was 2
        s.sendto(bytearray(self.cmd_discover,'latin-1'), ('255.255.255.255', 46000) )
        try:
            while True:
                data, addr = s.recvfrom(11200)
                if len(data) > 14:
                    mac = ""
                    for i in range(5,11):
                        if data[i] < 10: mac += "0"
                        mac += str(hex(data[i]))+":"
                    mac = mac.replace("0x","").upper()[:-1]
                    ip = str(data[11]) + "." + str(data[12]) + "." + str(data[13]) + "." + str(data[14])
                    port = data[15]*0x100 + data[16]
                    name = ""
                    for i in range(18,18+data[17]):
                        name += chr(data[i])
                    devices.append([mac,ip,str(port),name])
        except socket.timeout:
            pass
        s.close()
        l = len(devices)
        self.logger.debug("Amount of device found: {l}")
        if l > 0:
            for i in range(0,len(devices)):
              # 0=mac 1=ip 2=port 3=name
                self.logger.debug("ip"+str(i)+": " + devices[i][1]+" name: "+devices[i][3]+" port: "+devices[i][2]+" mac: "+devices[i][0])
                
    def sendToWS(ws_ipaddr, ws_port, cmd):           # oeffnet jeweils einen neuen Socket und verschickt cmd; Rueckmeldung = Rueckmeldung der WS
        tries = 5                                    # Anzahl der Versuche
        v = 0
        data = ""
        while data == "" and v <= tries:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            s.settimeout(udpTimeOut)
            try:
                s.connect((ws_ipaddr, int(ws_port)))
                s.sendall(cmd)
                data, addr = s.recvfrom(11200)
                s.close()
            except:
                pass
            v +=1
      return data

    def sendReboot(self, ws_ipaddr, ws_port):
        #answer = sendToWS(ws_ipaddr, ws_port, bytearray(cmd_reboot,'latin-1'))
        #ret = "done" if answer == bytearray(ok_cmd_reboot,'latin-1') else "failed"
        #return ret
        return "done" if sendToWS(ws_ipaddr, ws_port, bytearray(self.cmd_reboot, 'latin-1')) == bytearray(self.ok_cmd_reboot, 'latin-1') else "failed"
        
    def getWSINTERVAL(ws_ipaddr, ws_port) :
        edata = sendToWS(ws_ipaddr, ws_port, bytearray(cmd_get_customE,'latin-1'))
        if edata != "" and len(edata) >= 12:
            id_len = edata[4]
            key_len = edata[id_len + 5]
            ip_len = edata[key_len + id_len + 6]
            wsINTERVAL = str(edata[ip_len + key_len + id_len + 9]*256 + edata[ip_len + key_len + id_len + 10])
        else:
            wsINTERVAL = "not found - try again!"
        #print("ip: " + ws_ipaddr + " port: " + ws_port + " " + " Versuche: " + str(v))
        #print("edata: " + str(arrTohex(edata)))
        return wsINTERVAL
        
    def perform(self):
        # Try to connect, and if it fail try to auto discover the device
        if self.connect() or self.discover():
            # Successfully connected to the GW1000 device, let's retrieve live data
            live_data = self._get_live_data()
            # self.logger.debug(f"live_data: {live_data}")

            # Parser live data and add observations
            self._parse_live_data(live_data)
            self.logger.debug(f"data_dict={self.data_dict}")
    
    def _get_live_data(self):
    # Get current live conditions from the GW1000 device
        try:
            # Packet Format: HEADER, CMD_GW1000_LIVE_DATA, SIZE, CHECKSUM
            packet = '\xFF\xFF\x27\x03\x2A'
            # Send the command CMD_GW1000_LIVE_DATA to the local network device
            self.connection.sendall(bytearray(packet,'latin-1'))
            live_data = self.connection.recv(1024)
            self.currentTimestamp = current_timestamp()
            return live_data
        except socket.error:
            self.logger.debug('Error: unable to retrieve live data from the local network device')
        finally:
            self.connection.close()

    def parse_item(self, item):
        """
        Default plugin parse_item method. Is called when the plugin is initialized.
        The plugin can, corresponding to its attribute keywords, decide what to do with
        the item in future, like adding it to an internal array for future reference
        :param item:    The item to process.
        :return:        If the plugin needs to be informed of an items change you should return a call back function
                        like the function update_item down below. An example when this is needed is the knx plugin
                        where parse_item returns the update_item function when the attribute knx_send is found.
                        This means that when the items value is about to be updated, the call back function is called
                        with the item, caller, source and dest as arguments and in case of the knx plugin the value
                        can be sent to the knx with a knx write function within the knx plugin.
        """
        if self.has_iattr(item.conf, 'foo_itemtag'):
            self.logger.debug(f"parse item: {item}")

    def parse_logic(self, logic):
        """
        Default plugin parse_logic method
        """
        if 'xxx' in logic.conf:
            # self.function(logic['name'])
            pass

    def update_item(self, item, caller=None, source=None, dest=None):
        """
        Item has been updated

        This method is called, if the value of an item has been updated by SmartHomeNG.
        It should write the changed value out to the device (hardware/interface) that
        is managed by this plugin.

        :param item: item to be updated towards the plugin
        :param caller: if given it represents the callers name
        :param source: if given it represents the source
        :param dest: if given it represents the dest
        """
        if self.alive and caller != self.get_shortname():
            # code to execute if the plugin is not stopped
            # and only, if the item has not been changed by this this plugin:
            self.logger.info(f"Update item: {item.property.path}, item has been changed outside this plugin")

            if self.has_iattr(item.conf, 'foo_itemtag'):
                self.logger.debug(f"update_item was called with item {item.property.path} from caller {caller}, source {source} and dest {dest}")
            pass

    def poll_device(self):
        """
        Polls for updates of the device

        This method is only needed, if the device (hardware/interface) does not propagate
        changes on it's own, but has to be polled to get the actual status.
        It is called by the scheduler which is set within run() method.
        """
        # # get the value from the device
        # device_value = ...
        #
        # # find the item(s) to update:
        # for item in self.sh.find_items('...'):
        #
        #     # update the item by calling item(value, caller, source=None, dest=None)
        #     # - value and caller must be specified, source and dest are optional
        #     #
        #     # The simple case:
        #     item(device_value, self.get_shortname())
        #     # if the plugin is a gateway plugin which may receive updates from several external sources,
        #     # the source should be included when updating the the value:
        #     item(device_value, self.get_shortname(), source=device_source_id)
        pass
        
    # Parse Live Data packet by iterate over sensors
    def _parse_live_data(self, packet):
        data = packet[5: len(packet) - 1]
        index = 0
        size = len(data)
        while index < size:
            index = self._read_sensor(data, index)

    def _read_sensor(self, data, index):
        switcher = {
            '1':  (self._indoor_temperature, 2),        # Indoor Temperature (C), size in bytes:2
            '2':  (self._outdoor_temperature, 2),       # Outdoor Temperature (C), size in bytes:2
            '3':  (self._ignore_sensor, 2),             # Dew point (C), size in bytes:2
            '4':  (self._ignore_sensor, 2),             # Wind chill (C), size in bytes:2
            '5':  (self._ignore_sensor, 2),             # Heat index (C), size in bytes:2
            '6':  (self._indoor_humidity, 1),           # Indoor Humidity (%), size in bytes:1
            '7':  (self._outdoor_humidity, 1),          # Outdoor Humidity (%), size in bytes:1
            '8':  (self._absolute_barometric, 2),       # Absolutely Barometric (hpa), size in bytes:2
            '9':  (self._relative_barometric, 2),       # Relative Barometric (hpa), size in bytes:2
            '10': (self._ignore_sensor, 2),             # Wind Direction (360), size in bytes:2
            '11': (self._wind_speed, 2),                # Wind Speed (m/s), size in bytes:2
            '12': (self._ignore_sensor, 2),             # Gust Speed (m/s), size in bytes:2
            '13': (self._rain_day, 2),                  # Rain Event (mm), size in bytes:2
            '14': (self._rain_day, 2),                  # Rain Rate (mm/h), size in bytes:2
            '15': (self._rain_day, 2),                  # Rain hour (mm), size in bytes:2
            '16': (self._rain_day, 2),                  # Rain Day (mm), size in bytes:2
            '17': (self._rain_day, 2),                  # Rain Week (mm), size in bytes:2
            '18': (self._rain_day, 4),                  # Rain Month (mm), size in bytes:4
            '19': (self._rain_day, 4),  # Rain Year (mm), size in bytes:4
            '20': (self._rain_day, 4),  # Rain Totals (mm), size in bytes:4
            '21': (self._light, 4),  # Light  (lux), size in bytes:4
            '22': (self._ignore_sensor, 2),  # UV  (uW/m2), size in bytes:2
            '23': (self._ignore_sensor, 1),  # UVI (0-15 index), size in bytes:1
            '24': (self._ignore_sensor, 6),  # Date and time, size in bytes:6
            '25': (self._wind_speed_max, 2),  # Day max_wind (m/s), size in bytes:2
            '26': (self._outdoor_temperature, 2),  # Temperature 1 (C), size in bytes:2
            '27': (self._ignore_sensor, 2),  # Temperature 2 (C), size in bytes:2
            '28': (self._ignore_sensor, 2),  # Temperature 3 (C), size in bytes:2
            '29': (self._ignore_sensor, 2),  # Temperature 4 (C), size in bytes:2
            '30': (self._ignore_sensor, 2),  # Temperature 5 (C), size in bytes:2
            '31': (self._ignore_sensor, 2),  # Temperature 6 (C), size in bytes:2
            '32': (self._ignore_sensor, 2),  # Temperature 7 (C), size in bytes:2
            '33': (self._ignore_sensor, 2),  # Temperature 8 (C), size in bytes:2
            '34': (self._outdoor_humidity, 1),  # Humidity 1 0-100%, size in bytes:1
            '35': (self._ignore_sensor, 1),  # Humidity 2 0-100%, size in bytes:1
            '36': (self._ignore_sensor, 1),  # Humidity 3 0-100%, size in bytes:1
            '37': (self._ignore_sensor, 1),  # Humidity 4 0-100%, size in bytes:1
            '38': (self._ignore_sensor, 1),  # Humidity 5 0-100%, size in bytes:1
            '39': (self._ignore_sensor, 1),  # Humidity 6 0-100%, size in bytes:1
            '40': (self._ignore_sensor, 1),  # Humidity 7 0-100%, size in bytes:1
            '41': (self._ignore_sensor, 1),  # Humidity 8 0-100%, size in bytes:1
            '42': (self._ignore_sensor, 2),  # PM2.5 1 (ug/m3), size in bytes:2
            '43': (self._ignore_sensor, 2),  # Soil Temperature_1 (C), size in bytes:2
            '44': (self._soil_moisture, 1),  # Soil Moisture_1 (%), size in bytes:1
            b'\x2D': (self._ignore_sensor, 2),  # Soil Temperature_2 (C), size in bytes:2
            b'\x2E': (self._soil_moisture, 1),  # Soil Moisture_2 (%), size in bytes:1
            b'\x2F': (self._ignore_sensor, 2),  # Soil Temperature_3 (C), size in bytes:2
            b'\x30': (self._soil_moisture, 1),  # Soil Moisture_3 (%), size in bytes:1
            b'\x31': (self._ignore_sensor, 2),  # Soil Temperature_4 (C), size in bytes:2
            b'\x32': (self._soil_moisture, 1),  # Soil Moisture_4 (%), size in bytes:1
            b'\x33': (self._ignore_sensor, 2),  # Soil Temperature_5 (C), size in bytes:2
            b'\x34': (self._soil_moisture, 1),  # Soil Moisture_5 (%), size in bytes:1
            b'\x35': (self._ignore_sensor, 2),  # Soil Temperature_6 (C), size in bytes:2
            b'\x36': (self._soil_moisture, 1),  # Soil Moisture_6 (%), size in bytes:1
            b'\x37': (self._ignore_sensor, 2),  # Soil Temperature_7 (C), size in bytes:2
            b'\x38': (self._soil_moisture, 1),  # Soil Moisture_7 (%), size in bytes:1
            b'\x39': (self._ignore_sensor, 2),  # Soil Temperature_8 (C), size in bytes:2
            b'\x3A': (self._soil_moisture, 1),  # Soil Moisture_8 (%), size in bytes:1
            b'\x3B': (self._ignore_sensor, 2),  # Soil Temperature_9 (C), size in bytes:2
            b'\x3C': (self._soil_moisture, 1),  # Soil Moisture_9 (%), size in bytes:1
            b'\x3D': (self._ignore_sensor, 2),  # Soil Temperature_10 (C), size in bytes:2
            b'\x3E': (self._soil_moisture, 1),  # Soil Moisture_10 (%), size in bytes:1
            b'\x3F': (self._ignore_sensor, 2),  # Soil Temperature_11 (C), size in bytes:2
            b'\x40': (self._soil_moisture, 1),  # Soil Moisture_11 (%), size in bytes:1
            b'\x41': (self._ignore_sensor, 2),  # Soil Temperature_12 (C), size in bytes:2
            b'\x42': (self._soil_moisture, 1),  # Soil Moisture_12 (%), size in bytes:1
            b'\x43': (self._ignore_sensor, 2),  # Soil Temperature_13 (C), size in bytes:2
            b'\x44': (self._soil_moisture, 1),  # Soil Moisture_13 (%), size in bytes:1
            b'\x45': (self._ignore_sensor, 2),  # Soil Temperature_14 (C), size in bytes:2
            b'\x46': (self._soil_moisture, 1),  # Soil Moisture_14 (%), size in bytes:1
            b'\x47': (self._ignore_sensor, 2),  # Soil Temperature_15 (C), size in bytes:2
            b'\x48': (self._soil_moisture, 1),  # Soil Moisture_15 (%), size in bytes:1
            b'\x49': (self._ignore_sensor, 2),  # Soil Temperature_16 (C), size in bytes:2
            b'\x4A': (self._soil_moisture, 1),  # Soil Moisture_16 (%), size in bytes:1
            '76': (self._ignore_sensor, 16),  # All_sensor lowbatt, size in bytes:16
            b'\x4D': (self._ignore_sensor, 2),  # 24h_avg pm25_ch1 (ug/m3), size in bytes:2
            b'\x4E': (self._ignore_sensor, 2),  # 24h_avg pm25_ch2 (ug/m3), size in bytes:2
            b'\x4F': (self._ignore_sensor, 2),  # 24h_avg pm25_ch3 (ug/m3), size in bytes:2
            b'\x50': (self._ignore_sensor, 2),  # 24h_avg pm25_ch4 (ug/m3), size in bytes:2
            b'\x51': (self._ignore_sensor, 2),  # PM2.5 2 (ug/m3), size in bytes:2
            b'\x52': (self._ignore_sensor, 2),  # PM2.5 3 (ug/m3), size in bytes:2
            b'\x53': (self._ignore_sensor, 2),  # PM2.5 4 (ug/m3), size in bytes:2
            b'\x58': (self._ignore_sensor, 1),  # Leak ch1 , size in bytes:1
            b'\x59': (self._ignore_sensor, 1),  # Leak ch2 , size in bytes:1
            b'\x5A': (self._ignore_sensor, 1),  # Leak ch3 , size in bytes:1
            b'\x5B': (self._ignore_sensor, 1),  # Leak ch4 , size in bytes:1
            b'\x60': (self._ignore_sensor, 1),  # Lightning distance 1-40KM, size in bytes:1
            b'\x61': (self._ignore_sensor, 4),  # Lightning detected_time (UTC), size in bytes:4
            b'\x62': (self._ignore_sensor, 4),  # Lightning power_time (UTC), size in bytes: 4
            b'\x63': (self._ignore_sensor, 3),  # Battery Temperature 1 (C), size in bytes: 3
            b'\x64': (self._ignore_sensor, 3),  # Battery Temperature 2 (C), size in bytes: 3
            b'\x65': (self._ignore_sensor, 3),  # Battery Temperature 3 (C), size in bytes: 3
            b'\x66': (self._ignore_sensor, 3),  # Battery Temperature 4 (C), size in bytes: 3
            b'\x67': (self._ignore_sensor, 3),  # Battery Temperature 5 (C), size in bytes: 3
            b'\x68': (self._ignore_sensor, 3),  # Battery Temperature 6 (C), size in bytes: 3
            b'\x69': (self._ignore_sensor, 3),  # Battery Temperature 7 (C), size in bytes: 3
            b'\x6A': (self._ignore_sensor, 3)   # Battery Temperature 8 (C), size in bytes: 3
        }
        sensor_id = data[index]
        # self.logger.debug(f"sensor_id: {sensor_id}")
        sensor_reader, size = switcher.get(str(sensor_id), (self._unknown_sensor, 1))
        # self.logger.debug(f"size: {size}")
        sensor_reader(data, index, size)
        return index + 1 + size
        
    def _indoor_temperature(self, data, index, size):
        indoor_temperature = read_int(data[index + 1: index + 1 + size], False, size) / 10.0  # Sensor Unit: degC
        # self.logger.debug(f"indoor_temperature: {indoor_temperature}")
        key = f"indoor_temperature_{data[index]}"
        self.data_dict.update({key: indoor_temperature})
        
    def _outdoor_temperature(self, data, index, size):
        outdoor_temperature = read_int(data[index + 1: index + 1 + size], False, size) / 10.0  # Sensor Unit: degC
        # self.logger.debug(f"outdoor_temperature: {outdoor_temperature} of sensor_id {data[index]}")
        key = f"outdoor_temperature_{data[index]}"
        self.data_dict.update({key: outdoor_temperature})
        
    def _indoor_humidity(self, data, index, size):
        indoor_humidity = read_int(data[index + 1: index + 1 + size], False, size)  # Sensor Unit: %
        # self.logger.debug(f"indoor_humidity: {indoor_humidity}")
        key = f"indoor_humidity_{data[index]}"
        self.data_dict.update({key: indoor_humidity})

    def _outdoor_humidity(self, data, index, size):
        outdoor_humidity = read_int(data[index + 1: index + 1 + size], False, size)  # Sensor Unit: %
        # self.logger.debug(f"outdoor_humidity: {outdoor_humidity}")
        key = f"outdoor_humidity_{data[index]}"
        self.data_dict.update({key: outdoor_humidity})

    def _relative_barometric(self, data, index, size):
        relative_barometric = read_int(data[index + 1: index + 1 + size], False, size)  # Sensor Unit: dPa
        relative_barometric /= 10.0  # Conversion from dPa to hPa
        # self.logger.debug(f"relative_barometric: {relative_barometric}")
        key = f"relative_barometric_{data[index]}"
        self.data_dict.update({key: relative_barometric})
        
    def _absolute_barometric(self, data, index, size):
        absolute_barometric = read_int(data[index + 1: index + 1 + size], False, size)  # Sensor Unit: dPa
        absolute_barometric /= 10.0  # Conversion from dPa to hPa
        # self.logger.debug(f"absolute_barometric: {absolute_barometric}")
        key = f"absolute_barometric_{data[index]}"
        self.data_dict.update({key: absolute_barometric})

    def _wind_speed(self, data, index, size):
        wind_speed = read_int(data[index + 1: index + 1 + size], False, size) / 10.0  # Sensor Unit: m/s
        # self.logger.debug(f"wind_speed: {wind_speed}")
        key = f"wind_speed_{data[index]}"
        self.data_dict.update({key: wind_speed})
        
    def _wind_speed_max(self, data, index, size):
        wind_speed_max = read_int(data[index + 1: index + 1 + size], False, size) / 10.0  # Sensor Unit: m/s
        # self.logger.debug(f"wind_speed_max: {wind_speed_max}")
        key = f"wind_speed_max_{data[index]}"
        self.data_dict.update({key: wind_speed_max})

    def _rain_day(self, data, index, size):
        rain_day = read_int(data[index + 1: index + 1 + size], False, size) / 10.0  # Sensor Unit: mm
        # self.logger.debug(f"rain_day: {rain_day} of sensor_id {data[index]}")
        key = f"rain_{data[index]}"
        self.data_dict.update({key: rain_day})

    def _light(self, data, index, size):
        light = read_int(data[index + 1: index + 1 + size], False, size) / 10.0  # Sensor Unit: lux
        solar_radiation = float(light) * 0.0079  # Convert lux into w/m2, 0.0079 is the ratio at sunlight spectrum
        solar_radiation *= 0.0036  # Convert w/m2 to MJ/m2/h, 1 W/m2 = 1 J/m2/Sec
        key = f"solar_radiation_{data[index]}"
        self.data_dict.update({key: solar_radiation})
        
    def _soil_moisture(self, data, index, size):
        soil_moisture = read_int(data[index + 1: index + 1 + size], False, size)  # Sensor Unit: dPa
        # self.logger.debug(f"soil_moisture: {soil_moisture} of sensor_id {data[index]}")
        key = f"soil_moisture_{data[index]}"
        self.data_dict.update({key: soil_moisture})

    # noinspection PyMethodMayBeStatic,PyUnusedLocal
    def _ignore_sensor(self, data, index, size):
        self.logger.debug(f'Ignoring Sensor Id: {data[index]}')

    # noinspection PyMethodMayBeStatic,PyUnusedLocal
    def _unknown_sensor(self, data, index, size):
        self.logger.debug(f'Unknown Sensor Id found: {data[index]}')

    # Helper function to reset the observation data for a new day
    def _reset_observations(self):
        self.observations = dict.fromkeys(self.observations, None)
        self.observation_counter = 0
        # self.startOfDayTimestamp = rmGetStartOfDay(self.currentTimestamp)

    # Helper function to add observations
    def _report_observations(self):
        for key, value in self.observations.items():
            if value is not None:
                self.addValue(key, self.startOfDayTimestamp, value)
        self.logger.debug(self.observations)

    # Helper function to calculate an observation average
    def _observation_average(self, key, new_value):
        total_value = 0.0 if self.observations[key] is None else float(self.observations[key]) * self.observation_counter
        average = (total_value + float(new_value)) / (self.observation_counter + 1)
        self.observations[key] = average

    # Helper function to check the new maximum and minimum of a observation
    def _observation_max_min(self, max_key, min_key, value):
        # Check if the value is a new maximum
        if self.observations[max_key] is None or value > self.observations[max_key]:
            self.observations[max_key] = value
        # Check if the value is a new minimum
        if self.observations[min_key] is None or value < self.observations[min_key]:
            self.observations[min_key] = value

    # Helper function to log errors
    def _log_error(self, message, packet=None):
        if packet is not None:
            self.lastKnownError = message + ' ' + ''.join('\\x%02X' % ord(b) for b in packet)
        else:
            self.lastKnownError = message
        self.logger.error(self.lastKnownError)

    def _parse_ecowitt_data_to_dict(self, data):
        """Parse the ecowitt data and add it to a dictionnary."""
        data = data.decode().splitlines()
        for line in data:
            if ':' in line:
                if '&' in line:
                    data_list = line.split('&')
                    for item in data_list:
                        key, value = item.split('=', 1)
                        try:
                            value = float(value)
                            if value.is_integer():
                                value = int(value)
                        except:
                            if type(value) is str:
                                value = value.lstrip()
                            pass
                        self.data_dict_im[key] = value
                else:
                    key, value = line.split(':', 1)
                    try:
                        value = float(value)
                        if value.is_integer():
                            value = int(value)
                    except:
                        if type(value) is str:
                            value = value.lstrip()
                        pass
                    self.data_dict_im[key] = value

        # add additional values
        if self.data_dict_im.keys() >= {"tempf", "humidity"}:
            self.data_dict_im['dewptf'] = self._get_dew_point_f(self.data_dict_im["tempf"], self.data_dict_im["humidity"])

        if self.data_dict_im.keys() >= {"tempf", "windspeedmph"}:
            self.data_dict_im['windchillf'] = round(self._get_wind_chill_f(self.data_dict_im["tempf"], self.data_dict_im["windspeedmph"]), 1)

        if self.data_dict_im.keys() >= {"tempf", "humidity", "windspeedmph"}:
            self.data_dict_im['feelslikef'] = round(self._get_feels_like_f(self.data_dict_im["tempf"], self.data_dict_im["humidity"], self.data_dict_im["windspeedmph"]), 1)
            
        if self.data_dict_im.keys() >= {"tempf", "humidity"}:
            self.data_dict_im['heatindexf'] = round(self._get_heat_index(self.data_dict_im["tempf"], self.data_dict_im["humidity"]), 1)
            
        if self.data_dict_im.keys() >= {"solarradiation"}:
            self.data_dict_im['brightness'] = round(self.data_dict_im["solarradiation"] * 126.7, 1)
 
        if self.data_dict_im.keys() >= {"tempf", "dewptf"}:
            tempf = self.data_dict_im["tempf"]
            dewptf = self.data_dict_im["dewptf"]
            self.data_dict_im['cloudf'] = round(((tempf-dewptf) / 4.4) * 1000 + (float(self._altitude)*3.28084))

        self.logger.debug(f"{self.get_shortname()}: data_dict_im={self.data_dict_im}")

        self.data_dict_me = self._convert_dict_from_imperial_metric(self.data_dict_im)
        self.logger.debug(f"{self.get_shortname()}: data_dict_me={self.data_dict_me}")
        return self.data_dict_me

    def _add_status_to_dict(self, d):                        # add Status to dict as 0/1 or True/False (if makeBool
        # add warnings & states

        # d.update({"running": func(int(wsconnected))})
        # d.update({"wswarning": func(int(inWStimeoutWarning))})
        # d.update({"sensorwarning": func(int(inSensorWarning))})
        # if inSensorWarning and SensorIsMissed != "": d.update({"missed" : SensorIsMissed})
        d.update({"batterywarning": self.battery_warning})
        # d.update({"stormwarning": func(int(inStormWarning))})
        # d.update({"tswarning": func(int(inTSWarning))})
        # d.update({"updatewarning": func(int(updateWarning))})
        # d.update({"leakwarning": func(int(inLeakageWarning))})
        # d.update({"co2warning": func(int(inCO2Warning))})
        # d.update({"time": strToNum(loxTime(time.time()))})
        return d

    def _convert_dict_from_imperial_metric(self, data_dict_im, ignore_empty=True):
        ignorelist = ["-9999", "None", "null"]
        data_dict_metric = {}
        data_dict_metric.update(data_dict_im)
        for key, value in data_dict_im.items():
            if key == "tempf" and not (ignore_empty and value in ignorelist):
                data_dict_metric["temp_c"] = self._f_to_c(data_dict_metric.pop(key), 1)
            elif "temp1f" in key and not (ignore_empty and value in ignorelist):
                data_dict_metric["temp1_c"] = self._f_to_c(data_dict_metric.pop(key), 1)
            elif "temp2f" in key and not (ignore_empty and value in ignorelist):
                data_dict_metric["temp2_c"] = self._f_to_c(data_dict_metric.pop(key), 1)
            elif "temp3f" in key and not (ignore_empty and value in ignorelist):
                data_dict_metric["temp3_c"] = self._f_to_c(data_dict_metric.pop(key), 1)
            elif "temp4f" in key and not (ignore_empty and value in ignorelist):
                data_dict_metric["temp4_c"] = self._f_to_c(data_dict_metric.pop(key), 1)
            elif "temp5f" in key and not (ignore_empty and value in ignorelist):
                data_dict_metric["temp5_c"] = self._f_to_c(data_dict_metric.pop(key), 1)
            elif "temp6f" in key and not (ignore_empty and value in ignorelist):
                data_dict_metric["temp6_c"] = self._f_to_c(data_dict_metric.pop(key), 1)
            elif "temp7f" in key and not (ignore_empty and value in ignorelist):
                data_dict_metric["temp7_c"] = self._f_to_c(data_dict_metric.pop(key), 1)
            elif "temp8f" in key and not (ignore_empty and value in ignorelist):
                data_dict_metric["temp8_c"] = self._f_to_c(data_dict_metric.pop(key), 1)
            elif "tf_ch1" in key and not (ignore_empty and value in ignorelist):
                data_dict_metric["tf_ch1_c"] = self._f_to_c(data_dict_metric.pop(key), 1)
            elif "tf_ch2" in key and not (ignore_empty and value in ignorelist):
                data_dict_metric["tf_ch2_c"] = self._f_to_c(data_dict_metric.pop(key), 1)
            elif "tf_ch3" in key and not (ignore_empty and value in ignorelist):
                data_dict_metric["tf_ch3_c"] = self._f_to_c(data_dict_metric.pop(key), 1)
            elif "tf_ch4" in key and not (ignore_empty and value in ignorelist):
                data_dict_metric["tf_ch4_c"] = self._f_to_c(data_dict_metric.pop(key), 1)
            elif "tf_ch5" in key and not (ignore_empty and value in ignorelist):
                data_dict_metric["tf_ch5_c"] = self._f_to_c(data_dict_metric.pop(key), 1)
            elif "tf_ch6" in key and not (ignore_empty and value in ignorelist):
                data_dict_metric["tf_ch6_c"] = self._f_to_c(data_dict_metric.pop(key), 1)
            elif "tf_ch7" in key and not (ignore_empty and value in ignorelist):
                data_dict_metric["tf_ch7_c"] = self._f_to_c(data_dict_metric.pop(key), 1)
            elif "tf_ch8" in key and not (ignore_empty and value in ignorelist):
                data_dict_metric["tf_ch8_c"] = self._f_to_c(data_dict_metric.pop(key), 1)
            elif "indoortempf" in key and not (ignore_empty and value in ignorelist):
                data_dict_metric["indoortemp_c"] = self._f_to_c(data_dict_metric.pop(key), 1)
            elif "tempinf" in key and not (ignore_empty and value in ignorelist):
                data_dict_metric["tempin_c"] = self._f_to_c(data_dict_metric.pop(key), 1)
            elif "windchillf" in key and not (ignore_empty and value in ignorelist):
                data_dict_metric["windchill_c"] = self._f_to_c(data_dict_metric.pop(key), 1)
            elif "feelslikef" in key and not (ignore_empty and value in ignorelist):
                data_dict_metric["feelslike_c"] = self._f_to_c(data_dict_metric.pop(key), 1)
            elif "dewptf" in key and not (ignore_empty and value in ignorelist):
                data_dict_metric["dewpt_c"] = self._f_to_c(data_dict_metric.pop(key), 1)
            elif "heatindexf" in key and not (ignore_empty and value in ignorelist):
                data_dict_metric["heatindex_c"] = self._f_to_c(data_dict_metric.pop(key), 1)
            elif "baromin" in key and not (ignore_empty and value in ignorelist):
                data_dict_metric["barom_hpa"] = self._in_to_hpa(data_dict_metric.pop(key), 2)
            elif "baromrelin" in key and not (ignore_empty and value in ignorelist):
                data_dict_metric["baromrel_hpa"] = self._in_to_hpa(data_dict_metric.pop(key), 2)
            elif "baromabsin" in key and not (ignore_empty and value in ignorelist):
                data_dict_metric["baromabs_hpa"] = self._in_to_hpa(data_dict_metric.pop(key), 2)
            elif "mph" in key and not (ignore_empty and value in ignorelist):
                data_dict_metric[key.replace("mph", "_kmh")] = self._mph_to_kmh(data_dict_metric.pop(key), 2)
            elif "maxdailygust" in key and not (ignore_empty and value in ignorelist):
                data_dict_metric[key.replace("maxdailygust", "maxdailygust_kmh")] = self._mph_to_kmh(data_dict_metric.pop(key), 2)
            elif "rainin" in key and not (ignore_empty and value in ignorelist):
                data_dict_metric[key.replace("rainin", "rain_mm")] = self._in_to_mm(data_dict_metric.pop(key), 2)
            elif "rainratein" in key and not (ignore_empty and value in ignorelist):
                data_dict_metric[key.replace("rainratein", "rainrate_mm")] = self._in_to_mm(data_dict_metric.pop(key), 2)
            elif "totalrain" in key and not (ignore_empty and value in ignorelist):
                data_dict_metric[key.replace("totalrain", "totalrain_mm")] = self._in_to_mm(data_dict_metric.pop(key), 2)
            elif "dateutc" in key and not (ignore_empty and value in ignorelist):
                dt = datetime.datetime.fromisoformat(value)
                data_dict_metric[key] = dt.replace(tzinfo=datetime.timezone.utc)
            elif key == "stationtype":
                firmware = self._version_string_to_num(value)

        batterycheck = self._check_battery(data_dict_metric)
        if batterycheck != "":
            if not self.battery_warning:
                self.logger.warning(f"<WARNING> battery level for sensor(s) {batterycheck} is critical - please swap battery")
                self.battery_warning = True
            elif self.battery_warning:
                self.logger.info("<OK> battery level for all sensors is ok again")
                self.battery_warning = False
        data_dict_metric.update({"batterywarning": self.battery_warning})

        return data_dict_metric

    def _get_dew_point_f(self, temp, hum):        # in/out: °F
        try:
            temp = round((float(temp) - 32) * 5 / 9.0, 1)
            s1 = math.log(float(hum) / 100.0)
            s2 = (float(temp) * 17.625) / (float(temp) + 243.04)
            s3 = (17.625 - s1) - s2
            dp = 243.04 * (s1 + s2) / s3           # in °C
            dp = round((float(dp) * 9 / 5) + 32, 1)     # in °F
        except ValueError:
            dp = -9999
        return dp

    def _get_wind_chill_f(self, temp, wspeed):
        return 35.74 + (0.6215*temp) - 35.75*(wspeed**0.16) + ((0.4275*temp)*(wspeed**0.16)) if temp <= 50 and wspeed >= 3 else temp

    def _get_heat_index(self, temp, hum):
        heat_index = 0.5 * (temp + 61. + (temp - 68.) * 1.2 + hum * 0.094)
        if heat_index >= 80:
            heat_index = -42.379 + (2.04901523 * temp) + (10.14333127 * hum) + (-0.22475541 * temp * hum) + (-6.83783e-3*temp**2) + (-5.481717e-2*hum**2) + (1.22874e-3*temp**2 * hum) + (8.5282e-4*temp*hum**2) + (-1.99e-6*temp**2*hum**2)
        return heat_index

    def _get_feels_like_f(self, temp, hum, wspeed):
        if temp <= 50 and wspeed > 3:
            feels_like = self._get_wind_chill_f(temp, wspeed)
        elif temp >= 80:
            feels_like = self._get_heat_index(temp, hum)
        else:
            feels_like = temp
        return feels_like

    def _f_to_c(self, f, n):                                           # convert Fahrenheit to Celsius
        out = "-9999"
        try:
            out = str(round((float(f)-32)*5/9.0, n))
        except ValueError:
            pass
        return out

    def _c_to_f(self, c, n):                                           # convert Celsius to Fahrenheit
        out = "-9999"
        try:
            out = str(round((float(c)*9/5.0) + 32, n))
        except ValueError:
            pass
        return out

    def _mph_to_kmh(self, f, n):                                       # convert mph to kmh
        return str(round(float(f)/0.621371, n))

    def _mph_to_ms(self, f, n):                                        # convert mph to m/s
        return str(round(float(f)/0.621371*1000/3600, n))

    def _in_to_hpa(self, f, n):                                        # convert inHg to HPa
        return str(round(float(f)/0.02953, n))

    def _hpa_to_in(self, f, n):                                        # convert HPa to inHg
        return str(round(float(f)/33.87, n))

    def _in_to_mm(self, f, n):                                         # convert in to mm
        return str(round(float(f)/0.0393701, n))

    def _kmh_to_kts(self, f, n):                                       # convert km/h to
        out = "null"
        try:
            out = str(round((float(f))/1.852, n))
        except ValueError:
            pass
        return out

    def _kmh_to_mph(self, f, n):                                       # convert kmh to mph
        return str(round(float(f)/1.609, n))

    def _mm_to_in(self, f, n):                                         # convert mm to in
        return str(round(float(f)/25.4, n))

    def _feet_to_m(self, f, n):                                        # convert feet to m
        return str(round(float(f)/3.281, n))

    def _m_to_feet(self, f, n):                                        # convert m to feet
        return str(round(float(f)*3.281, n))

    def _utc_to_local(self, utctime):
        offset = (-1*time.timezone)                                    # Zeitzone ausgleichen
        if time.localtime(utctime)[8]:
            offset = offset + 3600  # Sommerzeit hinzu
        localtime = utctime + offset
        return localtime

    def _dec_hour_to_hm_str(self, sh):                                  # convert dec. hour to h:m
        f_sh = float(sh)
        sh_std = int(f_sh)
        sh_min = round((f_sh-int(f_sh))*60)
        return str(sh_std)+":"+str(sh_min)

    def _version_string_to_num(self, s):
        try:
            vpos = s.index("V")+1
            return int(s[vpos:].replace(".", ""))
        except ValueError:
            return

    def _check_battery(self, d):
        # check known sensors if battery is still ok; if not fill outstring with comma-separated list of sensor names
        # 2do: tf_batt und leaf_batt noch nicht sicher, wie dargestellt - vermutlich in V
        # Ambient macht ausschliesslich 0/1 wobei 1 = ok und 0 = low
        is_ambient_weather = self._check_ambient_weather(d)
        outstr = ""
        for key, value in d.items():
            if is_ambient_weather and ("batt" in key or "batleak" in key) and int(value) == 0:
                outstr += key + " "
            # battery-reporting will be same for all weatherstations again after firmware-update of HP2551 v1.6.7
            # elif "EasyWeather" in FWver and "batt" in key and int(value) == 1 : outstr += key + " "
            else:
                if ("wh65batt" in key or "lowbatt" in key or "wh26batt" in key or "wh25batt" in key) and int(value) == 1:
                    outstr += key + " "
                elif "batt" in key and len(key) == 5 and int(value) == 1 and not is_ambient_weather:
                    outstr += key + " "
                elif ("wh57batt" in key or "pm25batt" in key or "leakbatt" in key or "co2_batt" in key) and int(value) < 2:
                    outstr += key + " "
                elif ("soilbatt" in key or "wh40batt" in key or "wh68batt" in key or "tf_batt" in key or "leaf_batt" in key) and float(value) <= 1.2:
                    outstr += key + " "
                elif "wh80batt" in key and float(value) < 2.3:
                    outstr += key + " "
        return outstr.strip()

    def _check_ambient_weather(self, d):
        # q&d check if input is coming from Ambient Weather station
        return True if "AMBWeather" in str(d) else False

# Helper function to get the current timestamp with microseconds
def current_timestamp():
    now = datetime.now()
    return time.mktime(now.timetuple()) + now.microsecond / 1e6
    
# Helper function to return an Integer from a network packet as BigEndian with different sizes, signed or unsigned.
def read_int(data, unsigned, size):
    if size == 1 and unsigned:
        return struct.unpack('>B', data[0:size])[0]
    elif size == 1 and not unsigned:
        return struct.unpack('>b', data[0:size])[0]
    elif size == 2 and unsigned:
        return struct.unpack('>H', data[0:size])[0]
    elif size == 2 and not unsigned:
        return struct.unpack('>h', data[0:size])[0]
    elif size == 4 and unsigned:
        return struct.unpack('>I', data[0:size])[0]
    elif size == 4 and not unsigned:
        return struct.unpack('>i', data[0:size])[0]