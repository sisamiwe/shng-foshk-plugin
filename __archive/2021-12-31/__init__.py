#!/usr/bin/env python3
# vim: set encoding=utf-8 tabstop=4 softtabstop=4 shiftwidth=4 expandtab
#########################################################################
#  Copyright 2021-      Michael Wenzel              wenzel_michael@web.de
#########################################################################
#  This file is part of SmartHomeNG.
#  https://www.smarthomeNG.de
#  https://knx-user-forum.de/forum/supportforen/smarthome-py
#
#  Plugin to connect to Foshk Weather Gateway and get data
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
import logging
from .webif import WebInterface
import socket
import sys
import datetime
import math
import threading
import time
from http.server import BaseHTTPRequestHandler
from collections import deque
import socketserver
import queue
import urllib.parse
import struct

from . import commands

my_queue = queue.Queue()

class Server(object):

    def run(self):
        pass

    def stop(self):
        pass


class WebserviceHttpHandler(BaseHTTPRequestHandler):

    def __init__(self, request, client_address, server):
        self.logger = logging.getLogger(__name__)
        super().__init__(request, client_address, server)

    def reply(self):
        # standard reply is HTTP code of 200 and the response string
        ok_answer = "OK\n"
        self.send_response(200)
        self.send_header('Content-Type', 'text/html')
        self.send_header('Content-Length', str(len(ok_answer)))
        self.send_header('Connection', 'Close')
        self.end_headers()

    def do_POST(self):
        # get the payload from an HTTP POST
        length = int(self.headers['Content-Length'])
        data = self.rfile.read(length)
        # self.logger.debug(f'POST: type={type(data)};  content={data}')
        my_queue.put(data)
        self.reply()

    def do_PUT(self):
        pass

    def do_GET(self):
        # get the query string from an HTTP GET
        data = urllib.parse.urlparse(self.path).query
        self.logger.debug(f'GET: {data}')
        my_queue.put(data)
        self.reply()


class TCPServer(Server, socketserver.TCPServer):

    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address, port, handler, ):
        self.logger = logging.getLogger(__name__)
        socketserver.TCPServer.__init__(self, (address, int(port)), handler)
        self.logger.debug(f'Init socket to listen on {address}:{port}')

    def run(self):
        self.logger.debug('Starting TCP Server')
        self.serve_forever()

    def stop(self):
        self.logger.debug('Stopping TCP Server')
        self.shutdown()
        self.server_close()


class Foshk(SmartPlugin):

    PLUGIN_VERSION = '1.0.0'    # (must match the version specified in plugin.yaml), use '1.0.0' for your initial plugin Release

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
        if not self._init_complete:
            return
            
        # define default values
        self._default_port = 45000                              # default port used by GW1000/GW1100
        self._default_broadcast_address = '255.255.255.255'     # default network broadcast address - the address that network broadcasts are sent to
        self._default_broadcast_port = 46000                    # default network broadcast port - the port that network broadcasts are sent to
        self._default_socket_timeout = 2                        # default socket timeout
        self._default_broadcast_timeout = 5                     # default broadcast timeout
        self._default_retry_wait = 10                           # default retry/wait time
        self._default_max_tries = 3                             # default max tries when polling the API
        self._default_max_age = 60                              # When run as a service the default age in seconds after which GW1000/GW1100 API data is considered stale and will not be used to arugment loop packets
        self._default_poll_interval = 20                        # default device poll interval
        self._default_lost_contact_log_period = 21600           # default period between lost contact log entries during an extended period of lost contact when run as a Service
        self._default_show_battery = False                      # default battery state filtering
        self.known_gateway_models = ('GW1000', 'GW1100')        # list for known gateway models

        # get the parameters for the plugin (as defined in metadata plugin.yaml):
        self._host_addr = self.get_parameter_value('Server_IP')
        self._host_port = self.get_parameter_value('Server_Port')
        self._cycle = self.get_parameter_value('Cycle')
        self._send_interval = self.get_parameter_value('Interval')
        self._poll_method = self.get_parameter_value('Poll_Method')
        self._gateway_addr = self.get_parameter_value('Gateway_IP')
        self._gateway_port = self.get_parameter_value('Gateway_Port')
        self._altitude = self.get_sh()._elev
                
        # Get commands and sensor definition from commands.py
        self._commandset = commands.commandset
        self._commands = commands.commands
        self._sensor_ids = commands.sensor_ids
        self._sensorset = commands.sensor_idt
        self._response_struct = commands.response_struct
        
        # Information about connected gateway
        self.gateway_mac = None
        self.gateway_ip = None
        self.gateway_port = None
        self.gateway_name = None
        self.gateway_model = None
        self.gateway_initialized = False
        self.gateway_set = False
                
        # Communication settings
        self.broadcast_address = None
        self.broadcast_port = None
        self.socket_timeout = None
        self.broadcast_timeout = None
        self.max_tries = None
        self.retry_wait = None
        self._queue_timeout = 10
        self._udp_time_out = 2
        self._broadcast_timeout = 2
        
        # Sensor settings
        self.battery_warning = False

        # Data variables
        self.data_dict_im = {}                                                              # dict to hold all information gotten from weatherstation gateway in imperial units
        self.data_dict_me = {}                                                              # dict to hold all information gotten from weatherstation gateway in metric units
        self.data_dict_live = {}                                                            # dict to hold all live data gotten from weatherstation gateway in metric units
        self.last_data_dict_im = {}                                                         # dict to hold all information gotten from weatherstation gateway in imperial units
        self.last_data_dict_me = {}                                                         # dict to hold all information gotten from weatherstation gateway in metric units
        self.customized_server = {}                                                         # dict to hold settings of customized server
        self.customized_path = {}                                                           # dict to hold settings of customized path
        self.gateway_details = {}
        self.sys_params_dict = {}
        self.sensor_data = {}
        self.gateway_list = []                                                              # list of all discovered gateways having a dict with details per gateway
        self._wind_avg10m = deque(maxlen=(int(10*60/int(self._send_interval))))             # holds 10 minutes of speed, direction and windgust
        
        # Plugin setting
        self.alive = None
        
        ### Initialisation Code starts here
        # get a station object to do the handle the interaction with the GW1000/GW1100 API
        gateway_ip_address = self._gateway_addr if self._gateway_addr != '' else None
        gateway_port = self._gateway_port if self._gateway_port != 0 else None
        
        self.station = Station(ip_address=gateway_ip_address, 
                               port=gateway_port, 
                               broadcast_address=self._default_broadcast_address, 
                               broadcast_port=self._default_broadcast_port, 
                               socket_timeout=self._default_socket_timeout, 
                               broadcast_timeout=self._default_broadcast_timeout, 
                               max_tries=self._default_max_tries, 
                               retry_wait=self._default_retry_wait, 
                               lost_contact_log_period=self._default_lost_contact_log_period)
        
        # Do we have a WH24 attached? First obtain our system parameters.
        _sys_params = self.station.get_system_params()
        
        # WH24 is indicated by the 6th byte being 0
        is_wh24 = _sys_params[5] == 0
        # Tell our sensor id decoding whether we have a WH24 or a WH65. By default we are coded to use a WH65. Is there a WH24 connected?
        if is_wh24:
            # set the WH24 sensor id decode dict entry
            self._sensor_ids[b'\x00']['name'] = 'wh24'
            self._sensor_ids[b'\x00']['long_name'] = 'WH24'
        
        # get a parser object to parse any data from the station
        self.parser = Parser(is_wh24, debug_rain=False, debug_wind=False)

        # get a sensors object to handle sensor ID data
        self.sensors_obj = .Sensors(show_battery=show_battery, debug_sensors=debug_sensors)


        # If needed for polling data
        if self._poll_method != 'live':
            # Initialize HTTP Server,
            self._server = TCPServer(self._host_addr, self._host_port, WebserviceHttpHandler)
            self._server_thread = \
                threading.Thread(target=self.run_server)
            self._server_thread.setDaemon(False)
            self._server_thread.setName('Fosh_TCP_Server')
            self._server_thread.start()
            
            # configure gateway
            if self.gateway_initialized is True:
                self.set_gateway_config(self.gateway_ip, self.gateway_port, self._host_addr, self._host_port, self._send_interval)
            
        # On initialization error use:
        #   self._init_complete = False
        #   return

        if not self.init_webinterface(WebInterface):
            self.logger.error("Unable to start Webinterface")
            self._init_complete = False
        else:
            self.logger.debug(f"Init of Plugin {self.get_shortname()} complete")
        return

    def run(self):
        """
        Run method for the plugin
        """
        self.logger.debug("Run method called")
        
        if self._poll_method != 'live':
            self.poll_data_from_http()
            self.scheduler_add('foshk_poll', self.poll_data_from_http, prio=3, cycle=self._cycle)
        else: 
            self.scheduler_add('foshk_poll', self.poll_data, prio=3, cycle=self._cycle)
        
        self.alive = True

        self.get_live_data(self.gateway_ip, self.gateway_port)
        # self.send_reboot(self.gateway_ip, self.gateway_port)
        self.get_sensor_id_new(self.gateway_ip, self.gateway_port)
        self.get_systems_parameter(self.gateway_ip, self.gateway_port)
        # self.get_offset_calibration(self.gateway_ip, self.gateway_port)
        # self.get_soil_calibration(self.gateway_ip, self.gateway_port)

    def stop(self):
        """
        Stop method for the plugin
        """
        self.logger.debug(f"{self.get_shortname()}: Stop method called")
        self.alive = False
        self.stop_server()

        try:
            self._sh.scheduler.remove('foshk_poll')
        except:
            self.logger.error(f"{self.get_shortname()}: Removing plugin scheduler failed: {sys.exc_info()}")

    def run_server(self):
        self._server.run()

    def stop_server(self):
        self._server.stop()
        self._server = None

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

    def poll_data_from_http(self):
        """Poll the data from queue"""
        try:
            data = my_queue.get(True, self._queue_timeout)
            # self.logger.debug(f"Raw data received is {type(data)}: {data}")
            self._parse_ecowitt_data_to_dict(data)
        except queue.Empty:
            pass
            
    def _init_gateway(self, ip_address=None, port=None, max_tries=self._default_max_tries, retry_wait=self._default_retry_wait):
        for attempt in range(max_tries):
            try:
                # discover devices on the local network, the result is a list of dicts in IP address order with each dict containing data for a unique discovered device
                device_list = self.discover()
                self.gateway_list = device_list
            except socket.error as e:
                self.logger.error(f"Unable to detect device IP address and port: {e} {type(e)}")
                # signal that we have a critical error
                raise
            else:
                # did we find any GW1000/GW1100
                if len(device_list) > 0:
                    # we have at least one, arbitrarily choose the first one found as the one to use
                    disc_ip = device_list[0]['ip_address']
                    disc_port = device_list[0]['port']
                    # log the fact as well as what we found
                    gw1000_str = ', '.join([':'.join(['%s:%d' % (d['ip_address'], d['port'])]) for d in device_list])
                    if len(device_list) == 1:
                        stem = "%s was" % device_list[0]['model']
                    else:
                        stem = "Multiple devices were"
                    self.logger.info(f"{stem} found at {gw1000_str}")
                    ip_address = disc_ip if ip_address is None else ip_address
                    port = disc_port if port is None else port
                    break
                else:
                    # did not discover any GW1000/GW1100 so log it
                    self.logger.debug(f"Failed attempt {attempt + 1} to detect device IP address and/or port")
                    # do we try again or raise an exception
                    if attempt < max_tries - 1:
                        # we still have at least one more try left so sleep and try again
                        time.sleep(retry_wait)
                    else:
                        # we've used all our tries, log it and raise an exception
                        _msg = f"Failed to detect device IP address and/or port after {attempt + 1} attempts"
                        self.logger.error(_msg)
                        raise GW1000IOError(_msg)
        # set our ip_address property but encode it first, it saves doing it repeatedly later
        self.gateway_ip = ip_address.encode()
        self.gateway_port = port
        self.max_tries = max_tries
        self.retry_wait = retry_wait
        self.gateway_mac = device_list[0]['mac']
        # get my device model
        try:
            _firmware_b = self.get_firmware_version()
        except GW1000IOError:
            self.gateway_model = None
        else:
            _firmware_t = struct.unpack("B" * len(_firmware_b), _firmware_b)
            _firmware_str = "".join([chr(x) for x in _firmware_t[5:5 + _firmware_t[4]]])
            self.gateway_model = self.get_model_from_firmware(_firmware_str)
        return True

    def discover_gateway(self):
        """Discover the GW1000 device on the local network """
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
        command_bytearray = self.__build_send_packet(self._commandset['cmd_broadcast'])
        for n in range(5):
            if self.gateway_initialized is False:
                try:
                    # Sent a CMD_BROADCAST command
                    sock.sendto(command_bytearray, ('255.255.255.255', 46000))
                    packet = sock.recv(1024)

                    # Check device name to avoid detection of other local Ecowitt/Ambient consoles
                    model = packet[18:len(packet) - 1].decode()
                    if model.startswith('GW'):
                        self.gateway_mac = "%x:%x:%x:%x:%x:%x" % struct.unpack("BBBBBB", packet[5:11])
                        self.gateway_ip = '%d.%d.%d.%d' % struct.unpack('>BBBB', packet[11:15])
                        self.gateway_port = struct.unpack('>H', packet[15: 17])[0]
                        self.gateway_model = model      # ToDo: Model kürzen
                        self.logger.debug(f"Weather device {self.gateway_model} with mac {self.gateway_mac} discovered at {self.gateway_ip}:{self.gateway_port}")
                    else:
                        self.logger.error(f'Error: Unsupported local console: {self.gateway_model}')
                except socket.error:
                    self.logger.error('Error: unable to find GW1000 device on local network')
        return True

    def get_gateway_interval(self, ws_ipaddr, ws_port):
        result = None
        edata = self._send_to_gateway(ws_ipaddr, ws_port, bytearray(commands.cmd_get_customE, 'latin-1'))
        if edata != "" and len(edata) >= 12:
            id_len = edata[4]
            key_len = edata[id_len + 5]
            ip_len = edata[key_len + id_len + 6]
            result = str(edata[ip_len + key_len + id_len + 9]*256 + edata[ip_len + key_len + id_len + 10])
        # self.logger.debug(f"get_gateway_interall: result={result}")
        return result

    def send_reboot(self, ws_ipaddr, ws_port):
        """
        answer = self._send_to_gateway(ws_ipaddr, ws_port, bytearray(cmd_reboot,'latin-1'))
        ret = "done" if answer == bytearray(ok_cmd_reboot,'latin-1') else "failed"
        return ret
        """
        command_bytearray = self.__build_send_packet(self._commandset['cmd_write_reboot'])
        response = self._send_to_gateway(ws_ipaddr, ws_port, command_bytearray)
        self.logger.debug(f"send_reboot: response={response}")
        result = self._parse_response(response)
        return "done" if result == 0 else "failed"

    def set_gateway_config(self, ws_ipaddr, ws_port, custom_host, custom_port, custom_interval):
        """ aktuelle Config auslesen, mit den Parametern ersetzen und in WS schreiben """
        custom_server_id = ""
        custom_password = ""
        custom_enabled = True
        custom_ecowitt = True
        custom_ecowitt_pathpath = "/data/report/"
        custom_wu_path = "/weatherstation/updateweatherstation.php"

        # Customized Path abfragen und speichern
        command_bytearray = self.__build_send_packet(self._commandset['cmd_read_customized_path'])
        customized_path = self._send_to_gateway(ws_ipaddr, ws_port, command_bytearray)
        self._parse_customized_path(customized_path)
        self.logger.debug(f"set_gateway_config: customized_path={self.customized_path}")
        if not (self.customized_path['custom_ecowitt_path'] == custom_ecowitt_pathpath and self.customized_path['custom_wu_path'] == custom_wu_path):
            self.logger.debug(f"Need to set customized path: Ecowitt: current={self.customized_path['custom_ecowitt_path']} vs. new={custom_ecowitt_pathpath} and WU: current={self.customized_path['custom_wu_path']} vs. new={custom_wu_path}")
            # Werte schreiben Customized Path
            ## Valuebytes (Inhalt) zusammenstellen
            valuebytes = bytearray()
            valuebytes.extend(self.__int2bytes(len(custom_ecowitt_pathpath), 1))
            valuebytes.extend(str.encode(custom_ecowitt_pathpath))
            valuebytes.extend(self.__int2bytes(len(custom_wu_path), 1))
            valuebytes.extend(str.encode(custom_wu_path))
             ## Sendepacket schnüren und senden
            command_bytearray = self.__build_send_packet(self._commandset['cmd_write_customized_path'], valuebytes)
            write_response = bool(bytes_to_int(self._send_to_gateway(ws_ipaddr, ws_port, command_bytearray), False))
            if write_response is True:
                self.logger.debug(f"<OK> Enable Gateway at {ws_ipaddr}:{ws_port} sending to Ecowitt-Path: {custom_ecowitt_pathpath} and WU-Path {custom_wu_path}: ok")
            else:
                self.logger.error(f"<ERROR> Enable Gateway at {ws_ipaddr}:{ws_port} sending to Ecowitt-Path: {custom_ecowitt_pathpath} and WU-Path {custom_wu_path}: failed")
        else:
            self.logger.debug(f"<INFO> Customized Path settings already correct; No need to do it again")

        # Customized Server Setting abfragen und speichern
        command_bytearray = self.__build_send_packet(self._commandset['cmd_read_customized'])
        customized_server = self._send_to_gateway(ws_ipaddr, ws_port, command_bytearray)
        self._parse_customized_server_setting(customized_server)
        self.logger.debug(f"set_gateway_config: customized_server={self.customized_server}")
        if not (self.customized_server['server_ip'] == custom_host and self.customized_server['port'] == custom_port and self.customized_server['interval'] == custom_interval and self.customized_server['is_active'] is True and self.customized_server['protocol'] == 'ecowitt'):
            self.logger.debug(f"Need to set customized server: Server_IP current={self.customized_server['server_ip']} vs. new={custom_host}; Port: current={self.customized_server['port']} vs. new={custom_port}; Interval: current={self.customized_server['interval']} vs. new={custom_port}; Active: current={self.customized_server['is_active']} vs. new=True; Protocol: current={self.customized_server['protocol']} vs. new='ecowitt'")
            # Werte schreiben Customized Server Setting
            ## Valuebytes (Inhalt) zusammenstellen
            valuebytes = bytearray()
            valuebytes.extend(self.__int2bytes(len(custom_server_id), 1))
            valuebytes.extend(str.encode(custom_server_id))
            valuebytes.extend(self.__int2bytes(len(custom_password), 1))
            valuebytes.extend(str.encode(custom_password))
            valuebytes.extend(self.__int2bytes(len(custom_host), 1))
            valuebytes.extend(str.encode(custom_host))
            valuebytes.extend(self.__int2bytes(custom_port, 2))
            valuebytes.extend(self.__int2bytes(custom_interval, 2))
            valuebytes.extend(self.__int2bytes(int(not(custom_ecowitt)), 1))
            valuebytes.extend(self.__int2bytes(int(custom_ecowitt), 1))
            self.logger.debug(f"Customized Server: valuebytes={valuebytes}")
            
            arr = bytearray(chr(len(custom_server_id)) + custom_server_id + chr(len(custom_password)) + custom_password + chr(len(custom_host)) + custom_host + chr(int(int(custom_port)/256)) + chr(int(int(custom_port)%256)) + chr(int(int(custom_interval)/256)) + chr(int(int(custom_interval)%256)) + chr(not custom_ecowitt) + chr(custom_enabled),'latin-1')
            self.logger.debug(f"Customized Server: valuebytes={arr}")
            
            ## Sendepacket schnüren
            command_bytearray = self.__build_send_packet(self._commandset['cmd_write_customized'], valuebytes)
            write_response = bool(bytes_to_int(self._send_to_gateway(ws_ipaddr, ws_port, command_bytearray), False))
            if write_response is True:
                self.logger.debug(f"<OK> Enable Gateway at {ws_ipaddr}:{ws_port} sending to {custom_host}:{custom_port} in 'Ecowitt' protocoll every {custom_interval}sec: ok")
            else:
                self.logger.error(f"<ERROR> Enable Gateway at {ws_ipaddr}:{ws_port} sending to {custom_host}:{custom_port} in 'Ecowitt' protocoll every {custom_interval}sec: failed")
        else:
            self.logger.debug(f"<INFO> Customized Server settings already correct; No need to do it again")
        return

    def get_live_data(self, ws_ipaddr, ws_port):
        """ Get current live conditions from the GW1000 device """
        command_bytearray = self.__build_send_packet(self._commandset['cmd_gw1000_livedata'])
        valuebytes = self._send_to_gateway(ws_ipaddr, ws_port, command_bytearray)
        self.logger.debug(f"get_live_data: valuebytes={valuebytes}")
        self._parse_live_data(valuebytes)
        self.logger.debug(f"data_dict_live={self.data_dict_live}")
        return
        
    def get_live_sensor_data(self):
        """Get all current sensor data.

        Obtain live sensor data from the GW1000/GW1100 API then parse the API response to create a timestamped data dict keyed by internal
        GW1000/GW1100 field name. Add current sensor battery state and signal level data to the data dict. If no data was obtained from the API the
        value None is returned.
        """

        # obtain the raw data via the GW1000/GW1100 API, we may get a GW1000IOError exception, if we do let it bubble up (the raw data is
        # the data returned from the GW1000/GW1100 inclusive of the fixed header, command, payload length, payload and checksum bytes)
        raw_data = self.get_livedata()
        # if we made it here our raw data was validated by checksum
        
        # get a timestamp to use in case our data does not come with one
        _timestamp = int(time.time())
        
        # parse the raw data (the parsed data is a dict keyed by internal GW1000/GW1100 field names and containing the decoded raw sensor data)
        parsed_data = self.parser.parse(raw_data, _timestamp)
        
        # log the parsed data but only if debug>=3
        self.logger.debug(f"Parsed data: {parsed_data}")
        
        # The parsed live data does not contain any sensor battery state or signal level data. The battery state and signal level data for each sensor can be obtained from the 
        # GW1000/GW1100 API via our Sensors object.
        
        # first we need to update our Sensors object with current sensor ID data
        self.update_sensor_id_data()
        
        # now add any sensor battery state and signal level data to the parsed data
        parsed_data.update(self.sensors_obj.battery_and_signal_data)
        
        # log the processed parsed data but only if debug>=3
        self.logger.debug(f"Processed parsed data: {parsed_data}")
        return parsed_data

    def get_model_from_firmware(self, firmware_string):
        """Determine the device model from the firmware version.

        To date GW1000 and GW1100 firmware versions have included the device model in the firmware version string returned via the device API. 
        Whilst this is not guaranteed to be the case for future firmware releases, in the absence of any other direct means of obtaining the device model number it is a useful means for
        determining the device model.

        The check is a simple check to see if the model name is contained in the firmware version string returned by the device API.

        If a known model is found in the firmware version string the model is returned as a string. 
        None is returned if (1) the firmware string is None or (2) a known model is not found in the firmware version string.
        """

        # do we have a firmware string
        if firmware_string is not None:
            # we have a firmware string so look for a known model in the string and return the result
            return self.get_model(firmware_string)
        else:
            # for some reason we have no firmware string, so return None
            return None

    def get_model_from_ssid(self, ssid_string):
        """Determine the device model from the device SSID.

        To date the GW1000 and GW1100 device SSID has included the device model in the SSID returned via the device API. Whilst this is not
        guaranteed to be the case for future firmware releases, in the absence of any other direct means of obtaining the device model
        number it is a useful means for determining the device model. This is particularly the case when using UDP broadcast to discover devices on the local network.

        Note that it may be possible to alter the SSID used by the device in which case this method may not provide an accurate result.
        However, as the device SSID is only used during initial device configuration and since altering the device SSID is not a normal
        part of the initial device configuration, this method of determining the device model is considered adequate for use during discovery by UDP broadcast.

        The check is a simple check to see if the model name is contained in the SSID returned by the device API.

        If a known model is found in the SSID the model is returned as a string. None is returned if (1) the SSID is None or (2) a known model is not found in the SSID.
        """

        return self.get_model(ssid_string)
       
    def get_model(self, t):
        """Determine the device model from a string.

        To date GW1000 and GW1100 firmware versions have included the device model in the firmware version string or the device SSID.
        Both the firmware version string and device SSID are available via the device API so checking the firmware version string or SSID
        provides a de facto method of determining the device model.

        This method uses a simple check to see if a known model name is contained in the string concerned. Known model strings are contained in a tuple Station.known_models.

        If a known model is found in the string the model is returned as a string. None is returned if a known model is not found in the string.
        """

        # do we have a string to check
        if t is not None:
            # we have a string, now do we have a know model in the string, if so return the model string
            for model in self.known_gateway_models:
                if model in t.upper():
                    return model
            # we don't have a known model so return None
            return None
        else:
            # we have no string so return None
            return None
        
    def _parse_response(self, response, commandname='', read_response=True):
        checksum = self.__calc_checksum(response[:-1])  # first, cut last byte (checksum) and then calculate checksum
        # self.logger.debug(f"_parse_response: checksum={checksum}")
        
        received_checksum = response[len(response) - 1]
        # self.logger.debug(f"_parse_response: received_checksum={received_checksum}")
        
        if received_checksum != checksum:
            self.logger.error(f'Calculated checksum {checksum} does not match received checksum of {received_checksum}! Ignoring response')
            return None

        # Extract command, valuebytes out of response
        command = response[2]
        # self.logger.debug(f"_parse_response: command={hex(command)}")
        if hex(command) == '0x27': 
            data_size = response[3:5].hex()
            valuebytes = response[5: len(response) - 1]
            self.logger.debug(f"_parse_response: got response from command={format(command, 'x')} with data_size of {data_size} bytes")
            return valuebytes
        elif hex(command) == '0x3c':
            data_size = struct.unpack(">H", response[3:5])[0]
            valuebytes = response[5:5 + data_size - 4]
            self.logger.debug(f"_parse_response: got response from command={format(command, 'x')} with data_size of {data_size} bytes")
            return valuebytes
        else:
            data_size = response[3]
            valuebytes = response[4: len(response) - 1]
            self.logger.debug(f"_parse_response: got response from command={format(command, 'x')} with data_size of {data_size} bytes and valuebytes={valuebytes}")
            return valuebytes

    def _parse_ecowitt_data_to_dict(self, data):
        """Parse the ecowitt data and add it to a dictionnary."""

        self.last_data_dict_im = self.data_dict_im          # speichern das alten dict, bevor es überschrieben wird
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
        self._add_new_data_to_dict(self.data_dict_im)

        # do checks an set global variables and add values to dict
        self._add_status_to_dict(self.data_dict_im)

        self.logger.debug(f"{self.get_shortname()}: data_dict_im={self.data_dict_im}")

        # convert dict with imperial units to dict with metric units
        self.last_data_dict_me = self.data_dict_me          # speichern das alten dict, bevor es überschrieben wird
        self.data_dict_me = self._convert_dict_from_imperial_to_metric(self.data_dict_im)
        self.logger.debug(f"{self.get_shortname()}: data_dict_me={self.data_dict_me}")
        return

    def _parse_customized_server_setting(self, valuebytes):
    
        # define start and end bytes for data
        server_id_size = valuebytes[0]
        password_size = valuebytes[server_id_size+1]
        server_size = valuebytes[server_id_size+password_size+2]
        
        server_id_start = 1
        server_id_end = server_id_start + server_id_size
        
        password_start = 1 + server_id_size + 1
        password_end = password_start + password_size
        
        server_ip_start = 1 + server_id_size + 1 + password_size + 1
        server_ip_end = server_ip_start + server_size
        
        port_start = server_ip_end
        interval_start = port_start+2
        
        # get data
        if server_id_start < server_id_end:
            server_id = valuebytes[server_id_start:server_id_end]
            # self.logger.debug(f"_parse_customized_server_setting: server_id={server_id}")
            self.customized_server['server_id'] = server_id

        if password_start < password_end:
            password = valuebytes[password_start:password_end]
            # self.logger.debug(f"_parse_customized_server_setting: password={password}")
            self.customized_server['password'] = password
            
        if server_ip_start < server_ip_end:
            server_ip = valuebytes[server_ip_start:server_ip_end].decode()
            # self.logger.debug(f"_parse_customized_server_setting: server_ip={server_ip}")
            self.customized_server['server_ip'] = server_ip
        
        port_bytes = valuebytes[port_start:port_start+2]
        port = port_bytes[0]*256+port_bytes[1]
        # self.logger.debug(f"_parse_customized_server_setting: port={port}")
        self.customized_server['port'] = port

        interval_bytes = valuebytes[interval_start:interval_start+2]
        interval = interval_bytes[0]*256+interval_bytes[1]
        # self.logger.debug(f"_parse_customized_server_setting: interval={interval}")
        self.customized_server['interval'] = interval
        
        server_type = bytes_to_int(valuebytes[interval_start+2:interval_start+3], False)
        server_types = ['ecowitt', 'weather unterground']
        self.customized_server['protocol'] = server_types[server_type]
        # self.logger.debug(f"_parse_customized_server_setting: server_type={server_type} resp. protocol {server_types[server_type]}")
        
        is_active = valuebytes[interval_start+2:interval_start+3]
        # self.logger.debug(f"_parse_customized_server_setting: is_active={bool(is_active)}")
        self.customized_server['is_active'] = bool(is_active)
        
    def _parse_customized_path(self, valuebytes):
    
        custom_ecowitt_path = ""
        custom_wu_path = ""
    
        # define start and end bytes for data
        ecowitt_path_length = valuebytes[0]
        wu_path_length = valuebytes[ecowitt_path_length + 1]

        # get data        
        for i in range(1, 1 + ecowitt_path_length): 
            custom_ecowitt_path += chr(valuebytes[i])
        for i in range(ecowitt_path_length + 2, ecowitt_path_length + 1 + wu_path_length): 
            custom_wu_path += chr(valuebytes[i])
       
        self.customized_path['custom_ecowitt_path'] = custom_ecowitt_path
        self.customized_path['custom_wu_path'] = custom_wu_path
        
    def _parse_firmware_version(self, valuebytes):
        return valuebytes[1:1+valuebytes[0]].decode()
        
    def _parse_systems_parameter(self, valuebytes):
        is_wh24 = valuebytes[1] == 0
        # Tell our sensor id decoding whether we have a WH24 or a WH65. By default we are coded to use a WH65. Is there a WH24 connected?
        if is_wh24:
            # set the WH24 sensor id decode dict entry
            self._sensor_ids[b'\x00']['name'] = 'wh24'
            self._sensor_ids[b'\x00']['long_name'] = 'WH24'
        self.sys_params_dict['is_wh24'] = is_wh24
        self.sys_params_dict['frequency'] = commands.frequencies[valuebytes[0]]
        self.sys_params_dict['utc'] = self.__decode_utc(valuebytes[2:6])
        self.sys_params_dict['timezone_index'] = valuebytes[6]
        self.sys_params_dict['dst_status'] = valuebytes[7] != 0
        date_time_str = time.strftime("%-d %B %Y %H:%M:%S", time.gmtime(self.sys_params_dict['utc']))
        self.logger.debug(f"_parse_systems_parameter: sys_params_dict={self.sys_params_dict}")
        return 

    def _parse_live_data(self, resp):
        self.logger.debug(f"_parse_live_data2: resp={resp}")
        data = {}
        if len(resp) > 0:
            index = 0
            while index < len(resp) - 1:
                try:
                    decode_str, field_size, field = self._response_struct[resp[index:index + 1]]
                except KeyError:
                    self.logger.error("Unknown field address '%s' detected. Remaining sensor data ignored." % (bytes_to_hex(resp[index:index + 1]),))
                    break
                else:
                    _field_data = getattr(self, decode_str)(resp[index + 1:index + 1 + field_size], field)
                    # self.logger.debug(f"_parse_live_data2: _field_data={_field_data}")
                    if _field_data is not None:
                        data.update(_field_data)
                    index += field_size + 1
        
        self.data_dict_live.update(data)
        self.logger.debug(f"_parse_live_data2: self.data_dict_live={self.data_dict_live}")
                    
    def _parse_live_data_alt(self, data):
        """ Parse Live Data packet by iterate over sensors """
        # self.logger.debug(f"_parse_live_data: with data={data}")
        index = 0
        size = len(data)
        while index < size:
            index = self._read_sensor(data, index)
# Todo          
    def _parse_co2_offset(self, data):
        # initialise a dict to hold our final data
        offset_dict = dict()
        # and decode/store the offset data
        # bytes 0 and 1 hold the CO2 offset
        offset_dict['co2'] = struct.unpack(">h", data[0:2])[0]
        # bytes 2 and 3 hold the PM2.5 offset
        offset_dict['pm25'] = struct.unpack(">h", data[2:4])[0]/10.0
        # bytes 4 and 5 hold the PM10 offset
        offset_dict['pm10'] = struct.unpack(">h", data[4:6])[0]/10.0
        return offset_dict
# Todo        
    def _parse_calibration(self, data):
        """Obtain GW1000/GW1100 calibration data."""
        # initialise a dict to hold our final data
        calibration_dict = dict()
        # and decode/store the calibration data
        # bytes 0 and 1 are reserved (lux to solar radiation conversion
        # gain (126.7))
        calibration_dict['uv'] = struct.unpack(">H", data[2:4])[0]/100.0
        calibration_dict['solar'] = struct.unpack(">H", data[4:6])[0]/100.0
        calibration_dict['wind'] = struct.unpack(">H", data[6:8])[0]/100.0
        calibration_dict['rain'] = struct.unpack(">H", data[8:10])[0]/100.0
        # obtain the offset calibration data via the API
        response = self.station.get_offset_calibration()
        # determine the size of the calibration data
        raw_data_size = six.indexbytes(response, 3)
        # extract the actual data
        data = response[4:4 + raw_data_size - 3]
        # and decode/store the offset calibration data
        calibration_dict['intemp'] = struct.unpack(">h", data[0:2])[0]/10.0
        try:
            calibration_dict['inhum'] = struct.unpack("b", data[2])[0]
        except TypeError:
            calibration_dict['inhum'] = struct.unpack("b", six.int2byte(data[2]))[0]
        calibration_dict['abs'] = struct.unpack(">l", data[3:7])[0]/10.0
        calibration_dict['rel'] = struct.unpack(">l", data[7:11])[0]/10.0
        calibration_dict['outtemp'] = struct.unpack(">h", data[11:13])[0]/10.0
        try:
            calibration_dict['outhum'] = struct.unpack("b", data[13])[0]
        except TypeError:
            calibration_dict['outhum'] = struct.unpack("b", six.int2byte(data[13]))[0]
        calibration_dict['dir'] = struct.unpack(">h", data[14:16])[0]
        return calibration_dict
# Todo        
    def _parse_soil_calibration(self, data):
        """Obtain GW1000/GW1100 soil moisture sensor calibration data. """
        # initialise a dict to hold our final data
        calibration_dict = {}
        # initialise a counter
        index = 0
        # iterate over the data
        while index < len(data):
            try:
                channel = data[index]
            except TypeError:
                channel = data[index]
            calibration_dict[channel] = {}
            try:
                humidity = data[index + 1]
            except TypeError:
                humidity = data[index + 1]
            calibration_dict[channel]['humidity'] = humidity
            calibration_dict[channel]['ad'] = struct.unpack(">h", data[index+2:index+4])[0]
            try:
                ad_select = sdata[index + 4]
            except TypeError:
                ad_select = data[index + 4]
            calibration_dict[channel]['ad_select'] = ad_select
            try:
                min_ad = six.byte2int(data[index + 5])
            except TypeError:
                min_ad = data[index + 5]
            calibration_dict[channel]['adj_min'] = min_ad
            calibration_dict[channel]['adj_max'] = struct.unpack(">h", data[index+6:index+8])[0]
            index += 8
        return calibration_dict

    def _read_sensor(self, data, index):
        sensor_id = data[index]
        sensor_id_hex = "0x{:02X}".format(sensor_id)
        # self.logger.debug(f"_read_sensor: sensor_id={sensor_id}")
        
        item = self._sensorset[sensor_id_hex]['item']
        name = self._sensorset[sensor_id_hex]['name']
        unit = self._sensorset[sensor_id_hex]['unit']
        size = self._sensorset[sensor_id_hex]['length']
        signed = self._sensorset[sensor_id_hex].get('signed', False)
        factor = self._sensorset[sensor_id_hex].get('factor', 1)
        # self.logger.debug(f"_read_sensor: item={item}, name={name}, unit={unit}, size={size}")
        
        value = read_int(data[index + 1: index + 1 + size], False, size) * factor
        if type(value) is float:
            value = round(value, 2)
        
        # self.logger.debug(f"_read_sensor: item={item}, value={value}")
        self.data_dict_live.update({name: value})
        
        # at Sensor_ID 15 add value für solar radiation
        if sensor_id_hex == '0x15':
            self.data_dict_live.update({'Solar Radiation': value * 0.0079 * 0.0036})        # Convert lux into w/m2, 0.0079 is the ratio at sunlight spectrum, Convert w/m2 to MJ/m2/h, 1 W/m2 = 1 J/m2/Sec
        
        return index + 1 + size

    def _add_new_data_to_dict(self, d):
        """add addition self-computed data to dict"""

        if d.keys() >= {"tempf", "humidity"}:
            d['dewptf'] = self._get_dew_point_f(d["tempf"], d["humidity"])

        if d.keys() >= {"tempf", "windspeedmph"}:
            d['windchillf'] = round(self._get_wind_chill_f(d["tempf"], d["windspeedmph"]), 1)

        if d.keys() >= {"tempf", "humidity", "windspeedmph"}:
            d['feelslikef'] = round(self._get_feels_like_f(d["tempf"], d["humidity"], d["windspeedmph"]), 1)

        if d.keys() >= {"tempf", "humidity"}:
            d['heatindexf'] = round(self._get_heat_index(d["tempf"], d["humidity"]), 1)

        if d.keys() >= {"solarradiation"}:
            d['brightness'] = round(d["solarradiation"] * 126.7, 1)

        if d.keys() >= {"tempf", "dewptf"}:
            tempf = d["tempf"]
            dewptf = d["dewptf"]
            d['cloudf'] = round(((tempf-dewptf) / 4.4) * 1000 + (float(self._altitude)*3.28084))

        try:
            windspeedmph = d.get("windspeedmph", 0)
            winddir = d.get("winddir", 0)
            windgustmph = d.get("windgustmph", 0)
            self._wind_avg10m.append([int(time.time()), windspeedmph, winddir, windgustmph])
            d.update({"windspdmph_avg10m": self.__avg_wind(self._wind_avg10m, 1)})
            d.update({"winddir_avg10m": self.__avg_wind(self._wind_avg10m, 2)})
            d.update({"windgustmph_max10m": self.__max_wind(self._wind_avg10m, 3)})
        except ValueError:
            pass

        """ TODO

        try:
            sr = d.get("solarradiation", None)
            if sr != "null" and float(sr) >= 120:
                try:
                    value = d.get("dateutc", None)
                    currtime = int(time.mktime(time.localtime(int(utcToLocal(time.mktime(time.strptime(value.replace("%20","+").replace("%3A",":"), "%Y-%m-%d+%H:%M:%S")))))))
                except ValueError:
                    currtime = time.localtime()

                try:
                    lasttime = int(getfromDict(min_max,["last_suntime"])) # last save time in min_max
                except ValueError:
                    lasttime = 0

                if currtime-lasttime >= 60 and float(sr) >= 120:       # only trigger if a minute before
                    min_max["sunmins"] += 1
                    min_max["last_suntime"] = currtime
                sunhours = str(round(min_max["sunmins"]/60,2))
                outstr += "&" + what + "=" + sunhours
        except ValueError:
            pass

        elif what == "ptrend":                                       # add pressure items ptrendN & pchangeN
            val = getfromDict(last_d_m,["ptrend1"])                    # attention! last_d_m needed !!!!!!!!!!
            if val != "null": outstr += "&ptrend1="+val
            val = getfromDict(last_d_m,["pchange1"])

            try:
                vnum = hpatoin(float(val),4)
                outstr += "&pchange1="+str(vnum)
            except ValueError:
                pass

            val = getfromDict(last_d_m,["ptrend3"])
            if val != "null": outstr += "&ptrend3="+val
            val = getfromDict(last_d_m,["pchange3"])

            try:
                vnum = hpatoin(float(val),4)
                outstr += "&pchange3="+str(vnum)
            except ValueError:
                pass
        """

        return

    def _add_status_to_dict(self, d):
        """add warnings & states to dict"""

        # d.update({"running": func(int(wsconnected))})
        # d.update({"wswarning": func(int(inWStimeoutWarning))})
        # d.update({"sensorwarning": func(int(inSensorWarning))})
        # if inSensorWarning and SensorIsMissed != "": d.update({"missed" : SensorIsMissed})
        self._check_battery(d)
        d.update({"batterywarning": self.battery_warning})
        # d.update({"stormwarning": func(int(inStormWarning))})
        # d.update({"tswarning": func(int(inTSWarning))})
        # d.update({"updatewarning": func(int(updateWarning))})
        # d.update({"leakwarning": func(int(inLeakageWarning))})
        # d.update({"co2warning": func(int(inCO2Warning))})
        # d.update({"time": strToNum(loxTime(time.time()))})
        return

    def _convert_dict_from_imperial_to_metric(self, data_dict_im, ignore_empty=True):
        ignorelist = ["-9999", "None", "null"]
        data_dict_metric = {}
        data_dict_metric.update(data_dict_im)
        for key, value in data_dict_im.items():
            if key == "tempf" and not (ignore_empty and value in ignorelist):
                data_dict_metric["temp_c"] = self.__f_to_c(data_dict_metric.pop(key), 1)
            elif "temp1f" in key and not (ignore_empty and value in ignorelist):
                data_dict_metric["temp1_c"] = self.__f_to_c(data_dict_metric.pop(key), 1)
            elif "temp2f" in key and not (ignore_empty and value in ignorelist):
                data_dict_metric["temp2_c"] = self.__f_to_c(data_dict_metric.pop(key), 1)
            elif "temp3f" in key and not (ignore_empty and value in ignorelist):
                data_dict_metric["temp3_c"] = self.__f_to_c(data_dict_metric.pop(key), 1)
            elif "temp4f" in key and not (ignore_empty and value in ignorelist):
                data_dict_metric["temp4_c"] = self.__f_to_c(data_dict_metric.pop(key), 1)
            elif "temp5f" in key and not (ignore_empty and value in ignorelist):
                data_dict_metric["temp5_c"] = self.__f_to_c(data_dict_metric.pop(key), 1)
            elif "temp6f" in key and not (ignore_empty and value in ignorelist):
                data_dict_metric["temp6_c"] = self.__f_to_c(data_dict_metric.pop(key), 1)
            elif "temp7f" in key and not (ignore_empty and value in ignorelist):
                data_dict_metric["temp7_c"] = self.__f_to_c(data_dict_metric.pop(key), 1)
            elif "temp8f" in key and not (ignore_empty and value in ignorelist):
                data_dict_metric["temp8_c"] = self.__f_to_c(data_dict_metric.pop(key), 1)
            elif "tf_ch1" in key and not (ignore_empty and value in ignorelist):
                data_dict_metric["tf_ch1_c"] = self.__f_to_c(data_dict_metric.pop(key), 1)
            elif "tf_ch2" in key and not (ignore_empty and value in ignorelist):
                data_dict_metric["tf_ch2_c"] = self.__f_to_c(data_dict_metric.pop(key), 1)
            elif "tf_ch3" in key and not (ignore_empty and value in ignorelist):
                data_dict_metric["tf_ch3_c"] = self.__f_to_c(data_dict_metric.pop(key), 1)
            elif "tf_ch4" in key and not (ignore_empty and value in ignorelist):
                data_dict_metric["tf_ch4_c"] = self.__f_to_c(data_dict_metric.pop(key), 1)
            elif "tf_ch5" in key and not (ignore_empty and value in ignorelist):
                data_dict_metric["tf_ch5_c"] = self.__f_to_c(data_dict_metric.pop(key), 1)
            elif "tf_ch6" in key and not (ignore_empty and value in ignorelist):
                data_dict_metric["tf_ch6_c"] = self.__f_to_c(data_dict_metric.pop(key), 1)
            elif "tf_ch7" in key and not (ignore_empty and value in ignorelist):
                data_dict_metric["tf_ch7_c"] = self.__f_to_c(data_dict_metric.pop(key), 1)
            elif "tf_ch8" in key and not (ignore_empty and value in ignorelist):
                data_dict_metric["tf_ch8_c"] = self.__f_to_c(data_dict_metric.pop(key), 1)
            elif "indoortempf" in key and not (ignore_empty and value in ignorelist):
                data_dict_metric["indoortemp_c"] = self.__f_to_c(data_dict_metric.pop(key), 1)
            elif "tempinf" in key and not (ignore_empty and value in ignorelist):
                data_dict_metric["tempin_c"] = self.__f_to_c(data_dict_metric.pop(key), 1)
            elif "windchillf" in key and not (ignore_empty and value in ignorelist):
                data_dict_metric["windchill_c"] = self.__f_to_c(data_dict_metric.pop(key), 1)
            elif "feelslikef" in key and not (ignore_empty and value in ignorelist):
                data_dict_metric["feelslike_c"] = self.__f_to_c(data_dict_metric.pop(key), 1)
            elif "dewptf" in key and not (ignore_empty and value in ignorelist):
                data_dict_metric["dewpt_c"] = self.__f_to_c(data_dict_metric.pop(key), 1)
            elif "heatindexf" in key and not (ignore_empty and value in ignorelist):
                data_dict_metric["heatindex_c"] = self.__f_to_c(data_dict_metric.pop(key), 1)
            elif "baromin" in key and not (ignore_empty and value in ignorelist):
                data_dict_metric["barom_hpa"] = self.__in_to_hpa(data_dict_metric.pop(key), 2)
            elif "baromrelin" in key and not (ignore_empty and value in ignorelist):
                data_dict_metric["baromrel_hpa"] = self.__in_to_hpa(data_dict_metric.pop(key), 2)
            elif "baromabsin" in key and not (ignore_empty and value in ignorelist):
                data_dict_metric["baromabs_hpa"] = self.__in_to_hpa(data_dict_metric.pop(key), 2)
                wnow = self._weather_now(float(data_dict_metric["baromabs_hpa"]), "DE")
                data_dict_metric.update({'wnowlvl': str(wnow[0])})
                data_dict_metric.update({'wnowtxt': str(wnow[1])})
            elif "mph" in key and not (ignore_empty and value in ignorelist):
                data_dict_metric[key.replace("mph", "_kmh")] = self.__mph_to_kmh(data_dict_metric.pop(key), 2)
            elif "maxdailygust" in key and not (ignore_empty and value in ignorelist):
                data_dict_metric[key.replace("maxdailygust", "maxdailygust_kmh")] = self.__mph_to_kmh(data_dict_metric.pop(key), 2)
            elif "rainin" in key and not (ignore_empty and value in ignorelist):
                data_dict_metric[key.replace("rainin", "rain_mm")] = self.__in_to_mm(data_dict_metric.pop(key), 2)
            elif "rainratein" in key and not (ignore_empty and value in ignorelist):
                data_dict_metric[key.replace("rainratein", "rainrate_mm")] = self.__in_to_mm(data_dict_metric.pop(key), 2)
            elif "totalrain" in key and not (ignore_empty and value in ignorelist):
                data_dict_metric[key.replace("totalrain", "totalrain_mm")] = self.__in_to_mm(data_dict_metric.pop(key), 2)
            elif "dateutc" in key and not (ignore_empty and value in ignorelist):
                dt = datetime.datetime.fromisoformat(value)
                data_dict_metric[key] = dt.replace(tzinfo=datetime.timezone.utc)
            elif key == "stationtype":
                firmware = self.__version_string_to_num(value)
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

    def _send_to_gateway(self, ws_ipaddr, ws_port, cmd):
        """oeffnet jeweils einen neuen Socket und verschickt cmd; Rueckmeldung = Rueckmeldung der WS"""
        tries = 5                                                  # Anzahl der Versuche
        v = 0
        data = ""
        while data == "" and v <= tries:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            s.settimeout(self._udp_time_out)
            try:
                s.connect((self.gateway_ip, int(ws_port)))
                s.sendall(cmd)
                data, addr = s.recvfrom(11200)
                s.close()
            except:
                pass
            v += 1
        
        self.logger.debug(f"_send_to_gateway: raw data={data}")
        
        valuebytes = self._parse_response(data)
        return valuebytes

    def _weather_now(self, hpa, lang):
        arr = [
                ["stürmisch, Regen", "regnerisch", "wechselhaft", "sonnig", "trocken, Gewitter"],
                ["stormachtig, regen", "regenachtig", "veranderlijk", "zonnig", "droog, onweer"],
                ["orageux, pluie", "pluvieux", "changeable", "ensoleillé", "sec, orage"],
                ["tormentoso, lluvia", "lluvioso", "cambiable", "soleado", "seco, tormenta"],
                ["búrky, dážď", "daždivý", "premenlivý", "slnečno", "suchá, búrka"],
                ["stormy, rainy", "rainy", "unstable", "sunny", "dry, thunderstorm"]
          ]
        if lang == "DE": zeile = 0
        elif lang == "NL": zeile = 1
        elif lang == "FR": zeile = 2
        elif lang == "ES": zeile = 3
        elif lang == "SK": zeile = 4
        else: zeile = 5                                        # defaults to english

        if hpa <= 980:              wnowlvl = 0                # stürmisch, Regen
        elif 980 < hpa <= 1000:     wnowlvl = 1                # regnerisch
        elif 1000 < hpa <= 1020:    wnowlvl = 2                # wechselhaft
        elif 1020 < hpa <= 1040:    wnowlvl = 3                # sonnig
        elif hpa > 1040:            wnowlvl = 4                # trocken, Gewitter

        wnowtxt = arr[zeile][wnowlvl]
        return wnowlvl,wnowtxt

    def _check_battery(self, dictionary):
        # check known sensors if battery is still ok; if not fill outstring with comma-separated list of sensor names
        # 2do: tf_batt und leaf_batt noch nicht sicher, wie dargestellt - vermutlich in V
        # Ambient macht ausschliesslich 0/1 wobei 1 = ok und 0 = low
        is_ambient_weather = self._check_ambient_weather(dictionary)
        outstr = ""
        for key, value in dictionary.items():
            if is_ambient_weather and ("batt" in key or "batleak" in key) and int(value) == 0:
                outstr += key + " "
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

        batterycheck = outstr.strip()
        # self.logger.debug(f"batterycheck: {batterycheck}")

        if batterycheck != "":
            if not self.battery_warning:
                self.logger.warning(f"<WARNING> battery level for sensor(s) {batterycheck} is critical - please swap battery")
                self.battery_warning = True
            elif self.battery_warning:
                self.logger.info("<OK> battery level for all sensors is ok again")
                self.battery_warning = False
        return batterycheck

    def _check_ambient_weather(self, dictionary):
        # q&d check if input is coming from Ambient Weather station
        return True if "AMBWeather" in str(dictionary) else False

    def __f_to_c(self, f, n):                                           # convert Fahrenheit to Celsius
        out = "-9999"
        try:
            out = str(round((float(f)-32)*5/9.0, n))
        except ValueError:
            pass
        return out

    def __c_to_f(self, c, n):                                           # convert Celsius to Fahrenheit
        out = "-9999"
        try:
            out = str(round((float(c)*9/5.0) + 32, n))
        except ValueError:
            pass
        return out

    def __mph_to_kmh(self, f, n):                                       # convert mph to kmh
        return str(round(float(f)/0.621371, n))

    def __mph_to_ms(self, f, n):                                        # convert mph to m/s
        return str(round(float(f)/0.621371*1000/3600, n))

    def __in_to_hpa(self, f, n):                                        # convert inHg to HPa
        return str(round(float(f)/0.02953, n))

    def __hpa_to_in(self, f, n):                                        # convert HPa to inHg
        return str(round(float(f)/33.87, n))

    def __in_to_mm(self, f, n):                                         # convert in to mm
        return str(round(float(f)/0.0393701, n))

    def __kmh_to_kts(self, f, n):                                       # convert km/h to
        out = "null"
        try:
            out = str(round((float(f))/1.852, n))
        except ValueError:
            pass
        return out

    def __kmh_to_mph(self, f, n):                                       # convert kmh to mph
        return str(round(float(f)/1.609, n))

    def __mm_to_in(self, f, n):                                         # convert mm to in
        return str(round(float(f)/25.4, n))

    def __feet_to_m(self, f, n):                                        # convert feet to m
        return str(round(float(f)/3.281, n))

    def __m_to_feet(self, f, n):                                        # convert m to feet
        return str(round(float(f)*3.281, n))

    def __utc_to_local(self, utctime):
        offset = (-1*time.timezone)                                    # Zeitzone ausgleichen
        if time.localtime(utctime)[8]:
            offset = offset + 3600  # Sommerzeit hinzu
        localtime = utctime + offset
        return localtime

    def __dec_hour_to_hm_str(self, sh):                                 # convert dec. hour to h:m
        f_sh = float(sh)
        sh_std = int(f_sh)
        sh_min = round((f_sh-int(f_sh))*60)
        return str(sh_std)+":"+str(sh_min)

    def __arr_to_hex_orig(self, a):
        s = ""
        for i in range(len(a)):
            z = str(hex(a[i]))
            s += z[:2]+"0"+z[2:] + " " if len(z) < 4 else z + " "
        return s

    def __crc_sum(self, data):
        summe = 0
        for i in range(2, len(data)-1):
            summe = summe + data[i]
        return summe % 256
        
    def __calc_checksum(self, packet):
        '''
        Calculate checksum packets

        :parameter packet: Data packet for which to calculate checksum
        :type packet: bytearray
        :return: Calculated checksum
        :rtype: int
        '''
        checksum = 0
        if len(packet) > 0:
            if packet[:2] == b'\xff\xff':
                packet = packet[2:]
                checksum = sum(packet)
                checksum = checksum - int(checksum / 256) * 256
            else:
                self.logger.error('bytes to calculate checksum from not starting with header bytes')
        else:
            self.logger.error('No bytes received to calculate checksum')
        return checksum
        
    def calc_checksum(self, data):
        """Calculate the checksum for a GW1000/GW1100 API call or response.

        The checksum used on the GW1000/GW1100 responses is simply the LSB of the sum of the bytes.

        data: The data on which the checksum is to be calculated. Byte string.

        Returns the checksum as an integer.
        """

        checksum = 0
        for b in data:
            checksum += b
        # we are only interested in the least significant byte
        return checksum % 256

    def __version_string_to_num(self, s):
        try:
            vpos = s.index("V")+1
            return int(s[vpos:].replace(".", ""))
        except ValueError:
            return

    def __avg_wind(self, deque, w):                                     # get avg from deque d, field w
        # self.logger.debug(f"__avg_wind: d={deque}, w={w}")
        s = 0
        if deque is None:
            return
        l = len(deque)
        for i in range(l):
            s = s + deque[i][w]
        a = round(s/l, 1)
        return a

    def __max_wind(self, d, w):                                         # get max value from deque d, field w
        s = 0
        l = len(d)
        for i in range(l):
            if d[i][w] > s: s = d[i][w]
        a = round(s,1)
        return a
        
    def __build_send_packet(self, cmd, valuebytes=None):
        packet = bytearray()
        packet.extend(self.__int2bytes(self._commandset['header'], 1))        # HEADER: Fixed header: 2 bytes, header is fixed as 0xffff
        packet.extend(self.__int2bytes(self._commandset['header'], 1))        # HEADER: Fixed header: 2 bytes, header is fixed as 0xffff
        packet.extend(self.__int2bytes(cmd, 1))                               # CMD: 1 byte, Command 
        packet.extend(self.__int2bytes(len(packet), 1))                       # SIZE: 1 byte, packet size，counted from CMD till CHECKSUM
        if valuebytes is not None:                                            # Valuebytes
            packet.extend(valuebytes)
            packet[3] = len(packet) - 1                                       # Korrektur der Nachrichtenlänge (size)
        packet.extend(self.__int2bytes(self.__calc_checksum(packet), 1))      # CHECKSUM: 1 byte, CHECKSUM=CMD+SIZE+DATA1+DATA2+…+DATAn
        # self.logger.debug(f"__build_send_packet: {self.__bytes2hexstring(packet)}")
        # self.logger.debug(f"__build_send_packet: {packet}")
        return packet
        
    def __int2bytes(self, value, length, signed=False):
        '''
        Convert value to bytearray with respect to defined length and sign format.
        Value exceeding limit set by length and sign will be truncated

        :parameter value: Value to convert
        :type value: int
        :parameter length: number of bytes to create
        :type length: int
        :parameter signed: True if result should be a signed int, False for unsigned
        :type signed: bool
        :return: Converted value
        :rtype: bytearray
        '''
        value = value % (2 ** (length * 8))
        return value.to_bytes(length, byteorder='big', signed=signed)
        
    def __bytes2hexstring(self, bytesvalue):
        '''
        Create hex-formatted string from bytearray
        :param bytesvalue: Bytes to convert
        :type bytesvalue: bytearray
        :return: Converted hex string
        :rtype: str
        '''
        return ''.join(f'{c:02x}' for c in bytesvalue)
        
    def __bytes_to_hex(self, iterable, separator=' ', caps=True):
        """Produce a hex string representation of a sequence of bytes."""

        # assume 'iterable' can be iterated by iterbytes and the individual elements can be formatted with {:02X}
        format_str = "{:02X}" if caps else "{:02x}"
        try:
            # most likely we are running python3 and iterable is not a bytestring, try again concercing iterable to a bytestring
            return separator.join(format_str.format(c) for c in iterable)
        except (TypeError, AttributeError):
            # TypeError - 'iterable' is not iterable
            # AttributeError - likely because separator is None
            # either way we can't represent as a string of hex bytes
            return "cannot represent '%s' as hexadecimal bytes" % (iterable,)
    
            
    def __batt_binary(self, batt):
        """Decode a binary battery state.
        Battery state is stored in bit 0 as either 0 or 1. If 1 the battery
        is low, if 0 the battery is normal. We need to mask off bits 1 to 7 as
        they are not guaranteed to be set in any particular way.
        """
        return batt & 1

    def __batt_int(self, batt):
        """Decode a integer battery state.
        According to the API documentation battery state is stored as an
        integer from 0 to 5 with <=1 being considered low. Experience with
        WH43 has shown that battery state 6 also exists when the device is
        run from DC. This does not appear to be documented in the API
        documentation.
        """
        return batt

    def __batt_volt(self, batt):
        """Decode a voltage battery state in 2mV increments.
        Battery state is stored as integer values of battery voltage/0.02
        with <=1.2V considered low.
        """
        return round(0.02 * batt, 2)

    def __batt_volt_tenth(self, batt):
        """Decode a voltage battery state in 100mV increments.
        Battery state is stored as integer values of battery voltage/0.1
        with <=1.2V considered low.
        """
        return round(0.1 * batt, 1)
        
    def __decode_utc(self, data, field=None):
        """Decode UTC time.

        The GW1000/GW1100 API claims to provide 'UTC time' as a 4 byte big
        endian integer. The 4 byte integer is a unix epoch timestamp;
        however, the timestamp is offset by the stations timezone. So for a
        station in the +10 hour timezone, the timestamp returned is the
        present epoch timestamp plus 10 * 3600 seconds.

        When decoded in localtime the decoded date-time is off by the
        station time zone, when decoded as GMT the date and time figures
        are correct but the timezone is incorrect.

        In any case decode the 4 byte big endian integer as is and any
        further use of this timestamp needs to take the above time zone
        offset into account when using the timestamp.
        """

        if len(data) == 4:
            # unpack the 4 byte int
            value = struct.unpack(">L", data)[0]
            # when processing the last lightning strike time if the value
            # is 0xFFFFFFFF it means we have never seen a strike so return
            # None
            value = value if value != 0xFFFFFFFF else None
        else:
            value = None
        if field is not None:
            return {field: value}
        else:
            return value
            
    def decode_temp(self, data, field=None):
        """Decode temperature data.

        Data is contained in a two byte big endian signed integer and
        represents tenths of a degree.
        """

        if len(data) == 2:
            value = struct.unpack(">h", data)[0] / 10.0
        else:
            value = None
        if field is not None:
            return {field: value}
        else:
            return value

    def decode_humid(self, data, field=None):
        """Decode humidity data.

        Data is contained in a single unsigned byte and represents whole
        units.
        """

        if len(data) == 1:
            value = struct.unpack("B", data)[0]
        else:
            value = None
        if field is not None:
            return {field: value}
        else:
            return value

    def decode_press(self, data, field=None):
        """Decode pressure data.

        Data is contained in a two byte big endian integer and represents
        tenths of a unit.
        """

        if len(data) == 2:
            value = struct.unpack(">H", data)[0] / 10.0
        else:
            value = None
        if field is not None:
            return {field: value}
        else:
            return value

    def decode_dir(self, data, field=None):
        """Decode direction data.

        Data is contained in a two byte big endian integer and represents
        whole degrees.
        """

        if len(data) == 2:
            value = struct.unpack(">H", data)[0]
        else:
            value = None
        if field is not None:
            return {field: value}
        else:
            return value

    def decode_big_rain(self, data, field=None):
        """Decode 4 byte rain data.

        Data is contained in a four byte big endian integer and represents
        tenths of a unit.
        """

        if len(data) == 4:
            value = struct.unpack(">L", data)[0] / 10.0
        else:
            value = None
        if field is not None:
            return {field: value}
        else:
            return value

    def decode_datetime(self, data, field=None):
        """Decode date-time data.

        Unknown format but length is six bytes.
        """

        if len(data) == 6:
            value = struct.unpack("BBBBBB", data)
        else:
            value = None
        if field is not None:
            return {field: value}
        else:
            return value

    def decode_distance(self, data, field=None):
        """Decode lightning distance.

        Data is contained in a single byte integer and represents a value
        from 0 to 40km.
        """

        if len(data) == 1:
            value = struct.unpack("B", data)[0]
            value = value if value <= 40 else None
        else:
            value = None
        if field is not None:
            return {field: value}
        else:
            return value
            
    def decode_count(self, data, field=None):
        """Decode lightning count.

        Count is an integer stored in a 4 byte big endian integer."""

        if len(data) == 4:
            value = struct.unpack(">L", data)[0]
        else:
            value = None
        if field is not None:
            return {field: value}
        else:
            return value

    # alias' for other decodes
    decode_speed = decode_press
    decode_rain = decode_press
    decode_rainrate = decode_press
    decode_light = decode_big_rain
    decode_uv = decode_press
    decode_uvi = decode_humid
    decode_moist = decode_humid
    decode_pm25 = decode_press
    decode_leak = decode_humid
    decode_pm10 = decode_press
    decode_co2 = decode_dir
    decode_wet = decode_humid

    def decode_wh34(self, data, field=None):
        """Decode WH34 sensor data.

        Data consists of three bytes:

        Byte    Field               Comments
        1-2     temperature         standard Ecowitt temperature data, two
                                    byte big endian signed integer
                                    representing tenths of a degree
        3       battery voltage     0.02 * value Volts
        """

        if len(data) == 3 and field is not None:
            results = dict()
            results[field] = self.decode_temp(data[0:2])
            # we could decode the battery voltage but we will be obtaining
            # battery voltage data from the sensor IDs in a later step so
            # we can skip it here
            return results
        return {}

    def decode_wh45(self, data, fields=None):
        """Decode WH45 sensor data.

        WH45 sensor data includes TH sensor values, CO2/PM2.5/PM10 sensor
        values and 24 hour aggregates and battery state data in 16 bytes.

        The 16 bytes of WH45 sensor data is allocated as follows:
        Byte(s) #      Data               Format          Comments
        bytes   1-2    temperature        short           C x10
                3      humidity           unsigned byte   percent
                4-5    PM10               unsigned short  ug/m3 x10
                6-7    PM10 24hour avg    unsigned short  ug/m3 x10
                8-9    PM2.5              unsigned short  ug/m3 x10
                10-11  PM2.5 24 hour avg  unsigned short  ug/m3 x10
                12-13  CO2                unsigned short  ppm
                14-15  CO2 24 our avg     unsigned short  ppm
                16     battery state      unsigned byte   0-5 <=1 is low
        """

        if len(data) == 16 and fields is not None:
            results = dict()
            results[fields[0]] = self.decode_temp(data[0:2])
            results[fields[1]] = self.decode_humid(data[2:3])
            results[fields[2]] = self.decode_pm10(data[3:5])
            results[fields[3]] = self.decode_pm10(data[5:7])
            results[fields[4]] = self.decode_pm25(data[7:9])
            results[fields[5]] = self.decode_pm25(data[9:11])
            results[fields[6]] = self.decode_co2(data[11:13])
            results[fields[7]] = self.decode_co2(data[13:15])
            # we could decode the battery state but we will be obtaining
            # battery state data from the sensor IDs in a later step so
            # we can skip it here
            return results
        return {}
        
    class CollectorThread(threading.Thread):
        """Class used to collect data via the GW1000/GW1100 API in a thread."""

        def __init__(self, client):
            # initialise our parent
            threading.Thread.__init__(self)
            # keep reference to the client we are supporting
            self.client = client
            self.name = 'gw1000-collector'

        def run(self):
            # rather than letting the thread silently fail if an exception
            # occurs within the thread, wrap in a try..except so the exception
            # can be caught and available exception information displayed
            try:
                # kick the collection off
                self.client.collect_sensor_data()
            except:
                # we have an exception so log what we can
                log_traceback_critical('    ****  ')

    class Station(object):
        """Class to interact directly with the GW1000/GW1100 API.

        A Station object knows how to:
        1.  discover a GW1000/GW1100 via UDP broadcast
        2.  send a command to the GW1000/GW1100 API
        3.  receive a response from the GW1000/GW1100 API
        4.  verify the response as valid

        A Station object needs an IP address and port as well as a network broadcast address and port.
        """

        # GW1000/GW1100 API commands
        commands = {
            'CMD_WRITE_SSID': b'\x11',
            'CMD_BROADCAST': b'\x12',
            'CMD_READ_ECOWITT': b'\x1E',
            'CMD_WRITE_ECOWITT': b'\x1F',
            'CMD_READ_WUNDERGROUND': b'\x20',
            'CMD_WRITE_WUNDERGROUND': b'\x21',
            'CMD_READ_WOW': b'\x22',
            'CMD_WRITE_WOW': b'\x23',
            'CMD_READ_WEATHERCLOUD': b'\x24',
            'CMD_WRITE_WEATHERCLOUD': b'\x25',
            'CMD_READ_STATION_MAC': b'\x26',
            'CMD_GW1000_LIVEDATA': b'\x27',
            'CMD_GET_SOILHUMIAD': b'\x28',
            'CMD_SET_SOILHUMIAD': b'\x29',
            'CMD_READ_CUSTOMIZED': b'\x2A',
            'CMD_WRITE_CUSTOMIZED': b'\x2B',
            'CMD_GET_MulCH_OFFSET': b'\x2C',
            'CMD_SET_MulCH_OFFSET': b'\x2D',
            'CMD_GET_PM25_OFFSET': b'\x2E',
            'CMD_SET_PM25_OFFSET': b'\x2F',
            'CMD_READ_SSSS': b'\x30',
            'CMD_WRITE_SSSS': b'\x31',
            'CMD_READ_RAINDATA': b'\x34',
            'CMD_WRITE_RAINDATA': b'\x35',
            'CMD_READ_GAIN': b'\x36',
            'CMD_WRITE_GAIN': b'\x37',
            'CMD_READ_CALIBRATION': b'\x38',
            'CMD_WRITE_CALIBRATION': b'\x39',
            'CMD_READ_SENSOR_ID': b'\x3A',
            'CMD_WRITE_SENSOR_ID': b'\x3B',
            'CMD_READ_SENSOR_ID_NEW': b'\x3C',
            'CMD_WRITE_REBOOT': b'\x40',
            'CMD_WRITE_RESET': b'\x41',
            'CMD_WRITE_UPDATE': b'\x43',
            'CMD_READ_FIRMWARE_VERSION': b'\x50',
            'CMD_READ_USR_PATH': b'\x51',
            'CMD_WRITE_USR_PATH': b'\x52',
            'CMD_GET_CO2_OFFSET': b'\x53',
            'CMD_SET_CO2_OFFSET': b'\x54'
        }
        # header used in each API command and response packet
        header = b'\xff\xff'
        # known device models
        known_models = ('GW1000', 'GW1100')
        
        def __init__(self, ip_address=None, port=None, broadcast_address=None, broadcast_port=None, socket_timeout=None, broadcast_timeout=None, max_tries=self._default_max_tries, retry_wait=self._default_retry_wait, mac=None, lost_contact_log_period=None):
            
            # network broadcast address
            self.broadcast_address = broadcast_address if broadcast_address is not None else default_broadcast_address
            # network broadcast port
            self.broadcast_port = broadcast_port if broadcast_port is not None else self._default_broadcast_port
            self.socket_timeout = socket_timeout if socket_timeout is not None else self._default_socket_timeout
            self.broadcast_timeout = broadcast_timeout if broadcast_timeout is not None else self._default_broadcast_timeout

            # initialise flags to indicate if IP address or port were discovered
            self.ip_discovered = ip_address is None
            self.port_discovered = port is None
            # if IP address or port was not specified (None) then attempt to discover the GW1000/GW1100 with a UDP broadcast
            if ip_address is None or port is None:
                for attempt in range(max_tries):
                    try:
                        # discover devices on the local network, the result is a list of dicts in IP address order with each dict containing data for a unique discovered device
                        device_list = self.discover()
                    except socket.error as e:
                        self.logger.error(f"Unable to detect device IP address and port: {e} {type(e)}")
                        # signal that we have a critical error
                        raise
                    else:
                        # did we find any GW1000/GW1100
                        if len(device_list) > 0:
                            # we have at least one, arbitrarily choose the first one found as the one to use
                            disc_ip = device_list[0]['ip_address']
                            disc_port = device_list[0]['port']
                            # log the fact as well as what we found
                            gw1000_str = ', '.join([':'.join(['%s:%d' % (d['ip_address'], d['port'])]) for d in device_list])
                            if len(device_list) == 1:
                                stem = f"{device_list[0]['model']} was"
                            else:
                                stem = "Multiple devices were"
                            self.logger.info(f"{stem} found at {gw1000_str}")
                            ip_address = disc_ip if ip_address is None else ip_address
                            port = disc_port if port is None else port
                            break
                        else:
                            # did not discover any GW1000/GW1100 so log it
                            self.logger.debug(f"Failed attempt {attempt + 1} to detect device IP address and/or port")
                            # do we try again or raise an exception
                            if attempt < max_tries - 1:
                                # we still have at least one more try left so sleep
                                # and try again
                                time.sleep(retry_wait)
                            else:
                                # we've used all our tries, log it and raise an exception
                                _msg = f"Failed to detect device IP address and/or port after {attempt + 1} attempts"
                                self.logger.error(_msg)
                                raise GW1000IOError(_msg)
            # set our ip_address property but encode it first, it saves doing it repeatedly later
            self.gateway_ip = ip_address.encode()
            self.gateway_port = port
            self.max_tries = max_tries
            self.retry_wait = retry_wait
            # get my GW1000/GW1100 MAC address to use later if we have to rediscover
            self.gateway_mac = device_list[0]['mac']
            # get my device model
            try:
                _firmware_b = self.get_firmware_version()
            except GW1000IOError:
                self.model = None
            else:
                _firmware_t = struct.unpack("B" * len(_firmware_b), _firmware_b)
                _firmware_str = "".join([chr(x) for x in _firmware_t[5:5 + _firmware_t[4]]])
                self.model = self.get_model_from_firmware(_firmware_str)

        def discover(self):
            """Discover any GW1000/GW1100 devices on the local network.

            Send a UDP broadcast and check for replies. Decode each reply to obtain details of any devices on the local network. Create a dict
            of details for each device including a derived model name. Construct a list of dicts with details of unique (MAC address)
            devices that responded. When complete return the list of devices found.
            """

            # create a socket object so we can broadcast to the network via # IPv4 UDP
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            # set socket datagram to broadcast
            s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            # set timeout
            s.settimeout(self.broadcast_timeout)
            # set TTL to 1 to so messages do not go past the local network segment
            ttl = struct.pack('b', 1)
            s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, ttl)
            # construct the packet to broadcast
            packet = self.build_cmd_packet('CMD_BROADCAST')
            self.logger.debug("Sending broadcast packet '%s' to '%s:%d'" % (bytes_to_hex(packet), self.broadcast_address, self.broadcast_port))
            # initialise a list for the results as multiple GW1000/GW1100 may respond
            result_list = []
            # send the Broadcast command
            s.sendto(packet, (self._broadcast_address, self._broadcast_port))
            # obtain any responses
            while True:
                try:
                    response = s.recv(1024)
                    # log the response if debug is high enough
                    self.logger.debug("Received broadcast response '%s'" % (bytes_to_hex(response),))
                except socket.timeout:
                    # if we timeout then we are done
                    break
                except socket.error:
                    # raise any other socket error
                    raise
                else:
                    # check the response is valid
                    try:
                        self.check_response(response, self.commands['CMD_BROADCAST'])
                    except (InvalidChecksum, InvalidApiResponse) as e:
                        # the response was not valid, log it and attempt again if we haven't had too many attempts already
                        self.logger.debug("Invalid response to command '%s': %s" % ('CMD_BROADCAST', e))
                    except Exception as e:
                        # Some other error occurred in check_response(),
                        # perhaps the response was malformed. Log the stack
                        # trace but continue.
                        self.logger.error("Unexpected exception occurred while checking response to command '%s': %s" % ('CMD_BROADCAST', e))
                    else:
                        # we have a valid response so decode the response and obtain a dict of device data
                        device = self.decode_broadcast_response(response)
                        # if we haven't seen this MAC before attempt to obtain and save the device model then add the device to our results list
                        if not any((d['mac'] == device['mac']) for d in result_list):
                            # determine the device model based on the device SSID and add the model to the device dict
                            device['model'] = self.get_model_from_ssid(device.get('ssid'))
                            # append the device to our list
                            result_list.append(device)
            # close our socket
            s.close()
            # now return our results
            return result_list

        @staticmethod
        def decode_broadcast_response(raw_data):
            """Decode a broadcast response and return the results as a dict.

            A GW1000/GW1100 response to a CMD_BROADCAST API command consists of a number of control structures around a payload of a data. 
            The API response is structured as follows:
                bytes 0-1 incl                  preamble, literal 0xFF 0xFF
                byte 2                          literal value 0x12
                bytes 3-4 incl                  payload size (big endian short integer)
                bytes 5-5+payload size incl     data payload (details below)
                byte 6+payload size             checksum

            The data payload is structured as follows:
                bytes 0-5 incl      GW1000/GW1100 MAC address
                bytes 6-9 incl      GW1000/GW1100 IP address
                bytes 10-11 incl    GW1000/GW1100 port number
                bytes 11-           GW1000/GW1100 AP SSID

            Note: The GW1000/GW1100 AP SSID for a given GW1000/GW1100 is fixed in size but this size can vary from device to device and across firmware versions.

            There also seems to be a peculiarity in the CMD_BROADCAST response  data payload whereby the first character of the GW1000/GW1100 AP SSID is a non-printable 
            ASCII character. The WS View app appears to ignore or not display this character nor does it appear to be used elsewhere. Consequently this character is ignored.

            raw_data:   a bytestring containing a validated (structure and checksum verified) raw data response to the CMD_BROADCAST API command

            Returns a dict with decoded data keyed as follows:
                'mac':          GW1000/GW1100 MAC address (string)
                'ip_address':   GW1000/GW1100 IP address (string)
                'port':         GW1000/GW1100 port number (integer)
                'ssid':         GW1000/GW1100 AP SSID (string)
            """

            # obtain the response size, it's a big endian short (two byte) integer
            resp_size = struct.unpack('>H', raw_data[3:5])[0]
            # now extract the actual data payload
            data = raw_data[5:resp_size + 2]
            # initialise a dict to hold our result
            data_dict = dict()
            # extract and decode the MAC address
            data_dict['mac'] = bytes_to_hex(data[0:6], separator=":")
            # extract and decode the IP address
            data_dict['ip_address'] = '%d.%d.%d.%d' % struct.unpack('>BBBB', data[6:10])
            # extract and decode the port number
            data_dict['port'] = struct.unpack('>H', data[10: 12])[0]
            # get the SSID as a bytestring
            ssid_b = data[13:]
            # create a format string so the SSID string can be unpacked into its bytes, remember the length can vary
            ssid_format = "B" * len(ssid_b)
            # unpack the SSID bytestring, we now have a tuple of integers representing each of the bytes
            ssid_t = struct.unpack(ssid_format, ssid_b)
            # convert the sequence of bytes to unicode characters and assemble as a string and return the result
            data_dict['ssid'] = "".join([chr(x) for x in ssid_t])
            # return the result dict
            return data_dict

        def get_model_from_firmware(self, firmware_string):
            """Determine the device model from the firmware version.

            To date GW1000 and GW1100 firmware versions have included the device model in the firmware version string returned via the device
            API. Whilst this is not guaranteed to be the case for future firmware releases, in the absence of any other direct means of
            obtaining the device model number it is a useful means for determining the device model.

            The check is a simple check to see if the model name is contained in the firmware version string returned by the device API.

            If a known model is found in the firmware version string the model is returned as a string. None is returned if (1) the firmware
            string is None or (2) a known model is not found in the firmware version string.
            """

            # do we have a firmware string
            if firmware_string is not None:
                # we have a firmware string so look for a known model in the string and return the result
                return self.get_model(firmware_string)
            else:
                # for some reason we have no firmware string, so return None
                return None

        def get_model_from_ssid(self, ssid_string):
            """Determine the device model from the device SSID.

            To date the GW1000 and GW1100 device SSID has included the device model in the SSID returned via the device API. Whilst this is not
            guaranteed to be the case for future firmware releases, in the absence of any other direct means of obtaining the device model
            number it is a useful means for determining the device model. This is particularly the case when using UDP broadcast to discover
            devices on the local network.

            Note that it may be possible to alter the SSID used by the device in which case this method may not provide an accurate result.
            However, as the device SSID is only used during initial device configuration and since altering the device SSID is not a normal
            part of the initial device configuration, this method of determining the device model is considered adequate for use during
            discovery by UDP broadcast.

            The check is a simple check to see if the model name is contained in the SSID returned by the device API.

            If a known model is found in the SSID the model is returned as a string. None is returned if (1) the SSID is None or (2) a known
            model is not found in the SSID.
            """

            return self.get_model(ssid_string)

        def get_model(self, t):
            """Determine the device model from a string.

            To date GW1000 and GW1100 firmware versions have included the device model in the firmware version string or the device SSID.
            Both the firmware version string and device SSID are available via the device API so checking the firmware version string or SSID
            provides a de facto method of determining the device model.

            This method uses a simple check to see if a known model name is contained in the string concerned.

            Known model strings are contained in a tuple Station.known_models.

            If a known model is found in the string the model is returned as a string. None is returned if a known model is not found in the string.
            """

            # do we have a string to check
            if t is not None:
                # we have a string, now do we have a know model in the string, if so return the model string
                for model in self.known_models:
                    if model in t.upper():
                        return model
                # we don't have a known model so return None
                return None
            else:
                # we have no string so return None
                return None

        def get_livedata(self):
            """Get GW1000/GW1100 live data.

            Sends the command to obtain live data from the GW1000/GW1100 to the API with retries. If the GW1000/GW1100 cannot be contacted
            re-discovery is attempted. If rediscovery is successful the command is tried again otherwise the lost contact timestamp is set and the
            exception raised. Any code that calls this method should be
            prepared to handle a GW1000IOError exception.
            """

            # send the API command to obtain live data from the GW1000/GW1100, be prepared to catch the exception raised if the GW1000/GW1100 cannot be contacted
            try:
                # return the validated API response
                return self.send_cmd_with_retries('CMD_GW1000_LIVEDATA')
            except GW1000IOError:
                # there was a problem contacting the GW1000/GW1100, it could be it has changed IP address so attempt to rediscover
                if not self.rediscover():
                    # we could not re-discover so raise the exception
                    raise
                else:
                    # we did rediscover successfully so try again, if it fails we get another GW1000IOError exception which will be raised
                    return self.send_cmd_with_retries('CMD_GW1000_LIVEDATA')

        def get_raindata(self):
            """Get GW1000/GW1100 rain data.

            Sends the command to obtain rain data from the GW10GW1000/GW110000 to the API with retries. If the GW1000/GW1100 cannot be contacted a
            GW1000IOError will have been raised by send_cmd_with_retries() which will be passed through by get_raindata(). Any code calling
            get_raindata() should be prepared to handle this exception.
            """

            return self.send_cmd_with_retries('CMD_READ_RAINDATA')

        def get_system_params(self):
            """Read GW1000/GW1100 system parameters.

            Sends the command to obtain system parameters from the GW1000/GW1100 to the API with retries. If the GW1000/GW1100 cannot
            be contacted a GW1000IOError will have been raised by send_cmd_with_retries() which will be passed through by
            get_system_params(). Any code calling get_system_params() should be prepared to handle this exception.
            """

            return self.send_cmd_with_retries('CMD_READ_SSSS')

        def get_ecowitt_net_params(self):
            """Get GW1000/GW1100 Ecowitt.net parameters.

            Sends the command to obtain the GW1000/GW1100 Ecowitt.net  parameters to the API with retries. If the GW1000/GW1100 cannot be
            contacted a GW1000IOError will have been raised by send_cmd_with_retries() which will be passed through by
            get_ecowitt_net_params(). Any code calling get_ecowitt_net_params() should be prepared to handle this exception.
            """

            return self.send_cmd_with_retries('CMD_READ_ECOWITT')

        def get_wunderground_params(self):
            """Get GW1000 Weather Underground parameters.

            Sends the command to obtain the GW1000/GW1100 Weather Underground parameters to the API with retries. If the GW1000/GW1100 cannot be
            contacted a GW1000IOError will have been raised by send_cmd_with_retries() which will be passed through by
            get_wunderground_params(). Any code calling get_wunderground_params() should be prepared to handle this
            exception.
            """

            return self.send_cmd_with_retries('CMD_READ_WUNDERGROUND')

        def get_weathercloud_params(self):
            """Get GW1000/GW1100 Weathercloud parameters.

            Sends the command to obtain the GW1000/GW1100 Weathercloud parameters to the API with retries. If the GW1000/GW1100 cannot be
            contacted a GW1000IOError will have been raised by send_cmd_with_retries() which will be passed through by
            get_weathercloud_params(). Any code calling get_weathercloud_params() should be prepared to handle this exception.
            """

            return self.send_cmd_with_retries('CMD_READ_WEATHERCLOUD')

        def get_wow_params(self):
            """Get GW1000/GW1100 Weather Observations Website parameters.

            Sends the command to obtain the GW1000/GW1100 Weather Observations Website parameters to the API with retries. If the GW1000/GW1100
            cannot be contacted a GW1000IOError will have been raised by send_cmd_with_retries() which will be passed through by
            get_wow_params(). Any code calling get_wow_params() should be prepared to handle this exception.
            """

            return self.send_cmd_with_retries('CMD_READ_WOW')

        def get_custom_params(self):
            """Get GW1000/GW1100 custom server parameters.

            Sends the command to obtain the GW1000/GW1100 custom server parameters to the API with retries. If the GW1000/GW1100 cannot be
            contacted a GW1000IOError will have been raised by send_cmd_with_retries() which will be passed through by
            get_custom_params(). Any code calling get_custom_params() should be prepared to handle this exception.
            """

            return self.send_cmd_with_retries('CMD_READ_CUSTOMIZED')

        def get_usr_path(self):
            """Get GW1000/GW1100 user defined custom path.

            Sends the command to obtain the GW1000/GW1100 user defined custom path to the API with retries. If the GW1000/GW1100 cannot be
            contacted a GW1000IOError will have been raised by send_cmd_with_retries() which will be passed through by
            get_usr_path(). Any code calling get_usr_path() should be prepared to handle this exception.
            """

            return self.send_cmd_with_retries('CMD_READ_USR_PATH')

        def get_mac_address(self):
            """Get GW1000/GW1100 MAC address.

            Sends the command to obtain the GW1000/GW1100 MAC address to the API with retries. If the GW1000/GW1100 cannot be contacted a
            GW1000IOError will have been raised by send_cmd_with_retries() which will be passed through by get_mac_address(). Any code calling
            get_mac_address() should be prepared to handle this exception.
            """

            return self.send_cmd_with_retries('CMD_READ_STATION_MAC')

        def get_firmware_version(self):
            """Get GW1000/GW1100 firmware version.

            Sends the command to obtain GW1000/GW1100 firmware version to the API with retries. If the GW1000/GW1100 cannot be contacted a
            GW1000IOError will have been raised by send_cmd_with_retries() which will be passed through by get_firmware_version(). Any code
            calling get_firmware_version() should be prepared to handle this exception.
            """

            return self.send_cmd_with_retries('CMD_READ_FIRMWARE_VERSION')

        def get_sensor_id(self):
            """Get GW1000/GW1100 sensor ID data.

            Sends the command to obtain sensor ID data from the GW1000/GW1100 to the API with retries. If the GW1000/GW1100 cannot be contacted
            re-discovery is attempted. If rediscovery is successful the command is tried again otherwise the lost contact timestamp is set and the
            exception raised. Any code that calls this method should be prepared to handle a GW1000IOError exception.
            """

            # send the API command to obtain sensor ID data from the GW1000/GW1100, be prepared to catch the exception raised if the GW1000/GW1100 cannot be contacted
            try:
                return self.send_cmd_with_retries('CMD_READ_SENSOR_ID_NEW')
            except GW1000IOError:
                # there was a problem contacting the GW1000/GW1100, it could be it has changed IP address so attempt to rediscover
                if not self.rediscover():
                    # we could not re-discover so raise the exception
                    raise
                else:
                    # we did rediscover successfully so try again, if it fails we get another GW1000IOError exception which will be raised
                    return self.send_cmd_with_retries('CMD_READ_SENSOR_ID_NEW')

        def get_mulch_offset(self):
            """Get multi-channel temperature and humidity offset data.

            Sends the command to obtain the multi-channel temperature and humidity offset data to the API with retries. If the GW1000/GW1100
            cannot be contacted a GW1000IOError will have been raised by send_cmd_with_retries() which will be passed through by
            get_mulch_offset(). Any code calling get_mulch_offset() should be prepared to handle this exception.
            """

            return self.send_cmd_with_retries('CMD_GET_MulCH_OFFSET')

        def get_pm25_offset(self):
            """Get PM2.5 offset data.

            Sends the command to obtain the PM2.5 sensor offset data to the API with retries. If the GW1000/GW1100 cannot be contacted a
            GW1000IOError will have been raised by send_cmd_with_retries() which will be passed through by get_pm25_offset(). Any code
            calling get_pm25_offset() should be prepared to handle this exception.
            """

            return self.send_cmd_with_retries('CMD_GET_PM25_OFFSET')

        def get_calibration_coefficient(self):
            """Get calibration coefficient data.

            Sends the command to obtain the calibration coefficient data to the API with retries. If the GW1000/GW1100 cannot be contacted a
            GW1000IOError will have been raised by send_cmd_with_retries() which will be passed through by get_calibration_coefficient(). Any
            code calling get_calibration_coefficient() should be prepared to handle this exception.
            """

            return self.send_cmd_with_retries('CMD_READ_GAIN')

        def get_soil_calibration(self):
            """Get soil moisture sensor calibration data.

            Sends the command to obtain the soil moisture sensor calibration data to the API with retries. If the GW1000/GW1100 cannot be
            contacted a GW1000IOError will have been raised by send_cmd_with_retries() which will be passed through by
            get_soil_calibration(). Any code calling get_soil_calibration() should be prepared to handle this exception.
            """

            return self.send_cmd_with_retries('CMD_GET_SOILHUMIAD')

        def get_offset_calibration(self):
            """Get offset calibration data.

            Sends the command to obtain the offset calibration data to the API with retries. If the GW1000/GW1100 cannot be contacted a
            GW1000IOError will have been raised by send_cmd_with_retries() which will be passed through by get_offset_calibration(). Any code
            calling get_offset_calibration() should be prepared to handle this exception.
            """

            return self.send_cmd_with_retries('CMD_READ_CALIBRATION')

        def get_co2_offset(self):
            """Get WH45 CO2, PM10 and PM2.5 offset data.

            Sends the command to obtain the WH45 CO2, PM10 and PM2.5 sensor offset data to the API with retries. If the GW1000/GW1100 cannot be
            contacted a GW1000IOError will have been raised by send_cmd_with_retries() which will be passed through by
            get_offset_calibration(). Any code calling get_offset_calibration() should be prepared to handle this exception.
            """

            return self.send_cmd_with_retries('CMD_GET_CO2_OFFSET')

        def send_cmd_with_retries(self, cmd, payload=b''):
            """Send a command to the GW1000/GW1100 API with retries and return the response.

            Send a command to the GW1000/GW1100 and obtain the response. If the the response is valid return the response. If the response is
            invalid an appropriate exception is raised and the command resent up to self.max_tries times after which the value None is returned.

            cmd: A string containing a valid GW1000/GW1100 API command, eg: 'CMD_READ_FIRMWARE_VERSION'
            payload: The data to be sent with the API command, byte string.

            Returns the response as a byte string or the value None.
            """

            # construct the message packet
            packet = self.build_cmd_packet(cmd, payload)
            # attempt to send up to 'self.max_tries' times
            for attempt in range(self.max_tries):
                response = None
                # wrap in  try..except so we can catch any errors
                try:
                    response = self.send_cmd(packet)
                except socket.timeout as e:
                    # a socket timeout occurred, log it
                    self.logger.debug("Failed to obtain response to attempt %d to send command '%s': %s" % (attempt + 1, cmd, e))
                except Exception as e:
                    # an exception was encountered, log it
                    self.logger.debug("Failed attempt %d to send command '%s': %s" % (attempt + 1, cmd, e))
                else:
                    # check the response is valid
                    try:
                        self.check_response(response, self.commands[cmd])
                    except (InvalidChecksum, InvalidApiResponse) as e:
                        # the response was not valid, log it and attempt again if we haven't had too many attempts already
                        self.logger.debug("Invalid response to attempt %d to send command '%s': %s" % (attempt + 1, cmd, e))
                    except Exception as e:
                        # Some other error occurred in check_response(),
                        # perhaps the response was malformed. Log the stack
                        # trace but continue.
                        self.logger.error("Unexpected exception occurred while checking response to attempt %d to send command '%s': %s" % (attempt + 1, cmd, e))
                    else:
                        # our response is valid so return it
                        return response
                # sleep before our next attempt, but skip the sleep if we have just made our last attempt
                if attempt < self.max_tries - 1:
                    time.sleep(self.retry_wait)
            # if we made it here we failed after self.max_tries attempts first of all log it
            _msg = ("Failed to obtain response to command '%s' after %d attempts" % (cmd, attempt + 1))
            if response is not None:
                self.logger.error(_msg)
            # finally raise a GW1000IOError exception
            raise GW1000IOError(_msg)

        def build_cmd_packet(self, cmd, payload=b''):
            """Construct an API command packet.

            A GW1000/GW1100 API command packet looks like: fixed header, command, size, data 1, data 2...data n, checksum

            where:
                fixed header is 2 bytes = 0xFFFF
                command is a 1 byte API command code
                size is 1 byte being the number of bytes of command to checksum
                data 1, data 2 ... data n is the data being transmitted and is
                    n bytes long
                checksum is a byte checksum of command + size + data 1 +
                    data 2 ... + data n

            cmd:     A string containing a valid GW1000/GW1100 API command, eg: 'CMD_READ_FIRMWARE_VERSION'
            payload: The data to be sent with the API command, byte string.

            Returns an API command packet as a bytestring.
            """

            # calculate size
            try:
                size = len(self.commands[cmd]) + 1 + len(payload) + 1
            except KeyError:
                raise UnknownCommand("Unknown API command '%s'" % (cmd,))
            # construct the portion of the message for which the checksum is calculated
            body = b''.join([self.commands[cmd], struct.pack('B', size), payload])
            # calculate the checksum
            checksum = self.calc_checksum(body)
            # return the constructed message packet
            return b''.join([self.header, body, struct.pack('B', checksum)])

        def send_cmd(self, packet):
            """Send a command to the GW1000/GW1100 API and return the response.

            Send a command to the GW1000/GW1100 and return the response. Socket related errors are trapped and raised, code calling send_cmd should
            be prepared to handle such exceptions.

            cmd: A valid GW1000/GW1100 API command

            Returns the response as a byte string.
            """

            # create a socket object for sending commands and broadcasting to the network
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            # set the socket timeout
            s.settimeout(self.socket_timeout)
            # wrap our connect in a try..except so we can catch any socket related exceptions
            try:
                # connect to the device
                s.connect((self.gateway_ip, self.gateway_port))
                # if required log the packet we are sending
                self.logger.debug("Sending packet '%s' to '%s:%d'" % (bytes_to_hex(packet), self.gateway_ip.decode(),self.gateway_port))
                # send the packet
                s.sendall(packet)
                # obtain the response, we assume here the response will be less than 1024 characters
                response = s.recv(1024)
                # if required log the response
                self.logger.debug("Received response '%s'" % (bytes_to_hex(response),))
                # return the response
                return response
            except socket.error:
                # we received a socket error, raise it
                raise
            finally:
                # make sure we close our socket
                s.close()

        def check_response(self, response, cmd_code):
            """Check the validity of a GW1000/GW1100 API response.

            Checks the validity of a GW1000/GW1100 API response. Two checks are performed:
                1.  the third byte of the response is the same as the command code used in the API call
                2.  the calculated checksum of the data in the response matches the checksum byte in the response

            If any check fails an appropriate exception is raised, if all checks pass the method exits without raising an exception.

            response: Response received from the GW1000/GW1100 API call. Byte string.
            cmd_code: Command code send to GW1000/GW1100 API. Byte string of length one.
            """

            # first check that the 3rd byte of the response is the command code that was issued
            if response[2] == __byte2int(cmd_code):
                # now check the checksum
                calc_checksum = self.calc_checksum(response[2:-1])
                resp_checksum = six.indexbytes(response, -1)
                if calc_checksum == resp_checksum:
                    # checksum check passed, response is deemed valid
                    return
                else:
                    # checksum check failed, raise an InvalidChecksum exception
                    _msg = f'Invalid checksum in API response. Calculated checksum {calc_checksum} does not match received checksum of {resp_checksum}! Ignoring response.'
                    raise InvalidChecksum(_msg)
            else:
                # command code check failed, raise an InvalidApiResponse exception
                _msg = f"CMD code of response {response[2]} does not match sent CMD code {bytes_to_int(cmd_code, False)}."
                raise InvalidApiResponse(_msg)

        @staticmethod
        def calc_checksum(data):
            """Calculate the checksum for a GW1000/GW1100 API call or response.

            The checksum used on the GW1000/GW1100 responses is simply the LSB of the sum of the bytes.

            data: The data on which the checksum is to be calculated. Byte string.
            Returns the checksum as an integer.
            """

            # initialise the checksum to 0
            checksum = 0
            # iterate over each byte in the response
            for b in data:
                # add the byte to the running total
                checksum += b
            # we are only interested in the least significant byte
            return checksum % 256

        def rediscover(self):
            """Attempt to rediscover a lost GW1000/GW1100.

            Use UDP broadcast to discover a GW1000/GW1100 that may have changed to a new IP. We should not be re-discovering a GW1000/GW1100 for
            which the user specified an IP, only for those for which we discovered the IP address on startup. If a GW1000/GW1100 is
            discovered then change my ip_address and port properties as necessary to use the device in future. If the rediscover was
            successful return True otherwise return False.
            """

            # we will only rediscover if we first discovered
            if self.ip_discovered:
                # log that we are attempting re-discovery
                self.logger.info("Attempting to re-discover %s..." % self.gateway_model)
                # attempt to discover up to self.max_tries times
                for attempt in range(self.max_tries):
                    # sleep before our attempt, but not if its the first one
                    if attempt > 0:
                        time.sleep(self.retry_wait)
                    try:
                        # discover devices on the local network, the result is a list of dicts in IP address order with each dict
                        # containing data for a unique discovered device
                        device_list = self.discover()
                    except socket.error as e:
                        # log the error
                        self.logger.debug("Failed attempt %d to detect any devices: %s (%s)" % (attempt + 1, e, type(e)))
                    else:
                        # did we find any GW1000/GW1100
                        if len(device_list) > 0:
                            # we have at least one, log the fact as well as what we found
                            gw1000_str = ', '.join([':'.join(['%s:%d' % b]) for b in device_list])
                            if len(device_list) == 1:
                                stem = "%s was" % device_list[0]['model']
                            else:
                                stem = "Multiple devices were"
                            loginf("%s found at %s" % (stem, gw1000_str))
                            # keep our current IP address and port in case we don't find a match as we will change our
                            # ip_address and port properties in order to get the MAC for that IP address and port
                            present_ip = self.ip_address
                            present_port = self.port
                            # iterate over each candidate checking their MAC address against my mac property. This way we know
                            # we are connecting to the GW1000/GW1100 we were previously using
                            for _ip, _port in device_list:
                                # do the MACs match, if so we have our old device and we can exit the loop
                                if self.gateway_mac == self.get_mac_address():
                                    self.gateway_ip = _ip.encode()
                                    self.gateway_port = _port
                                    break
                            else:
                                # exhausted the device_list without a match, revert to our old IP address and port
                                self.gateway_ip = present_ip
                                self.gateway_port = present_port
                                # and continue the outer loop if we have any attempts left
                                continue
                            # log the new IP address and port
                            self.logger.info("%s at address %s:%d will be used" % (self.gateway_model, self.gateway_model_ip.decode(), self.gateway_port))
                            # return True indicating the re-discovery was successful
                            return True
                        else:
                            # did not discover any GW1000/GW1100 so log it
                            self.logger.debug("Failed attempt %d to detect any devices" % (attempt + 1,))
                else:
                    # we exhausted our attempts at re-discovery so log it
                    self.logger.info("Failed to detect original %s after %d attempts" % (self.gateway_model, attempt + 1))
            else:
                # an IP address was specified so we cannot go searching, log it
                self.logger.debug("IP address specified in 'plugin,yaml', re-discovery was not attempted")
            # if we made it here re-discovery was unsuccessful so return False
            return False

    class Parser(object):
        """Class to parse GW1000/GW1100 sensor data."""

        multi_batt = {'wh40': {'mask': 1 << 4},
                      'wh26': {'mask': 1 << 5},
                      'wh25': {'mask': 1 << 6},
                      'wh65': {'mask': 1 << 7}
                      }
        # Dictionary keyed by GW1000/GW1100 response element containing various parameters for each response 'field'. 
        # Dictionary tuple format is (decode function name, size of data in bytes, GW1000/GW1100 field name)
        response_struct = {
            b'\x01': ('decode_temp', 2, 'intemp'),
            b'\x02': ('decode_temp', 2, 'outtemp'),
            b'\x03': ('decode_temp', 2, 'dewpoint'),
            b'\x04': ('decode_temp', 2, 'windchill'),
            b'\x05': ('decode_temp', 2, 'heatindex'),
            b'\x06': ('decode_humid', 1, 'inhumid'),
            b'\x07': ('decode_humid', 1, 'outhumid'),
            b'\x08': ('decode_press', 2, 'absbarometer'),
            b'\x09': ('decode_press', 2, 'relbarometer'),
            b'\x0A': ('decode_dir', 2, 'winddir'),
            b'\x0B': ('decode_speed', 2, 'windspeed'),
            b'\x0C': ('decode_speed', 2, 'gustspeed'),
            b'\x0D': ('decode_rain', 2, 'rainevent'),
            b'\x0E': ('decode_rainrate', 2, 'rainrate'),
            b'\x0F': ('decode_rain', 2, 'rainhour'),
            b'\x10': ('decode_rain', 2, 'rainday'),
            b'\x11': ('decode_rain', 2, 'rainweek'),
            b'\x12': ('decode_big_rain', 4, 'rainmonth'),
            b'\x13': ('decode_big_rain', 4, 'rainyear'),
            b'\x14': ('decode_big_rain', 4, 'raintotals'),
            b'\x15': ('decode_light', 4, 'light'),
            b'\x16': ('decode_uv', 2, 'uv'),
            b'\x17': ('decode_uvi', 1, 'uvi'),
            b'\x18': ('decode_datetime', 6, 'datetime'),
            b'\x19': ('decode_speed', 2, 'daymaxwind'),
            b'\x1A': ('decode_temp', 2, 'temp1'),
            b'\x1B': ('decode_temp', 2, 'temp2'),
            b'\x1C': ('decode_temp', 2, 'temp3'),
            b'\x1D': ('decode_temp', 2, 'temp4'),
            b'\x1E': ('decode_temp', 2, 'temp5'),
            b'\x1F': ('decode_temp', 2, 'temp6'),
            b'\x20': ('decode_temp', 2, 'temp7'),
            b'\x21': ('decode_temp', 2, 'temp8'),
            b'\x22': ('decode_humid', 1, 'humid1'),
            b'\x23': ('decode_humid', 1, 'humid2'),
            b'\x24': ('decode_humid', 1, 'humid3'),
            b'\x25': ('decode_humid', 1, 'humid4'),
            b'\x26': ('decode_humid', 1, 'humid5'),
            b'\x27': ('decode_humid', 1, 'humid6'),
            b'\x28': ('decode_humid', 1, 'humid7'),
            b'\x29': ('decode_humid', 1, 'humid8'),
            b'\x2A': ('decode_pm25', 2, 'pm251'),
            b'\x2B': ('decode_temp', 2, 'soiltemp1'),
            b'\x2C': ('decode_moist', 1, 'soilmoist1'),
            b'\x2D': ('decode_temp', 2, 'soiltemp2'),
            b'\x2E': ('decode_moist', 1, 'soilmoist2'),
            b'\x2F': ('decode_temp', 2, 'soiltemp3'),
            b'\x30': ('decode_moist', 1, 'soilmoist3'),
            b'\x31': ('decode_temp', 2, 'soiltemp4'),
            b'\x32': ('decode_moist', 1, 'soilmoist4'),
            b'\x33': ('decode_temp', 2, 'soiltemp5'),
            b'\x34': ('decode_moist', 1, 'soilmoist5'),
            b'\x35': ('decode_temp', 2, 'soiltemp6'),
            b'\x36': ('decode_moist', 1, 'soilmoist6'),
            b'\x37': ('decode_temp', 2, 'soiltemp7'),
            b'\x38': ('decode_moist', 1, 'soilmoist7'),
            b'\x39': ('decode_temp', 2, 'soiltemp8'),
            b'\x3A': ('decode_moist', 1, 'soilmoist8'),
            b'\x3B': ('decode_temp', 2, 'soiltemp9'),
            b'\x3C': ('decode_moist', 1, 'soilmoist9'),
            b'\x3D': ('decode_temp', 2, 'soiltemp10'),
            b'\x3E': ('decode_moist', 1, 'soilmoist10'),
            b'\x3F': ('decode_temp', 2, 'soiltemp11'),
            b'\x40': ('decode_moist', 1, 'soilmoist11'),
            b'\x41': ('decode_temp', 2, 'soiltemp12'),
            b'\x42': ('decode_moist', 1, 'soilmoist12'),
            b'\x43': ('decode_temp', 2, 'soiltemp13'),
            b'\x44': ('decode_moist', 1, 'soilmoist13'),
            b'\x45': ('decode_temp', 2, 'soiltemp14'),
            b'\x46': ('decode_moist', 1, 'soilmoist14'),
            b'\x47': ('decode_temp', 2, 'soiltemp15'),
            b'\x48': ('decode_moist', 1, 'soilmoist15'),
            b'\x49': ('decode_temp', 2, 'soiltemp16'),
            b'\x4A': ('decode_moist', 1, 'soilmoist16'),
            b'\x4C': ('decode_batt', 16, 'lowbatt'),
            b'\x4D': ('decode_pm25', 2, 'pm251_24h_avg'),
            b'\x4E': ('decode_pm25', 2, 'pm252_24h_avg'),
            b'\x4F': ('decode_pm25', 2, 'pm253_24h_avg'),
            b'\x50': ('decode_pm25', 2, 'pm254_24h_avg'),
            b'\x51': ('decode_pm25', 2, 'pm252'),
            b'\x52': ('decode_pm25', 2, 'pm253'),
            b'\x53': ('decode_pm25', 2, 'pm254'),
            b'\x58': ('decode_leak', 1, 'leak1'),
            b'\x59': ('decode_leak', 1, 'leak2'),
            b'\x5A': ('decode_leak', 1, 'leak3'),
            b'\x5B': ('decode_leak', 1, 'leak4'),
            b'\x60': ('decode_distance', 1, 'lightningdist'),
            b'\x61': ('decode_utc', 4, 'lightningdettime'),
            b'\x62': ('decode_count', 4, 'lightningcount'),
            # WH34 battery data is not obtained from live data rather it is
            # obtained from sensor ID data
            b'\x63': ('decode_wh34', 3, 'temp9'),
            b'\x64': ('decode_wh34', 3, 'temp10'),
            b'\x65': ('decode_wh34', 3, 'temp11'),
            b'\x66': ('decode_wh34', 3, 'temp12'),
            b'\x67': ('decode_wh34', 3, 'temp13'),
            b'\x68': ('decode_wh34', 3, 'temp14'),
            b'\x69': ('decode_wh34', 3, 'temp15'),
            b'\x6A': ('decode_wh34', 3, 'temp16'),
            # WH45 battery data is not obtained from live data rather it is
            # obtained from sensor ID data
            b'\x70': ('decode_wh45', 16, ('temp17', 'humid17', 'pm10',
                                          'pm10_24h_avg', 'pm255', 'pm255_24h_avg',
                                          'co2', 'co2_24h_avg')),
            b'\x71': (None, None, None),
            b'\x72': ('decode_wet', 1, 'leafwet1'),
            b'\x73': ('decode_wet', 1, 'leafwet2'),
            b'\x74': ('decode_wet', 1, 'leafwet3'),
            b'\x75': ('decode_wet', 1, 'leafwet4'),
            b'\x76': ('decode_wet', 1, 'leafwet5'),
            b'\x77': ('decode_wet', 1, 'leafwet6'),
            b'\x78': ('decode_wet', 1, 'leafwet7'),
            b'\x79': ('decode_wet', 1, 'leafwet8')
        }

        # tuple of field codes for rain related fields in the GW1000/GW1100 live data so we can isolate these fields
        rain_field_codes = (b'\x0D', b'\x0E', b'\x0F', b'\x10',
                            b'\x11', b'\x12', b'\x13', b'\x14')
        # tuple of field codes for wind related fields in the GW1000/GW1100 live data so we can isolate these fields
        wind_field_codes = (b'\x0A', b'\x0B', b'\x0C', b'\x19')

        def __init__(self, is_wh24=False, debug_rain=False, debug_wind=False):
            # Tell our battery state decoding whether we have a WH24 or a WH65 (they both share the same battery state bit). 
            # By default we are coded to use a WH65. But is there a WH24 connected?
            if is_wh24:
                # We have a WH24. On startup we are set for a WH65 but if it is a restart we will likely already be setup for a WH24. We need to handle both cases.
                if 'wh24' not in self.multi_batt.keys():
                    # we don't have a 'wh24' entry so create one, it's the same as the 'wh65' entry
                    self.multi_batt['wh24'] = self.multi_batt['wh65']
                    # and pop off the no longer needed WH65 decode dict entry
                    self.multi_batt.pop('wh65')
            else:
                # We don't have a WH24 but a WH65. On startup we are set for a WH65 but if it is a restart it is possible we have already
                # been setup for a WH24. We need to handle both cases.
                if 'wh65' not in self.multi_batt.keys():
                    # we don't have a 'wh65' entry so create one, it's the same as the 'wh24' entry
                    self.multi_batt['wh65'] = self.multi_batt['wh24']
                    # and pop off the no longer needed WH65 decode dict entry
                    self.multi_batt.pop('wh24')
            # get debug_rain and debug_wind
            self.debug_rain = debug_rain
            self.debug_wind = debug_wind

        def parse(self, raw_data, timestamp=None):
            """Parse raw sensor data.

            Parse the raw sensor data and create a dict of sensor observations/status data. Add a timestamp to the data if one does not already exist.

            Returns a dict of observations/status data."""

            # obtain the response size, it's a big endian short (two byte) integer
            resp_size = struct.unpack(">H", raw_data[3:5])[0]
            # obtain the response
            resp = raw_data[5:5 + resp_size - 4]
            # log the actual sensor data as a sequence of bytes in hex
            self.logger.debug("sensor data is '%s'" % (bytes_to_hex(resp),))
            data = {}
            if len(resp) > 0:
                index = 0
                while index < len(resp) - 1:
                    try:
                        decode_str, field_size, field = self.response_struct[resp[index:index + 1]]
                    except KeyError:
                        # We struck a field 'address' we do not know how to process. Ideally we would like to skip and move onto the next field (if there is one) but the problem is
                        # we do not know how long the data of this unknown field is. We could go on guessing the field data size by looking for the next field address but we won't
                        # know if we do find a valid field address is it a field address or data from this field? Of course this could also be corrupt data (unlikely though as it was
                        # decoded using a checksum). So all we can really do is accept the data we have so far, log the issue and ignore the remaining data.
                        self.logger.error("Unknown field address '%s' detected. Remaining sensor data ignored." % (bytes_to_hex(resp[index:index + 1]),))
                        break
                    else:
                        _field_data = getattr(self, decode_str)(resp[index + 1:index + 1 + field_size], field)
                        if _field_data is not None:
                            data.update(_field_data)
                            if self.debug_rain and resp[index:index + 1] in self.rain_field_codes:
                                self.logger.info("parse: raw rain data: field:%s and data:%s decoded as %s=%s" % (bytes_to_hex(resp[index:index + 1]),
                                                                                                                     bytes_to_hex(resp[index + 1:index + 1 + field_size]),
                                                                                                                     field,
                                                                                                                     _field_data[field]))
                            if self.debug_wind and resp[index:index + 1] in self.wind_field_codes:
                                self.logger.info("parse: raw wind data: field:%s and data:%s decoded as %s=%s" % (resp[index:index + 1],
                                                                                                                     bytes_to_hex(resp[index + 1:index + 1 + field_size]),
                                                                                                                     field,
                                                                                                                     _field_data[field]))
                        index += field_size + 1
            # if it does not exist add a datetime field with the current epoch timestamp
            if 'datetime' not in data or 'datetime' in data and data['datetime'] is None:
                data['datetime'] = timestamp if timestamp is not None else int(time.time() + 0.5)
            return data

        @staticmethod
        def decode_temp(data, field=None):
            """Decode temperature data.

            Data is contained in a two byte big endian signed integer and represents tenths of a degree.
            """

            if len(data) == 2:
                value = struct.unpack(">h", data)[0] / 10.0
            else:
                value = None
            if field is not None:
                return {field: value}
            else:
                return value

        @staticmethod
        def decode_humid(data, field=None):
            """Decode humidity data.

            Data is contained in a single unsigned byte and represents whole units.
            """

            if len(data) == 1:
                value = struct.unpack("B", data)[0]
            else:
                value = None
            if field is not None:
                return {field: value}
            else:
                return value

        @staticmethod
        def decode_press(data, field=None):
            """Decode pressure data.

            Data is contained in a two byte big endian integer and represents tenths of a unit.
            """

            if len(data) == 2:
                value = struct.unpack(">H", data)[0] / 10.0
            else:
                value = None
            if field is not None:
                return {field: value}
            else:
                return value

        @staticmethod
        def decode_dir(data, field=None):
            """Decode direction data.

            Data is contained in a two byte big endian integer and represents whole degrees.
            """

            if len(data) == 2:
                value = struct.unpack(">H", data)[0]
            else:
                value = None
            if field is not None:
                return {field: value}
            else:
                return value

        @staticmethod
        def decode_big_rain(data, field=None):
            """Decode 4 byte rain data.

            Data is contained in a four byte big endian integer and represents tenths of a unit.
            """

            if len(data) == 4:
                value = struct.unpack(">L", data)[0] / 10.0
            else:
                value = None
            if field is not None:
                return {field: value}
            else:
                return value

        @staticmethod
        def decode_datetime(data, field=None):
            """Decode date-time data.

            Unknown format but length is six bytes.
            """

            if len(data) == 6:
                value = struct.unpack("BBBBBB", data)
            else:
                value = None
            if field is not None:
                return {field: value}
            else:
                return value

        @staticmethod
        def decode_distance(data, field=None):
            """Decode lightning distance.

            Data is contained in a single byte integer and represents a value from 0 to 40km.
            """

            if len(data) == 1:
                value = struct.unpack("B", data)[0]
                value = value if value <= 40 else None
            else:
                value = None
            if field is not None:
                return {field: value}
            else:
                return value

        @staticmethod
        def decode_utc(data, field=None):
            """Decode UTC time.

            The GW1000/GW1100 API claims to provide 'UTC time' as a 4 byte big endian integer. The 4 byte integer is a unix epoch timestamp;
            however, the timestamp is offset by the stations timezone. So for a station in the +10 hour timezone, the timestamp returned is the
            present epoch timestamp plus 10 * 3600 seconds.

            When decoded in localtime the decoded date-time is off by the station time zone, when decoded as GMT the date and time figures
            are correct but the timezone is incorrect.

            In any case decode the 4 byte big endian integer as is and any further use of this timestamp needs to take the above time zone
            offset into account when using the timestamp.
            """

            if len(data) == 4:
                # unpack the 4 byte int
                value = struct.unpack(">L", data)[0]
                # when processing the last lightning strike time if the value is 0xFFFFFFFF it means we have never seen a strike so return None
                value = value if value != 0xFFFFFFFF else None
            else:
                value = None
            if field is not None:
                return {field: value}
            else:
                return value

        @staticmethod
        def decode_count(data, field=None):
            """Decode lightning count.

            Count is an integer stored in a 4 byte big endian integer."""

            if len(data) == 4:
                value = struct.unpack(">L", data)[0]
            else:
                value = None
            if field is not None:
                return {field: value}
            else:
                return value

        # alias' for other decodes
        decode_speed = decode_press
        decode_rain = decode_press
        decode_rainrate = decode_press
        decode_light = decode_big_rain
        decode_uv = decode_press
        decode_uvi = decode_humid
        decode_moist = decode_humid
        decode_pm25 = decode_press
        decode_leak = decode_humid
        decode_pm10 = decode_press
        decode_co2 = decode_dir
        decode_wet = decode_humid

        def decode_wh34(self, data, field=None):
            """Decode WH34 sensor data.

            Data consists of three bytes:
                Byte    Field               Comments
                1-2     temperature         standard Ecowitt temperature data, two
                                            byte big endian signed integer
                                            representing tenths of a degree
                3       battery voltage     0.02 * value Volts
            """

            if len(data) == 3 and field is not None:
                results = dict()
                results[field] = self.decode_temp(data[0:2])
                # we could decode the battery voltage but we will be obtaining battery voltage data from the sensor IDs in a later step so we can skip it here
                return results
            return {}

        def decode_wh45(self, data, fields=None):
            """Decode WH45 sensor data.

            WH45 sensor data includes TH sensor values, CO2/PM2.5/PM10 sensor values and 24 hour aggregates and battery state data in 16 bytes.
            The 16 bytes of WH45 sensor data is allocated as follows:
                Byte(s) #      Data               Format          Comments
                bytes   1-2    temperature        short           C x10
                        3      humidity           unsigned byte   percent
                        4-5    PM10               unsigned short  ug/m3 x10
                        6-7    PM10 24hour avg    unsigned short  ug/m3 x10
                        8-9    PM2.5              unsigned short  ug/m3 x10
                        10-11  PM2.5 24 hour avg  unsigned short  ug/m3 x10
                        12-13  CO2                unsigned short  ppm
                        14-15  CO2 24 our avg     unsigned short  ppm
                        16     battery state      unsigned byte   0-5 <=1 is low
            """

            if len(data) == 16 and fields is not None:
                results = dict()
                results[fields[0]] = self.decode_temp(data[0:2])
                results[fields[1]] = self.decode_humid(data[2:3])
                results[fields[2]] = self.decode_pm10(data[3:5])
                results[fields[3]] = self.decode_pm10(data[5:7])
                results[fields[4]] = self.decode_pm25(data[7:9])
                results[fields[5]] = self.decode_pm25(data[9:11])
                results[fields[6]] = self.decode_co2(data[11:13])
                results[fields[7]] = self.decode_co2(data[13:15])
                # we could decode the battery state but we will be obtaining battery state data from the sensor IDs in a later step so we can skip it here
                return results
            return {}

        @staticmethod
        def decode_batt(data, field=None):
            """Decode battery status data.

            GW1000/GW1100 firmware version 1.6.4 and earlier supported 16 bytes of battery state data at response field x4C for the following sensors:
                WH24, WH25, WH26(WH32), WH31 ch1-8, WH40, WH41/WH43 ch1-4,
                WH51 ch1-8, WH55 ch1-4, WH57, WH68 and WS80

            As of firmware version 1.6.5 the 16 bytes of battery state data is no longer returned at all. CMD_READ_SENSOR_ID_NEW or
            CMD_READ_SENSOR_ID must be used to obtain battery state information for connected sensors. The decode_batt() method has been retained
            to support devices using firmware version 1.6.4 and earlier.

            Since the GW1000/GW1100 driver now obtains battery state information via CMD_READ_SENSOR_ID_NEW or CMD_READ_SENSOR_ID only
            the decode_batt() method now returns None so that firmware versions before 1.6.5 continue to be supported.
            """

            return None

    class Sensors(object):
        """Class to manage GW1000/GW1100 sensor ID data.

        Class Sensors allows access to various elements of sensor ID data via a
        number of properties and methods when the class is initialised with the
        GW1000/GW1100 API response to a CMD_READ_SENSOR_ID_NEW or
        CMD_READ_SENSOR_ID command.

        A Sensors object can be initialised with sensor ID data on
        instantiation or an existing Sensors object can be updated by calling
        the set_sensor_id_data() method passing the sensor ID data to be used
        as the only parameter.
        """

        # Tuple of sensor ID values for sensors that are not registered with
        # the GW1000/GW1100. 'fffffffe' means the sensor is disabled,
        # 'ffffffff' means the sensor is registering.
        not_registered = ('fffffffe', 'ffffffff')

        def __init__(self, sensor_id_data=None, show_battery=False, debug_sensors=False):
            """Initialise myself"""

            # set the show_battery property
            self.show_battery = show_battery
            # initialise a dict to hold the parsed sensor data
            self.sensor_data = dict()
            # parse the raw sensor ID data and store the results in my parsed
            # sensor data dict
            self.set_sensor_id_data(sensor_id_data)
            # debug sensors
            self.debug_sensors = debug_sensors

        def set_sensor_id_data(self, id_data):
            """Parse the raw sensor ID data and store the results."""

            # initialise our parsed sensor ID data dict
            self.sensor_data = {}
            # do we have any raw sensor ID data
            if id_data is not None and len(id_data) > 0:
                # determine the size of the sensor id data, it's a big endian
                # short (two byte) integer at bytes 4 and 5
                data_size = struct.unpack(">H", id_data[3:5])[0]
                # extract the actual sensor id data
                data = id_data[5:5 + data_size - 4]
                # initialise a counter
                index = 0
                # iterate over the data
                while index < len(data):
                    # get the sensor address
                    address = data[index:index + 1]
                    # do we know how to decode this address
                    if address in Gw1000Collector.sensor_ids.keys():
                        # get the sensor ID
                        sensor_id = bytes_to_hex(data[index + 1: index + 5],
                                                 separator='',
                                                 caps=False)
                        # get the method to be used to decode the battery state
                        # data
                        batt_fn = Gw1000Collector.sensor_ids[data[index:index + 1]]['batt_fn']
                        # get the raw battery state data
                        batt = six.indexbytes(data, index + 5)
                        # if we are not showing all battery state data then the
                        # battery state for any sensor with signal == 0 must be set
                        # to None, otherwise parse the raw battery state data as
                        # applicable
                        if not self.show_battery and six.indexbytes(data, index + 6) == 0:
                            batt_state = None
                        else:
                            # parse the raw battery state data
                            batt_state = getattr(self, batt_fn)(batt)
                        # now add the sensor to our sensor data dict
                        self.sensor_data[address] = {'id': sensor_id,
                                                     'battery': batt_state,
                                                     'signal': six.indexbytes(data, index + 6)
                                                     }
                    else:
                        if self.debug_sensors:
                            loginf("Unknown sensor ID '%s'" % bytes_to_hex(address))
                    # each sensor entry is seven bytes in length so skip to the
                    # start of the next sensor
                    index += 7
        

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
        
class InvalidApiResponse(Exception):
    """Exception raised when an API call response is invalid."""


class InvalidChecksum(Exception):
    """Exception raised when an API call response contains an invalid
    checksum."""


class GW1000IOError(Exception):
    """Exception raised when an input/output error with the GW1000/GW1100 is
    encountered."""


class UnknownCommand(Exception):
    """Exception raised when an unknown API command is used."""
    
    
# ============================================================================
#                             Utility functions
# ============================================================================


def natural_sort_keys(source_dict):
    """Return a naturally sorted list of keys for a dict."""

    def atoi(text):
        return int(text) if text.isdigit() else text

    def natural_keys(text):
        """Natural key sort.

        Allows use of key=natural_keys to sort a list in human order, eg:
            alist.sort(key=natural_keys)

        http://nedbatchelder.com/blog/200712/human_sorting.html (See
        Toothy's implementation in the comments)
        """

        return [atoi(c) for c in re.split(r'(\d+)', text.lower())]

    # create a list of keys in the dict
    keys_list = list(source_dict.keys())
    # naturally sort the list of keys where, for example, xxxxx16 appears in the
    # correct order
    keys_list.sort(key=natural_keys)
    # return the sorted list
    return keys_list


def natural_sort_dict(source_dict):
    """Return a string representation of a dict sorted naturally by key.

    When represented as a string a dict is displayed in the format:
        {key a:value a, key b: value b ... key z: value z}
    but the order of the key:value pairs is unlikely to be alphabetical.
    Displaying dicts of key:value pairs in logs or on the console in
    alphabetical order by key assists in the analysis of the the dict data.
    Where keys are strings with leading digits a natural sort is useful.
    """

    # first obtain a list of key:value pairs as string sorted naturally by key
    sorted_dict_fields = ["'%s': '%s'" % (k, source_dict[k]) for k in natural_sort_keys(source_dict)]
    # return as a string of comma separated key:value pairs in braces
    return "{%s}" % ", ".join(sorted_dict_fields)


def bytes_to_hex(iterable, separator=' ', caps=True):
    """Produce a hex string representation of a sequence of bytes."""

    # assume 'iterable' can be iterated by iterbytes and the individual
    # elements can be formatted with {:02X}
    format_str = "{:02X}" if caps else "{:02x}"
    try:
        return separator.join(format_str.format(c) for c in six.iterbytes(iterable))
    except ValueError:
        # most likely we are running python3 and iterable is not a bytestring,
        # try again coercing iterable to a bytestring
        return separator.join(format_str.format(c) for c in six.iterbytes(six.b(iterable)))
    except (TypeError, AttributeError):
        # TypeError - 'iterable' is not iterable
        # AttributeError - likely because separator is None
        # either way we can't represent as a string of hex bytes
        return "cannot represent '%s' as hexadecimal bytes" % (iterable,)
        
def bytes_to_int(rawbytes, signed=False):
    '''
    Convert bytearray to value with respect to sign format

    :parameter rawbytes: Bytes to convert
    :parameter signed: True if result should be a signed int, False for unsigned
    :type signed: bool
    :return: Converted value
    :rtype: int
    '''
    return int.from_bytes(rawbytes, byteorder='little', signed=signed)

def obfuscate(plain, obf_char='*'):
    """Obfuscate all but the last x characters in a string.

    Obfuscate all but (at most) the last four characters of a string. Always
    reveal no more than 50% of the characters. The obfuscation character
    defaults to '*' but can be set when the function is called.
    """

    if plain is not None and len(plain) > 0:
        # obtain the number of the characters to be retained
        stem = 4
        stem = 3 if len(plain) < 8 else stem
        stem = 2 if len(plain) < 6 else stem
        stem = 1 if len(plain) < 4 else stem
        stem = 0 if len(plain) < 3 else stem
        if stem > 0:
            # we are retaining some characters so do a little string
            # manipulation
            obfuscated = obf_char * (len(plain) - stem) + plain[-stem:]
        else:
            # we are obfuscating everything
            obfuscated = obf_char * len(plain)
        return obfuscated
    else:
        # if we received None or a zero length string then return it
        return plain

