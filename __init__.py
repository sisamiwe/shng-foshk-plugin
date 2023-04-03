#!/usr/bin/env python3
# vim: set encoding=utf-8 tabstop=4 softtabstop=4 shiftwidth=4 expandtab
#########################################################################
#  Copyright 2022-      Michael Wenzel              wenzel_michael@web.de
#########################################################################
#  This file is part of SmartHomeNG.
#  https://www.smarthomeNG.de
#  https://knx-user-forum.de/forum/supportforen/smarthome-py
#
#  Plugin to connect to Foshk Weather Gateway.
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


#########################################################################
#
# ToDo
#  - tswarning                  is there a thunderstorm coming
#  - set CMD_WRITE_CALIBRATION
#  - set CMD_WRITE_RAINDATA
#  - set CMD_WRITE_GAIN
#  - sunhours
#  - ptrend
#  - correct datetime of packets to timezone
#  - check solar radiation / UV between API and ECOWITT
########################################


# API: https://osswww.ecowitt.net/uploads/20210716/WN1900%20GW1000,1100%20WH2680,2650%20telenet%20v1.6.0%20.pdf


from lib.model.smartplugin import SmartPlugin
from lib.utils import Utils
from lib.shtime import Shtime
from .webif import WebInterface

import logging
import re
import socket
import struct
import threading
import time
import queue
import math
import requests
import configparser
import socketserver

from collections import deque
from typing import Union
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler

import urllib.parse as urlparse


# SET GLOBAL DEFAULTS
# default network broadcast address - the address that network broadcasts are sent to
DEFAULT_BROADCAST_ADDRESS = '255.255.255.255'
# default network broadcast port - the port that network broadcasts are sent to
DEFAULT_BROADCAST_PORT = 46000
# default socket timeout
DEFAULT_SOCKET_TIMEOUT = 2
# default broadcast timeout
DEFAULT_BROADCAST_TIMEOUT = 5
# default retry/wait time
DEFAULT_RETRY_WAIT = 10
# default max tries when polling the API
DEFAULT_MAX_TRIES = 3
# firmware update url
FW_UPDATE_URL = 'http://download.ecowitt.net/down/filewave?v=FirwaveReadme.txt'.replace("\"", "")
# default port for tcp server
DEFAULT_TCP_PORT = 8080
# known device models
KNOWN_MODELS = ('GW1000', 'GW1100', 'GW2000', 'WH2650', 'WH2680', 'WN1900')


class Foshk(SmartPlugin):
    """
    Main class of the Plugin. Does all plugin specific stuff and provides the update functions for the items.
    """

    META_ATTRIBUTES = ['gateway_model',
                       'frequency',
                       'sensor_warning',
                       'battery_warning',
                       'storm_warning',
                       'thunderstorm_warning',
                       'weatherstation_warning',
                       'firmware_version',
                       'firmware_update_available',
                       'firmware_update_text',
                       ]

    TCP_ATTRIBUTES = ['runtime']

    PLUGIN_VERSION = '1.1.1'

    def __init__(self, sh):
        """
        Initializes the plugin.
        """

        # call init code of parent class (SmartPlugin)
        super().__init__()

        # get the parameters for the plugin (as defined in metadata plugin.yaml):
        self._broadcast_address = None
        self._broadcast_port = None
        self._gateway_address = self.get_parameter_value('Gateway_IP')
        if self._gateway_address == '127.0.0.1':
            self._gateway_address = None
        self._gateway_port = self.get_parameter_value('Gateway_Port')
        if self._gateway_port == 0 or not is_port_valid(self._gateway_port):
            self._gateway_port = None
        self._gateway_poll_cycle = self.get_parameter_value('Gateway_Poll_Cycle')
        self._fw_update_check_cycle = self.get_parameter_value('FW_Update_Check_Cycle') * 24 * 60 * 60                    # convert from days into seconds
        self._battery_warning = self.get_parameter_value('Battery_Warning')
        self._sensor_warning = self.get_parameter_value('Sensor_Warning')
        _ecowitt_data_cycle = self.get_parameter_value('Ecowitt_Data_Cycle')
        self._use_customer_server = bool(_ecowitt_data_cycle)
        if self._use_customer_server:
            self._http_server_ip = Utils.get_local_ipv4_address()
            self._http_server_port = self.select_port_for_tcp_server(DEFAULT_TCP_PORT)
            self._data_cycle = max(_ecowitt_data_cycle, 16)
            self.logger.debug(f"Receiving ECOWITT data has been enabled. Data upload to {self._http_server_ip}:{self._http_server_port} with an interval of {self._data_cycle}s will be set.")
            if not self._http_server_ip or not self._http_server_port:
                self.logger.error(f"Receiving ECOWITT data has been enabled, but not able to define server ip or port with setting {self._http_server_ip}:{self._http_server_port}")
                self._init_complete = False

        # define properties
        self.data_dict = {'api': {}, 'tcp': {}}                                     # dict to hold all live data gotten from weather station gateway via tcp and api
        self.gateway_connected = False                                              # is gateway connected; driver established
        self.api_data_thread = None                                                 # thread property for get data via api
        self.tcp_data_thread = None                                                 # thread property for get data via http
        self.update_available = False                                               # is a newer firmware available
        self.api_driver = None                                                      # api driver object
        self.tcp_driver = None                                                      # tcp driver object
        self.alive = False                                                          # plugin alive
        self._altitude = self.get_sh()._elev                                        # altitude of installation used from shNG setting
        self.language = self.get_sh().get_defaultlanguage()                         # current shNG language (= 'de')

        # get a Gw1000Driver object
        try:
            self.logger.debug(f"Start interrogating.....")
            self.api_driver = Gw1000Driver(self,
                                           poll_interval=self._gateway_poll_cycle,
                                           broadcast_address=self._broadcast_address,
                                           broadcast_port=self._broadcast_port,
                                           ip_address=self._gateway_address,
                                           gateway_port=self._gateway_port)

            self.logger.debug(f"Interrogating {self.api_driver.collector.station.model} at {self.api_driver.collector.station.ip_address.decode()}:{self.api_driver.collector.station.port}")
            self.gateway_connected = True
        except GW1000IOError as e:
            self.logger.error(f"Unable to connect to device: {e}")
            self._init_complete = False

        # if usage of customer service is enabled
        if self._use_customer_server:
            # initialize tcp server
            try:
                self.tcp_driver = Gw1000TcpDriver(tcp_server_address=self._http_server_ip,
                                                  tcp_server_port=self._http_server_port,
                                                  data_cycle=self._data_cycle,
                                                  gateway_address=self._gateway_address,
                                                  plugin_instance=self)
            except Exception as e:
                self.logger.error(f"Unable to start 'tcp_driver' thread: {e}")
                self._init_complete = False

        # get webinterface
        if not self.init_webinterface(WebInterface):
            self.logger.warning("Webinterface not initialized")

    def run(self):
        """
        Run method for the plugin
        """

        self.logger.debug("Run method called")
        self.alive = True

        # add scheduler for update check if FW-Check is activated
        if self._fw_update_check_cycle > 0:
            self.scheduler_add('Foshk FW Update Check', self.check_firmware_update, cycle=self._fw_update_check_cycle)

        # if customer server is used, set parameters accordingly
        if self._use_customer_server:
            self.set_custom_params(custom_server_id='', custom_password='', custom_host=self._http_server_ip, custom_port=self._http_server_port, custom_interval=self._data_cycle, custom_type=False, custom_enabled=True)
            self.set_usr_path()

        # set class property to selected IP
        self._gateway_address = self.api_driver.collector.station.gateway_ip
        self._gateway_port = self.api_driver.collector.station.gateway_port

        # start endless loop for 'get_api_data' in own thread until plugin stops
        try:
            self.get_api_data_thread_startup()
        except Exception as e:
            self.logger.error(f"Unable to start 'get_api_data' thread: {e}")
        # if usage of customer service is enabled
        if self._use_customer_server:
            # start endless loop for 'get_tcp_data' in own thread until plugin stops
            try:
                self.get_tcp_data_thread_startup()
            except Exception as e:
                self.logger.error(f"Unable to start 'get_tcp_data' thread: {e}")

        self.update_gateway_meta_data_items()

    def stop(self):
        """
        Stop method for the plugin
        """

        self.alive = False

        self.logger.debug("Shutdown von GW1000 Collector Thread called")
        self.api_driver.closePort()
        self.gateway_connected = False

        self.logger.debug("Shutdown von FoshkPlugin Thread for getting API data called")
        self.get_api_data_thread_shutdown()

        if self._fw_update_check_cycle > 0:
            self.scheduler_remove('Foshk FW Update Check')

        if self._use_customer_server:
            self.logger.debug("Shutdown von FoshkPlugin Thread for getting TCP data called")
            self.get_tcp_data_thread_shutdown()

            self.logger.debug("Stop von FoshkPlugin TCP Server called")
            self.tcp_driver.closePort()

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

        if self.has_iattr(item.conf, 'foshk_attibute'):
            foshk_attribute = (self.get_iattr_value(item.conf, 'foshk_attibute')).lower()

            if foshk_attribute in self.META_ATTRIBUTES:
                source = 'meta'

            elif foshk_attribute in self.TCP_ATTRIBUTES:
                source = 'ecowitt'

            elif self.has_iattr(item.conf, 'foshk_datasource'):
                foshk_datasource = (self.get_iattr_value(item.conf, 'foshk_datasource')).lower()
                if foshk_datasource == 'ecowitt' and not self._use_customer_server:
                    self.logger.warning(f" Item {item.path()} should use datasource {foshk_datasource} as per item.yaml, but 'ECOWITT'-protocol not enabled. Item ignored")
                    source = None
                else:
                    source = foshk_datasource

            else:
                source = 'api'

            item_config_data_dict = {'foshk_attribute': foshk_attribute, 'source': source, 'match': f'{source}.{foshk_attribute}'}
            self.add_item(item, config_data_dict=item_config_data_dict, mapping=None)

            if foshk_attribute.startswith('set'):
                return self.update_item

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
            self.logger.info(f"Update item: {item.property.path}, item has been changed outside this plugin")

            if self.has_iattr(item.conf, 'foshk_attibute'):
                self.logger.debug(f"update_item was called with item {item.property.path} from caller {caller}, source {source} and dest {dest}")
            pass

    def select_port_for_tcp_server(self, port: int) -> int:
        """
        Check if default port for tcp server is free and can be used

        :param port: port number to be used
        :type port: int

        :return: selected port
        :rtype: int
        """

        for attempt in range(20):
            port = port + attempt
            # self.logger.debug(f"try port={port}")
            if is_port_in_use(port):
                self.logger.debug(f"select_port_for_tcp_server: Port {port} is already in use. Trying next one...")
            else:
                # self.logger.debug(f"select_port_for_tcp_server: Port {port} can be used")
                return port

    def get_api_data_thread_startup(self):
        """
        Start a thread that get data from the GW1000/GW1100 driver.
        """

        try:
            _name = 'plugins.' + self.get_fullname() + '.get_api_data'
            self.api_data_thread = threading.Thread(target=self.get_api_data, name=_name)
            self.api_data_thread.daemon = False
            self.api_data_thread.start()
            self.logger.debug("FoshkPlugin thread for 'get_api_data' has been started")
        except threading.ThreadError:
            self.logger.error("Unable to launch FoshkPlugin thread for 'get_api_data'.")
            self.api_data_thread = None

    def get_api_data_thread_shutdown(self):
        """
        Shut down the thread that gets data from the GW1000/GW1100 driver.
        """

        if self.api_data_thread:
            self.api_data_thread.join()
            if self.api_data_thread.is_alive():
                self.logger.error("Unable to shut down 'get_api_data' thread")
            else:
                self.logger.info("FoshkPlugin thread 'get_api_data' has been terminated")
                self.api_data_thread = None

    def get_tcp_data_thread_startup(self):
        """
        Start a thread that get data from the TCP Server.
        """

        try:
            _name = 'plugins.' + self.get_fullname() + '.get_tcp_data'
            self.tcp_data_thread = threading.Thread(target=self.get_tcp_data, name=_name)
            self.tcp_data_thread.daemon = False
            self.tcp_data_thread.start()
            self.logger.debug("FoshkPlugin thread for 'get_tcp_data' has been started")
        except threading.ThreadError:
            self.logger.error("Unable to launch FoshkPlugin thread for 'get_tcp_data'.")
            self.tcp_data_thread = None

    def get_tcp_data_thread_shutdown(self):
        """
        Shut down the thread that gets data from the TCP Server.
        """

        if self.tcp_data_thread:
            self.tcp_data_thread.join()
            if self.tcp_data_thread.is_alive():
                self.logger.error("Unable to shut down 'get_tcp_data' thread")
            else:
                self.logger.info("FoshkPlugin 'get_tcp_data' thread has been terminated")
                self.tcp_data_thread = None

    def get_api_data(self):
        """
        Gets data from collector in endless loop
        """

        while self.alive:
            for packet in self.api_driver.genLoopPackets():
                # log packet and store it
                self.logger.debug(f"get_api_data: packet={packet}")
                self.data_dict['api'] = packet
                # start item update
                self.update_item_values(packet, 'api')

    def get_tcp_data(self):
        """
        Gets data from client in endless loop
        """

        while self.alive:
            for packet in self.tcp_driver.genLoopPackets():
                # log packet and store it
                self.logger.debug(f"get_tcp_data: packet={packet}")
                self.data_dict['tcp'] = packet
                # start item update
                self.update_item_values(packet, 'ecowitt')

    def update_item_values(self, data: dict, source: str):
        """
        Updates the value of connected items

        :param data: data to be used for update
        :param source: source the data come from
        """

        self.logger.debug(f"Called with source={source}")

        for foshk_attribute in data:
            item_list = self.get_item_list('match', f'{source}.{foshk_attribute}')
            if not item_list:
                # self.logger.debug(f"No item found for foshk_attribute={foshk_attribute!r} at datasource={source!r} has been found.")
                continue
            elif len(item_list) > 1:
                # self.logger.debug(f"More than one item found for foshk_attribute={foshk_attribute!r} at datasource={source!r} has been found. First one will be used.")
                continue

            item = item_list[0]
            value = data[foshk_attribute]
            # self.logger.debug(f"Value {value} will be set to item={item.path()} with foshk_attribute={foshk_attribute}, datasource={source}")
            item(value, self.get_shortname(), source)

    def firmware_update(self):
        """
        Run firmware update
        """

        result = self.api_driver.collector.firmware_update()
        if result == 'SUCCESS':
            self.logger.debug(f"firmware_update: {result}")
        else:
            self.logger.error(f"firmware_update: {result}")

    def check_firmware_update(self):
        """
        Check if firmware update is available
        """

        fw_info = requests.get(FW_UPDATE_URL)
        self.logger.debug(f"check_firmware_update: getting update info from {FW_UPDATE_URL} results in {fw_info.status_code}")

        if fw_info.status_code == 200:
            # get current firmware version
            current_firmware = self.api_driver.firmware_version

            model = "unknown"
            for i in KNOWN_MODELS:
                if i in current_firmware.upper():
                    model = i

            # establish configparser
            config = configparser.ConfigParser(allow_no_value=True, strict=False)
            # read response text
            config.read_string(fw_info.text)

            # extract information for given model
            remote_firmware = config.get(model, "VER", fallback="unknown")
            remote_firmware_notes = config.get(model, "NOTES", fallback="").split(";")
            use_app = "WS View"

            if ver_str_to_num(remote_firmware) and ver_str_to_num(current_firmware) and (ver_str_to_num(remote_firmware) > ver_str_to_num(current_firmware)):
                self.logger.warning(f"Firmware update for {model} available. Installed version is: {current_firmware}, available version is: {remote_firmware}. Use the app {use_app} to update!")
                self.logger.debug(f"remote_firmware_notes={remote_firmware_notes}")
                self.logger.info(' '.join(remote_firmware_notes))
                self.update_available = True
                packet = {'firmware_update_available': True, 'firmware_update_text': remote_firmware_notes}

            else:
                self.logger.info(f"No newer firmware found for {model}. Installed version is: {current_firmware}, available version is: {remote_firmware}.")
                self.update_available = False
                packet = {'firmware_update_available': False, 'firmware_update_text': []}

            self.update_item_values(packet, 'meta')

    def set_usr_path(self, custom_ecowitt_path: str = "/data/report/", custom_wu_path: str = "/weatherstation/updateweatherstation.php?"):
        """
        Set user path for Ecowitt data to receive

        :param custom_ecowitt_path: path for ecowitt data upload
        :type custom_ecowitt_path: str
        :param custom_wu_path: path for wu data upload
        :type custom_wu_path: str
        """

        result = self.api_driver.collector.set_usr_path(custom_ecowitt_path, custom_wu_path)
        if result == 'SUCCESS' or result == 'NO NEED':
            self.logger.debug(f"set_usr_path: {result}")
        else:
            self.logger.error(f"set_usr_path: {result}")

    def set_custom_params(self, custom_server_id: str, custom_password: str, custom_host: str, custom_port: int, custom_interval: int, custom_type: bool, custom_enabled: bool):
        """
        Set customer parameter for Ecowitt data to receive

        :param custom_server_id: custom_server_id
        :param custom_password: custom_password
        :param custom_host: Ip address of customer host
        :param custom_port: port of customer host
        :param custom_interval: cycle of data upload
        :param custom_type: type of custom data upload
        :param custom_enabled: enable / disable custom upload
        """

        result = self.api_driver.collector.set_custom_params(custom_server_id, custom_password, custom_host, custom_port, custom_interval, custom_type, custom_enabled)
        if result == 'SUCCESS' or result == 'NO NEED':
            self.logger.debug(f"set_custom_params: {result}")
        else:
            self.logger.error(f"set_custom_params: {result}")

    def reboot(self):
        """
        Reboot device
        """

        result = self.api_driver.collector.reboot()
        if result == 'SUCCESS' or result == 'NO NEED':
            self.logger.debug(f"reboot: {result}")
        else:
            self.logger.error(f"reboot: {result}")

    def reset(self):
        """
        Reset device
        """

        result = self.api_driver.collector.reset()
        if result == 'SUCCESS' or result == 'NO NEED':
            self.logger.debug(f"reset: {result}")
        else:
            self.logger.error(f"reset: {result}")

    def update_gateway_meta_data_items(self):
        packet = dict()
        packet['gateway_model'] = self.stationmodel
        packet['frequency'] = self.system_parameters['frequency']
        packet['firmware_version'] = self.firmware_version
        self.update_item_values(packet, 'meta')

    @property
    def stationmodel(self) -> str:
        return self.api_driver.collector.station.model

    @property
    def firmware_version(self) -> str:
        return self.api_driver.collector.firmware_version

    @property
    def system_parameters(self) -> dict:
        return self.api_driver.collector.system_parameters

    @property
    def batterywarning(self) -> bool:
        return self._battery_warning

    @property
    def sensorwarning(self) -> bool:
        return self._sensor_warning

    @property
    def broadcast_address(self) -> str:
        return self._broadcast_address

    @property
    def broadcast_port(self) -> int:
        return self._broadcast_port

    @property
    def gateway_address(self):
        return self._gateway_address

    @property
    def gateway_port(self) -> int:
        return self._gateway_port

    @property
    def gateway_poll_cycle(self) -> int:
        return self._gateway_poll_cycle

    @property
    def log_level(self) -> int:
        return self.logger.getEffectiveLevel()

# ============================================================================
#                           Gateway API Error classes
# ============================================================================


class InvalidApiResponse(Exception):
    """Exception raised when an API call response is invalid."""


class InvalidChecksum(Exception):
    """Exception raised when an API call response contains an invalid checksum."""


class GW1000IOError(Exception):
    """Exception raised when an input/output error with the GW1000/GW1100 is encountered."""


class UnknownCommand(Exception):
    """Exception raised when an unknown API command is used."""

# ============================================================================
#                             Gateway API Object
# ============================================================================


class Gw1000(object):
    """
    Base class for interacting with a GW1000/GW1100.

    There are a number of common properties and methods (eg IP address, field map, rain calculation etc) when dealing with a GW1000/GW1100 as a driver.
    This class captures those common features.
    """

    def __init__(self, data_cycle, plugin_instance):
        """
        Initialise a GW1000 object.
        """

        # init logger
        self._plugin_instance = plugin_instance
        self.logger = self._plugin_instance.logger
        self.logger.debug("Init Gw1000 Object")

        # set the language property to the global language
        self.language = self._plugin_instance.language

        # how often (in seconds) we will receive data
        self.data_cycle = data_cycle

        # Is a WH32 in use. WH32 TH sensor can override/provide outdoor TH data to the GW1000/GW1100. In terms of TH data the process is transparent
        # and we do not need to know if a WH32 or other sensor is providing outdoor TH data but in terms of battery state we need to know so the
        # battery state data can be reported against the correct sensor.
        use_th32 = False

        # do we show all battery state data including nonsense data or do we filter those sensors with signal state == 0
        self.show_battery = False

        # create deque to hold 10 minutes of wind speed, wind direction and windgust
        self.wind_avg10m = deque(maxlen=(int(10*60/int(self.data_cycle))))

        # is there a battery warning (any battery low/critical)
        self.battery_warning = False

        # is there a sensor warning (any missed sensor)
        self.sensor_warning = False

        # SET SPECIFIC LOGGERS
        # set specific debug settings rain
        self.debug_rain = False
        # set specific debug settings wind
        self.debug_wind = False
        # set specific debug settings loop data
        self.debug_loop = False
        # set specific debug settings sensors
        self.debug_sensors = False

        # initialise last lightning count and last rain properties
        self.last_lightning = None
        self.last_rain = None
        self.rain_mapping_confirmed = False
        self.rain_total_field = None

        # Finally, log any config that is not being pushed any further down. Log specific debug but only if set to True
        debug_list = []
        if self.debug_rain:
            debug_list.append(f"debug_rain is {self.debug_rain}")
        if self.debug_wind:
            debug_list.append(f"debug_wind is {self.debug_wind}")
        if self.debug_loop:
            debug_list.append(f"debug_loop is {self.debug_loop}")
        if len(debug_list) > 0:
            self.logger.info(" ".join(debug_list))

    def add_calculated_data(self, data):
        """
        Add calculated data to dict

        :param data: dict of parsed GW1000/GW1100 API data
        :type data: dict
        """

        if "outtemp" in data:

            if "windspeed" in data:
                data['feels_like'] = self.get_windchill_index_metric(data["outtemp"], data["windspeed"])
                if data.keys() >= {"outhumid"}:
                    data['feels_like'] = self.calculate_feels_like(data["outtemp"], data["windspeed"])

            if "outhumid" in data:
                dewpt_c = self.get_dew_point_c(data["outtemp"], data["outhumid"])
                data['outdewpt'] = dewpt_c
                data['outfrostpt'] = self.get_frost_point_c(data["outtemp"], dewpt_c)
                data['cloud_ceiling'] = self.cloud_ceiling(data["outtemp"], dewpt_c)
                data['outabshum'] = self.get_abs_hum_c(data["outtemp"], data["outhumid"])

        if "intemp" in data and 'intemp' in data:
            data['indewpt'] = self.get_dew_point_c(data["intemp"], data["intemp"])
            data['inabshum'] = self.get_abs_hum_c(data["intemp"], data["intemp"])

        for i in range(1, 9):
            if f'temp{i}' in data and f'humid{i}' in data:
                data[f'dewpt{i}'] = self.get_dew_point_c(data[f'temp{i}'], data[f'humid{i}'])
                data[f'abshum{i}'] = self.get_abs_hum_c(data[f'temp{i}'], data[f'humid{i}'])

        if "winddir" in data:
            data['winddir_text'] = self.get_wind_dir_text(data["winddir"], self.language)

        if "windspeed" in data:
            windspeed_bft = self.get_beaufort_number(data["windspeed"])
            windspeed_bft_text = self.get_beaufort_description(windspeed_bft, self.language)
            data['windspeed_bft'] = windspeed_bft
            data['windspeed_bft_text'] = windspeed_bft_text

        if "absbarometer" in data:
            data['weather_text'] = self.get_weather_now(data["absbarometer"], self.language)

        if any(k in data for k in ('winddir', 'windspeed', 'gustspeed')):
            self.wind_avg10m.append([int(time.time()), data["windspeed"], data["winddir"], data["gustspeed"]])

            if "windspeed_avg10m" not in data:
                data['windspeed_avg10m'] = self.get_avg_wind(self.wind_avg10m, 1)

            if "winddir_avg10m" not in data:
                data['winddir_avg10m'] = self.get_avg_wind(self.wind_avg10m, 2)

            if "gustspeed_avg10m" not in data:
                data['gustspeed_avg10m'] = self.get_max_wind(self.wind_avg10m, 3)

    def get_cumulative_rain_field(self, data):
        """
        Determine the cumulative rain field used to derive field 'rain'.

        Ecowitt rain gauges/GW1000/GW1100 emit various rain totals but result needs a per period value for field rain. Try the 'big' (4 byte)
        counters starting at the longest period and working our way down. This should only need be done once.

        :param data: dict of parsed GW1000/GW1100 API data
        :type data: dict
        """

        self.rain_total_field = None

        for key in ('raintotals', 'rainyear', 'rainmonth'):
            if key in data:
                self.rain_total_field = key
                break

        if self.rain_total_field:
            self.rain_mapping_confirmed = True
            self.logger.info(f"Using '{self.rain_total_field}' for rain total")
        elif self.debug_rain:
            # if debug_rain is set log that we had nothing
            self.logger.info("No suitable field found for rain total")

    def calculate_rain(self, data):
        """
        Calculate total rainfall for a period.

        'rain' is calculated as the change in a user designated cumulative rain field between successive periods. 'rain' is only calculated if the
        field to be used has been selected and the designated field exists.

        :param data: dict of parsed GW1000/GW1100 API data
        :type data: dict
        """

        # have we decided on a field to use and is the field present
        if self.rain_mapping_confirmed and self.rain_total_field in data:
            # yes on both counts, so get the new total
            new_total = data[self.rain_total_field]
            # now calculate field rain as the difference between the new and old totals
            data['rain'] = self.delta_rain(new_total, self.last_rain)
            # if debug_rain is set log some pertinent values
            if self.debug_rain:
                self.logger.info(f"calculate_rain: last_rain={self.last_rain} new_total={new_total} calculated rain={data['rain']}")
            # save the new total as the old total for next time
            self.last_rain = new_total

    def calculate_lightning_count(self, data):
        """
        Calculate total lightning strike count for a period.

        'lightning_strike_count' is calculated as the change in field 'lightningcount' between successive periods. 'lightning_strike_count'
        is only calculated if 'lightningcount' exists.

        :param data: dict of parsed GW1000/GW1100 API data
        :type data: dict
        """

        # is the lightningcount field present
        if 'lightningcount' in data:
            # yes, so get the new total
            new_total = data['lightningcount']
            # now calculate field lightning_strike_count as the difference
            # between the new and old totals
            data['lightning_strike_count'] = self.delta_lightning(new_total, self.last_lightning)
            # save the new total as the old total for next time
            self.last_lightning = new_total

    def calculate_feels_like(self, temperature_c: float, windspeed_kmh: float) -> float:
        """
        Computes the feels-like temperature

        :param temperature_c: ambient temperature in celsius
        :param windspeed_kmh: wind speed in km/h
        :return: feels like temperature in celsius
        """

        # convert to fahrenheit and mph
        temperature_f = c_to_f(temperature_c, 2)
        windspeed_mph = kmh_to_mph(windspeed_kmh, 2)

        # Try Wind Chill first
        feels_like = self.get_windchill_index_imperial(temperature_f, windspeed_mph)

        # Replace it with the Heat Index, if necessary
        if feels_like == temperature_f and temperature_f >= 80:
            feels_like = self.get_heat_index(temperature_f, windspeed_mph)

        # convert back to celsius and return
        return f_to_c(feels_like, 1)

    @staticmethod
    def delta_rain(rain: float, last_rain: float) -> Union[None, float]:
        """
        Calculate rainfall from successive cumulative values.

        Rainfall is calculated as the difference between two cumulative values.
        If either value is None the value None is returned. If the previous
        value is greater than the latest value a counter wrap around is assumed
        and the latest value is returned.

        :param rain:      current cumulative rain value
        :param last_rain: last cumulative rain value
        """

        logger = logging.getLogger(__name__)

        # logger.debug(f"delta_rain: rain={rain}, last_rain={last_rain}")

        # do we have a last rain value
        if last_rain is None:
            # no, log it and return None
            logger.info(f"skipping rain measurement of {rain}: no last rain")
            return None
        # do we have a non-None current rain value
        if rain is None:
            # no, log it and return None
            logger.info("skipping rain measurement: no current rain")
            return None
        # is the last rain value greater than the current rain value
        if rain < last_rain:
            # it is, assume a counter wrap around/reset, log it and return the
            # latest rain value
            logger.info(f"rain counter wraparound detected: new={rain} last={last_rain}")
            return rain
        # otherwise return the difference between the counts
        return rain - last_rain

    @staticmethod
    def delta_lightning(count: int, last_count: int) -> Union[None, int]:
        """
        Calculate lightning strike count from successive cumulative values.

        Lightning strike count is calculated as the difference between two
        cumulative values. If either value is None the value None is returned.
        If the previous value is greater than the latest value a counter wrap
        around is assumed and the latest value is returned.

        :param count:      current cumulative lightning count
        :param last_count: last cumulative lightning count
        """

        logger = logging.getLogger(__name__)

        # do we have a last count
        if last_count is None:
            # no, log it and return None
            logger.info(f"Skipping lightning count of {count}: no last count")
            return None
        # do we have a non-None current count
        if count is None:
            # no, log it and return None
            logger.info("Skipping lightning count: no current count")
            return None
        # is the last count greater than the current count
        if count < last_count:
            # it is, assume a counter wrap around/reset, log it and return the
            # latest count
            logger.info(f"Lightning counter wraparound detected: new={count} last={last_count}")
            return count
        # otherwise return the difference between the counts
        return count - last_count

    @staticmethod
    def get_dew_point_c(t_air_c: float, rel_humidity: float) -> float:
        """
        Compute the dew point in degrees Celsius

        :param t_air_c: current ambient temperature in degrees Celsius
        :param rel_humidity: relative humidity in %
        :return: the dew point in degrees Celsius
        """

        const = MAGNUS_COEFFICIENTS['positive'] if t_air_c > 0 else MAGNUS_COEFFICIENTS['negative']

        try:
            pa = rel_humidity / 100. * math.exp(const['b'] * t_air_c / (const['c'] + t_air_c))
            dew_point_c = round(const['c'] * math.log(pa) / (const['b'] - math.log(pa)), 1)
        except ValueError:
            dew_point_c = -9999
        return dew_point_c

    @staticmethod
    def get_frost_point_c(t_air_c: float, dew_point_c: float) -> float:
        """
        Compute the frost point in degrees Celsius

        :param t_air_c: current ambient temperature in degrees Celsius
        :param dew_point_c: current dew point in degrees Celsius
        :return: the frost point in degrees Celsius
        """

        try:
            dew_point_k = 273.15 + dew_point_c
            t_air_k = 273.15 + t_air_c
            frost_point_k = dew_point_k - t_air_k + 2671.02 / ((2954.61 / t_air_k) + 2.193665 * math.log(t_air_k) - 13.3448)
            frost_point_c = round(frost_point_k - 273.15, 1)
        except ValueError:
            frost_point_c = -9999
        return frost_point_c

    @staticmethod
    def get_abs_hum_c(t_air_c: float, rel_humidity: float) -> float:
        """
        Return the absolute humidity in (g/cm3) from the relative humidity in % and temperature (Celsius)
    
        :param t_air_c: temperature in celsius
        :param rel_humidity: relative humidity in %
        :return: val = absolute humidity in (g/cm3)
        """

        const = MAGNUS_COEFFICIENTS['positive'] if t_air_c > 0 else MAGNUS_COEFFICIENTS['negative']
        mw = 18.016  # kg/kmol (Molekulargewicht des Wasserdampfes)
        rs = 8314.3  # J/(kmol*K) (universelle Gaskonstante)

        def svp():
            """Compute saturated water vapor pressure (Sättigungsdampfdruck) in hPa"""
            return const['a'] * math.exp((const['b'] * t_air_c) / (const['c'] + t_air_c))

        def vp():
            """Compute actual water vapor pressure (Dampfdruck) in hPa"""
            return rel_humidity / 100 * svp()

        return round(10 ** 5 * mw / rs * vp() / (t_air_c + 273.15), 1)

    @staticmethod
    def get_windchill_index_metric(t_air_c: float, wind_speed: float) -> float:
        """
        Compute the wind chill index

        :param t_air_c: current ambient temperature in degrees Celsius
        :param wind_speed: wind speed in kilometers/hour
        :return: the wind chill index
        """

        return round(13.12 + 0.6215*t_air_c - 11.37*math.pow(wind_speed, 0.16) + 0.3965*t_air_c*math.pow(wind_speed, 0.16), 1)

    @staticmethod
    def get_windchill_index_imperial(air_temp_f: float, wind_speed_mph: float) -> float:
        """
        Compute the wind chill index

        :param air_temp_f: current ambient temperature in fahrenheit
        :param wind_speed_mph: wind speed in miles/hour
        :return: the wind chill index
        """

        if air_temp_f <= 50 and wind_speed_mph >= 3:
            windchill = 35.74 + (0.6215*air_temp_f) - 35.75*(wind_speed_mph**0.16) + ((0.4275*air_temp_f)*(wind_speed_mph**0.16))
        else:
            windchill = air_temp_f

        return round(windchill, 1)

    @staticmethod
    def get_heat_index(temperature_f: float, rel_hum: float):
        """
        Compute the heat index

        :param temperature_f: current ambient temperature in fahrenheit
        :type temperature_f: float
        :param rel_hum: rel humidity
        :type rel_hum: float

        :return: the heat index
        :rtype: float
        """

        heat_index = 0.5 * (temperature_f + 61.0 + ((temperature_f-68.0)*1.2) + (rel_hum*0.094))
        if heat_index >= 80:
            heat_index = -42.379 + 2.04901523*temperature_f + 10.14333127*rel_hum - .22475541*temperature_f*rel_hum - .00683783*temperature_f*temperature_f - .05481717*rel_hum*rel_hum + .00122874*temperature_f*temperature_f*rel_hum + .00085282*temperature_f*rel_hum*rel_hum - .00000199*temperature_f*temperature_f*rel_hum*rel_hum
            if rel_hum < 13 and 80 <= temperature_f <= 112:
                heat_index = heat_index - ((13-rel_hum)/4)*math.sqrt((17-math.fabs(temperature_f-95.))/17)
                if rel_hum > 85 and 80 <= temperature_f <= 87:
                    heat_index = heat_index + ((rel_hum-85)/10) * ((87-temperature_f)/5)
        return round(heat_index, 1)

    @staticmethod
    def get_weather_now(hpa: float, lang: str = 'de') -> str:
        """
        Computes text for current weather condition

        :param hpa: current air pressure in hpa
        :param lang: acronym of language
        :return: wind direction text
        """

        _weather_now_de = ["undefiniert", "stürmisch, Regen", "regnerisch", "wechselhaft", "sonnig", "trocken, Gewitter"]
        _weather_now_en = ["undefined", "stormy, rainy", "rainy", "unstable", "sunny", "dry, thunderstorm"]

        if hpa <= 980:
            entry = 1                # stürmisch, Regen
        elif 980 < hpa <= 1000:
            entry = 2                # regnerisch
        elif 1000 < hpa <= 1020:
            entry = 3                # wechselhaft
        elif 1020 < hpa <= 1040:
            entry = 4                # sonnig
        elif 1040 < hpa:
            entry = 5                # trocken, Gewitter
        else:
            entry = 0

        if lang == 'de':
            return _weather_now_de[entry]
        else:
            return _weather_now_en[entry]

    @staticmethod
    def get_wind_dir_text(wdir: float, lang: str = 'de') -> str:
        """
        Computes wind direction text on wind direction in degrees

        :param wdir: wind direction in degrees
        :param lang: acronym of language
        :return: wind direction text
        """

        _wind_dir_zz = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE", "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]
        _wind_dir_de = ["Nord", "Nordnordost", "Nordost", "Ostnordost", "Ost", "Ostsüdost", "Südost", "Südsüdost", "Süd", "Südsüdwest", "Südwest", "Westsüdwest", "West", "Westnordwest", "Nordwest", "Nordnordwest"]
        _wind_dir_en = ["north", "north-northeast", "northeast", "east-northeast", "east", "east-southeast", "southeast", "south-southeast", "south", "south-southwest", "southwest", "west-southwest", "west", "west-northwest", "north-west", "north-northwest"]
        _wind_dir_xx = ["N", "N-NO", "NO", "O-NO", "O", "O-SO", "SO", "S-SO", "S", "S-SW", "SW", "W-SW", "W", "W-NW", "NW", "N-NW"]

        if lang == 'de':
            dir_list = _wind_dir_de
        elif lang == 'en':
            dir_list = _wind_dir_en
        elif lang == 'xx':
            dir_list = _wind_dir_xx
        else:
            dir_list = _wind_dir_zz

        try:
            val = int((float(wdir)/22.5)+.5)
            s = dir_list[(val % 16)]
        except ValueError:
            s = "null"
        return s

    @staticmethod
    def make_weather_forecast(diff: float, lang: str = 'de') -> str:
        """
        Computes weather forecast based on changes for relative air pressure

        :param diff: pressure difference between now and 3 hours ago
        :param lang: acronym of language
        :return: the wind chill index
        """

        _weather_forecast_de = ["Sturm mit Hagel", "Regen/Unwetter", "regnerisch", "baldiger Regen", "gleichbleibend", "lange schön", "schön & labil", "Sturmwarnung"]
        _weather_forecast_en = ["storm with hail", "rain/storm", "rainy", "soon rain", "constant", "nice for a long time", "nice & unstable", "storm warning"]

        _weather_forecast = _weather_forecast_de if lang == "de" else _weather_forecast_en

        if diff <= -8:
            wproglvl = 0               # Sturm mit Hagel
        elif -8 < diff <= -5:
            wproglvl = 1               # Regen/Unwetter
        elif -5 < diff <= -3:
            wproglvl = 2               # regnerisch
        elif -3 < diff <= -0.5:
            wproglvl = 3               # baldiger Regen
        elif -0.5 < diff <= 0.5:
            wproglvl = 4               # gleichbleibend
        elif 0.5 < diff <= 3:
            wproglvl = 5               # lange schön
        elif 3 < diff <= 5:
            wproglvl = 6               # schön & labil
        elif 5 < diff:
            wproglvl = 7               # Sturmwarnung
        else:
            wproglvl = 0

        wprogtxt = _weather_forecast[wproglvl]
        return wprogtxt

    @staticmethod
    def cloud_ceiling(temp: float, dewpt: float) -> float:
        """
        Computes cloud ceiling (Wolkenuntergrenze/Konvektionskondensationsniveau)

        :param temp: outside temperatur in celsius
        :param dewpt: outside dew point in celsius
        :return: cloud ceiling in meter
        """

        # Faustformel für die Berechnung der Höhe der Wolkenuntergrenze von Quellwolken: Höhe in Meter = 122 mal Spread (Taupunktdifferenz)
        return int(round((temp - dewpt) * 122, 1))

    @staticmethod
    def get_avg_wind(d, w):
        """
        get avg from deque d , field w
        """

        s = 0
        for i in range(len(d)):
            s = s + d[i][w]
        return round(s/len(d), 1)

    @staticmethod
    def get_max_wind(d, w):
        """
        get max from deque d, field w
        """

        s = 0
        for i in range(len(d)):
            if d[i][w] > s:
                s = d[i][w]
        return round(s, 1)

    @staticmethod
    def get_beaufort_number(speed_in_mps: float) -> Union[None, int]:
        """
        get the beaufort number from windspeed in meters per second
        """

        try:
            # Origin of table: https://www.smarthomeng.de/vom-winde-verweht
            table = [
                (0.3, 0),
                (1.6, 1),
                (3.4, 2),
                (5.5, 3),
                (8.0, 4),
                (10.8, 5),
                (13.9, 6),
                (17.2, 7),
                (20.8, 8),
                (24.5, 9),
                (28.5, 10),
                (32.7, 11),
                (999,  12)]
            return min(filter(lambda x: x[0] >= speed_in_mps, table))[1]
        except ValueError:
            return None

    @staticmethod
    def get_beaufort_description(speed_in_bft: int, lang: str = 'de') -> Union[None, str]:
        """
        get the beaufort description from beaufort number
        """

        # source for german descriptions https://www.smarthomeng.de/vom-winde-verweht
        _beaufort_descriptions_de = ["Windstille",
                                     "leiser Zug",
                                     "leichte Brise",
                                     "schwacher Wind",
                                     "mäßiger Wind",
                                     "frischer Wind",
                                     "starker Wind",
                                     "steifer Wind",
                                     "stürmischer Wind",
                                     "Sturm",
                                     "schwerer Sturm",
                                     "orkanartiger Sturm",
                                     "Orkan"]
        # source for english descriptions https://simple.wikipedia.org/wiki/Beaufort_scale
        _beaufort_descriptions_en = ["Calm",
                                     "Light air",
                                     "Light breeze",
                                     "Gentle breeze",
                                     "Moderate breeze",
                                     "Fresh breeze",
                                     "Strong breeze",
                                     "High wind",
                                     "Fresh Gale",
                                     "Strong Gale",
                                     "Storm",
                                     "Violent storm",
                                     "Hurricane-force"]

        logger = logging.getLogger(__name__)

        if speed_in_bft is None:
            logger.warning(f"speed_in_bft is given as None")
            return None
        if type(speed_in_bft) is not int:
            logger.error(f"speed_in_bft is not given as int: '{speed_in_bft}'")
            return None
        if (speed_in_bft < 0) or (speed_in_bft > 12):
            logger.error(f"speed_in_bft is out of scale: '{speed_in_bft}'")
            return None
        if lang == 'de':
            return _beaufort_descriptions_de[speed_in_bft]
        return _beaufort_descriptions_en[speed_in_bft]


class Collector(object):
    """
    Base class for a client that polls an API.
    """

    # a queue object for passing data back to the driver
    my_queue = queue.Queue()

    def __init__(self, plugin_instance):
        self._plugin_instance = plugin_instance
        self.logger = self._plugin_instance.logger
        self.logger.debug('Init Collector Object')
        self.queue = queue.Queue()
        pass

    def startup(self):
        pass

    def shutdown(self):
        pass


# ============================================================================
#                            Gateway API classes
# ============================================================================


class Gw1000Driver(Gw1000):
    """GW1000/GW1100 driver class.

    A driver to emit loop packets based on observational data obtained from the GW1000/GW1100 API. The Gw1000Driver should be used when there is no other data source.

    Data is obtained from the GW1000/GW1100 API. The data is parsed and emitted as a loop packet.

    Class Gw1000Collector collects and parses data from the GW1000/GW1100 API. The Gw1000Collector runs in a separate thread so as to not block the main
    processing loop. The Gw1000Collector is turn uses child classes Station and Parser to interact directly with the GW1000/GW1100 API and
    parse the API responses respectively."""

    def __init__(self,
                 plugin_instance,
                 poll_interval: int,
                 broadcast_address=None,
                 broadcast_port=None,
                 ip_address=None,
                 gateway_port=None,
                 use_th32=False):
        """
        Initialise a GW1000/GW1100 driver object.
        """

        # get instance
        self._plugin_instance = plugin_instance
        self.logger = self._plugin_instance.logger

        # get data poll cycle
        self.poll_interval = poll_interval

        self.driver_alive = False

        # now initialize my superclasses
        super().__init__(self.poll_interval, self._plugin_instance)

        # network broadcast address and port
        self.broadcast_address = broadcast_address
        if self.broadcast_address is None:
            self.broadcast_address = DEFAULT_BROADCAST_ADDRESS

        self.broadcast_port = broadcast_port
        if self.broadcast_port is None:
            self.broadcast_port = DEFAULT_BROADCAST_PORT

        self.socket_timeout = DEFAULT_SOCKET_TIMEOUT
        self.broadcast_timeout = DEFAULT_BROADCAST_TIMEOUT

        # set the IP address property to the GW1000/GW1100 IP address
        self.ip_address = ip_address  # will be None if it need to be auto detected

        # set the port property from obtain the GW1000/GW1100 port from the config dict for port number we have a default value we can use, so if port is not specified use the default
        self.port = gateway_port  # will be None if it need to be auto detected

        # how many times to poll the API before giving up, default is DEFAULT_MAX_TRIES
        self.max_tries = DEFAULT_MAX_TRIES

        # wait time in seconds between retries, default is DEFAULT_RETRY_WAIT seconds
        self.retry_wait = DEFAULT_RETRY_WAIT

        # log the relevant settings/parameters we are using
        self.logger.debug("Starting Gw1000Driver")

        # Is a WH32 in use. WH32 TH sensor can override/provide outdoor TH data to the GW1000/GW1100. In terms of TH data the process is transparent
        # and we do not need to know if a WH32 or other sensor is providing outdoor TH data but in terms of battery state we need to know so the
        # battery state data can be reported against the correct sensor.
        use_th32 = use_th32

        # log all found sensors since beginning of plugin as a set
        self.sensors = []

        # log sensors, that were missed with count of cycles
        self.sensors_missed = {}

        # create an Gw1000Collector object to interact with the GW1000/GW1100 API
        self.collector = Gw1000Collector(ip_address=self.ip_address,
                                         port=self.port,
                                         broadcast_address=self.broadcast_address,
                                         broadcast_port=self.broadcast_port,
                                         socket_timeout=self.socket_timeout,
                                         broadcast_timeout=self.broadcast_timeout,
                                         poll_interval=self.poll_interval,
                                         max_tries=self.max_tries,
                                         retry_wait=self.retry_wait,
                                         use_th32=use_th32,
                                         show_battery=self.show_battery,
                                         debug_rain=self.debug_rain,
                                         debug_wind=self.debug_wind,
                                         debug_sensors=self.debug_sensors,
                                         plugin_instance=self._plugin_instance)

        # log setup
        if self.ip_address is None and self.port is None:
            self.logger.info(f'{self.collector.station.model} IP address and port not specified, attempting to discover {self.collector.station.model}...')
        elif self.ip_address is None:
            self.logger.info(f'{self.collector.station.model} IP address not specified, attempting to discover {self.collector.station.model}...')
        elif self.port is None:
            self.logger.info(f'{self.collector.station.model} port not specified, attempting to discover {self.collector.station.model}...')
        self.logger.info(f'{self.collector.station.model} address is {self.collector.station.ip_address.decode()}:{self.collector.station.port}')
        self.logger.info(f'poll interval is {self.poll_interval} seconds')
        self.logger.debug(f'max tries is {self.max_tries}, retry wait time is {self.retry_wait} seconds')
        self.logger.debug(f'broadcast address is {self.broadcast_address}:{self.broadcast_port}, broadcast timeout is {self.broadcast_timeout} seconds')
        self.logger.debug(f'socket timeout is {self.socket_timeout} seconds')

        # start the Gw1000Collector in its own thread
        self.collector.startup()
        self.driver_alive = True

    def genLoopPackets(self):
        """
        Generator function that returns loop packets.

        Run a continuous loop checking the Gw1000Collector queue for data. When data arrives map the raw data to a loop packet and yield the packet.
        """

        # generate loop packets forever
        while self.driver_alive:
            # wrap in a try to catch any instances where the queue is empty
            try:
                # get any data from the collector queue
                queue_data = self.collector.data_queue.get(True, 10)
            except queue.Empty:
                # self.logger.debug("API. genLoopPackets: there was nothing in the queue so continue")
                # there was nothing in the queue so continue
                pass
            else:
                # We received something in the queue, it will be one of three things:
                # 1. a dict containing sensor data
                # 2. an exception
                # 3. the value None signalling a serious error that means the Collector needs to shut down

                # if the data is of instance dict, it must have data
                if isinstance(queue_data, dict):
                    self.logger.debug(f"API. genLoopPackets: queue_data={queue_data}")
                    # Now start to create a loop packet.

                    # put timestamp of now to packet
                    packet = {'timestamp': int(time.time() + 0.5)}

                    if 'datetime' in queue_data and isinstance(queue_data['datetime'], datetime):
                        packet['datetime_utc'] = queue_data['datetime']
                    else:
                        # we don't have a datetime at utc so create one
                        packet['datetime_utc'] = datetime.utcnow().replace(tzinfo=timezone.utc, microsecond=0)

                    if self.debug_loop:
                        self.logger.debug(f"Received {self.collector.station.model} data (debug_loop): {datetime_to_string(packet['datetime_utc'])} {natural_sort_dict(queue_data)}")

                    # if not already determined, determine which cumulative rain field will be used to determine the per period rain field
                    if not self.rain_mapping_confirmed:
                        self.get_cumulative_rain_field(queue_data)

                    # get the rainfall for this period from total
                    self.calculate_rain(queue_data)

                    # get the lightning strike count for this period from total
                    self.calculate_lightning_count(queue_data)

                    # add calculated data to queue_data
                    self.add_calculated_data(queue_data)

                    # add sensor warning data field and log entry if enabled
                    if self._plugin_instance.sensorwarning:
                        self.check_sensors(queue_data)

                    # add battery warning data field and log entry if enabled
                    if self._plugin_instance.batterywarning:
                        self.check_battery(queue_data)

                    # add the queue_data to the empty packet
                    packet.update(queue_data)

                    # log the packet if necessary, there are several debug settings that may require this, start from the highest (most encompassing) and work to the lowest (least encompassing)
                    if self.debug_loop:
                        self.logger.info(f"API. genLoopPackets: Packet {datetime_to_string(packet['datetime_utc'])}: {natural_sort_dict(packet)}")
                    # yield the loop packet
                    yield packet
                    # time.sleep(self.poll_interval)

                # if it's a tuple then it's a tuple with an exception and exception text
                elif isinstance(queue_data, BaseException):
                    # We have an exception. The collector did not deem it serious enough to want to shutdown or it would have sent None instead. If it is anything else we log it and then raise it.

                    # first extract our exception
                    e = queue_data
                    # and process it if we have something
                    if e:
                        # is it a GW1000Error
                        self.logger.error(f"Caught unexpected exception {e.__class__.__name__}: {e}")
                        # then raise it
                        raise e

                # if it's None then its a signal, the Collector needs to shutdown
                elif queue_data is None:
                    # if debug_loop log what we received
                    if self.debug_loop:
                        self.logger.info("Received 'None'")
                    # we received the signal to shutdown, so call closePort()
                    self.closePort()
                    # and raise an exception to cause the engine to shutdown
                    raise GW1000IOError("Gw1000Collector needs to shutdown")
                # if it's none of the above (which it should never be) we don't know what to do with it so pass and wait for the next item in the queue

    def check_battery(self, data):
        """
        Check if batteries states are critical, create log entry and add a separate field for battery warning.
        """

        # get battery data
        raw_data = self.collector.battery_desc
        # init string to collect message
        batterycheck = ''
        # iterate over data to look for critical battery
        for key in raw_data:
            if raw_data[key] != 'OK':
                if batterycheck != '':
                    batterycheck += ', '
                batterycheck += key
        # check result, create log entry data field
        if batterycheck != "":
            data['battery_warning'] = 0
            if not self.battery_warning:
                self.logger.warning(f"<WARNING> Battery level for sensor(s) {batterycheck} is critical - please swap battery")
                self.battery_warning = True
                data['battery_warning'] = 1
        elif self.battery_warning:
            self.logger.info("<OK> Battery level for all sensors is ok again")
            self.battery_warning = False
            data['battery_warning'] = 0

    def check_sensors(self, data: dict, missing_count: int = 2):
        """
        Check if all know sensors are still connected, create log entry and add a separate field for sensor warning.
        """

        # get currently connected sensors
        connected_sensors = self.collector.sensors.connected_sensors
        # self.logger.debug(f"check_sensors: connected_sensors={connected_sensors}")
        # log all found sensors during runtime
        self.sensors = list(set(self.sensors + connected_sensors))
        # check if all sensors are still connected, create log entry data field
        if set(connected_sensors) == set(self.sensors):
            # self.logger.debug(f"check_sensors: All sensors are still connected!")
            self.sensor_warning = False
            data['sensor_warning'] = 0
        else:
            missing_sensors = list(set(self.sensors).difference(set(connected_sensors)))
            self.update_missing_sensor_dict(missing_sensors)

            blacklist = set()
            for sensor in self.sensors_missed:
                if self.sensors_missed[sensor] >= missing_count:
                    blacklist.add(sensor)

            if blacklist:
                self.logger.error(f"API: check_sensors: The following sensors where lost (more than {missing_count} data cycles): {list(blacklist)}")
                self.sensor_warning = True
                data['sensor_warning'] = 1
            else:
                self.sensor_warning = False
                data['sensor_warning'] = 0

    def update_missing_sensor_dict(self, missing_sensors: list):
        """
        Get list of sensors, which were lost/missed in last data cycle and udpate missing_sensor_dict with count of missing cycles.
        """

        for sensor in missing_sensors:
            if sensor not in self.sensors_missed:
                self.sensors_missed[sensor] = 1
            else:
                self.sensors_missed[sensor] += 1

        self.logger.debug(f"sensors_missed={self.sensors_missed}")

    @property
    def hardware_name(self):
        """
        Return the hardware name.

        Use the device model from our Collector's Station object, but if this
        is None use the driver name.
        """

        if self.collector.station.model is not None:
            return self.collector.station.model

    @property
    def mac_address(self):
        """
        Return the GW1000/GW1100 MAC address.
        """

        return self.collector.mac_address

    @property
    def firmware_version(self):
        """
        Return the GW1000/GW1100 firmware version string.
        """

        return self.collector.firmware_version

    @property
    def sensor_id_data(self):
        """
        Return the GW1000/GW1100 sensor identification data.

        The sensor ID data is available via the data property of the Collector objects' sensors property.
        """

        return self.collector.sensors.data

    def closePort(self):
        """
        Close down the driver port.
        """

        # in this case there is no port to close, just shutdown the collector
        self.driver_alive = False
        self.collector.shutdown()


class Gw1000Collector:
    """
    Class to poll the GW1000/GW1100 API, decode and return data to the driver.
    """

    # map of sensor ids to short name, long name and battery byte decode function
    sensor_ids = {
        b'\x00': {'name': 'wh65', 'long_name': 'WH65', 'batt_fn': 'batt_binary'},
        b'\x01': {'name': 'wh68', 'long_name': 'WH68', 'batt_fn': 'batt_volt'},
        b'\x02': {'name': 'ws80', 'long_name': 'WS80', 'batt_fn': 'batt_volt'},
        b'\x03': {'name': 'wh40', 'long_name': 'WH40', 'batt_fn': 'batt_binary'},
        b'\x04': {'name': 'wh25', 'long_name': 'WH25', 'batt_fn': 'batt_binary'},
        b'\x05': {'name': 'wh26', 'long_name': 'WH26', 'batt_fn': 'batt_binary'},
        b'\x06': {'name': 'wh31_ch1', 'long_name': 'WH31 ch1', 'batt_fn': 'batt_binary'},
        b'\x07': {'name': 'wh31_ch2', 'long_name': 'WH31 ch2', 'batt_fn': 'batt_binary'},
        b'\x08': {'name': 'wh31_ch3', 'long_name': 'WH31 ch3', 'batt_fn': 'batt_binary'},
        b'\x09': {'name': 'wh31_ch4', 'long_name': 'WH31 ch4', 'batt_fn': 'batt_binary'},
        b'\x0a': {'name': 'wh31_ch5', 'long_name': 'WH31 ch5', 'batt_fn': 'batt_binary'},
        b'\x0b': {'name': 'wh31_ch6', 'long_name': 'WH31 ch6', 'batt_fn': 'batt_binary'},
        b'\x0c': {'name': 'wh31_ch7', 'long_name': 'WH31 ch7', 'batt_fn': 'batt_binary'},
        b'\x0d': {'name': 'wh31_ch8', 'long_name': 'WH31 ch8', 'batt_fn': 'batt_binary'},
        b'\x0e': {'name': 'wh51_ch1', 'long_name': 'WH51 ch1', 'batt_fn': 'batt_binary'},
        b'\x0f': {'name': 'wh51_ch2', 'long_name': 'WH51 ch2', 'batt_fn': 'batt_binary'},
        b'\x10': {'name': 'wh51_ch3', 'long_name': 'WH51 ch3', 'batt_fn': 'batt_binary'},
        b'\x11': {'name': 'wh51_ch4', 'long_name': 'WH51 ch4', 'batt_fn': 'batt_binary'},
        b'\x12': {'name': 'wh51_ch5', 'long_name': 'WH51 ch5', 'batt_fn': 'batt_binary'},
        b'\x13': {'name': 'wh51_ch6', 'long_name': 'WH51 ch6', 'batt_fn': 'batt_binary'},
        b'\x14': {'name': 'wh51_ch7', 'long_name': 'WH51 ch7', 'batt_fn': 'batt_binary'},
        b'\x15': {'name': 'wh51_ch8', 'long_name': 'WH51 ch8', 'batt_fn': 'batt_binary'},
        b'\x16': {'name': 'wh41_ch1', 'long_name': 'WH41 ch1', 'batt_fn': 'batt_int'},
        b'\x17': {'name': 'wh41_ch2', 'long_name': 'WH41 ch2', 'batt_fn': 'batt_int'},
        b'\x18': {'name': 'wh41_ch3', 'long_name': 'WH41 ch3', 'batt_fn': 'batt_int'},
        b'\x19': {'name': 'wh41_ch4', 'long_name': 'WH41 ch4', 'batt_fn': 'batt_int'},
        b'\x1a': {'name': 'wh57', 'long_name': 'WH57', 'batt_fn': 'batt_int'},
        b'\x1b': {'name': 'wh55_ch1', 'long_name': 'WH55 ch1', 'batt_fn': 'batt_int'},
        b'\x1c': {'name': 'wh55_ch2', 'long_name': 'WH55 ch2', 'batt_fn': 'batt_int'},
        b'\x1d': {'name': 'wh55_ch3', 'long_name': 'WH55 ch3', 'batt_fn': 'batt_int'},
        b'\x1e': {'name': 'wh55_ch4', 'long_name': 'WH55 ch4', 'batt_fn': 'batt_int'},
        b'\x1f': {'name': 'wh34_ch1', 'long_name': 'WH34 ch1', 'batt_fn': 'batt_volt'},
        b'\x20': {'name': 'wh34_ch2', 'long_name': 'WH34 ch2', 'batt_fn': 'batt_volt'},
        b'\x21': {'name': 'wh34_ch3', 'long_name': 'WH34 ch3', 'batt_fn': 'batt_volt'},
        b'\x22': {'name': 'wh34_ch4', 'long_name': 'WH34 ch4', 'batt_fn': 'batt_volt'},
        b'\x23': {'name': 'wh34_ch5', 'long_name': 'WH34 ch5', 'batt_fn': 'batt_volt'},
        b'\x24': {'name': 'wh34_ch6', 'long_name': 'WH34 ch6', 'batt_fn': 'batt_volt'},
        b'\x25': {'name': 'wh34_ch7', 'long_name': 'WH34 ch7', 'batt_fn': 'batt_volt'},
        b'\x26': {'name': 'wh34_ch8', 'long_name': 'WH34 ch8', 'batt_fn': 'batt_volt'},
        b'\x27': {'name': 'wh45', 'long_name': 'WH45', 'batt_fn': 'batt_int'},
        b'\x28': {'name': 'wh35_ch1', 'long_name': 'WH35 ch1', 'batt_fn': 'batt_volt'},
        b'\x29': {'name': 'wh35_ch2', 'long_name': 'WH35 ch2', 'batt_fn': 'batt_volt'},
        b'\x2a': {'name': 'wh35_ch3', 'long_name': 'WH35 ch3', 'batt_fn': 'batt_volt'},
        b'\x2b': {'name': 'wh35_ch4', 'long_name': 'WH35 ch4', 'batt_fn': 'batt_volt'},
        b'\x2c': {'name': 'wh35_ch5', 'long_name': 'WH35 ch5', 'batt_fn': 'batt_volt'},
        b'\x2d': {'name': 'wh35_ch6', 'long_name': 'WH35 ch6', 'batt_fn': 'batt_volt'},
        b'\x2e': {'name': 'wh35_ch7', 'long_name': 'WH35 ch7', 'batt_fn': 'batt_volt'},
        b'\x2f': {'name': 'wh35_ch8', 'long_name': 'WH35 ch8', 'batt_fn': 'batt_volt'}
    }

    # list of dicts of weather services that I know about
    services = [{'name': 'ecowitt_net', 'long_name': 'Ecowitt.net'},
                {'name': 'wunderground', 'long_name': 'Wunderground'},
                {'name': 'weathercloud', 'long_name': 'Weathercloud'},
                {'name': 'wow', 'long_name': 'Weather Observations Website'},
                {'name': 'custom', 'long_name': 'Customized'}
                ]

    # create queue object
    data_queue = queue.Queue()

    def __init__(self,
                 ip_address=None,
                 port=None,
                 broadcast_address=None,
                 broadcast_port=None,
                 socket_timeout=None,
                 broadcast_timeout=None,
                 poll_interval=0,
                 max_tries=DEFAULT_MAX_TRIES,
                 retry_wait=DEFAULT_RETRY_WAIT,
                 use_th32=False,
                 show_battery=False,
                 debug_rain=False,
                 debug_wind=False,
                 debug_sensors=False,
                 plugin_instance=None):
        """
        Initialise our class.
        """

        # initialize my base class:
        # super().__init__(plugin_instance)

        # handle plugin instance
        self._plugin_instance = plugin_instance
        self.logger = self._plugin_instance.logger

        # interval between polls of the API, use a default
        self.poll_interval = poll_interval

        # how many times to poll the API before giving up, default is DEFAULT_MAX_TRIES
        self.max_tries = max_tries

        # period in seconds to wait before polling again, default is DEFAULT_RETRY_WAIT seconds
        self.retry_wait = retry_wait

        # are we using a th32 sensor
        self.use_th32 = use_th32

        # create queue object
        self.data_queue = queue.Queue()

        # get a station object to do the handle the interaction with the GW1000/GW1100 API
        self.station = Gw1000Collector.Station(ip_address=ip_address,
                                               port=port,
                                               broadcast_address=broadcast_address,
                                               broadcast_port=broadcast_port,
                                               socket_timeout=socket_timeout,
                                               broadcast_timeout=broadcast_timeout,
                                               max_tries=max_tries,
                                               retry_wait=retry_wait)

        # Do we have a WH24 attached? First obtain our system parameters.
        _sys_params = self.station.get_system_params()

        # WH24 is indicated by the 6th byte being 0
        is_wh24 = _sys_params[5] == 0

        # Tell our sensor id decoding whether we have a WH24 or a WH65. By default we are coded to use a WH65. Is there a WH24 connected?
        if is_wh24:
            # set the WH24 sensor id decode dict entry
            self.sensor_ids[b'\x00']['name'] = 'wh24'
            self.sensor_ids[b'\x00']['long_name'] = 'WH24'

        # start off logging failures
        self.log_failures = True

        # get a parser object to parse any data from the station
        self.parser = Gw1000Collector.Parser(is_wh24, debug_rain, debug_wind)

        # get a sensors object to handle sensor ID data
        self.sensors_obj = Gw1000Collector.Sensors(show_battery=show_battery, debug_sensors=debug_sensors, plugin_instance=plugin_instance)

        # create a thread property
        self.thread = None

        # we start off not collecting data, it will be turned on later when we are threaded
        self.collect_data = False

    def collect_sensor_data(self):
        """
        Collect sensor data by polling the API.

        Loop forever waking periodically to see if it is time to quit or collect more data.
        """

        # initialise ts of last time API was polled
        last_poll = 0
        # collect data continuously while we are told to collect data
        while self.collect_data:
            # store the current time
            now = time.time()
            # is it time to poll?
            if now - last_poll > self.poll_interval:
                # it is time to poll, wrap in a try..except in case we get a GW1000IOError exception
                try:
                    queue_data = self.get_live_sensor_data()
                except GW1000IOError as e:
                    # a GW1000IOError occurred, most likely because the Station object could not contact the GW1000/GW1100
                    # first up log the event, but only if we are logging failures
                    if self.log_failures:
                        self.logger.error('Unable to obtain live sensor data')
                    # assign the GW1000IOError exception so it will be sent in the queue to our controlling object
                    queue_data = e
                # put the queue data in the queue
                self.data_queue.put(queue_data)
                # debug log when we will next poll the API
                # self.logger.debug(f'Next update in {self.poll_interval} seconds')
                # reset the last poll ts
                last_poll = now
            # sleep for a second and then see if its time to poll again
            time.sleep(1)

    def get_live_sensor_data(self):
        """
        Get all current sensor data.

        Obtain live sensor data from the GW1000/GW1100 API then parse the API response to create a timestamped data dict keyed by internal
        GW1000/GW1100 field name. Add current sensor battery state and signal level data to the data dict. If no data was obtained from the API the
        value None is returned.
        """

        # obtain the raw data via the GW1000/GW1100 API, we may get a GW1000IOError exception, if we do let it bubble up (the raw data is
        # the data returned from the GW1000/GW1100 inclusive of the fixed header, command, payload length, payload and checksum bytes)
        raw_data = self.station.get_livedata()
        # if we made it here our raw data was validated by checksum get a timestamp to use in case our data does not come with one
        _timestamp = int(time.time())
        # parse the raw data (the parsed data is a dict keyed by internal GW1000/GW1100 field names and containing the decoded raw sensor data)
        parsed_data = self.parser.parse(raw_data, _timestamp)
        # log the parsed data but only if debug>=3
        # self.logger.debug(f"Parsed data: {parsed_data}")
        # The parsed live data does not contain any sensor battery state or signal level data. The battery state and signal level data for each
        # sensor can be obtained from the GW1000/GW1100 API via our Sensors object.
        # first we need to update our Sensors object with current sensor ID data
        self.update_sensor_id_data()
        # now add any sensor battery state and signal level data to the parsed data
        parsed_data.update(self.sensors_obj.battery_and_signal_data)
        # log the processed parsed data but only if debug>=3
        # self.logger.debug(f"Processed parsed data: {parsed_data}")
        return parsed_data

    def update_sensor_id_data(self):
        """
        Update the Sensors object with current sensor ID data.
        """

        # get the current sensor ID data
        sensor_id_data = self.station.get_sensor_id()
        # now use the sensor ID data to re-initialise our sensors object
        self.sensors_obj.set_sensor_id_data(sensor_id_data)

    @property
    def rain_data(self):
        """
        Obtain GW1000/GW1100 rain data.
        """

        # obtain the rain data data via the API
        response = self.station.get_raindata()
        # determine the size of the rain data
        raw_data_size = response[3]
        # extract the actual data
        data = response[4:4 + raw_data_size - 3]
        # initialise a dict to hold our final data
        data_dict = dict()
        data_dict['rain_rate'] = self.parser.decode_big_rain(data[0:4])
        data_dict['rain_day'] = self.parser.decode_big_rain(data[4:8])
        data_dict['rain_week'] = self.parser.decode_big_rain(data[8:12])
        data_dict['rain_month'] = self.parser.decode_big_rain(data[12:16])
        data_dict['rain_year'] = self.parser.decode_big_rain(data[16:20])
        return data_dict

    @property
    def mulch_offset(self):
        """
        Obtain GW1000/GW1100 multi-channel temperature and humidity offset data.
        """

        # obtain the mulch offset data via the API
        response = self.station.get_mulch_offset()
        # determine the size of the mulch offset data
        raw_data_size = response[3]
        # extract the actual data
        data = response[4:4 + raw_data_size - 3]
        # initialise a counter
        index = 0
        # initialise a dict to hold our final data
        offset_dict = {}
        # iterate over the data
        while index < len(data):
            try:
                channel = byte_to_int(data[index])
            except TypeError:
                channel = data[index]
            offset_dict[channel] = {}
            try:
                offset_dict[channel]['hum'] = struct.unpack("b", data[index + 1])[0]
            except TypeError:
                offset_dict[channel]['hum'] = struct.unpack("b", int_to_bytes(data[index + 1]))[0]
            try:
                offset_dict[channel]['temp'] = struct.unpack("b", data[index + 2])[0] / 10.0
            except TypeError:
                offset_dict[channel]['temp'] = struct.unpack("b", int_to_bytes(data[index + 2]))[0] / 10.0
            index += 3
        return offset_dict

    @property
    def pm25_offset(self):
        """
        Obtain GW1000/GW1100 PM2.5 offset data.
        """

        # obtain the PM2.5 offset data via the API
        response = self.station.get_pm25_offset()
        # determine the size of the PM2.5 offset data
        raw_data_size = response[3]
        # extract the actual data
        data = response[4:4 + raw_data_size - 3]
        # initialise a counter
        index = 0
        # initialise a dict to hold our final data
        offset_dict = {}
        # iterate over the data
        while index < len(data):
            try:
                channel = byte_to_int(data[index])
            except TypeError:
                channel = data[index]
            offset_dict[channel] = struct.unpack(">h", data[index+1:index+3])[0]/10.0
            index += 3
        return offset_dict

    @property
    def co2_offset(self):
        """
        Obtain GW1000/GW1100 WH45 CO2, PM10 and PM2.5 offset data.
        """

        # obtain the WH45 offset data via the API
        response = self.station.get_co2_offset()
        # determine the size of the WH45 offset data
        raw_data_size = response[3]
        # extract the actual data
        data = response[4:4 + raw_data_size - 3]
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

    @property
    def calibration(self):
        """
        Obtain GW1000/GW1100 calibration data.
        """

        # obtain the calibration data via the API
        response = self.station.get_calibration_coefficient()
        # determine the size of the calibration data
        raw_data_size = response[3]
        # extract the actual data
        data = response[4:4 + raw_data_size - 3]
        # initialise a dict to hold our final data
        calibration_dict = dict()
        # and decode/store the calibration data  bytes 0 and 1 are reserved (lux to solar radiation conversion gain (126.7))
        calibration_dict['gain uv'] = struct.unpack(">H", data[2:4])[0]/100.0
        calibration_dict['gain solar radiation'] = struct.unpack(">H", data[4:6])[0]/100.0
        calibration_dict['gain wind'] = struct.unpack(">H", data[6:8])[0]/100.0
        calibration_dict['gain rain'] = struct.unpack(">H", data[8:10])[0]/100.0
        # obtain the offset calibration data via the API
        response = self.station.get_offset_calibration()
        # determine the size of the calibration data
        raw_data_size = response[3]
        # extract the actual data
        data = response[4:4 + raw_data_size - 3]
        # and decode/store the offset calibration data
        calibration_dict['offset indoor temp'] = struct.unpack(">h", data[0:2])[0]/10.0
        try:
            calibration_dict['offset indoor hum'] = struct.unpack("b", data[2])[0]
        except TypeError:
            calibration_dict['offset indoor hum'] = struct.unpack("b", int_to_bytes(data[2]))[0]
        calibration_dict['offset absolute pressure'] = struct.unpack(">l", data[3:7])[0]/10.0
        calibration_dict['offset relative pressure'] = struct.unpack(">l", data[7:11])[0]/10.0
        calibration_dict['offset outdoor temp'] = struct.unpack(">h", data[11:13])[0]/10.0
        try:
            calibration_dict['offset outdoor hum'] = struct.unpack("b", data[13])[0]
        except TypeError:
            calibration_dict['offset outdoor hum'] = struct.unpack("b", int_to_bytes(data[13]))[0]
        calibration_dict['offset wind direction'] = struct.unpack(">h", data[14:16])[0]
        return calibration_dict

    @property
    def soil_calibration(self):
        """
        Obtain GW1000/GW1100 soil moisture sensor calibration data.
        """

        # obtain the soil moisture calibration data via the API
        response = self.station.get_soil_calibration()
        # determine the size of the calibration data
        raw_data_size = response[3]
        # extract the actual data
        data = response[4:4 + raw_data_size - 3]
        # initialise a dict to hold our final data
        calibration_dict = {}
        # initialise a counter
        index = 0
        # iterate over the data
        while index < len(data):
            try:
                channel = byte_to_int(data[index])
            except TypeError:
                channel = data[index]
            calibration_dict[channel] = {}
            try:
                humidity = byte_to_int(data[index + 1])
            except TypeError:
                humidity = data[index + 1]
            calibration_dict[channel]['humidity'] = humidity
            calibration_dict[channel]['ad'] = struct.unpack(">h", data[index+2:index+4])[0]
            try:
                ad_select = byte_to_int(data[index + 4])
            except TypeError:
                ad_select = data[index + 4]
            calibration_dict[channel]['ad_select'] = ad_select != 0
            try:
                min_ad = byte_to_int(data[index + 5])
            except TypeError:
                min_ad = data[index + 5]
            calibration_dict[channel]['adj_min'] = min_ad
            calibration_dict[channel]['adj_max'] = struct.unpack(">h", data[index+6:index+8])[0]
            index += 8
        return calibration_dict

    @property
    def system_parameters(self):
        """
        Obtain GW1000/GW1100 system parameters.
        """

        frequency = {0: '433 MHz',
                     1: '866 MHz',
                     2: '915 MHz',
                     3: '920 MHz'
                     }

        sensor_type = {0: 'WH24',
                       1: 'WH65'
                       }

        # obtain the system parameters data via the API
        response = self.station.get_system_params()
        # determine the size of the system parameters data
        raw_data_size = response[3]
        # extract the actual system parameters data
        data = response[4:4 + raw_data_size - 3]
        # initialise a dict to hold our final data
        data_dict = dict()
        data_dict['frequency'] = frequency[data[0]]
        data_dict['sensor type'] = sensor_type[data[1]]
        data_dict['utc'] = datetime.fromtimestamp(self.parser.decode_utc(data[2:6])).replace(tzinfo=timezone.utc)
        data_dict['timezone index'] = data[6]
        data_dict['daylight saving time'] = data[7] != 0
        return data_dict

    @property
    def ecowitt_net(self):
        """
        Obtain GW1000/GW1100 Ecowitt.net service parameters.

        Returns a dictionary of settings.
        """

        # obtain the system parameters data via the API
        response = self.station.get_ecowitt_net_params()
        # determine the size of the system parameters data
        raw_data_size = response[3]
        # extract the actual system parameters data
        data = response[4:4 + raw_data_size - 3]
        # initialise a dict to hold our final data
        data_dict = dict()
        data_dict['interval'] = data[0]
        # obtain the GW1000/GW1100 MAC address
        data_dict['mac'] = self.mac_address
        return data_dict

    @property
    def wunderground(self):
        """
        Obtain GW1000/GW1100 Weather Underground service parameters.

        Returns a dictionary of settings with string data in unicode format.
        """

        # obtain the system parameters data via the API
        response = self.station.get_wunderground_params()
        # determine the size of the system parameters data
        raw_data_size = response[3]
        # extract the actual system parameters data
        data = response[4:4 + raw_data_size - 3]
        # return data
        # initialise a dict to hold our final data
        data_dict = {}
        # obtain the required data from the response decoding any bytestrings
        id_size = data[0]
        data_dict['id'] = data[1:1+id_size].decode()
        password_size = data[1+id_size]
        data_dict['password'] = data[2+id_size:2+id_size+password_size].decode()
        return data_dict

    @property
    def weathercloud(self):
        """
        Obtain GW1000/GW1100 Weathercloud service parameters.

        Returns a dictionary of settings with string data in unicode format.
        """

        # obtain the system parameters data via the API
        response = self.station.get_weathercloud_params()
        # determine the size of the system parameters data
        raw_data_size = response[3]
        # extract the actual system parameters data
        data = response[4:4 + raw_data_size - 3]
        # initialise a dict to hold our final data
        data_dict = {}
        # obtain the required data from the response decoding any bytestrings
        id_size = data[0]
        data_dict['id'] = data[1:1+id_size].decode()
        key_size = data[1+id_size]
        data_dict['key'] = data[2+id_size:2+id_size+key_size].decode()
        return data_dict

    @property
    def wow(self):
        """
        Obtain GW1000/GW1100 Weather Observations Website service parameters.

        Returns a dictionary of settings with string data in unicode format.
        """

        # obtain the system parameters data via the API
        response = self.station.get_wow_params()
        # determine the size of the system parameters data
        raw_data_size = response[3]
        # extract the actual system parameters data
        data = response[4:4 + raw_data_size - 3]
        # initialise a dict to hold our final data
        data_dict = {}
        # obtain the required data from the response decoding any bytestrings
        id_size = data[0]
        data_dict['id'] = data[1:1+id_size].decode()
        password_size = data[1+id_size]
        data_dict['password'] = data[2+id_size:2+id_size+password_size].decode()
        station_num_size = data[1+id_size]
        data_dict['station_num'] = data[3+id_size+password_size:3+id_size+password_size+station_num_size].decode()
        return data_dict

    @property
    def custom(self):
        """
        Obtain GW1000/GW1100 custom server parameters.

        Returns a dictionary of settings with string data in unicode format.
        """

        # obtain the system parameters data via the API
        response = self.station.get_custom_params()
        # determine the size of the system parameters data
        raw_data_size = response[3]
        # extract the actual system parameters data
        data = response[4:4 + raw_data_size - 3]
        # initialise a dict to hold our final data
        data_dict = {}
        # obtain the required data from the response decoding any bytestrings
        index = 0
        id_size = data[index]
        index += 1
        data_dict['server id'] = data[index:index+id_size].decode()
        index += id_size
        password_size = data[index]
        index += 1
        data_dict['password'] = data[index:index+password_size].decode()
        index += password_size
        server_size = data[index]
        index += 1
        data_dict['server'] = data[index:index+server_size].decode()
        index += server_size
        data_dict['port'] = struct.unpack(">h", data[index:index + 2])[0]
        index += 2
        data_dict['interval'] = struct.unpack(">h", data[index:index + 2])[0]
        index += 2
        data_dict['protocol type'] = ['Ecowitt', 'WU'][data[index]]
        index += 1
        data_dict['active'] = data[index] != 0
        # the user path is obtained separately, get the user path and add it to our response
        data_dict.update(self.usr_path)
        return data_dict

    @property
    def usr_path(self):
        """
        Obtain the GW1000/GW1100 user defined custom paths.

        The GW1000/GW1100 allows definition of remote server customs paths for  use when uploading to a custom service using Ecowitt or Weather
        Underground format. Different paths may be specified for each protocol.

        Returns a dictionary with each path as a unicode text string.
        """

        # return the GW1000/GW1100 user defined custom path
        response = self.station.get_usr_path()
        # determine the size of the user path data
        raw_data_size = response[3]
        # extract the actual system parameters data
        data = response[4:4 + raw_data_size - 3]
        # initialise a dict to hold our final data
        data_dict = {}
        index = 0
        ecowitt_size = data[index]
        index += 1
        data_dict['ecowitt path'] = data[index:index+ecowitt_size].decode()
        index += ecowitt_size
        wu_size = data[index]
        index += 1
        data_dict['wu path'] = data[index:index+wu_size].decode()
        return data_dict

    @property
    def mac_address(self):
        """
        Obtain the MAC address of the GW1000/GW1100.

        Returns the GW1000/GW1100 MAC address as a string of colon separated hex bytes.
        """

        # obtain the GW1000/GW1100 MAC address bytes
        station_mac_b = self.station.get_mac_address()

        # return the formatted string
        # return bytes_to_hex(station_mac_b[4:10], separator=":")
        # return station_mac_b[4:10].hex(":")
        return "%X:%X:%X:%X:%X:%X" % struct.unpack("BBBBBB", station_mac_b[4:10])

    @property
    def firmware_version(self):
        """
        Obtain the GW1000/GW1100 firmware version string.

        The firmware version can be obtained from the GW1000/GW1100 via an API call made by a Station object. The Station object takes care of making
        the API call and validating the response. What is returned is the raw response as a bytestring. The raw response is unpacked into a sequence
        of bytes. The length of the firmware string is in byte 4 and the firmware string starts at byte 5. The bytes comprising the firmware are
        extracted and converted to unicode characters before being reassembled into a string containing the firmware version.
        """

        # get the firmware bytestring via the API
        firmware_b = self.station.get_firmware_version()
        # create a format string so the firmware string can be unpacked into its bytes
        firmware_format = "B" * len(firmware_b)
        # unpack the firmware response bytestring, we now have a tuple of integers representing each of the bytes
        firmware_t = struct.unpack(firmware_format, firmware_b)
        # get the length of the firmware string, it is in byte 4
        str_length = firmware_t[4]
        # the firmware string starts at byte 5 and is str_length bytes long, convert the sequence of bytes to unicode characters and assemble as a
        # string and return the result
        return "".join([chr(x) for x in firmware_t[5:5 + str_length]])

    @property
    def sensors(self):
        """
        Get the current Sensors object.

        A Sensors object holds the address, id, battery state and signal level data sensors known to the GW1000/GW1100. The sensor id value can be
        used to discriminate between connected sensors, connecting sensors and disabled sensor addresses.

        Before using the Gw1000Collector's Sensors object it should be updated with recent sensor ID data via the GW1000/GW1100 API
        """

        # obtain current sensor id data via the API, we may get a GW1000IOError exception, if we do let it bubble up
        response = self.station.get_sensor_id()
        # if we made it here our response was validated by checksum re-initialise our sensors object with the sensor ID data we just obtained
        self.sensors_obj.set_sensor_id_data(response)
        # return our Sensors object
        return self.sensors_obj

    @property
    def battery_desc(self):
        """Battery description"""

        return self.sensors.battery_description_data

    def firmware_update(self):
        """Update the GW1000/GW1100 firmware."""

        response = self.station.set_firmware_upgrade()
        result = 'SUCCESS' if response[4] == 0 else 'FAIL'
        return result

    def set_usr_path(self, custom_ecowitt_pathpath, custom_wu_path):
        """Set the customized path.

        current is read to determine, whether writing new configuration is needed
        """

        current_usr_path = self.usr_path
        _ecowitt_path = current_usr_path['ecowitt path']
        _wu_path = current_usr_path['wu path']
        # _wu_path += '?' if _wu_path.endswith('php') else _wu_path

        self.logger.debug(f"To be set customized path: Ecowitt: current='{_ecowitt_path}' vs. new='{custom_ecowitt_pathpath}' and WU: current='{_wu_path}' vs. new='{custom_wu_path}'")

        if not (_ecowitt_path == custom_ecowitt_pathpath and _wu_path == custom_wu_path):
            self.logger.debug(f"Need to set customized path: Ecowitt: current='{_ecowitt_path}' vs. new='{custom_ecowitt_pathpath}' and WU: current='{_wu_path}' vs. new='{custom_wu_path}'")
            response = self.station.set_usr_path(custom_ecowitt_pathpath, custom_wu_path)
            result = 'SUCCESS' if response[4] == 0 else 'FAIL'
        else:
            self.logger.debug(f"Customized Path settings already correct; No need to write it")
            result = 'NO NEED'
        return result

    def set_custom_params(self, custom_server_id, custom_password, custom_host, custom_port, custom_interval, custom_type, custom_enabled):
        """
        Set the customized parameters.

        current configuration is read to dertermine, wether writing new configuration is needed
        """

        current_custom_params = self.custom
        new_custom_params = {'server id': custom_server_id, 'password': custom_password, 'server': custom_host, 'port': custom_port, 'interval': custom_interval, 'protocol type': ['Ecowitt', 'WU'][int(custom_type)], 'active': bool(int(custom_enabled))}

        if new_custom_params.items() <= current_custom_params.items():
            self.logger.debug(f"Customized Server settings already correct; No need to do it again")
            result = 'NO NEED'
        else:
            self.logger.debug(f"Request to set customized server: current setting={current_custom_params}")
            self.logger.debug(f"Request to set customized server:     new setting={new_custom_params}")
            response = self.station.set_custom_params(custom_server_id, custom_password, custom_host, custom_port, custom_interval, custom_type, custom_enabled)
            result = 'SUCCESS' if response[4] == 0 else 'FAIL'
        return result

    def reboot(self):
        """Reboot the GW1000/GW1100."""

        response = self.station.set_reboot()
        result = 'SUCCESS' if response[4] == 0 else 'FAIL'
        return result

    def reset(self):
        """Reset the GW1000/GW1100."""

        response = self.station.set_reset()
        result = 'SUCCESS' if response[4] == 0 else 'FAIL'
        return result

    def startup(self):
        """Start a thread that collects data from the GW1000/GW1100 API."""

        try:
            self.thread = Gw1000Collector.CollectorThread(self)
            self.collect_data = True
            self.thread.daemon = True
            _name = 'plugins.' + self._plugin_instance.get_fullname() + '.Gw1000CollectorThread'
            self.thread.setName(_name)
            self.thread.start()
        except threading.ThreadError:
            self.logger.error("Unable to launch Gw1000Collector thread")
            self.thread = None

    def shutdown(self):
        """
        Shut down the thread that collects data from the GW1000/GW1100 API.

        Tell the thread to stop, then wait for it to finish.
        """

        # we only need do something if a thread exists
        if self.thread:
            # tell the thread to stop collecting data
            self.collect_data = False
            # terminate the thread
            self.thread.join(10)
            # log the outcome
            if self.thread.is_alive():
                self.logger.error("Unable to shut down Gw1000Collector thread")
            else:
                self.logger.info("Gw1000Collector thread has been terminated")
        self.thread = None

    class CollectorThread(threading.Thread):
        """Class used to collect data via the GW1000/GW1100 API in a thread."""

        def __init__(self, client):

            # init logger
            self.logger = logging.getLogger(__name__)

            # initialise our parent
            threading.Thread.__init__(self)

            # keep reference to the client we are supporting
            self.client = client
            self.name = 'gw1000-collector'

        def run(self):
            # rather than letting the thread silently fail if an exception occurs within the thread, wrap in a try..except so the exception
            # can be caught and available exception information displayed
            try:
                # kick the collection off
                self.client.collect_sensor_data()
            except Exception as e:
                self.logger.error(f"Not able to start 'gw1000-collector' Thread. Error was {e}")
                pass

    class Station(object):
        """
        Class to interact directly with the GW1000/GW1100 API.

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

        def __init__(self, ip_address=None, port=None,
                     broadcast_address=None, broadcast_port=None,
                     socket_timeout=None, broadcast_timeout=None,
                     max_tries=DEFAULT_MAX_TRIES,
                     retry_wait=DEFAULT_RETRY_WAIT, mac=None):

            # init logger
            self.logger = logging.getLogger(__name__)

            # network broadcast address
            self.broadcast_address = broadcast_address if broadcast_address is not None else DEFAULT_BROADCAST_ADDRESS
            # network broadcast port
            self.broadcast_port = broadcast_port if broadcast_port is not None else DEFAULT_BROADCAST_PORT
            self.socket_timeout = socket_timeout if socket_timeout is not None else DEFAULT_SOCKET_TIMEOUT
            self.broadcast_timeout = broadcast_timeout if broadcast_timeout is not None else DEFAULT_BROADCAST_TIMEOUT

            self.device_list = []

            # initialise flags to indicate if IP address or port were discovered
            self.ip_discovered = ip_address is None
            self.port_discovered = port is None
            # if IP address or port was not specified (None) then attempt to
            # discover the GW1000/GW1100 with a UDP broadcast
            if ip_address is None or port is None:
                for attempt in range(max_tries):
                    try:
                        # discover devices on the local network, the result is a list of dicts in IP address order with each dict
                        # containing data for a unique discovered device
                        self.device_list = self.discover()
                    except socket.error as e:
                        self.logger.error(f"Unable to detect device IP address and port: {e} ({type(e)})")
                        # signal that we have a critical error
                        raise
                    else:
                        # did we find any GW1000/GW1100
                        if len(self.device_list) > 0:
                            # we have at least one, arbitrarily choose the first one found as the one to use
                            disc_ip = self.device_list[0]['ip_address']
                            disc_port = self.device_list[0]['port']
                            # log the fact as well as what we found
                            gw1000_str = ', '.join(f"{d['model']}: {d['ip_address']}:{ d['port']}" for d in self.device_list)

                            if len(self.device_list) == 1:
                                stem = f"{self.device_list[0]['model']} was"
                            else:
                                stem = "Multiple devices were"
                            self.logger.info(f"{stem} found: {gw1000_str}. First one selected for plugin. To use dedicated one, define IP of dedicated Gateway in Plugin Setup.")
                            ip_address = disc_ip if ip_address is None else ip_address
                            port = disc_port if port is None else port
                            break
                        else:
                            # did not discover any GW1000/GW1100 so log it
                            self.logger.debug(f"Failed attempt {attempt + 1,} to detect device IP address and/or port")
                            # do we try again or raise an exception
                            if attempt < max_tries - 1:
                                # we still have at least one more try left so sleep and try again
                                time.sleep(retry_wait)
                            else:
                                # we've used all our tries, log it and raise an exception
                                _msg = f"Failed to detect device IP address and/or port after {attempt + 1,} attempts"
                                self.logger.error(_msg)
                                raise GW1000IOError(_msg)
            # set our ip_address property but encode it first, it saves doing it repeatedly later
            self.ip_address = ip_address.encode()
            self.port = port
            self.max_tries = max_tries
            self.retry_wait = retry_wait
            # start off logging failures
            self.log_failures = True
            # get my GW1000/GW1100 MAC address to use later if we have to rediscover
            if mac is None:
                self.mac = self.get_mac_address()
            else:
                self.mac = mac
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
            """
            Discover any GW1000/GW1100 devices on the local network.

            Send a UDP broadcast and check for replies. Decode each reply to obtain details of any devices on the local network. Create a dict
            of details for each device including a derived model name. Construct a list of dicts with details of unique (MAC address)
            devices that responded. When complete return the list of devices found.
            """

            # create a socket object so we can broadcast to the network via IPv4 UDP
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
            # self.logger.debug(f"Sending broadcast packet <{packet}> in Hex: '{bytes_to_hex(packet)}' to '{self.broadcast_address}:{self.broadcast_port}'")
            # initialise a list for the results as multiple GW1000/GW1100 may respond
            result_list = []
            # send the Broadcast command
            s.sendto(packet, (self.broadcast_address, self.broadcast_port))
            # obtain any responses
            while True:
                try:
                    response = s.recv(1024)
                    # log the response if debug is high enough
                    self.logger.debug(f"Received broadcast response in HEX '{bytes_to_hex(response)}' and in Bytes {response}")
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
                        self.logger.debug(f"Invalid response to command 'CMD_BROADCAST': {e}")
                    except Exception as e:
                        # Some other error occurred in check_response(), perhaps the response was malformed. Log the stack trace but continue.
                        self.logger.error(f"Unexpected exception occurred while checking response to command 'CMD_BROADCAST': {e}")
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

        @property
        def gateway_ip(self):
            return self.ip_address.decode()

        @property
        def gateway_port(self):
            return self.port

        @staticmethod
        def decode_broadcast_response(raw_data):
            """
            Decode a broadcast response and return the results as a dict.

            A GW1000/GW1100 response to a CMD_BROADCAST API command consists of a number of control structures around a payload of a data. The API
            response is structured as follows:
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

            There also seems to be a peculiarity in the CMD_BROADCAST response data payload whereby the first character of the GW1000/GW1100 AP
            SSID is a non-printable ASCII character. The WS View app appears to ignore or not display this character nor does it appear to be used
            elsewhere. Consequently this character is ignored.

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
            """
            Determine the device model from the firmware version.

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
            """
            Determine the device model from the device SSID.

            To date the GW1000 and GW1100 device SSID has included the device
            model in the SSID returned via the device API. Whilst this is not
            guaranteed to be the case for future firmware releases, in the
            absence of any other direct means of obtaining the device model
            number it is a useful means for determining the device model. This
            is particularly the case when using UDP broadcast to discover
            devices on the local network.

            Note that it may be possible to alter the SSID used by the device
            in which case this method may not provide an accurate result.
            However, as the device SSID is only used during initial device
            configuration and since altering the device SSID is not a normal
            part of the initial device configuration, this method of
            determining the device model is considered adequate for use during
            discovery by UDP broadcast.

            The check is a simple check to see if the model name is contained
            in the SSID returned by the device API.

            If a known model is found in the SSID the model is returned as a
            string. None is returned if (1) the SSID is None or (2) a known
            model is not found in the SSID.
            """

            return self.get_model(ssid_string)

        @staticmethod
        def get_model(t):
            """
            Determine the device model from a string.

            To date GW1000 and GW1100 firmware versions have included the
            device model in the firmware version string or the device SSID.
            Both the firmware version string and device SSID are available via
            the device API so checking the firmware version string or SSID
            provides a de facto method of determining the device model.

            This method uses a simple check to see if a known model name is
            contained in the string concerned.

            Known model strings are contained in a tuple Station.KNOWN_MODELS.

            If a known model is found in the string the model is returned as a
            string. None is returned if a known model is not found in the
            string.
            """

            # do we have a string to check
            if t is not None:
                # we have a string, now do we have a know model in the string, if so return the model string
                for model in KNOWN_MODELS:
                    if model in t.upper():
                        return model
                # we don't have a known model so return None
                return None
            else:
                # we have no string so return None
                return None

        def get_livedata(self):
            """
            Get GW1000/GW1100 live data.

            Sends the command to obtain live data from the GW1000/GW1100 to the
            API with retries. If the GW1000/GW1100 cannot be contacted
            re-discovery is attempted. If rediscovery is successful the command
            is tried again otherwise the lost contact timestamp is set and the
            exception raised. Any code that calls this method should be
            prepared to handle a GW1000IOError exception.
            """

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
            """
            Get GW1000/GW1100 rain data.

            Sends the command to obtain rain data from the GW10GW1000/GW110000
            to the API with retries. If the GW1000/GW1100 cannot be contacted a
            GW1000IOError will have been raised by send_cmd_with_retries()
            which will be passed through by get_raindata(). Any code calling
            get_raindata() should be prepared to handle this exception.
            """

            return self.send_cmd_with_retries('CMD_READ_RAINDATA')

        def get_system_params(self):
            """
            Read GW1000/GW1100 system parameters.

            Sends the command to obtain system parameters from the GW1000/GW1100 to the API with retries. If the GW1000/GW1100 cannot
            be contacted a GW1000IOError will have been raised by send_cmd_with_retries() which will be passed through by
            get_system_params(). Any code calling get_system_params() should be prepared to handle this exception.
            """

            return self.send_cmd_with_retries('CMD_READ_SSSS')

        def get_ecowitt_net_params(self):
            """
            Get GW1000/GW1100 Ecowitt.net parameters.

            Sends the command to obtain the GW1000/GW1100 Ecowitt.net
            parameters to the API with retries. If the GW1000/GW1100 cannot be
            contacted a GW1000IOError will have been raised by
            send_cmd_with_retries() which will be passed through by
            get_ecowitt_net_params(). Any code calling get_ecowitt_net_params()
            should be prepared to handle this exception.
            """

            return self.send_cmd_with_retries('CMD_READ_ECOWITT')

        def get_wunderground_params(self):
            """
            Get GW1000 Weather Underground parameters.

            Sends the command to obtain the GW1000/GW1100 Weather Underground
            parameters to the API with retries. If the GW1000/GW1100 cannot be
            contacted a GW1000IOError will have been raised by
            send_cmd_with_retries() which will be passed through by
            get_wunderground_params(). Any code calling
            get_wunderground_params() should be prepared to handle this
            exception.
            """

            return self.send_cmd_with_retries('CMD_READ_WUNDERGROUND')

        def get_weathercloud_params(self):
            """
            Get GW1000/GW1100 Weathercloud parameters.

            Sends the command to obtain the GW1000/GW1100 Weathercloud
            parameters to the API with retries. If the GW1000/GW1100 cannot be
            contacted a GW1000IOError will have been raised by
            send_cmd_with_retries() which will be passed through by
            get_weathercloud_params(). Any code calling
            get_weathercloud_params() should be prepared to handle this
            exception.
            """

            return self.send_cmd_with_retries('CMD_READ_WEATHERCLOUD')

        def get_wow_params(self):
            """
            Get GW1000/GW1100 Weather Observations Website parameters.

            Sends the command to obtain the GW1000/GW1100 Weather Observations
            Website parameters to the API with retries. If the GW1000/GW1100
            cannot be contacted a GW1000IOError will have been raised by
            send_cmd_with_retries() which will be passed through by
            get_wow_params(). Any code calling get_wow_params() should be
            prepared to handle this exception.
            """

            return self.send_cmd_with_retries('CMD_READ_WOW')

        def get_custom_params(self):
            """
            Get GW1000/GW1100 custom server parameters.

            Sends the command to obtain the GW1000/GW1100 custom server parameters to the API with retries. If the GW1000/GW1100 cannot be
            contacted a GW1000IOError will have been raised by send_cmd_with_retries() which will be passed through by
            get_custom_params(). Any code calling get_custom_params() should be prepared to handle this exception.
            """

            return self.send_cmd_with_retries('CMD_READ_CUSTOMIZED')

        def set_custom_params(self, custom_server_id, custom_password, custom_host, custom_port, custom_interval, custom_type, custom_enabled):
            """
            Set GW1000/GW1100 custom server parameters.

            Sends the command to obtain the GW1000/GW1100 custom server parameters to the API with retries. If the GW1000/GW1100 cannot be
            contacted a GW1000IOError will have been raised by send_cmd_with_retries() which will be passed through by
            get_custom_params(). Any code calling set_custom_params() should be prepared to handle this exception.
            """

            payload = bytearray(chr(len(custom_server_id)) + custom_server_id + chr(len(custom_password)) + custom_password + chr(len(custom_host)) + custom_host + chr(int(int(custom_port)/256)) + chr(int(int(custom_port) % 256)) + chr(int(int(custom_interval)/256)) + chr(int(int(custom_interval) % 256)) + chr(int(custom_type)) + chr(int(custom_enabled)), 'latin-1')
            self.logger.debug(f"Customized Server: payload={payload}")
            return self.send_cmd_with_retries('CMD_WRITE_CUSTOMIZED', payload)

        def get_usr_path(self):
            """
            Get GW1000/GW1100 user defined custom path.

            Sends the command to obtain the GW1000/GW1100 user defined custom path to the API with retries. If the GW1000/GW1100 cannot be
            contacted a GW1000IOError will have been raised by send_cmd_with_retries() which will be passed through by
            get_usr_path(). Any code calling get_usr_path() should be prepared to handle this exception.
            """

            return self.send_cmd_with_retries('CMD_READ_USR_PATH')

        def set_usr_path(self, custom_ecowitt_pathpath, custom_wu_path):
            """
            Get GW1000/GW1100 user defined custom path.

            Sends the command to set the GW1000/GW1100 user defined custom path to the API with retries. If the GW1000/GW1100 cannot be
            contacted a GW1000IOError will have been raised by send_cmd_with_retries() which will be passed through by
            set_usr_path(). Any code calling set_usr_path() should be prepared to handle this exception.
            """
            self.logger.debug(f"set_usr_path: set user path called with custom_ecowitt_pathpath={custom_ecowitt_pathpath} and custom_wu_path={custom_wu_path}")

            payload = bytearray()
            payload.extend(int_to_bytes(len(custom_ecowitt_pathpath), 1))
            payload.extend(str.encode(custom_ecowitt_pathpath))
            payload.extend(int_to_bytes(len(custom_wu_path), 1))
            payload.extend(str.encode(custom_wu_path))
            self.logger.debug(f"Customized Path: payload={payload}")
            return self.send_cmd_with_retries('CMD_WRITE_USR_PATH', payload)

        def get_mac_address(self):
            """
            Get GW1000/GW1100 MAC address.

            Sends the command to obtain the GW1000/GW1100 MAC address to the
            API with retries. If the GW1000/GW1100 cannot be contacted a
            GW1000IOError will have been raised by send_cmd_with_retries()
            which will be passed through by get_mac_address(). Any code calling
            get_mac_address() should be prepared to handle this exception.
            """

            return self.send_cmd_with_retries('CMD_READ_STATION_MAC')

        def get_firmware_version(self):
            """
            Get GW1000/GW1100 firmware version.

            Sends the command to obtain GW1000/GW1100 firmware version to the API with retries. If the GW1000/GW1100 cannot be contacted a
            GW1000IOError will have been raised by send_cmd_with_retries() which will be passed through by get_firmware_version(). Any code
            calling get_firmware_version() should be prepared to handle this exception.
            """

            return self.send_cmd_with_retries('CMD_READ_FIRMWARE_VERSION')

        def set_firmware_upgrade(self):
            """
            Set GW1000/GW1100 firmware upgrade.

            Sends the command to upgrade GW1000/GW1100 firmware version to the API with retries. If the GW1000/GW1100 cannot be contacted a
            GW1000IOError will have been raised by send_cmd_with_retries() which will be passed through by get_firmware_version(). Any code
            calling get_firmware_version() should be prepared to handle this exception.
            """

            self.logger.debug(f"set_firmware_upgrade: Firmware update called for {self.ip_address.decode()}:{self.port}")
            payload = bytearray()
            payload.extend(self.ip_address)
            payload.extend(int_to_bytes(self.port, 2))
            self.logger.debug(f"set_firmware_upgrade: payload={payload}")
            return self.send_cmd_with_retries('CMD_WRITE_UPDATE', payload)

        def get_sensor_id(self):
            """
            Get GW1000/GW1100 sensor ID data.

            Sends the command to obtain sensor ID data from the GW1000/GW1100
            to the API with retries. If the GW1000/GW1100 cannot be contacted
            re-discovery is attempted. If rediscovery is successful the command
            is tried again otherwise the lost contact timestamp is set and the
            exception raised. Any code that calls this method should be
            prepared to handle a GW1000IOError exception.
            """

            try:
                return self.send_cmd_with_retries('CMD_READ_SENSOR_ID_NEW')
            except GW1000IOError:
                # there was a problem contacting the GW1000/GW1100, it could be it has changed IP address so attempt to rediscover
                if not self.rediscover():
                    # we could not re-discover so raise the exception
                    raise
                else:
                    # we did rediscover successfully so try again, if it fails we get another GW1000IOError exception which will be
                    # raised
                    return self.send_cmd_with_retries('CMD_READ_SENSOR_ID_NEW')

        def get_mulch_offset(self):
            """
            Get multi-channel temperature and humidity offset data.

            Sends the command to obtain the multi-channel temperature and
            humidity offset data to the API with retries. If the GW1000/GW1100
            cannot be contacted a GW1000IOError will have been raised by
            send_cmd_with_retries() which will be passed through by
            get_mulch_offset(). Any code calling get_mulch_offset() should be
            prepared to handle this exception.
            """

            return self.send_cmd_with_retries('CMD_GET_MulCH_OFFSET')

        def get_pm25_offset(self):
            """
            Get PM2.5 offset data.

            Sends the command to obtain the PM2.5 sensor offset data to the API
            with retries. If the GW1000/GW1100 cannot be contacted a
            GW1000IOError will have been raised by send_cmd_with_retries()
            which will be passed through by get_pm25_offset(). Any code
            calling get_pm25_offset() should be prepared to handle this
            exception.
            """

            return self.send_cmd_with_retries('CMD_GET_PM25_OFFSET')

        def get_calibration_coefficient(self):
            """
            Get calibration coefficient data.

            Sends the command to obtain the calibration coefficient data to the API with retries. If the GW1000/GW1100 cannot be contacted a
            GW1000IOError will have been raised by send_cmd_with_retries() which will be passed through by get_calibration_coefficient(). Any
            code calling get_calibration_coefficient() should be prepared to handle this exception.
            """

            return self.send_cmd_with_retries('CMD_READ_GAIN')

        def get_soil_calibration(self):
            """
            Get soil moisture sensor calibration data.

            Sends the command to obtain the soil moisture sensor calibration data to the API with retries. If the GW1000/GW1100 cannot be
            contacted a GW1000IOError will have been raised by send_cmd_with_retries() which will be passed through by
            get_soil_calibration(). Any code calling get_soil_calibration() should be prepared to handle this exception.
            """

            return self.send_cmd_with_retries('CMD_GET_SOILHUMIAD')

        def get_offset_calibration(self):
            """
            Get offset calibration data.

            Sends the command to obtain the offset calibration data to the API
            with retries. If the GW1000/GW1100 cannot be contacted a
            GW1000IOError will have been raised by send_cmd_with_retries()
            which will be passed through by get_offset_calibration(). Any code
            calling get_offset_calibration() should be prepared to handle this
            exception.
            """

            return self.send_cmd_with_retries('CMD_READ_CALIBRATION')

        def get_co2_offset(self):
            """
            Get WH45 CO2, PM10 and PM2.5 offset data.

            Sends the command to obtain the WH45 CO2, PM10 and PM2.5 sensor
            offset data to the API with retries. If the GW1000/GW1100 cannot be
            contacted a GW1000IOError will have been raised by
            send_cmd_with_retries() which will be passed through by
            get_offset_calibration(). Any code calling get_offset_calibration()
            should be prepared to handle this exception.
            """

            return self.send_cmd_with_retries('CMD_GET_CO2_OFFSET')

        def set_reboot(self):
            """
            Reboot GW1000/GW1100 .

            Sends the command to reboot GW1000/GW1100 to the API with retries. If the GW1000/GW1100 cannot be contacted a
            GW1000IOError will have been raised by send_cmd_with_retries() which will be passed through by set_reboot(). Any code
            calling set_reboot() should be prepared to handle this exception.
            """

            self.logger.debug(f"set_reboot: Reboot called for {self.ip_address.decode()}:{self.port}")
            return self.send_cmd_with_retries('CMD_WRITE_REBOOT')

        def set_reset(self):
            """
            Reset GW1000/GW1100 .

            Sends the command to reboot GW1000/GW1100 to the API with retries. If the GW1000/GW1100 cannot be contacted a
            GW1000IOError will have been raised by send_cmd_with_retries() which will be passed through by set_reboot(). Any code
            calling set_reboot() should be prepared to handle this exception.
            """

            self.logger.debug(f"set_reboot: Reset called for {self.ip_address.decode()}:{self.port}")
            return self.send_cmd_with_retries('CMD_WRITE_RESET')

        def send_cmd_with_retries(self, cmd, payload=b''):
            """
            Send a command to the GW1000/GW1100 API with retries and return the response.

            Send a command to the GW1000/GW1100 and obtain the response. If the the response is valid return the response. If the response is
            invalid an appropriate exception is raised and the command resent up to self.max_tries times after which the value None is returned.

            cmd: A string containing a valid GW1000/GW1100 API command, eg: 'CMD_READ_FIRMWARE_VERSION'
            payload: The data to be sent with the API command, byte string.

            Returns the response as a byte string or the value None.
            """

            # construct the message packet
            packet = self.build_cmd_packet(cmd, payload)
            # attempt to send up to 'self.max_tries' times
            response = None
            for attempt in range(self.max_tries):
                # wrap in  try..except so we can catch any errors
                try:
                    response = self.send_cmd(packet)
                except socket.timeout as e:
                    # a socket timeout occurred, log it
                    if self.log_failures:
                        self.logger.debug(f"Failed to obtain response to attempt {attempt + 1} to send command '{cmd}': {e}")
                except Exception as e:
                    # an exception was encountered, log it
                    if self.log_failures:
                        self.logger.debug(f"Failed attempt {attempt + 1} to send command '{cmd}':{e}")
                else:
                    # check the response is valid
                    # self.logger.debug(f"send_cmd_with_retries: cmd={cmd}, self.commands[cmd]={self.commands[cmd]}, response={response}")
                    try:
                        self.check_response(response, self.commands[cmd])
                    except (InvalidChecksum, InvalidApiResponse) as e:
                        # the response was not valid, log it and attempt again if we haven't had too many attempts already
                        self.logger.debug(f"Invalid response to attempt {attempt + 1} to send command '{cmd}':{e}")
                    except Exception as e:
                        # Some other error occurred in check_response(), perhaps the response was malformed. Log  but continue.
                        self.logger.error(f"Unexpected exception occurred while checking response to attempt {attempt + 1} to send command '{cmd}':{e}")
                    else:
                        # our response is valid so return it
                        return response
                # sleep before our next attempt, but skip the sleep if we have just made our last attempt
                if attempt < self.max_tries - 1:
                    time.sleep(self.retry_wait)

            # if we made it here we failed after self.max_tries attempts first of all log it
            _msg = f"Failed to obtain response to command '{cmd}' after {self.max_tries} attempts"

            if response is not None or self.log_failures:
                self.logger.error(_msg)
            # finally raise a GW1000IOError exception
            raise GW1000IOError(_msg)

        def build_cmd_packet(self, cmd, payload=b''):
            """
            Construct an API command packet.

            A GW1000/GW1100 API command packet looks like:

            fixed header, command, size, data 1, data 2...data n, checksum

            where:
                fixed header is 2 bytes = 0xFFFF
                command is a 1 byte API command code
                size is 1 byte being the number of bytes of command to checksum
                data 1, data 2 ... data n is the data being transmitted and is n bytes long
                checksum is a byte checksum of command + size + data 1 + data 2 ... + data n

            cmd:     A string containing a valid GW1000/GW1100 API command, eg: 'CMD_READ_FIRMWARE_VERSION'
            payload: The data to be sent with the API command, byte string.

            Returns an API command packet as a bytestring.
            """

            # calculate size
            try:
                size = len(self.commands[cmd]) + 1 + len(payload) + 1
            except KeyError:
                raise UnknownCommand(f"Unknown API command '{cmd}'")
            # construct the portion of the message for which the checksum is calculated
            body = bytearray()
            body.extend(self.commands[cmd])
            body.extend(struct.pack('B', size))
            body.extend(payload)
            # body = b''.join([self.commands[cmd], struct.pack('B', size), payload])

            # calculate the checksum
            checksum = self.calc_checksum(body)

            # finalize message
            cmd_packet = bytearray()
            cmd_packet.extend(self.header)
            cmd_packet.extend(body)
            cmd_packet.extend(struct.pack('B', checksum))

            # return the constructed message packet
            # return b''.join([self.header, body, struct.pack('B', checksum)])
            return cmd_packet

        def send_cmd(self, packet):
            """
            Send a command to the GW1000/GW1100 API and return the response.

            Send a command to the GW1000/GW1100 and return the response. Socket
            related errors are trapped and raised, code calling send_cmd should
            be prepared to handle such exceptions.

            cmd: A valid GW1000/GW1100 API command

            Returns the response as a byte string.
            """

            # create a socket object for sending commands and broadcasting to the network, would normally do this using a with statement but
            # with statement support for socket.socket did not appear until python 3.
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            # set the socket timeout
            s.settimeout(self.socket_timeout)
            # wrap our connect in a try..except so we can catch any socket related exceptions
            try:
                # connect to the device
                s.connect((self.ip_address, self.port))
                # if required log the packet we are sending
                # self.logger.debug(f"Sending packet <{packet}> in Hex: '{bytes_to_hex(packet)}' to '{self.ip_address.decode()}:{self.port}'")
                # send the packet
                s.sendall(packet)
                # obtain the response, we assume here the response will be less than 1024 characters
                response = s.recv(1024)
                # if required log the response
                # self.logger.debug(f"Received response in HEX '{bytes_to_hex(response)}' and in Bytes {response}")
                # return the response
                return response
            except socket.error:
                # we received a socket error, raise it
                raise
            finally:
                # make sure we close our socket
                s.close()

        def check_response(self, response, cmd_code):
            """
            Check the validity of a GW1000/GW1100 API response.

            Checks the validity of a GW1000/GW1100 API response. Two checks are performed:
                1.  the third byte of the response is the same as the command code used in the API call
                2.  the calculated checksum of the data in the response matches the checksum byte in the response

            If any check fails an appropriate exception is raised, if all checks pass the method exits without raising an exception.

            response: Response received from the GW1000/GW1100 API call. Bytestring.
            cmd_code: Command code send to GW1000/GW1100 API. Byte string of length one.
            """

            # first check that the 3rd byte of the response is the command code that was issued
            # self.logger.debug(f"CMD out of response is {(response[2])} vs. CMD was {byte_to_int(cmd_code)}")
            if response[2] == byte_to_int(cmd_code):
                # now check the checksum
                calc_checksum = self.calc_checksum(response[2:-1])
                resp_checksum = response[-1]
                # self.logger.debug(f"check_response: checksum extracted from response={resp_checksum} vs. checksum calculated from response={calc_checksum}")
                if calc_checksum == resp_checksum:
                    # checksum check passed, response is deemed valid
                    return
                else:
                    # checksum check failed, raise an InvalidChecksum exception
                    _msg = "Invalid checksum in API response. Expected '%s' (0x%s), received '%s' (0x%s)." % (calc_checksum, "{:02X}".format(calc_checksum), resp_checksum, "{:02X}".format(resp_checksum))
                    raise InvalidChecksum(_msg)
            else:
                # command code check failed, raise an InvalidApiResponse exception
                exp_int = byte_to_int(cmd_code)
                resp_int = response[2]
                _msg = "Invalid command code in API response. Expected '%s' (0x%s), received '%s' (0x%s)." % (exp_int, "{:02X}".format(exp_int), resp_int, "{:02X}".format(resp_int))
                raise InvalidApiResponse(_msg)

        @staticmethod
        def calc_checksum(data):
            """
            Calculate the checksum for a GW1000/GW1100 API call or response.

            The checksum used on the GW1000/GW1100 responses is simply the LSB of the sum of the bytes.

            data: The data on which the checksum is to be calculated. Byte string.

            Returns the checksum as an integer.
            """

            checksum = sum(data)
            return checksum - int(checksum / 256) * 256

        def rediscover(self):
            """
            Attempt to rediscover a lost GW1000/GW1100.

            Use UDP broadcast to discover a GW1000/GW1100 that may have changed to a new IP. We should not be re-discovering a GW1000/GW1100 for
            which the user specified an IP, only for those for which we discovered the IP address on startup. If a GW1000/GW1100 is
            discovered then change my ip_address and port properties as necessary to use the device in future. If the rediscover was
            successful return True otherwise return False.
            """

            # we will only rediscover if we first discovered
            if self.ip_discovered:
                # log that we are attempting re-discovery
                if self.log_failures:
                    self.logger.info(f"Attempting to re-discover {self.model}...")
                # attempt to discover up to self.max_tries times
                for attempt in range(self.max_tries):
                    # sleep before our attempt, but not if it's the first one
                    if attempt > 0:
                        time.sleep(self.retry_wait)
                    try:
                        # discover devices on the local network, the result is a list of dicts in IP address order with each dict
                        # containing data for a unique discovered device
                        self.device_list = self.discover()
                    except socket.error as e:
                        # log the error
                        self.logger.debug(f"Failed attempt {attempt + 1} to detect any devices: {e} {type(e)}")
                    else:
                        # did we find any GW1000/GW1100
                        if len(self.device_list) > 0:
                            # we have at least one, log the fact as well as what we found
                            gw1000_str = ', '.join(f"{d['model']}: {d['ip_address']}:{ d['port']}" for d in self.device_list)
                            if len(self.device_list) == 1:
                                stem = f"{self.device_list[0]['model']} was"
                            else:
                                stem = "Multiple devices were"
                            self.logger.info(f"{stem} found at {gw1000_str}")
                            # keep our current IP address and port in case we don't find a match as we will change our
                            # ip_address and port properties in order to get the MAC for that IP address and port
                            present_ip = self.ip_address
                            present_port = self.port
                            # iterate over each candidate checking their MAC address against my mac property. This way we know
                            # we are connecting to the GW1000/GW1100 we were previously using
                            for _ip, _port in self.device_list:
                                # do the MACs match, if so we have our old device and we can exit the loop
                                if self.mac == self.get_mac_address():
                                    self.ip_address = _ip.encode()
                                    self.port = _port
                                    break
                            else:
                                # exhausted the device_list without a match, revert to our old IP address and port
                                self.ip_address = present_ip
                                self.port = present_port
                                # and continue the outer loop if we have any attempts left
                                continue
                            # log the new IP address and port
                            self.logger.info(f"{self.model} at address {self.ip_address.decode()}:{self.port} will be used")
                            # return True indicating the re-discovery was successful
                            return True
                        else:
                            # did not discover any GW1000/GW1100 so log it
                            if self.log_failures:
                                self.logger.debug(f"Failed attempt {attempt + 1} to detect any devices")
                else:
                    # we exhausted our attempts at re-discovery so log it
                    if self.log_failures:
                        self.logger.info(f"Failed to detect original {self.model} after {self.max_tries} attempts")
            else:
                # an IP address was specified so we cannot go searching, log it
                if self.log_failures:
                    self.logger.debug("IP address specified in config, re-discovery was not attempted")
            # if we made it here re-discovery was unsuccessful so return False
            return False

    class Parser(object):
        """Class to parse GW1000/GW1100 sensor data."""

        # TODO. Would be good to get rid of this too, but it is presently used elsewhere
        multi_batt = {'wh40': {'mask': 1 << 4},
                      'wh26': {'mask': 1 << 5},
                      'wh25': {'mask': 1 << 6},
                      'wh65': {'mask': 1 << 7}
                      }
        # Dictionary keyed by GW1000/GW1100 response element containing various parameters for each response 'field'. Dictionary tuple format is
        # (decode function name, size of data in bytes, GW1000/GW1100 field name)
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
            b'\x16': ('decode_uv', 2, 'solarradiation'),
            b'\x17': ('decode_uvi', 1, 'uvi'),
            b'\x18': ('decode_datetime', 6, 'datetime'),
            b'\x19': ('decode_speed', 2, 'winddaymax'),
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
            # WH34 battery data is not obtained from live data rather it is obtained from sensor ID data
            b'\x63': ('decode_wh34', 3, 'temp9'),
            b'\x64': ('decode_wh34', 3, 'temp10'),
            b'\x65': ('decode_wh34', 3, 'temp11'),
            b'\x66': ('decode_wh34', 3, 'temp12'),
            b'\x67': ('decode_wh34', 3, 'temp13'),
            b'\x68': ('decode_wh34', 3, 'temp14'),
            b'\x69': ('decode_wh34', 3, 'temp15'),
            b'\x6A': ('decode_wh34', 3, 'temp16'),
            # WH45 battery data is not obtained from live data rather it is obtained from sensor ID data
            b'\x70': ('decode_wh45', 16, ('temp17', 'humid17', 'pm10', 'pm10_24h_avg', 'pm255', 'pm255_24h_avg', 'co2', 'co2_24h_avg')),
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
        rain_field_codes = (b'\x0D', b'\x0E', b'\x0F', b'\x10', b'\x11', b'\x12', b'\x13', b'\x14')
        # tuple of field codes for wind related fields in the GW1000/GW1100 live data so we can isolate these fields
        wind_field_codes = (b'\x0A', b'\x0B', b'\x0C', b'\x19')

        def __init__(self, is_wh24=False, debug_rain=False, debug_wind=False):

            # init logger
            self.logger = logging.getLogger(__name__)

            # Tell our battery state decoding whether we have a WH24 or a WH65 (they both share the same battery state bit). By default we are
            # coded to use a WH65. But is there a WH24 connected?
            if is_wh24:
                # We have a WH24. On startup we are set for a WH65 but if it is a restart we will likely already be setup for a WH24. We need
                # to handle both cases.
                if 'wh24' not in self.multi_batt.keys():
                    # we don't have a 'wh24' entry so create one, it's the same as the 'wh65' entry
                    self.multi_batt['wh24'] = self.multi_batt['wh65']
            else:
                # We don't have a WH24 but a WH65. On startup we are set for a WH65 but if it is a restart it is possible we have already
                # been setup for a WH24. We need to handle both cases.
                if 'wh65' not in self.multi_batt.keys():
                    # we don't have a 'wh65' entry so create one, it's the same as the 'wh24' entry
                    self.multi_batt['wh65'] = self.multi_batt['wh24']
            # get debug_rain and debug_wind
            self.debug_rain = debug_rain
            self.debug_wind = debug_wind

        def parse(self, raw_data, timestamp=None):
            """
            Parse raw sensor data.

            Parse the raw sensor data and create a dict of sensor observations/status data. Add a timestamp to the data if one does not already exist.

            Returns a dict of observations/status data."""

            # obtain the response size, it's a big endian short (two byte) integer
            resp_size = struct.unpack(">H", raw_data[3:5])[0]
            # obtain the response
            resp = raw_data[5:5 + resp_size - 4]
            # log the actual sensor data as a sequence of bytes in hex
            # self.logger.debug(f"sensor data={bytes_to_hex(resp}")
            data = {}
            if len(resp) > 0:
                index = 0
                while index < len(resp) - 1:
                    try:
                        decode_str, field_size, field = self.response_struct[resp[index:index + 1]]
                        # self.logger.debug(f"resp[index:index + 1]={resp[index:index + 1]}")
                    except KeyError:
                        # We struck a field 'address' we do not know how to process. Ideally we would like to skip and move onto
                        # the next field (if there is one) but the problem is we do not know how long the data of this unknown
                        # field is. We could go on guessing the field data size by looking for the next field address but we won't
                        # know if we do find a valid field address is it a field address or data from this field? Of course this
                        # could also be corrupt data (unlikely though as it was decoded using a checksum). So all we can really do is
                        # accept the data we have so far, log the issue and ignore the remaining data.
                        self.logger.error(f"Unknown field address '{bytes_to_hex(resp[index:index + 1])}' detected. Remaining sensor data ignored.")
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
            if 'datetime' not in data or ('datetime' in data and data['datetime'] is None):
                # self.logger.debug(f"parse: datetime not in data")
                datetime.fromtimestamp(timestamp).replace(tzinfo=timezone.utc) if timestamp is not None else datetime.fromtimestamp(int(time.time() + 0.5)).replace(tzinfo=timezone.utc)
            return data

        @staticmethod
        def decode_temp(data, field=None):
            """
            Decode temperature data.

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
            """
            Decode humidity data.

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

        @staticmethod
        def decode_press(data, field=None):
            """
            Data is contained in a two byte big endian integer and represents
            tenths of a unit. If data contains more than two bytes take the
            last two bytes. If field is not None return the result as a dict in
            the format {field: decoded value} otherwise return just the decoded
            value.
            Also used to decode other two byte big endian integer fields.
            """

            if len(data) == 2:
                value = struct.unpack(">H", data)[0] / 10.0
            elif len(data) > 2:
                value = struct.unpack(">H", data[-2:])[0] / 10.0
            else:
                value = None
            if field is not None:
                return {field: value}
            else:
                return value

        @staticmethod
        def decode_uv(data, field=None):
            """
            Data is contained in a two byte big endian integer and represents
            tenths of a unit. If data contains more than two bytes take the
            last two bytes. If field is not None return the result as a dict in
            the format {field: decoded value} otherwise return just the decoded
            value.
            Also used to decode other two byte big endian integer fields.
            """

            if len(data) == 2:
                value = struct.unpack(">H", data)[0] / 10.0
            elif len(data) > 2:
                value = struct.unpack(">H", data[-2:])[0] / 10.0
            else:
                value = None
            if field is not None:
                return {field: value}
            else:
                return value

        @staticmethod
        def decode_dir(data, field=None):
            """
            Decode direction data.

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

        @staticmethod
        def decode_big_rain(data, field=None):
            """
            Decode 4 byte rain data.

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

        @staticmethod
        def decode_datetime(data, field=None):
            """
            Decode date-time data.

            Unknown format but length is six bytes.
            """

            if len(data) == 6:
                value = struct.unpack("BBBBBB", data)
                value = datetime.fromtimestamp(value[0]).replace(tzinfo=timezone.utc)       # convert timestamp to datetime
            else:
                value = None
            if field is not None:
                return {field: value}
            else:
                return value

        @staticmethod
        def decode_distance(data, field=None):
            """
            Decode lightning distance.

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

        @staticmethod
        def decode_utc(data, field=None):
            """
            Decode UTC time.

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

        @staticmethod
        def decode_count(data, field=None):
            """
            Decode lightning count.

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
        decode_uvi = decode_humid
        decode_moist = decode_humid
        decode_pm25 = decode_press
        decode_leak = decode_humid
        decode_pm10 = decode_press
        decode_co2 = decode_dir
        decode_wet = decode_humid

        def decode_wh34(self, data, field=None):
            """
            Decode WH34 sensor data.

            Data consists of three bytes:
                Byte    Field               Comments
                1-2     temperature         standard Ecowitt temperature data, two byte big endian signed integer representing tenths of a degree
                3       battery voltage     0.02 * value Volts
            """

            if len(data) == 3 and field is not None:
                results = {field: self.decode_temp(data[0:2])}
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
                # we could decode the battery state but we will be obtaining battery state data from the sensor IDs in a later step so
                # we can skip it here
                return results
            return {}

        @staticmethod
        def decode_batt(data, field=None):
            """
            Decode battery status data.

            GW1000/GW1100 firmware version 1.6.4 and earlier supported 16 bytes of battery state data at response field x4C for the following
            sensors:
                WH24, WH25, WH26(WH32), WH31 ch1-8, WH40, WH41/WH43 ch1-4, WH51 ch1-8, WH55 ch1-4, WH57, WH68 and WS80

            As of firmware version 1.6.5 the 16 bytes of battery state data is no longer returned at all. CMD_READ_SENSOR_ID_NEW or
            CMD_READ_SENSOR_ID must be used to obtain battery state information for connected sensors. The decode_batt() method has been retained
            to support devices using firmware version 1.6.4 and earlier.

            Since the GW1000/GW1100 driver now obtains battery state information via CMD_READ_SENSOR_ID_NEW or CMD_READ_SENSOR_ID only
            the decode_batt() method now returns None so that firmware versions before 1.6.5 continue to be supported.
            """

            return None

    class Sensors(object):
        """
        Class to manage GW1000/GW1100 sensor ID data.

        Class Sensors allows access to various elements of sensor ID data via a number of properties and methods when the class is initialised with the
        GW1000/GW1100 API response to a CMD_READ_SENSOR_ID_NEW or CMD_READ_SENSOR_ID command.

        A Sensors object can be initialised with sensor ID data on instantiation or an existing Sensors object can be updated by calling
        the set_sensor_id_data() method passing the sensor ID data to be used as the only parameter.
        """

        # Tuple of sensor ID values for sensors that are not registered with the GW1000/GW1100. 'fffffffe' means the sensor is disabled, 'ffffffff' means the sensor is registering.
        not_registered = ('fffffffe', 'ffffffff')

        def __init__(self, sensor_id_data=None, show_battery=False, debug_sensors=False, plugin_instance=None):

            # get instance
            self._plugin_instance = plugin_instance
            self.logger = self._plugin_instance.logger

            # set the show_battery property
            self.show_battery = show_battery

            # initialise a dict to hold the parsed sensor data
            self.sensor_data = {}

            # parse the raw sensor ID data and store the results in my parsed sensor data dict
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
                        sensor_id = bytes_to_hex(data[index + 1: index + 5], separator='', caps=False)
                        # get the method to be used to decode the battery state data
                        batt_fn = Gw1000Collector.sensor_ids[data[index:index + 1]]['batt_fn']
                        # get the raw battery state data
                        batt = data[index + 5]
                        # if we are not showing all battery state data then the battery state for any sensor with signal == 0 must be set to None, otherwise parse the raw battery state data as applicable
                        if not self.show_battery and data[index + 6] == 0:
                            batt_state = None
                        else:
                            # parse the raw battery state data
                            batt_state = getattr(self, batt_fn)(batt)
                        # now add the sensor to our sensor data dict
                        self.sensor_data[address] = {'id': sensor_id, 'battery': batt_state, 'signal': data[index + 6]}
                    else:
                        if self.debug_sensors:
                            self.logger.info("Unknown sensor ID '%s'" % bytes_to_hex(address))
                    # each sensor entry is seven bytes in length so skip to the
                    # start of the next sensor
                    index += 7

        @property
        def addresses(self):
            """
            Obtain a list of sensor addresses.

            This includes all sensor addresses reported by the GW1000/GW1100, this includes:
            - sensors that are actually connected to the GW1000/GW1100
            - sensors that are attempting to connect to the GW1000/GW1100
            - GW1000/GW1100 sensor addresses that are searching for a sensor
            - GW1000/GW1100 sensor addresses that are disabled
            """

            # this is simply the list of keys to our sensor data dict
            return self.sensor_data.keys()

        @property
        def connected_addresses(self):
            """
            Obtain a list of sensor addresses for connected sensors only.

            Sometimes we only want a list of addresses for sensors that are actually connected to the GW1000/GW1100. We can filter out those
            addresses that do not have connected sensors by looking at the sensor ID. If the sensor ID is 'fffffffe' either the sensor is
            connecting to the GW1000/GW1100 or the GW1000/GW1100 is searching for a sensor for that address. If the sensor ID is 'ffffffff' the
            GW1000/GW1100 sensor address is disabled.
            """

            # initialise a list to hold our connected sensor addresses
            connected_list = list()
            # iterate over all sensors
            for address, data in self.sensor_data.items():
                # if the sensor ID is neither 'fffffffe' or 'ffffffff' then it must be connected
                if data['id'] not in self.not_registered:
                    connected_list.append(address)
            return connected_list

        @property
        def connected_sensors(self):
            """
            Obtain a list of sensor types for connected sensors only.

            Sometimes we only want a list of sensors that are actually connected to the GW1000/GW1100.
            """

            # initialise a list to hold our connected sensors
            connected_list = list()
            # iterate over our connected sensors
            for sensor in self.connected_addresses:
                # get the sensor name
                connected_list.append(Gw1000Collector.sensor_ids[sensor]['name'])
            return connected_list

        @property
        def data(self):
            """Obtain the data dict for all known sensors."""

            return self.sensor_data

        def id(self, address):
            """Obtain the sensor ID for a given sensor address."""

            return self.sensor_data[address]['id']

        def battery_state(self, address):
            """Obtain the sensor battery state for a given sensor address."""

            return self.sensor_data[address]['battery']

        def signal_level(self, address):
            """Obtain the sensor signal level for a given sensor address."""

            return self.sensor_data[address]['signal']

        @property
        def battery_and_signal_data(self):
            """
            Obtain a dict of sensor battery state and signal level data.

            Iterate over the list of connected sensors and obtain a dict of sensor battery state data for each connected sensor.
            """

            # initialise a dict to hold the battery state data
            data = {}
            # iterate over our connected sensors
            for sensor in self.connected_addresses:
                # get the sensor name
                sensor_name = Gw1000Collector.sensor_ids[sensor]['name']
                # create the sensor battery state field for this sensor
                data[f"{sensor_name}_batt"] = self.battery_state(sensor)
                # create the sensor signal level field for this sensor
                data[f"{sensor_name}_sig"] = self.signal_level(sensor)

            # return our data
            return data

        @property
        def battery_description_data(self):
            """
            Obtain a dict of sensor battery state description data.

            Iterate over the list of connected sensors and obtain a dict of sensor battery state description data for each connected sensor.
            """

            # initialise a dict to hold the battery state description data
            data = {}
            for sensor in self.connected_addresses:
                # get the sensor name
                sensor_name = Gw1000Collector.sensor_ids[sensor]['name']
                # create the sensor battery state description field for this sensor
                data[sensor_name] = self.battery_desc(sensor, self.battery_state(sensor))

            # return our data
            return data

        @staticmethod
        def battery_desc(address, value):
            """
            Determine the battery state description for a given sensor.

            Given the address...
            """

            if value is not None:
                batt_fn = Gw1000Collector.sensor_ids[address].get('batt_fn')
                if batt_fn == 'batt_binary':
                    if value == 0:
                        return "OK"
                    elif value == 1:
                        return "low"
                    else:
                        return 'Unknown'
                elif batt_fn == 'batt_int':
                    if value <= 1:
                        return "low"
                    elif value == 6:
                        return "DC"
                    elif value <= 5:
                        return "OK"
                    else:
                        return 'Unknown'
                elif batt_fn == 'batt_volt' or batt_fn == 'batt_volt_tenth':
                    if value <= 1.2:
                        return "low"
                    else:
                        return "OK"
            else:
                return 'Unknown'

        @staticmethod
        def batt_binary(batt):
            """
            Decode a binary battery state.

            Battery state is stored in bit 0 as either 0 or 1. If 1 the battery is low, if 0 the battery is normal. We need to mask off bits 1 to 7 as
            they are not guaranteed to be set in any particular way.
            """

            return batt & 1

        @staticmethod
        def batt_int(batt):
            """
            Decode a integer battery state.

            According to the API documentation battery state is stored as an integer from 0 to 5 with <=1 being considered low. Experience with
            WH43 has shown that battery state 6 also exists when the device is run from DC. This does not appear to be documented in the API
            documentation.
            """

            return batt

        @staticmethod
        def batt_volt(batt):
            """
            Decode a voltage battery state in 2mV increments.

            Battery state is stored as integer values of battery voltage/0.02 with <=1.2V considered low.
            """

            return round(0.02 * batt, 2)

        @staticmethod
        def batt_volt_tenth(batt):
            """
            Decode a voltage battery state in 100mV increments.

            Battery state is stored as integer values of battery voltage/0.1
            with <=1.2V considered low.
            """

            return round(0.1 * batt, 1)

# ============================================================================
#                        Gateway TCP/ECOWITT classes
# ============================================================================


class Gw1000TcpDriver(Gw1000):

    def __init__(self, tcp_server_address, tcp_server_port, data_cycle, gateway_address, plugin_instance):
        """Initialise a GW1000/GW1100 API driver object."""

        # now initialize my superclasses
        super().__init__(data_cycle, plugin_instance)

        # init instance
        self._plugin_instance = plugin_instance
        self.logger = self._plugin_instance.logger

        # log the relevant settings/parameters we are using
        self.logger.debug("Starting Gw1000TcpDriver")

        # log all found sensors since beginning of plugin as a set
        self.sensors = []

        # log sensors, that were missed with count of cycles
        self.sensors_missed = {}

        # get ECOWITT client
        self.client = EcowittClient(tcp_server_address=tcp_server_address,
                                    tcp_server_port=tcp_server_port,
                                    debug_rain=False,
                                    debug_wind=False,
                                    plugin_instance=plugin_instance)

        # start the ECOWITT client in its own thread
        self.client.startup()
        self.driver_alive = True

        self.ip_selected_gateway = gateway_address

    def closePort(self):
        self.logger.info('Stop and Shutdown of FoshkPlugin TCP Server called')
        self.driver_alive = False
        self.client.stop_server()
        self.client.shutdown()

    def genLoopPackets(self):
        # generate loop packets forever
        while self.driver_alive:
            # wrap in a try to catch any instances where the queue is empty
            try:
                # get any data from the collector queue
                queue_data = self.client.data_queue.get(True, 10)
                # self.logger.debug(f"TCP: queue_data={queue_data}")
            except queue.Empty:
                # self.logger.debug("TCP. genLoopPackets: there was nothing in the queue so continue")
                # there was nothing in the queue so continue
                pass
            else:
                self.logger.debug(f"TCP. genLoopPackets: queue_data={queue_data}")
                parsed_data = self.client.parser.parse(queue_data)
                self.logger.debug(f"TCP. genLoopPackets: parsed_data={parsed_data}")

                client_ip = parsed_data['client_ip']
                # self.logger.debug(f"TCP. genLoopPackets: client_ip={client_ip}, gateway_ip={self.ip_selected_gateway}")

                if client_ip == self.ip_selected_gateway:
                    con_data = self.client.parser.convert_data(parsed_data)
                    self.client.sensors_obj.get_sensor_data(con_data)
                    # self.logger.debug(f"TCP. genLoopPackets: con_data={con_data}")

                    clean_data = self.client.parser.clean_data(con_data)
                    self.logger.debug(f"TCP. genLoopPackets: clean_data={clean_data}")

                    # put timestamp of now to packet
                    packet = {'timestamp': int(time.time() + 0.5)}

                    if 'datetime' in clean_data and isinstance(clean_data['datetime'], datetime):
                        packet['datetime_utc'] = clean_data['datetime']
                    else:
                        # we don't have a datetime at utc so create one
                        packet['datetime_utc'] = datetime.utcnow().replace(tzinfo=timezone.utc)

                    # if not already determined, determine which cumulative rain field will be used to determine the per period rain field
                    if not self.rain_mapping_confirmed:
                        self.get_cumulative_rain_field(clean_data)

                    # get the rainfall for this period from total
                    self.calculate_rain(clean_data)

                    # get the lightning strike count for this period from total
                    self.calculate_lightning_count(clean_data)

                    # add calculated data to queue_data
                    self.add_calculated_data(clean_data)

                    # add battery warning data field and log entry if enabled
                    if self._plugin_instance.batterywarning:
                        self.check_battery(clean_data)

                    # add sensor warning data field and log entry if enabled
                    if self._plugin_instance.sensorwarning:
                        self.check_sensors(clean_data)

                    # add the queue_data to the empty packet
                    packet.update(clean_data)

                    # log the packet if necessary, there are several debug settings that may require this, start from the highest (most encompassing) and work to the lowest (least encompassing)
                    if self.debug_loop:
                        self.logger.info(f"TCP. genLoopPackets: Packet {datetime_to_string(packet['datetime_utc'])}: {natural_sort_dict(packet)}")
                    # yield the loop packet
                    yield packet
                # else:
                    # self.logger.debug(f"TCP. genLoopPackets: Received message was from client_ip={client_ip} and therefore not from selected  gateway={self.ip_selected_gateway}. Message will be ignored.")

    def check_battery(self, data):
        """Check if batteries states are critical, create log entry and add a separate field for battery warning."""

        # get battery data
        raw_data = self.client.battery_desc
        # init string to collect message
        batterycheck = ''
        # iterate over data to look for critical battery
        for key in raw_data:
            if raw_data[key] != 'OK':
                if batterycheck != '':
                    batterycheck += ', '
                batterycheck += key
        # check result, create log entry data field
        if batterycheck != "":
            data['battery_warning'] = 0
            if not self.battery_warning:
                self.logger.warning(f"<WARNING> TCP: Battery level for sensor(s) {batterycheck} is critical - please swap battery")
                self.battery_warning = True
                data['battery_warning'] = 1
        elif self.battery_warning:
            self.logger.info("<OK> TCP: Battery level for all sensors is ok again")
            self.battery_warning = False
            data['battery_warning'] = 0

    def check_sensors(self, data: dict, missing_count: int = 2):
        """Check if all know sensors are still connected, create log entry and add a separate field for sensor warning."""

        # get currently connected sensors
        connected_sensors = self.client.sensors.connected_sensors
        # log all found sensors during runtime
        self.sensors = list(set(self.sensors + connected_sensors))

        # check if all sensors are still connected, create log entry data field
        if set(connected_sensors) == set(self.sensors):
            # self.logger.debug(f"check_sensors: All sensors are still connected!")
            self.sensor_warning = False
            data['sensor_warning'] = 0
            self.sensors_missed.clear()
        else:
            missing_sensors = list(set(self.sensors).difference(set(connected_sensors)))
            self.update_missing_sensor_dict(missing_sensors)

            blacklist = set()
            for sensor in self.sensors_missed:
                if self.sensors_missed[sensor] >= missing_count:
                    blacklist.add(sensor)

            if blacklist:
                self.logger.error(f"TCP: check_sensors: The following sensors where lost (more than {missing_count} data cycles): {list(blacklist)}")
                self.sensor_warning = True
                data['sensor_warning'] = 1
            else:
                self.sensor_warning = False
                data['sensor_warning'] = 0

    def update_missing_sensor_dict(self, missing_sensors: list):
        """
        Get list of sensors, which were lost/missed in last data cycle and udpate missing_sensor_dict with count of missing cycles.
        """

        for sensor in missing_sensors:
            if sensor not in self.sensors_missed:
                self.sensors_missed[sensor] = 1
            else:
                self.sensors_missed[sensor] += 1

        self.logger.debug(f"sensors_missed={self.sensors_missed}")


class EcowittClient:
    """
    Use the ecowitt protocol (not WU protocol) to capture data

    Capture data from devices that transmit using ecowitt protocol, such as the
    Fine Offset GW1000 bridge.

    * the bridge attempts to upload to rtpdate.ecowitt.net using HTTP GET
    * the protocol is called 'ecowitt' - it is similar to but incompatible with WU

    The ecowitt.net server responds with HTTP 200.  However, the payload varies
    depending on the configuration.

    When the device is not registered, the ecowitt.net server replies with:

    {"errcode":"40001","errmsg":"invalid passkey"}

    When the device has been registered, the ecowitt.net server replies with:

    {"errcode":"0","errmsg":"ok","UTC_offset":"-18000"}

    The device is a bit chatty - every 2 seconds it does a UDP broadcast.  Every
    10 seconds it does an ARP broadcast.

    The UDP broadcast packet is 35 bytes.  It contains the MAC address, IP address,
    and SSID of the GW1000.  For example:

    FFFF120021807D5A3D537AC0A84C08AFC810475731303030422D5749464935333741B3

    which breaks down to:

    FFFF 120021 807D5A3D537A C0A84C08 AFC810 475731303030422D5749464935333741
         ------ ------------ -------- ------ --------------------------------
         ?      MAC          IPADDR   ?       G W 1 0 0 0 B - W I F I 5 3 7 A

    Here the IPADDR is 192.168.76.8, and the SSID uses the last 4 digits of the
    MAC address.

    """

    sensor_ids = {
            'wh65':     {'long_name': 'WH65',     'batt_fn': 'batt_binary'},
            'wh68':     {'long_name': 'WH68',     'batt_fn': 'batt_volt'},
            'ws80':     {'long_name': 'WS80',     'batt_fn': 'batt_volt'},
            'wh40':     {'long_name': 'WH40',     'batt_fn': 'batt_binary'},
            'wh25':     {'long_name': 'WH25',     'batt_fn': 'batt_binary'},
            'wh26':     {'long_name': 'WH26',     'batt_fn': 'batt_binary'},
            'wh31_ch1': {'long_name': 'WH31 ch1', 'batt_fn': 'batt_binary'},
            'wh31_ch2': {'long_name': 'WH31 ch2', 'batt_fn': 'batt_binary'},
            'wh31_ch3': {'long_name': 'WH31 ch3', 'batt_fn': 'batt_binary'},
            'wh31_ch4': {'long_name': 'WH31 ch4', 'batt_fn': 'batt_binary'},
            'wh31_ch5': {'long_name': 'WH31 ch5', 'batt_fn': 'batt_binary'},
            'wh31_ch6': {'long_name': 'WH31 ch6', 'batt_fn': 'batt_binary'},
            'wh31_ch7': {'long_name': 'WH31 ch7', 'batt_fn': 'batt_binary'},
            'wh31_ch8': {'long_name': 'WH31 ch8', 'batt_fn': 'batt_binary'},
            'wh51_ch1': {'long_name': 'WH51 ch1', 'batt_fn': 'batt_volt'},
            'wh51_ch2': {'long_name': 'WH51 ch2', 'batt_fn': 'batt_volt'},
            'wh51_ch3': {'long_name': 'WH51 ch3', 'batt_fn': 'batt_volt'},
            'wh51_ch4': {'long_name': 'WH51 ch4', 'batt_fn': 'batt_volt'},
            'wh51_ch5': {'long_name': 'WH51 ch5', 'batt_fn': 'batt_volt'},
            'wh51_ch6': {'long_name': 'WH51 ch6', 'batt_fn': 'batt_volt'},
            'wh51_ch7': {'long_name': 'WH51 ch7', 'batt_fn': 'batt_volt'},
            'wh51_ch8': {'long_name': 'WH51 ch8', 'batt_fn': 'batt_volt'},
            'wh41_ch1': {'long_name': 'WH41 ch1', 'batt_fn': 'batt_int'},
            'wh41_ch2': {'long_name': 'WH41 ch2', 'batt_fn': 'batt_int'},
            'wh41_ch3': {'long_name': 'WH41 ch3', 'batt_fn': 'batt_int'},
            'wh41_ch4': {'long_name': 'WH41 ch4', 'batt_fn': 'batt_int'},
            'wh57':     {'long_name': 'WH57',     'batt_fn': 'batt_int'},
            'wh55_ch1': {'long_name': 'WH55 ch1', 'batt_fn': 'batt_int'},
            'wh55_ch2': {'long_name': 'WH55 ch2', 'batt_fn': 'batt_int'},
            'wh55_ch3': {'long_name': 'WH55 ch3', 'batt_fn': 'batt_int'},
            'wh55_ch4': {'long_name': 'WH55 ch4', 'batt_fn': 'batt_int'},
            'wh34_ch1': {'long_name': 'WH34 ch1', 'batt_fn': 'batt_volt'},
            'wh34_ch2': {'long_name': 'WH34 ch2', 'batt_fn': 'batt_volt'},
            'wh34_ch3': {'long_name': 'WH34 ch3', 'batt_fn': 'batt_volt'},
            'wh34_ch4': {'long_name': 'WH34 ch4', 'batt_fn': 'batt_volt'},
            'wh34_ch5': {'long_name': 'WH34 ch5', 'batt_fn': 'batt_volt'},
            'wh34_ch6': {'long_name': 'WH34 ch6', 'batt_fn': 'batt_volt'},
            'wh34_ch7': {'long_name': 'WH34 ch7', 'batt_fn': 'batt_volt'},
            'wh34_ch8': {'long_name': 'WH34 ch8', 'batt_fn': 'batt_volt'},
            'wh45':     {'long_name': 'WH45',     'batt_fn': 'batt_int'},
            'wh35_ch1': {'long_name': 'WH35 ch1', 'batt_fn': 'batt_volt'},
            'wh35_ch2': {'long_name': 'WH35 ch2', 'batt_fn': 'batt_volt'},
            'wh35_ch3': {'long_name': 'WH35 ch3', 'batt_fn': 'batt_volt'},
            'wh35_ch4': {'long_name': 'WH35 ch4', 'batt_fn': 'batt_volt'},
            'wh35_ch5': {'long_name': 'WH35 ch5', 'batt_fn': 'batt_volt'},
            'wh35_ch6': {'long_name': 'WH35 ch6', 'batt_fn': 'batt_volt'},
            'wh35_ch7': {'long_name': 'WH35 ch7', 'batt_fn': 'batt_volt'},
            'wh35_ch8': {'long_name': 'WH35 ch8', 'batt_fn': 'batt_volt'}
        }

    # create queue object
    data_queue = queue.Queue()

    def __init__(self, tcp_server_address, tcp_server_port, data_cycle=0, use_th32=False, show_battery=False, debug_rain=False, debug_wind=False, debug_sensors=False, plugin_instance=None):

        # initialize superclass
        # super().__init__(plugin_instance)

        # get instance
        self._plugin_instance = plugin_instance
        self.logger = self._plugin_instance.logger

        self._server_thread = None
        self.collect_data = False
        self.data_cylce = data_cycle

        # log the relevant settings/parameters we are using
        self.logger.debug("Starting EcowittClient")

        # get a parser object to parse any data from the station
        self.parser = EcowittClient.Parser(plugin_instance)

        # get tcp server object
        self._server = EcowittClient.TCPServer(tcp_server_address, tcp_server_port, EcowittClient.Handler, plugin_instance)

        # get a sensors object to handle sensor data
        self.sensors_obj = EcowittClient.Sensors(show_battery=show_battery, debug_sensors=debug_sensors, plugin_instance=plugin_instance)

    def run_server(self):
        self._server.run()

    def stop_server(self):
        self._server.stop()
        self._server = None

    def startup(self):
        """Start a thread that collects data from the GW1000/GW1100 TCP."""

        try:
            self._server_thread = threading.Thread(target=self.run_server)
            self._server_thread.setDaemon(True)
            _name = 'plugins.' + self._plugin_instance.get_fullname() + '.Gw1000TCP-Server'
            self._server_thread.setName(_name)
            self._server_thread.start()
        except threading.ThreadError:
            self.logger.error("Unable to launch Gw1000Collector thread")
            self._server_thread = None

    def shutdown(self):
        """Shut down the thread that collects data from the GW1000/GW1100 TCP."""

        if self._server_thread:
            self.collect_data = False
            self._server_thread.join(10)
            if self._server_thread.is_alive():
                self.logger.error("Unable to shut down Gw1000Collector thread")
            else:
                self.logger.info("Gw1000Collector thread has been terminated")
        self._server_thread = None

    @property
    def sensors(self):
        """Get the current Sensors object."""

        return self.sensors_obj

    @property
    def battery_desc(self):

        return self.sensors_obj.battery_description_data

    @property
    def firmware_version(self):
        """Obtain the GW1000/GW1100 firmware version string."""

        return self.sensors_obj.sensor_data['firmware']

    @property
    def model(self):
        """Obtain the model."""

        t = self.sensors_obj.sensor_data['model']
        if t is not None:
            # we have a string, now do we have a know model in the string, if so return the model string
            for model in KNOWN_MODELS:
                if model in t.upper():
                    return model
            # we don't have a known model so return None
            return None
        else:
            # we have no string so return None
            return None

    @property
    def frequency(self):
        """Obtain the GW1000/GW1100 frequency."""

        return self.sensors_obj.sensor_data['frequency']

    @property
    def device_id(self):
        """Generate device_id from passkey"""

        return str(hash(self.sensors_obj.sensor_data['passkey']))[1:13]

    @property
    def gateway_ip(self):
        """Obtain the GW1000/GW1100 IP."""

        return self.sensors_obj.sensor_data['client_ip']

    def get_queue(self):
        return self.data_queue

    class Server(object):

        def run(self):
            pass

        def stop(self):
            pass

    class TCPServer(Server, socketserver.TCPServer):

        daemon_threads = True
        allow_reuse_address = True

        def __init__(self, address, port, handler, plugin_instance):

            # init instance
            self._plugin_instance = plugin_instance
            self.logger = self._plugin_instance.logger

            # init TCP Server
            self.logger.info(f"start tcp server at {address}:{port}")
            socketserver.TCPServer.__init__(self, (address, int(port)), handler)

        def run(self):
            # self.logger.debug("start tcp server")
            self.serve_forever()

        def stop(self):
            self.logger.debug("Stop von FoshkPlugin TCP Server called")
            self.shutdown()
            self.server_close()

    class Handler(BaseHTTPRequestHandler):

        def reply(self):
            # standard reply is HTTP code of 200 and the response string
            ok_answer = "OK\n"
            self.send_response(200)
            self.send_header("Content-Length", str(len(ok_answer)))
            self.end_headers()
            self.wfile.write(ok_answer.encode())

        def do_POST(self):
            # get the payload from an HTTP POST
            # logger = logging.getLogger(__name__)
            client_ip = self.client_address[0]
            # logger.debug(f"POST: client_address={client_ip}")
            length = int(self.headers["Content-Length"])
            data = self.rfile.read(length)
            # logger.debug(f"POST: {str(data)}")
            self.reply()
            try:
                data = data.decode()
            except Exception:
                pass
            else:
                data += f'&client_ip={client_ip}'
                # logger.debug(f"POST: {obfuscate_passwords(str(data))}")
                EcowittClient.data_queue.put(data)

        def do_PUT(self):
            pass

        def do_GET(self):
            logger = logging.getLogger(__name__)
            # get the query string from an HTTP GET
            data = urlparse.urlparse(self.path).query
            logger.debug(f"GET: {obfuscate_passwords(data)}")
            EcowittClient.data_queue.put(data)
            self.reply()

    class Parser(object):
        """Class to parse GW1000/GW1100 ECOWITT data."""

        def __init__(self, plugin_instance):

            # set properties
            self._last_rain = None
            self._rain_mapping_confirmed = False
            self._plugin_instance = plugin_instance
            self.logger = self._plugin_instance.logger

        @staticmethod
        def parse(data):
            """Parse the ecowitt data and add it to a dictionary."""
            data_dict = {}
            line = data.splitlines()[0]
            if ':' in line and '&' in line:
                for item in line.split('&'):
                    key, value = item.split('=', 1)
                    try:
                        value = float(value)
                        if value.is_integer():
                            value = int(value)
                    except Exception:
                        if type(value) is str:
                            value = value.lstrip()
                        pass
                    data_dict[key] = value
            return data_dict

        def convert_data(self, data):
            """Harmonize field names and convert into metric units"""

            response_struct = {
                # Generic
                'client_ip':            (None,      'client_ip'),
                'PASSKEY':              (None,      'passkey'),
                'stationtype':          (None,      'firmware'),
                'freq':                 (None,      'frequency'),
                'model':                (None,      'model'),
                'dateutc':              (str_to_datetimeutc,   'datetime'),
                'runtime':              (None,      'runtime'),
                'interval':             (None,      'interval'),
                # Indoor
                'tempinf':              (f_to_c,    'intemp'),
                'humidityin':           (None,      'inhumid'),
                'baromrelin':           (in_to_hpa, 'relbarometer'),
                'baromabsin':           (in_to_hpa, 'absbarometer'),
                # WH 65 / WH24
                'tempf':                (f_to_c,    'outtemp'),
                'humidity':             (None,      'outhumid'),
                'winddir':              (None,      'winddir'),
                'windspeedmph':         (mph_to_ms, 'windspeed'),
                'windgustmph':          (mph_to_ms, 'gustspeed'),
                'maxdailygust':         (mph_to_ms, 'winddaymax'),
                'solarradiation':       (solar,      'solarradiation'),
                'uv':                   (None,      'uvi'),
                'rainratein':           (in_to_mm,  'rainrate'),
                'eventrainin':          (in_to_mm,  'rainevent'),
                'hourlyrainin':         (in_to_mm,  'rainhour'),
                'dailyrainin':          (in_to_mm,  'rainday'),
                'weeklyrainin':         (in_to_mm,  'rainweek'),
                'monthlyrainin':        (in_to_mm,  'rainmonth'),
                'yearlyrainin':         (in_to_mm,  'rainyear'),
                'totalrainin':          (in_to_mm,  'raintotal'),
                'wh65batt':             (None,      'wh65_batt'),
                # WH31
                'temp1f':               (f_to_c,    'temp1'),
                'humidity1':            (None,      'humid1'),
                'batt1':                (None,      'wh31_ch1_batt'),
                'temp2f':               (f_to_c,    'temp2'),
                'humidity2':            (None,      'humid2'),
                'batt2':                (None,      'wh31_ch2_batt'),
                'temp3f':               (f_to_c,    'temp3'),
                'humidity3':            (None,      'humid3'),
                'batt3':                (None,      'wh31_ch3_batt'),
                'temp4f':               (f_to_c,    'temp4'),
                'humidity4':            (None,      'humid4'),
                'batt4':                (None,      'wh31_ch4_batt'),
                'temp5f':               (f_to_c,    'temp5'),
                'humidity5':            (None,      'humid5'),
                'batt5':                (None,      'wh31_ch5_batt'),
                'temp6f':               (f_to_c,    'temp6'),
                'humidity6':            (None,      'humid6'),
                'batt6':                (None,      'wh31_ch6_batt'),
                'temp7f':               (f_to_c,    'temp7'),
                'humidity7':            (None,      'humid7'),
                'batt7':                (None,      'wh31_ch7_batt'),
                'temp8f':               (f_to_c,    'temp8'),
                'humidity8':            (None,      'humid8'),
                'batt8':                (None,      'wh31_ch8_batt'),
                # WN51
                'soilmoisture1':        (None,      'soilmoist1'),
                'soilbatt1':            (None,      'wh51_ch1_batt'),
                'soilmoisture2':        (None,      'soilmoist2'),
                'soilbatt2':            (None,      'wh51_ch2_batt'),
                'soilmoisture3':        (None,      'soilmoist3'),
                'soilbatt3':            (None,      'wh51_ch3_batt'),
                'soilmoisture4':        (None,      'soilmoist4'),
                'soilbatt4':            (None,      'wh51_ch4_batt'),
                'soilmoisture5':        (None,      'soilmoist5'),
                'soilbatt5':            (None,      'wh51_ch5_batt'),
                'soilmoisture6':        (None,      'soilmoist6'),
                'soilbatt6':            (None,      'wh51_ch6_batt'),
                'soilmoisture7':        (None,      'soilmoist7'),
                'soilbatt7':            (None,      'wh51_ch7_batt'),
                'soilmoisture8':        (None,      'soilmoist8'),
                'soilbatt8':            (None,      'wh51_ch8_batt'),
                # WH34
                'tf_ch1':               (f_to_c,    'temp_tf_ch1'),
                'tf_ch2':               (f_to_c,    'temp_tf_ch2'),
                'tf_ch3':               (f_to_c,    'temp_tf_ch3'),
                'tf_ch4':               (f_to_c,    'temp_tf_ch4'),
                'tf_ch5':               (f_to_c,    'temp_tf_ch5'),
                'tf_ch6':               (f_to_c,    'temp_tf_ch6'),
                'tf_ch7':               (f_to_c,    'temp_tf_ch7'),
                'tf_ch8':               (f_to_c,    'temp_tf_ch8'),
                # WH45
                'tf_co2':               (f_to_c, 'temp17'),
                'humi_co2':             (None, 'humid17'),
                'pm10_co2':             (None, 'pm10'),
                'pm10_24h_co2':         (None, 'pm10_24h_avg'),
                'pm25_co2':             (None, 'pm255'),
                'pm25_24h_co2':         (None, 'pm255_24h_avg'),
                'co2':                  (None, 'co2'),
                'co2_24h':              (None, 'co2_24h_avg'),
                'co2_batt':             (None, 'wh45_batt'),
                # WH41 / WH43
                'pm25_ch1':             (None, 'pm251'),
                'pm25_avg_24h_ch1':     (None, 'pm251_24h_avg'),
                'pm25batt1':            (None, 'pm251_batt'),
                'pm25_ch2':             (None, 'pm252'),
                'pm25_avg_24h_ch2':     (None, 'pm252_24h_avg'),
                'pm25batt2':            (None, 'pm252_batt'),
                'pm25_ch3':             (None, 'pm253'),
                'pm25_avg_24h_ch3':     (None, 'pm253_24h_avg'),
                'pm25batt3':            (None, 'pm253_batt'),
                'pm25_ch4':             (None, 'pm254'),
                'pm25_avg_24h_ch4':     (None, 'pm254_24h_avg'),
                'pm25batt4':            (None, 'pm254_batt'),
                # WH55
                'leak1':                (None, 'leak_ch1'),
                'leak2':                (None, 'leak_ch2'),
                'leak3':                (None, 'leak_ch3'),
                'leak4':                (None, 'leak_ch4'),
                'leakbatt1':            (None, 'leak_ch1_batt'),
                'leakbatt2':            (None, 'leak_ch2_batt'),
                'leakbatt3':            (None, 'leak_ch3_batt'),
                'leakbatt4':            (None, 'leak_ch4_batt'),
                # WH25
                'wh25batt':             (None, 'wh25_batt'),
                # WH57
                'lightning_day':        (None,       'lightning_num'),
                'lightning_distance':   (None,       'lightning'),
                'lightning_time':       (None,       'lightning_time'),
                # others
                'cloudf':               (f_to_m,     'cloud_ceiling'),
                'indoortempf':          (f_to_m,     'indoortemp'),
                'windchillf':           (f_to_m,     'windchill'),
                'feelslikef':           (f_to_m,     'feelslike'),
                'dewptf':               (f_to_m,     'dewpt'),
                'heatindexf':           (f_to_m,     'heatindex'),
                'baromin':              (in_to_hpa,  'baromin'),
                'absbaro':              (in_to_hpa,  'baromin'),
                }

            data_dict = {}
            for key in data:
                try:
                    decoder, field = response_struct[key]
                except KeyError:
                    self.logger.error(f"Unknown key '{key}' with value '{data[key]}'detected. Try do decode remaining sensor data.")
                    pass
                else:
                    if decoder:
                        data_dict[field] = decoder(data[key])
                    else:
                        data_dict[field] = data[key]
            return data_dict

        @staticmethod
        def clean_data(data):
            """Harmonize field names and convert into metric units"""

            _ignore_fields = ['passkey', 'firmware', 'frequency', 'model', 'client_ip']

            data_dict = {}
            for key in data:
                if key.lower() not in _ignore_fields:
                    data_dict[key] = data[key]
            return data_dict

    class Sensors(object):
        """Class to manage GW1000/GW1100 sensor ID data."""

        def __init__(self, show_battery=False, debug_sensors=False, plugin_instance=None):
            """Initialise myself"""

            # get instance logger
            self._plugin_instance = plugin_instance

            # set the show_battery property
            self.show_battery = show_battery

            # initialise a dict to hold the parsed sensor data
            self.sensor_data = {}

            # parse the raw sensor ID data and store the results in my parsed sensor data dict
            # self.set_sensor_id_data(sensor_id_data)

            # debug sensors
            self.debug_sensors = debug_sensors

        def get_sensor_data(self, data):
            self.sensor_data = data

        @property
        def connected_sensors(self):
            """Obtain a list of sensor types for connected sensors only. """

            connected_list = []
            for element in self.sensor_data:
                if element.endswith('batt'):
                    connected_list.append(element[:-5])
            return connected_list

        @property
        def battery_description_data(self):
            """Obtain a dict of sensor battery state description data"""

            data = {}
            for element in self.sensor_data:
                if element.endswith('batt'):
                    sensor = element[:-5]
                    data[sensor] = self.battery_desc(sensor, self.sensor_data[element])
            # return our data
            return data

        @staticmethod
        def battery_desc(address, value):
            """Determine the battery state description for a given sensor."""

            if value is not None:
                batt_fn = EcowittClient.sensor_ids[address].get('batt_fn')
                if batt_fn == 'batt_binary':
                    if value == 0:
                        return "OK"
                    elif value == 1:
                        return "low"
                    else:
                        return 'Unknown'
                elif batt_fn == 'batt_int':
                    if value <= 1:
                        return "low"
                    elif value == 6:
                        return "DC"
                    elif value <= 5:
                        return "OK"
                    else:
                        return 'Unknown'
                elif batt_fn == 'batt_volt' or batt_fn == 'batt_volt_tenth':
                    if value <= 1.2:
                        return "low"
                    else:
                        return "OK"
            else:
                return 'Unknown'

        @staticmethod
        def batt_binary(batt):
            """
            Decode a binary battery state.

            Battery state is stored in bit 0 as either 0 or 1. If 1 the battery is low, if 0 the battery is normal. We need to mask off bits 1 to 7 as
            they are not guaranteed to be set in any particular way.
            """

            return batt & 1

        @staticmethod
        def batt_int(batt):
            """
            Decode a integer battery state.

            According to the API documentation battery state is stored as an integer from 0 to 5 with <=1 being considered low. Experience with
            WH43 has shown that battery state 6 also exists when the device is run from DC. This does not appear to be documented in the API
            documentation.
            """

            return batt

        @staticmethod
        def batt_volt(batt):
            """
            Decode a voltage battery state in 2mV increments.

            Battery state is stored as integer values of battery voltage/0.02 with <=1.2V considered low.
            """

            return round(0.02 * batt, 2)

        @staticmethod
        def batt_volt_tenth(batt):
            """
            Decode a voltage battery state in 100mV increments.

            Battery state is stored as integer values of battery voltage/0.1
            with <=1.2V considered low.
            """

            return round(0.1 * batt, 1)

# ============================================================================
#                             Utility functions
# ============================================================================


def natural_sort_keys(source_dict) -> list:
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
    # naturally sort the list of keys where, for example, xxxxx16 appears in the correct order
    keys_list.sort(key=natural_keys)
    # return the sorted list
    return keys_list


def natural_sort_dict(source_dict) -> str:
    """
    Return a string representation of a dict sorted naturally by key.

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

    # assume 'iterable' can be iterated by iterbytes and the individual elements can be formatted with {:02X}
    format_str = "{:02X}" if caps else "{:02x}"
    try:
        return separator.join(format_str.format(c) for c in iterable)
    except ValueError:
        # most likely we are running python3 and iterable is not a bytestring,
        # try again coercing iterable to a bytestring
        return separator.join(format_str.format(c) for c in iterable.encode())
    except (TypeError, AttributeError):
        # TypeError - 'iterable' is not iterable
        # AttributeError - likely because separator is None
        # either way we can't represent as a string of hex bytes
        return "cannot represent '%s' as hexadecimal bytes" % (iterable,)


def byte_to_int(rawbytes, signed=False):
    """
    Convert bytearray to value with respect to sign format

    :parameter rawbytes: Bytes to convert
    :parameter signed: True if result should be a signed int, False for unsigned
    :type signed: bool
    :return: Converted value
    :rtype: int
    """

    return int.from_bytes(rawbytes, byteorder='little', signed=signed)


def int_to_bytes(value, length=1, signed=False):
    """
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
    """

    value = value % (2 ** (length * 8))
    return value.to_bytes(length, byteorder='big', signed=signed)


def obfuscate(plain, obf_char='*'):
    """
    Obfuscate all but the last x characters in a string.

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


def timestamp_to_string(ts, format_str="%Y-%m-%d %H:%M:%S %Z") -> str:
    """
    Return a string formatted from the timestamp

    Example:
    >>> import os
    >>> os.environ['TZ'] = 'America/Los_Angeles'
    >>> time.tzset()
    >>> print(timestamp_to_string(1196705700))
    2007-12-03 10:15:00 PST (1196705700)
    >>> print(timestamp_to_string(None))
    ******* N/A *******     (    N/A   )
    """
    if ts is not None:
        return "%s (%d)" % (time.strftime(format_str, time.localtime(ts)), ts)
    else:
        return "******* N/A *******     (    N/A   )"


def to_sorted_string(rec: dict) -> str:
    """Return a sorted string """

    import locale
    return ", ".join(["%s: %s" % (k, rec.get(k)) for k in sorted(rec, key=locale.strxfrm)])


def c_to_f(temp_c: float, n: int = 0) -> float:
    """Convert degree celsius to fahrenheit"""

    return round((temp_c * 9/5) + 32, n)


def f_to_c(temp_f, n: int = 1) -> float:
    """Convert fahrenheit to degree celsius"""

    return round((temp_f - 32) * 5/9, n)


def ver_str_to_num(s: str) -> Union[None, int]:
    """Extract Verion Number of Firmware out of String"""

    try:
        vpos = s.index("V")+1
        return int(s[vpos:].replace(".", ""))
    except ValueError:
        return


def mph_to_kmh(f: float, n: int = 1) -> float:
    """Convert mph to kmh"""

    return round(float(f) / 0.621371192, n)


def kmh_to_mph(f: float, n: int = 1) -> float:
    """Convert km/h to moh"""

    return round(float(f) * 0.621371192, n)


def mph_to_ms(f: float, n: int = 1) -> float:
    """Convert mph to m/s"""

    return round(float(f)/0.621371*1000/3600, n)


def in_to_hpa(f: float, n: int = 2) -> float:
    """Convert in to hPa"""

    return round(float(f)/0.02953, n)


def hpa_to_in(f: float, n: int = 1) -> float:
    """Convert hPa to inHg"""
    return round(float(f)/33.87, n)


def in_to_mm(f: float, n: int = 2) -> float:
    """Convert in to mm"""

    return round(float(f)*25.4, n)


def f_to_m(f: float, n: int = 1) -> float:
    """Convert feet to m"""

    return round(float(f)/3.281, n)


def obfuscate_passwords(msg: str) -> str:
    """Hide password"""
    return re.sub(r'(PASSWORD|PASSKEY)=[^&]+', r'\1=XXXX', msg)


def is_port_valid(port: int) -> bool:
    """check if port is between 1 and 65535"""
    return True if 1 <= port <= 65535 else False


def is_port_in_use(port: int) -> bool:
    """Check if default port for tcp server is free and can be used"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(('127.0.0.1', port)) == 0


def str_to_datetimeutc(datetimestr: str) -> Union[datetime, None]:
    """Decodes string in datetime format to datetime object"""
    try:
        dt = datetime.strptime(datetimestr, "%Y-%m-%d+%H:%M:%S").replace(tzinfo=timezone.utc)
    except ValueError:
        return None
    else:
        return dt


def datetime_to_string(dt: datetime) -> str:
    """Converts datetime object to string"""
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def utc_to_local(utc_dt: datetime) -> datetime:
    return utc_dt.replace(tzinfo=timezone.utc).astimezone(tz=Shtime.tz())


def solar(f: float, n: int = 0) -> float:
    return round(float(f)*1, n)


MAGNUS_COEFFICIENTS = dict(
    positive=dict(a=7.5, b=17.368, c=238.88),
    negative=dict(a=7.6, b=17.966, c=247.15),
)
