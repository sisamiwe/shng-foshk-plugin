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
########################################


# API: https://osswww.ecowitt.net/uploads/20210716/WN1900%20GW1000,1100%20WH2680,2650%20telenet%20v1.6.0%20.pdf
# API: http://blog.meteodrenthe.nl/wp-content/uploads/2023/02/WN1900-GW10001100-WH26802650-telenet-v1.6.4.pdf


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
from dataclasses import dataclass
# from json.decoder import JSONDecodeError
import urllib.parse as urlparse


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

    PLUGIN_VERSION = '1.1.2'

    def __init__(self, sh):
        """
        Initializes the plugin.
        """

        # call init code of parent class (SmartPlugin)
        super().__init__()

        # get the parameters for the plugin (as defined in metadata plugin.yaml):
        self.gateway_address = self.get_parameter_value('Gateway_IP')
        if self.gateway_address == '127.0.0.1':
            self.gateway_address = None

        self.gateway_port = self.get_parameter_value('Gateway_Port')
        if self.gateway_port == 0 or not is_port_valid(self.gateway_port):
            self.gateway_port = None

        self.gateway_poll_cycle = self.get_parameter_value('Gateway_Poll_Cycle')
        self.fw_update_check_cycle = self.get_parameter_value('FW_Update_Check_Cycle') * 24 * 60 * 60                    # convert from days into seconds
        self.show_battery_warning = self.get_parameter_value('Battery_Warning')
        self.show_sensor_warning = self.get_parameter_value('Sensor_Warning')
        self.use_wh32 = self.get_parameter_value('Use_of_WH32')
        self.ignore_wh40_batt = self.get_parameter_value('Ignore_WH40_Battery')

        interface_config = {'ip_address': self.gateway_address,
                            'port': self.gateway_port,
                            'poll_interval': self.gateway_poll_cycle,
                            'fw_check_interval': self.fw_update_check_cycle,
                            'show_battery_warning': self.show_battery_warning,
                            'show_sensor_warning': self.show_sensor_warning,
                            'use_wh32': self.use_wh32,
                            'ignore_wh40_batt': self.ignore_wh40_batt}

        _ecowitt_data_cycle = self.get_parameter_value('Ecowitt_Data_Cycle')
        self.use_customer_server = bool(_ecowitt_data_cycle)
        if self.use_customer_server:
            self.http_server_ip = Utils.get_local_ipv4_address()
            self.http_server_port = self.select_port_for_tcp_server(8080)
            self.data_cycle = max(_ecowitt_data_cycle, 16)
            self.logger.debug(f"Receiving ECOWITT data has been enabled. Data upload to {self.http_server_ip}:{self.http_server_port} with an interval of {self.data_cycle}s will be set.")

            interface_config.update({'http_server_ip': self.http_server_ip,
                                     'http_server_port': self.http_server_port,
                                     'http_data_cycle': self.data_cycle})

            if not self.http_server_ip or not self.http_server_port:
                self.logger.error(f"Receiving ECOWITT data has been enabled, but not able to define server ip or port with setting {self.http_server_ip}:{self.http_server_port}")
                self._init_complete = False

        # init Class InterfaceConfig
        self.interface_config = InterfaceConfig(**interface_config)

        # define variables and attributes
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

        # get a GatewayApiDriver object
        try:
            self.logger.debug(f"Start interrogating.....")
            self.api_driver = GatewayApiDriver(ip_address=self.gateway_address,
                                               port=self.gateway_port,
                                               poll_interval=self.gateway_poll_cycle,
                                               plugin_instance=self)

            self.logger.debug(f"Interrogating {self.api_driver.collector.device.model} at {self.api_driver.collector.device.ip_address.decode()}:{self.api_driver.collector.device.port}")
            self.gateway_connected = True
        except GatewayIOError as e:
            self.logger.error(f"Unable to connect to device: {e}")
            self._init_complete = False

        # if usage of customer service is enabled, initialize tcp server
        if self.use_customer_server:
            try:
                self.tcp_driver = GatewayTcpDriver(tcp_server_address=self.http_server_ip,
                                                   tcp_server_port=self.http_server_port,
                                                   data_cycle=self.data_cycle,
                                                   gateway_address=self.gateway_address,
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

        # if customer server is used, set parameters accordingly
        if self.use_customer_server:
            self._set_custom_params(custom_server_id='', custom_password='', custom_host=self.http_server_ip, custom_port=self.http_server_port, custom_interval=self.data_cycle, custom_type=False, custom_enabled=True)
            self._set_usr_path()

        # set class property to selected IP
        self.gateway_address = self.api_driver.collector.device.ip_address
        self.gateway_port = self.api_driver.collector.device.port

        # start endless loop for 'get_api_data' in own thread until plugin stops
        self.get_api_data_thread_startup()

        # if usage of customer service is enabled
        if self.use_customer_server:
            # start endless loop for 'get_tcp_data' in own thread until plugin stops
            self.get_tcp_data_thread_startup()

        self.update_gateway_meta_data_items()

    def stop(self):
        """
        Stop method for the plugin
        """

        self.alive = False

        self.logger.debug("Shutdown von Gateway Driver Thread called")
        self.api_driver.closePort()
        self.gateway_connected = False

        self.logger.debug("Shutdown von FoshkPlugin Thread for getting API data called")
        self.get_api_data_thread_shutdown()

        if self.use_customer_server:
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

        if self.has_iattr(item.conf, 'foshk_attribute'):
            foshk_attribute = (self.get_iattr_value(item.conf, 'foshk_attribute')).lower()

            if foshk_attribute in self.META_ATTRIBUTES:
                source = 'meta'

            elif foshk_attribute in self.TCP_ATTRIBUTES:
                source = 'ecowitt'

            elif self.has_iattr(item.conf, 'foshk_datasource'):
                foshk_datasource = (self.get_iattr_value(item.conf, 'foshk_datasource')).lower()
                if foshk_datasource == 'ecowitt' and not self.use_customer_server:
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

            if self.has_iattr(item.conf, 'foshk_attribute'):
                self.logger.debug(f"update_item was called with item {item.property.path} from caller {caller}, source {source} and dest {dest}")
                foshk_attribute = (self.get_iattr_value(item.conf, 'foshk_attribute')).lower()

                if foshk_attribute == 'reset':
                    self.reset()
                elif foshk_attribute == 'reboot':
                    self.reboot()

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
        Start a thread that get data from the Ecowitt Gateway driver.
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
        Shut down the thread that gets data from the Ecowitt Gateway driver.
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

        self.logger.debug(f"Updating item values finished")

    def firmware_update(self):
        """
        Run firmware update
        """

        result = self.api_driver.collector.device.do_firmware_update()
        if result == 'SUCCESS':
            self.logger.debug(f"firmware_update: {result}")
        else:
            self.logger.error(f"firmware_update: {result}")

    def _set_usr_path(self, custom_ecowitt_path: str = "/data/report/", custom_wu_path: str = "/weatherstation/updateweatherstation.php?"):
        """
        Set user path for Ecowitt data to receive

        :param custom_ecowitt_path: path for ecowitt data upload
        :type custom_ecowitt_path: str
        :param custom_wu_path: path for wu data upload
        :type custom_wu_path: str
        """

        result = self.api_driver.collector.device.set_usr_path(custom_ecowitt_path, custom_wu_path)
        if result == 'SUCCESS' or result == 'NO NEED':
            self.logger.debug(f"set_usr_path: {result}")
        else:
            self.logger.error(f"set_usr_path: {result}")

    def _set_custom_params(self, custom_server_id: str, custom_password: str, custom_host: str, custom_port: int, custom_interval: int, custom_type: bool, custom_enabled: bool):
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

        result = self.api_driver.collector.device.set_custom_params(custom_server_id, custom_password, custom_host, custom_port, custom_interval, custom_type, custom_enabled)
        if result == 'SUCCESS' or result == 'NO NEED':
            self.logger.debug(f"set_custom_params: {result}")
        else:
            self.logger.error(f"set_custom_params: {result}")

    def reboot(self):
        """
        Reboot device
        """

        result = self.api_driver.collector.device.reboot()
        if result == 'SUCCESS' or result == 'NO NEED':
            self.logger.debug(f"reboot: {result}")
        else:
            self.logger.error(f"reboot: {result}")

    def reset(self):
        """
        Reset device
        """

        result = self.api_driver.collector.device.reset()
        if result == 'SUCCESS' or result == 'NO NEED':
            self.logger.debug(f"reset: {result}")
        else:
            self.logger.error(f"reset: {result}")

    def update_gateway_meta_data_items(self):
        packet = dict()
        packet['gateway_model'] = self.api_driver.collector.device.model
        packet['frequency'] = self.api_driver.collector.device.system_params.get('frequency')
        packet['firmware_version'] = self.api_driver.collector.device.firmware_version
        self.update_item_values(packet, 'meta')

    @property
    def station_model(self) -> str:
        return self.api_driver.collector.device.model

    @property
    def firmware_version(self) -> str:
        return self.api_driver.collector.device.firmware_version

    @property
    def system_parameters(self) -> dict:
        return self.api_driver.collector.device.system_params

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


class GatewayIOError(Exception):
    """Exception raised when an input/output error with the Ecowitt Gateway is encountered."""


class UnknownApiCommand(Exception):
    """Exception raised when an unknown API command is used."""


# ============================================================================
#                           Gateway Config classes
# ============================================================================

@dataclass
class DebugOptions:
    """Class to simplify use and handling of device debug options."""

    # special debugger for rain
    rain: bool = True

    # special debugger for wind
    wind: bool = True

    # special debugger for loop
    loop: bool = True

    # special debugger for sensors
    sensors: bool = True


@dataclass
class InterfaceConfig:
    """Class to simplify use and handling of gateway interface config options."""
    
    # known device models
    known_models = ('GW1000', 'GW1100', 'GW2000', 'WH2650', 'WH2680', 'WN1900')

    # Gateway IP for api communication
    ip_address: str = None

    # Gateway port for api communication
    port: int = 45000

    # network broadcast address - the address that network broadcasts are sent to
    broadcast_address: str = '255.255.255.255'

    # network broadcast port - the port that network broadcasts are sent to
    broadcast_port: int = 46000

    # default socket timeout in sec
    socket_timeout: int = 2

    # default broadcast timeout in sec
    broadcast_timeout: int = 5

    # default retry/wait time in sec
    retry_wait: int = 10

    # default max tries when polling the API
    max_tries: int = 3

    # When run as a service the default age in seconds after which API data is considered stale and will not be used to augment loop packets
    max_age: int = 60

    # default device poll interval in sec
    poll_interval: int = 20

    # default period between lost contact log entries during an extended period of lost contact when run as a Service  in sec
    lost_contact_log_period: int = 21600

    # default battery state filtering
    show_battery: bool = False

    # default firmware update check interval in sec
    fw_check_interval: int = 86400

    # show availability of firmware update
    show_fw_update_avail: bool = True

    # log unknown fields
    log_unknown_fields: bool = False

    # create a separate field for summarized battery warning
    show_battery_warning: bool = False

    # create a separate field for summarized sensor warning
    show_sensor_warning: bool = False

    # is WH32 in use
    use_wh32: bool = True

    # should WH40 batt be ignored
    ignore_wh40_batt: bool = True

    # ip-address of http server for uploading ecowitt protocol
    http_server_ip: str = None

    # port of http server for uploading ecowitt protocol
    http_server_port: int = None

    # data cycle for uploading ecowitt protocol
    http_data_cycle: int = None


# ============================================================================
#                             Gateway Object
# ============================================================================


class Gateway(object):
    """
    Base class for interacting with an Ecowitt Gateway.

    There are a number of common properties and methods (e.g. IP address, field map, rain calculation etc.) when dealing with an Ecowitt Gateway as a driver.
    This class captures those common features.
    """

    def __init__(self, data_cycle, debug, plugin_instance):
        """
        Initialise a Gateway object.
        """

        # init logger
        self._plugin_instance = plugin_instance
        self.logger = self._plugin_instance.logger
        self.logger.debug("Init Gateway Object")

        # set the language property to the global language
        self.language = self._plugin_instance.language

        # how often (in seconds) we will receive data
        self.data_cycle = data_cycle

        # create deque to hold 10 minutes of wind speed, wind direction and windgust
        self.wind_avg10m = deque(maxlen=(int(10*60/int(self.data_cycle))))

        # get debug settings
        self.debug = debug if debug is not None else DebugOptions()

        # is there a sensor warning
        self.sensor_warning = False

        # is there a battery warning
        self.battery_warning = False

        # all found sensors since beginning of plugin
        self.sensors_all = []

        # sensors, that were missed with count of cycles
        self.sensors_missed = {}

        # initialise last lightning count and last rain properties
        self.last_lightning = None
        self.last_rain = None
        self.piezo_last_rain = None
        self.rain_mapping_confirmed = False
        self.rain_total_field = None
        self.piezo_rain_mapping_confirmed = False
        self.piezo_rain_total_field = None

        # Finally, log any config that is not being pushed any further down. Log specific debug but only if set to True
        debug_list = []
        if self.debug.rain:
            debug_list.append(f"debug_rain is {self.debug.rain}")
        if self.debug.wind:
            debug_list.append(f"debug_wind is {self.debug.wind}")
        if self.debug.loop:
            debug_list.append(f"debug_loop is {self.debug.loop}")
        if self.debug.sensors:
            debug_list.append(f"debug_sensors is {self.debug.sensors}")
        if len(debug_list) > 0:
            self.logger.info(" ".join(debug_list))

    def add_calculated_data(self, data):
        """
        Add calculated data to dict

        :param data: dict of parsed Ecowitt Gateway API data
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
        """Determine the cumulative rain field used to derive field 'rain'.

        Ecowitt gateway devices emit various rain totals but WeeWX needs a per period value for field rain. Try the 'big' (four byte) counters
        starting at the longest period and working our way down. This should only need be done once.

        This is further complicated by the introduction of 'piezo' rain with the WS90. Do a second round of checks on the piezo rain equivalents and
        create piezo equivalent properties.

        data: dic of parsed device API data
        """

        # Do we have a confirmed field to use for calculating rain? If we do we
        # can skip this otherwise we need to look for one.
        if not self.rain_mapping_confirmed:
            # We have no field for calculating rain so look for one, if device field 'raintotals' is present used that as our first choice.
            # Otherwise, work down the list in order of descending period.
            if 'raintotals' in data:
                self.rain_total_field = 'raintotals'
                self.rain_mapping_confirmed = True
            # raintotals is not present so now try rainyear
            elif 'rainyear' in data:
                self.rain_total_field = 'rainyear'
                self.rain_mapping_confirmed = True
            # rainyear is not present so now try rainmonth
            elif 'rainmonth' in data:
                self.rain_total_field = 'rainmonth'
                self.rain_mapping_confirmed = True
            # do nothing, we can try again next packet
            else:
                self.rain_total_field = None
            # if we found a field log what we are using
            if self.rain_mapping_confirmed:
                self.logger.info(f"Using '{self.rain_total_field}' for rain total")
            elif self.debug.rain:
                # if debug_rain is set log that we had nothing
                self.logger.info("No suitable field found for rain")

        # now do the same for piezo rain

        # Do we have a confirmed field to use for calculating piezo rain? If we
        # do we can skip this otherwise we need to look for one.
        if not self.piezo_rain_mapping_confirmed:
            # We have no field for calculating piezo rain so look for one, if device field 'p_rainyear' is present used that as our first
            # choice. Otherwise, work down the list in order of descending period.
            if 'p_rainyear' in data:
                self.piezo_rain_total_field = 'p_rainyear'
                self.piezo_rain_mapping_confirmed = True
            # rainyear is not present so now try rainmonth
            elif 'p_rainmonth' in data:
                self.piezo_rain_total_field = 'p_rainmonth'
                self.piezo_rain_mapping_confirmed = True
            # do nothing, we can try again next packet
            else:
                self.piezo_rain_total_field = None
            # if we found a field log what we are using
            if self.piezo_rain_mapping_confirmed:
                self.logger.info(f"Using '{self.piezo_rain_total_field}' for piezo rain total")
            elif self.debug.rain:
                # if debug_rain is set log that we had nothing
                self.logger.info("No suitable field found for piezo rain")

    def calculate_rain(self, data):
        """
        Calculate total rainfall for a period.

        'rain' is calculated as the change in a user designated cumulative rain field between successive periods. 'rain' is only calculated if the
        field to be used has been selected and the designated field exists.

        :param data: dict of parsed Ecowitt Gateway API data
        :type data: dict
        """

        # have we decided on a field to use and is the field present
        if self.rain_mapping_confirmed and self.rain_total_field in data:
            # yes on both counts, so get the new total
            new_total = data[self.rain_total_field]
            # now calculate field rain as the difference between the new and old totals
            data['rain'] = self.delta_rain(new_total, self.last_rain)
            # if debug_rain is set log some pertinent values
            if self.debug.rain:
                self.logger.info(f"calculate_rain: last_rain={self.last_rain} new_total={new_total} calculated rain={data['rain']}")
            # save the new total as the old total for next time
            self.last_rain = new_total

        # now do the same for piezo rain

        # have we decided on a field to use for piezo rain and is the field  present
        if self.piezo_rain_mapping_confirmed and self.piezo_rain_total_field in data:
            # yes on both counts, so get the new total
            piezo_new_total = data[self.piezo_rain_total_field]
            # now calculate field p_rain as the difference between the new and
            # old totals
            data['p_rain'] = self.delta_rain(piezo_new_total, self.piezo_last_rain, descriptor='piezo rain')
            # if debug_rain is set log some pertinent values
            if self.debug.rain:
                self.logger.info(f"calculate_rain: piezo_last_rain={self.piezo_last_rain} piezo_new_total={piezo_new_total} calculated p_rain={data['p_rain']}")
            # save the new total as the old total for next time
            self.piezo_last_rain = piezo_new_total

    def calculate_lightning_count(self, data):
        """
        Calculate total lightning strike count for a period.

        'lightning_strike_count' is calculated as the change in field 'lightningcount' between successive periods. 'lightning_strike_count'
        is only calculated if 'lightningcount' exists.

        :param data: dict of parsed Ecowitt Gateway API data
        :type data: dict
        """

        # is the lightningcount field present
        if 'lightningcount' in data:
            # yes, so get the new total
            new_total = data['lightningcount']
            # now calculate field lightning_strike_count as the difference between the new and old totals
            data['lightning_strike_count'] = self.delta_lightning(new_total, self.last_lightning)
            # save the new total as the old total for next time
            self.last_lightning = new_total

    def calculate_feels_like(self, temperature_c: float, windspeed_kmh: float) -> float:
        """
        Computes the feels-like temperature

        :param temperature_c: ambient temperature in Celsius
        :param windspeed_kmh: wind speed in km/h
        :return: feels like temperature in Celsius
        """

        # convert to Fahrenheit and mph
        temperature_f = c_to_f(temperature_c, 2)
        windspeed_mph = kmh_to_mph(windspeed_kmh, 2)

        # Try Wind Chill first
        feels_like = self.get_windchill_index_imperial(temperature_f, windspeed_mph)

        # Replace it with the Heat Index, if necessary
        if feels_like == temperature_f and temperature_f >= 80:
            feels_like = self.get_heat_index(temperature_f, windspeed_mph)

        # convert back to Celsius and return
        return f_to_c(feels_like, 1)

    def delta_rain(self, rain: float, last_rain: float, descriptor: str = 'rain') -> Union[None, float]:
        """Calculate rainfall from successive cumulative values.

        Rainfall is calculated as the difference between two cumulative values. If either value is None the value None is returned. If the previous
        value is greater than the latest value a counter wrap around is assumed and the latest value is returned.

        rain:       current cumulative rain value
        last_rain:  last cumulative rain value
        descriptor: string to indicate what rain data we are working with
        """

        # do we have a last rain value
        if last_rain is None:
            # no, log it and return None
            self.logger.info(f"skipping {descriptor} measurement of {rain}: no last rain")
            return None
        # do we have a non-None current rain value
        if rain is None:
            # no, log it and return None
            self.logger.info("skipping {descriptor} measurement: no current rain")
            return None
        # is the last rain value greater than the current rain value
        if rain < last_rain:
            # it is, assume a counter wrap around/reset, log it and return the latest rain value
            self.logger.info(f" {descriptor} counter wraparound detected: new={rain} last={last_rain}")
            return rain
        # otherwise return the difference between the counts
        return rain - last_rain

    def delta_lightning(self, count: int, last_count: int) -> Union[None, int]:
        """
        Calculate lightning strike count from successive cumulative values.

        Lightning strike count is calculated as the difference between two cumulative values. If either value is None the value None is returned.
        If the previous value is greater than the latest value a counter wrap around is assumed and the latest value is returned.

        :param count:      current cumulative lightning count
        :param last_count: last cumulative lightning count
        """

        # do we have a last count
        if last_count is None:
            # no, log it and return None
            self.logger.info(f"Skipping lightning count of {count}: no last count")
            return None
        # do we have a non-None current count
        if count is None:
            # no, log it and return None
            self.logger.info("Skipping lightning count: no current count")
            return None
        # is the last count greater than the current count
        if count < last_count:
            # it is, assume a counter wrap around/reset, log it and return the latest count
            self.logger.info(f"Lightning counter wraparound detected: new={count} last={last_count}")
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
    
        :param t_air_c: temperature in Celsius
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

        :param air_temp_f: current ambient temperature in Fahrenheit
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

        :param temperature_f: current ambient temperature in Fahrenheit
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

        _weather_now_de = ["stürmisch, Regen", "regnerisch", "wechselhaft", "sonnig", "trocken, Gewitter"]
        _weather_now_en = ["stormy, rainy", "rainy", "unstable", "sunny", "dry, thunderstorm"]
        _weather_now = _weather_now_de if lang == "de" else _weather_now_en

        if hpa <= 980:
            entry = 0                # stürmisch, Regen
        elif hpa <= 1000:
            entry = 1                # regnerisch
        elif hpa <= 1020:
            entry = 2                # wechselhaft
        elif hpa <= 1040:
            entry = 3                # sonnig
        else:
            entry = 4                # trocken, Gewitter

        return _weather_now[entry]

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
            _wind_dir = _wind_dir_de
        elif lang == 'en':
            _wind_dir = _wind_dir_en
        elif lang == 'xx':
            _wind_dir = _wind_dir_xx
        else:
            _wind_dir = _wind_dir_zz

        try:
            val = int((float(wdir)/22.5)+.5)
            s = _wind_dir[(val % 16)]
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
        elif diff <= -5:
            wproglvl = 1               # Regen/Unwetter
        elif diff <= -3:
            wproglvl = 2               # regnerisch
        elif diff <= -0.5:
            wproglvl = 3               # baldiger Regen
        elif diff <= 0.5:
            wproglvl = 4               # gleichbleibend
        elif diff <= 3:
            wproglvl = 5               # lange schön
        elif diff <= 5:
            wproglvl = 6               # schön & labil
        else:
            wproglvl = 7               # Sturmwarnung

        return _weather_forecast[wproglvl]

    @staticmethod
    def cloud_ceiling(temp: float, dewpt: float) -> float:
        """
        Computes cloud ceiling (Wolkenuntergrenze/Konvektionskondensationsniveau)
        Faustformel für die Berechnung der Höhe der Wolkenuntergrenze von Quellwolken: Höhe in Meter = 122 x Spread (Taupunktdifferenz)

        :param temp: outside temperatur in celsius
        :param dewpt: outside dew point in celsius
        :return: cloud ceiling in meter
        """

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
        https://www.smarthomeng.de/vom-winde-verweht
        """

        beaufort = [(0.3, 0),
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
                   (999, 12)]

        try:
            return int(min(filter(lambda x: x[0] >= speed_in_mps, beaufort))[1])
        except ValueError:
            return None

    @staticmethod
    def get_beaufort_description(speed_in_bft: int, lang: str = 'de') -> Union[None, str]:
        """
        get the beaufort description from beaufort number
        """

        # source for german descriptions https://www.smarthomeng.de/vom-winde-verweht
        _beaufort_descriptions_de = ["Windstille", "leiser Zug", "leichte Brise", "schwacher Wind", "mäßiger Wind", "frischer Wind", "starker Wind", "steifer Wind", "stürmischer Wind", "Sturm", "schwerer Sturm", "orkanartiger Sturm", "Orkan"]
        # source for english descriptions https://simple.wikipedia.org/wiki/Beaufort_scale
        _beaufort_descriptions_en = ["Calm", "Light air", "Light breeze", "Gentle breeze", "Moderate breeze", "Fresh breeze", "Strong breeze", "High wind", "Fresh Gale", "Strong Gale", "Storm", "Violent storm", "Hurricane-force"]
        _beaufort_descriptions = _beaufort_descriptions_de if lang == 'de' else _beaufort_descriptions_en

        if speed_in_bft is None or not isinstance(speed_in_bft, int) or not (0 <= speed_in_bft <= 12):
            return None
        return _beaufort_descriptions[speed_in_bft]

    def check_battery(self, data, battery_data):
        """Check if batteries states are critical, create log entry and add a separate field for battery warning."""

        # init string to collect message
        batterycheck = ''
        # iterate over data to look for critical battery
        for key in battery_data:
            if battery_data[key] != 'OK':
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

    def check_sensors(self, data: dict, connected_sensors, missing_count: int = 2):
        """
        Check if all know sensors are still connected, create log entry and add a separate field for sensor warning.
        """

        # log all found sensors during runtime
        self.sensors_all = list(set(self.sensors_all + connected_sensors))
        # check if all sensors are still connected, create log entry data field
        if set(connected_sensors) == set(self.sensors_all):
            # self.logger.debug(f"check_sensors: All sensors are still connected!")
            self.sensor_warning = False
            data['sensor_warning'] = 0
        else:
            missing_sensors = list(set(self.sensors_all).difference(set(connected_sensors)))
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

# ============================================================================
#                            Gateway API classes
# ============================================================================


class GatewayApiDriver(Gateway):
    """Ecowitt Gateway driver class.

    A driver to emit loop packets based on observational data obtained from the Ecowitt Gateway API. The GatewayApiDriver should be used when there is no other data source.

    Data is obtained from the Ecowitt Gateway API. The data is parsed and emitted as a loop packet.

    Class GatewayApiClient collects and parses data from the Ecowitt Gateway API. The GatewayApiClient runs in a separate thread so as to not block the main
    processing loop. The GatewayApiClient is turn uses child classes Station and Parser to interact directly with the Ecowitt Gateway API and
    parse the API responses respectively."""

    def __init__(self,
                 broadcast_address=None,
                 broadcast_port=None,
                 ip_address=None,
                 port=None,
                 poll_interval: int = None,
                 plugin_instance=None):

        # get instance
        self._plugin_instance = plugin_instance
        self.logger = self._plugin_instance.logger

        # get interface config
        self.interface_config = self._plugin_instance.interface_config

        # set driver to alive
        self.driver_alive = False

        # get debug options
        self.debug = DebugOptions()

        # now initialize my superclasses
        super().__init__(poll_interval, self.debug, plugin_instance)

        # log the relevant settings/parameters we are using
        self.logger.debug("Starting GatewayApiDriver")

        # create an GatewayApiClient object to interact with the Ecowitt Gateway API
        self.collector = GatewayCollector(ip_address=ip_address,
                                          port=port,
                                          broadcast_address=broadcast_address,
                                          broadcast_port=broadcast_port,
                                          poll_interval=poll_interval,
                                          debug=self.debug,
                                          plugin_instance=plugin_instance)

        # log setup
        if ip_address is None and port is None:
            self.logger.info(f'{self.collector.device.model} IP address and port not specified, attempting to discover {self.collector.device.model}...')
        elif ip_address is None:
            self.logger.info(f'{self.collector.device.model} IP address not specified, attempting to discover {self.collector.device.model}...')
        elif port is None:
            self.logger.info(f'{self.collector.device.model} port not specified, attempting to discover {self.collector.device.model}...')
        self.logger.info(f'{self.collector.device.model} address is {self.collector.device.ip_address.decode()}:{self.collector.device.port}')
        self.logger.info(f'poll interval is {poll_interval} seconds')
        self.logger.debug(f'max tries is {self.interface_config.max_tries}, retry wait time is {self.interface_config.retry_wait} seconds')
        self.logger.debug(f'broadcast address is {self.interface_config.broadcast_address}:{self.interface_config.broadcast_port}, broadcast timeout is {self.interface_config.broadcast_timeout} seconds')
        self.logger.debug(f'socket timeout is {self.interface_config.socket_timeout} seconds')

        # start the GatewayApiClient in its own thread
        self.collector.startup()
        self.driver_alive = True

    def genLoopPackets(self):
        """
        Generator function that returns loop packets.

        Run a continuous loop checking the GatewayApiClient queue for data. When data arrives map the raw data to a loop packet and yield the packet.
        """

        while self.driver_alive:
            try:
                # get any data from the collector queue
                queue_data = self.collector.data_queue.get(True, 10)
                # self.logger.debug(f"received queue data: {queue_data}")
            except queue.Empty:
                # self.logger.debug("API. genLoopPackets: there was nothing in the queue so continue")
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
                    packet = {}

                    # put timestamp and datetime to paket if not present
                    if 'timestamp' not in queue_data:
                        packet['timestamp'] = int(time.time())
                    if 'datetime' not in queue_data:
                        packet['datetime'] = datetime.now().replace(microsecond=0)

                    if self.debug.loop:
                        self.logger.debug(f"API. Received data from {self.collector.device.model}: {natural_sort_dict(queue_data)}")

                    # if not already determined, determine which cumulative rain field will be used to determine the per period rain field
                    if not self.rain_mapping_confirmed:
                        self.get_cumulative_rain_field(queue_data)

                    # get the rainfall for this period from total
                    self.calculate_rain(queue_data)

                    # get the lightning strike count for this period from total
                    self.calculate_lightning_count(queue_data)

                    # add calculated data to queue_data
                    self.add_calculated_data(queue_data)

                    if self.interface_config.show_sensor_warning:
                        # add sensor warning data field and log entry
                        self.check_sensors(queue_data, self.collector.device.api.sensors.connected_addresses)

                    if self.interface_config.show_battery_warning:
                        # add battery warning data field and log entry
                        self.check_battery(queue_data, self.collector.device.api.sensors.battery_description_data)

                    # add the queue_data to the empty packet
                    packet.update(queue_data)

                    # log the packet if necessary
                    if self.debug.loop:
                        self.logger.info(f"API. genLoopPackets: packet={natural_sort_dict(packet)}")
                    yield packet

                # if it's a tuple then it's a tuple with an exception and exception text
                elif isinstance(queue_data, BaseException):
                    # We have an exception. The collector did not deem it serious enough to want to shut down or it would have sent None instead. If it is anything else we log it and then raise it.

                    # first extract our exception
                    e = queue_data
                    # and process it if we have something
                    if e:
                        # is it a GatewayError
                        self.logger.error(f"Caught unexpected exception {e.__class__.__name__}: {e}")
                        # then raise it
                        raise e

                # if it's None then its a signal, the Collector needs to shut down
                elif queue_data is None:
                    # if debug_loop log what we received
                    if self.debug.loop:
                        self.logger.info("Received 'None'")
                    # we received the signal to shut down, so call closePort()
                    self.closePort()
                    # and raise an exception to cause the engine to shut down
                    raise GatewayIOError("GatewayApiClient needs to shutdown")

    def closePort(self):
        """
        Close down the driver port.
        """

        # in this case there is no port to close, just shutdown the collector
        self.driver_alive = False
        self.collector.shutdown()


class GatewayCollector:
    """Class to collect data from an Ecowitt LAN/Wi-Fi Gateway device.

    A GatewayCollector object is responsible for obtaining data from an Ecowitt LAN/Wi-Fi Gateway device and passing relevant data to its parent
    driver/service. A GatewayCollector object uses subordinate classes to obtain data from the gateway device via the Ecowitt LAN/Wi-Fi Gateway
    device API and direct HTTP requests suitable for passing to its parent driver/service. A GatewayCollector can also be used to obtain device data
    when the driver is operated in direct mode.

    A GatewayCollector object uses a GatewayDevice object to handle all interaction with the device.
    """

    data_queue = queue.Queue()

    def __init__(self,
                 ip_address=None,
                 port=None,
                 broadcast_address=None,
                 broadcast_port=None,
                 poll_interval=None,
                 debug=None,
                 plugin_instance=None):
        """Initialise our class."""

        # get plugin instance
        self._plugin_instance = plugin_instance
        self.logger = self._plugin_instance.logger

        # get interface config
        self.interface_config = self._plugin_instance.interface_config
        self.poll_interval = poll_interval if poll_interval is not None else self.interface_config.poll_interval
        self.fw_update_check_interval = self.interface_config.fw_check_interval
        self.show_fw_update_avail = self.interface_config.show_fw_update_avail
        ignore_wh40_batt = self.interface_config.ignore_wh40_batt

        # get a GatewayDevice to handle interaction with the gateway device
        self.device = GatewayDevice(ip_address=ip_address,
                                    port=port,
                                    broadcast_address=broadcast_address,
                                    broadcast_port=broadcast_port,
                                    debug=debug,
                                    plugin_instance=plugin_instance)

        # start off logging failures
        self.log_failures = True

        # do we have a legacy WH40 and how are we handling its battery state data
        if b'\x03' in self.device.api.sensors.connected_addresses and self.device.api.sensors.legacy_wh40:
            # we have a connected legacy WH40
            if ignore_wh40_batt:
                _msg = 'Legacy WH40 detected, WH40 battery state data will be ignored'
            else:
                _msg = 'Legacy WH40 detected, WH40 battery state data will be reported'
            self.logger.info(_msg)

        # create a thread property
        self.thread = None

        # we start off not collecting data, it will be turned on later when we are threaded
        self.collect_data = False

    def collect(self):
        """Collect and queue sensor data.

        Loop forever waking periodically to see if it is time to quit or collect more data. A dictionary of data is placed in the queue on each
        successful poll of the device. If an exception is raised when interacting with the device the exception is placed in the queue as a
        signal to our parent that there is a problem.
        """

        # initialise ts of last time API was polled
        last_poll = 0
        # initialise ts of last firmware check
        last_fw_check = 0

        # collect data continuously while we are told to collect data
        while self.collect_data:
            # store the current time
            now = time.time()
            # is it time to poll?
            if now - last_poll > self.poll_interval:
                # it is time to poll, wrap in a try..except in case we get a GatewayIOError exception
                try:
                    queue_data = self.get_current_data()
                except GatewayIOError as e:
                    # a GatewayIOError occurred, most likely because the Station object could not contact the device first up log the event, but only if we are logging failures
                    if self.log_failures:
                        self.logger.error(f'Unable to obtain live sensor data. Error {e!r} occurred')
                    # assign the GatewayIOError exception, so it will be sent in the queue to our controlling object
                    queue_data = e
                else:
                    # do a firmware update check if required
                    if now - last_fw_check > self.fw_update_check_interval and self.show_fw_update_avail:
                        update_available, latest_firmware, update_text = self.device.check_firmware_update()
                        if update_available:
                            self.logger.warning(f"A newer firmware for {self.device.model} is available. Installed version is: {self.device.firmware_version}, new version is: {latest_firmware}.")
                            self.logger.info(f"    update at http://{self.device.ip_address.decode()} or via the WSView Plus app")

                        queue_data.update({'firmware_update_available': update_available, 'firmware_update_text': update_text})
                        last_fw_check = now

                # put the queue data in the queue
                self.data_queue.put(queue_data)
                # debug log when we will next poll the API
                self.logger.debug(f'Next update in {self.poll_interval} seconds')
                # reset the last poll ts
                last_poll = now

            # sleep for a second and then see if it's time to poll again
            time.sleep(1)

    def get_current_data(self):
        """Get all current sensor data.

        Return current sensor data, battery state data and signal state data for each sensor. The current sensor data consists of sensor data
        available through multiple API api_commands. Each API command response is parsed and the results accumulated in a dictionary. Battery and signal
        state for each sensor is added to this dictionary. The dictionary is timestamped and the timestamped accumulated data is returned. If the
        API does not return any data a suitable exception will have been raised.
        """

        # Now obtain the bulk of the current sensor data via the API. If the data cannot be obtained we will see a GWIOError exception which we
        # just let bubble up. Otherwise, we are returned the parsed live data.
        parsed_data = self.device.livedata
        self.logger.debug(f"xxxxxx livedata={parsed_data}")
        # add the datetime to the data dict in case our data does not come with one
        if 'datetime' not in parsed_data:
            parsed_data['datetime'] = datetime.now().replace(microsecond=0)
        # add the timestamp to the data dict in case our data does not come with one
        if 'timestamp' not in parsed_data:
            parsed_data['timestamp'] = int(time.time())
        # Now get the parsed rain data via the API. If the data cannot be obtained we may see an GWIOError exception or an UnknownApiCommand
        # exception. If we get the UnknownApiCommand exception it is likely due to an old device that cannot handle CMD_READ_RAIN in which case our
        # only available rain data will already be in our livedata response. So just set the raindata response to None. If we get a GWIOError then
        # let it bubble up.
        try:
            parsed_rain_data = self.device.rain
        except UnknownApiCommand:
            parsed_rain_data = None
        except GatewayIOError:
            raise
        # now update our parsed data with the parsed rain data if we have any
        if parsed_rain_data is not None:
            self.logger.debug(f"xxxxxx parsed_rain_data={parsed_rain_data}")
            parsed_data.update(parsed_rain_data)
        # log the parsed data
        self.logger.debug(f"Parsed data: {parsed_data}")
        # The parsed data does not currently contain any sensor battery state or signal level data so obtain the parsed sensor battery state
        # and signal level data from our GatewayDevice.
        try:
            parsed_sensor_state_data = self.device.sensor_state
        except GatewayIOError:
            raise
        # now update our parsed data with the parsed sensor state data if we have any
        if parsed_sensor_state_data is not None:
            self.logger.debug(f"xxxxxx parsed_sensor_state_data={parsed_sensor_state_data}")
            parsed_data.update(parsed_sensor_state_data)
        # log the processed parsed data but only if debug>=3
        self.logger.debug(f"Processed parsed data: {parsed_data}")
        return parsed_data

    # @property
    # def calibration(self):
    #     """Obtain device calibration data."""
    #
    #     # obtain the calibration data via the API
    #     parsed_cal_coeff = self.device.api.get_calibration_coefficient()
    #     # obtain the offset calibration data via the API
    #     parsed_offset = self.device.api.get_offset_calibration()
    #     # update our parsed gain data with the parsed offset calibration data
    #     parsed_cal_coeff.update(parsed_offset)
    #     # return the parsed data
    #     return parsed_cal_coeff
    #
    # @property
    # def sensors(self):
    #     """Get the current Sensors object.
    #
    #     A Sensors object holds the address, id, battery state and signal level
    #     data sensors known to the device. The sensor id value can be used to
    #     discriminate between connected sensors, connecting sensors and disabled
    #     sensor addresses.
    #
    #     Before using the GatewayCollector's Sensors object it should be updated
    #     with recent sensor ID data via the API
    #     """
    #
    #     # obtain current sensor id data via the API, we may get a GWIOError
    #     # exception, if we do let it bubble up
    #     # TODO. This should return a value
    #     response = self.device.api.get_sensor_id()
    #     # if we made it here our response was validated by checksum
    #     # re-initialise our sensors object with the sensor ID data we just
    #     # obtained
    #     self.device.api.sensors.set_sensor_id_data(response)
    #     # return our Sensors object
    #     return self.device.api.sensors
    #
    def startup(self):
        """Start a thread that collects data from the API."""

        try:
            self.thread = GatewayCollector.CollectorThread(self)
            self.collect_data = True
            self.thread.setDaemon(True)
            self.thread.setName('GatewayCollectorThread')
            self.thread.start()
        except threading.ThreadError:
            self.logger.error("Unable to launch GatewayCollector thread")
            self.thread = None

    def shutdown(self):
        """Shut down the thread that collects data from the API.

        Tell the thread to stop, then wait for it to finish.
        """

        # we only need do something if a thread exists
        if self.thread:
            # tell the thread to stop collecting data
            self.collect_data = False
            # terminate the thread
            self.thread.join(10.0)
            # log the outcome
            if self.thread.is_alive():
                self.logger.error("Unable to shut down GatewayCollector thread")
            else:
                self.logger.info("GatewayCollector thread has been terminated")
        self.thread = None

    class CollectorThread(threading.Thread):
        """Class using a thread to collect data via the Ecowitt LAN/Wi-Fi Gateway API."""

        def __init__(self, client):
            # initialise our parent
            threading.Thread.__init__(self)
            # keep reference to the client we are supporting
            self.client = client
            self.name = 'gateway-collector'

        def run(self):
            # rather than letting the thread silently fail if an exception occurs within the thread, wrap in a try..except 
            # so the exception can be caught and available exception information displayed
            try:
                # kick the collection off
                self.client.collect()
            except:
                pass


class ApiParser(object):
    """Class to parse and decode device API response payload data.

    The main function of class Parser is to parse and decode the payloads of the device response to the following API calls:
    - CMD_GW1000_LIVEDATA
    - CMD_READ_RAIN

    By virtue of its ability to decode fields in the above API responses the decode methods of class Parser are also used individually
    elsewhere in the driver to decode simple responses received from the device, eg when reading device configuration settings.
    """

    # Dictionary of 'address' based data. Dictionary is keyed by device data field 'address' containing various parameters for each
    # 'address'. Dictionary tuple format is:
    #   (decode fn, size, field name)
    # where:
    #   decode fn:  the decode function name to be used for the field
    #   size:       the size of field data in bytes
    #   field name: the name of the device field to be used for the decoded data

    live_data_struct = {
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
        b'\x0F': ('decode_gain_100', 2, 'raingain'),
        b'\x10': ('decode_rain', 2, 'rainday'),
        b'\x11': ('decode_rain', 2, 'rainweek'),
        b'\x12': ('decode_big_rain', 4, 'rainmonth'),
        b'\x13': ('decode_big_rain', 4, 'rainyear'),
        b'\x14': ('decode_big_rain', 4, 'raintotals'),
        b'\x15': ('decode_light', 4, 'light'),
        b'\x16': ('decode_uv', 2, 'uv'),
        b'\x17': ('decode_uvi', 1, 'uvi'),
        b'\x18': ('decode_datetime_as_dt', 6, 'datetime'),
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
        # WN34 battery data is not obtained from live data rather it is obtained from sensor ID data
        b'\x63': ('decode_wn34', 3, 'temp9'),
        b'\x64': ('decode_wn34', 3, 'temp10'),
        b'\x65': ('decode_wn34', 3, 'temp11'),
        b'\x66': ('decode_wn34', 3, 'temp12'),
        b'\x67': ('decode_wn34', 3, 'temp13'),
        b'\x68': ('decode_wn34', 3, 'temp14'),
        b'\x69': ('decode_wn34', 3, 'temp15'),
        b'\x6A': ('decode_wn34', 3, 'temp16'),
        # WH45 battery data is not obtained from live data rather it is obtained from sensor ID data
        b'\x70': ('decode_wh45', 16, ('temp17', 'humid17', 'pm10', 'pm10_24h_avg', 'pm255', 'pm255_24h_avg', 'co2', 'co2_24h_avg')),
        # b'\x71': (None, None, None),   # placeholder for unknown field 0x71
        b'\x72': ('decode_wet', 1, 'leafwet1'),
        b'\x73': ('decode_wet', 1, 'leafwet2'),
        b'\x74': ('decode_wet', 1, 'leafwet3'),
        b'\x75': ('decode_wet', 1, 'leafwet4'),
        b'\x76': ('decode_wet', 1, 'leafwet5'),
        b'\x77': ('decode_wet', 1, 'leafwet6'),
        b'\x78': ('decode_wet', 1, 'leafwet7'),
        b'\x79': ('decode_wet', 1, 'leafwet8')
    }
    rain_data_struct = {
        b'\x0D': ('decode_rain', 2, 'rainevent'),
        b'\x0E': ('decode_rainrate', 2, 'rainrate'),
        b'\x0F': ('decode_gain_100', 2, 'raingain'),
        b'\x10': ('decode_big_rain', 4, 'rainday'),
        b'\x11': ('decode_big_rain', 4, 'rainweek'),
        b'\x12': ('decode_big_rain', 4, 'rainmonth'),
        b'\x13': ('decode_big_rain', 4, 'rainyear'),
        b'\x7A': ('decode_int', 1, 'rain_priority'),
        b'\x7B': ('decode_int', 1, 'rad_comp'),
        b'\x80': ('decode_rainrate', 2, 'p_rainrate'),
        b'\x81': ('decode_rain', 2, 'p_rainevent'),
        b'\x82': ('decode_reserved', 2, 'p_rainhour'),
        b'\x83': ('decode_big_rain', 4, 'p_rainday'),
        b'\x84': ('decode_big_rain', 4, 'p_rainweek'),
        b'\x85': ('decode_big_rain', 4, 'p_rainmonth'),
        b'\x86': ('decode_big_rain', 4, 'p_rainyear'),
        # field 0x87 and 0x88 hold device parameter data that is not included in the loop packets, hence the device field is not used (None).
        b'\x87': ('decode_rain_gain', 20, None),
        b'\x88': ('decode_rain_reset', 3, None)
    }
    # tuple of field codes for device rain related fields in the live data
    # so we can isolate these fields
    rain_field_codes = (b'\x0D', b'\x0E', b'\x0F', b'\x10',
                        b'\x11', b'\x12', b'\x13', b'\x14',
                        b'\x80', b'\x81', b'\x83', b'\x84',
                        b'\x85', b'\x86')
    # tuple of field codes for wind related fields in the device live data
    # so we can isolate these fields
    wind_field_codes = (b'\x0A', b'\x0B', b'\x0C', b'\x19')

    def __init__(self, log_unknown_fields=True, plugin_instance=None):

        # get instance
        self._plugin_instance = plugin_instance
        self.logger = self._plugin_instance.logger

        # do we log unknown fields at info or leave at debug
        self.log_unknown_fields = log_unknown_fields

    def parse_addressed_data(self, payload, structure):
        """Parse an address structure API response payload.

        Parses the data payload of an API response that uses an addressed data structure, ie each data element is in the format

        <address byte> <data byte(s)>

        Data elements may be in any order and the data portion of each data element may consist of one or mor bytes.

        payload:   API response payload to be parsed, bytestring
        structure: dict keyed by data element address and containing the decode function, field size and the field name to be
                   used as the key against which the decoded data is to be stored in the result dict

        Returns a dict of decoded data keyed by destination field name
        """

        # initialise a dict to hold our parsed data
        data = dict()
        # do we have any payload data to operate on
        if len(payload) > 0:
            # we have payload data
            # set a counter to keep track of where we are in the payload
            index = 0
            # work through the payload until we reach the end
            while index < len(payload) - 1:
                # obtain the decode function, field size and field name for the current field, wrap in a try..except in case we
                # encounter a field address we do not know about
                try:
                    decode_fn_str, field_size, field = structure[payload[index:index + 1]]
                except KeyError:
                    # We struck a field 'address' we do not know how to process. We can't skip to the next field so all we
                    # can really do is accept the data we have so far, log the issue and ignore the remaining data.
                    # are we logging as info or debug, get an appropriate log function
                    if self.log_unknown_fields:
                        log_fn = self.logger.info
                    else:
                        log_fn = self.logger.debug
                    # now call it
                    log_fn(f"Unknown field address '{bytes_to_hex(payload[index:index + 1])}' detected. Remaining data '{bytes_to_hex(payload[index + 1:])}' ignored.")
                    # and break, there is nothing more we can with this data
                    break
                else:
                    _field_data = getattr(self, decode_fn_str)(payload[index + 1:index + 1 + field_size], field)
                    # do we have any decoded data?
                    if _field_data is not None:
                        # we have decoded data so add the decoded data to our data dict
                        data.update(_field_data)
                    else:
                        # we received None from the decode function, this usually indicates a field marked as 'reserved' in
                        # the API documentation
                        pass
                    # we are finished with this field, move onto the next
                    index += field_size + 1
        return data

    def parse_livedata(self, response):
        """Parse data from a CMD_GW1000_LIVEDATA API response.

        Parse the raw sensor data obtained from the CMD_GW1000_LIVEDATA API command and create a dict of sensor observations/status data.
        Returns a dict of observations/status data.

        Response consists of a variable number of bytes determined by the number of connected sensors. Decode as follows:
            Byte(s)     Data            Format          Comments
            1-2         header          -               fixed header 0xFFFF
            3           command code    byte            0x27
            4-5         size            unsigned short
            ....
            6-2nd last byte
                    data structure follows the structure of
                    Parser.live_data_struct in the format:
                        address (byte)
                        data    length: as per second element of tuple
                                decode: Parser method as per first element of
                                        tuple
            ....
            last byte   checksum        byte            LSB of the sum of the command, size and data bytes
        """

        # obtain the payload size, it's a big endian short (two byte) integer
        payload_size = struct.unpack(">H", response[3:5])[0]
        # obtain the payload
        payload = response[5:5 + payload_size - 4]
        # this is addressed data, so we can call parse_addressed_data() and
        # return the result
        return self.parse_addressed_data(payload, self.live_data_struct)

    def parse_read_rain(self, response):
        """Parse data from a CMD_READ_RAIN API response.

        Parse the raw sensor data obtained from the CMD_READ_RAIN API command and create a dict of sensor observations/status data.
        Returns a dict of observations/status data.

        Response consists of a variable number of bytes determined by the connected sensors. Decode as follows:
            Byte(s)     Data            Format          Comments
            1-2         header          -               fixed header 0xFFFF
            3           command code    byte            0x57
            4-5         size            unsigned short
            ....
            6-2nd last byte
                    data structure follows the structure of
                    Parser.rain_data_struct in the format:
                        address (byte)
                        data    length: as per second element of tuple
                                decode: Parser method as per first element of tuple
            ....
            last byte   checksum        byte            LSB of the sum of the command, size and data bytes
        """

        # obtain the payload size, it's a big endian short (two byte) integer
        payload_size = struct.unpack(">H", response[3:5])[0]
        # obtain the payload
        payload = response[5:5 + payload_size - 4]
        # this is addressed data, so we can call parse_addressed_data() and
        # return the result
        return self.parse_addressed_data(payload, self.rain_data_struct)

    def parse_read_raindata(self, response):
        """Parse data from a CMD_READ_RAINDATA API response.

        Response consists of 25 bytes as follows:
            Byte(s) Data            Format          Comments
            1-2     header          -               fixed header 0xFFFF
            3       command code    byte            0x2C
            4       size            byte
            5-8     rainrate        unsigned long   0 to 60000 in tenths mm/hr 0 to 6000.0
            9-12    rainday         unsigned long   0 to 99999 in tenths mm 0 to 9999.9
            13-16   rainweek        unsigned long   0 to 99999 in tenths mm 0 to 9999.9
            17-20   rainmonth       unsigned long   0 to 99999 in tenths mm 0 to 9999.9
            21-24   rainyear        unsigned long   0 to 99999 in tenths mm 0 to 9999.9
            25      checksum        byte            LSB of the sum of the command, size and data bytes
        """

        # determine the size of the rain data
        size = response[3]
        # extract the actual data
        data = response[4:4 + size - 3]
        # initialise a dict to hold our parsed data
        data_dict = dict()
        data_dict['rainrate'] = self.decode_big_rain(data[0:4])
        data_dict['rainday'] = self.decode_big_rain(data[4:8])
        data_dict['rainweek'] = self.decode_big_rain(data[8:12])
        data_dict['rainmonth'] = self.decode_big_rain(data[12:16])
        data_dict['rainyear'] = self.decode_big_rain(data[16:20])
        return data_dict

    @staticmethod
    def parse_get_mulch_offset(response):
        """Parse data from a CMD_GET_MulCH_OFFSET API response.

        Response consists of 29 bytes as follows:
            Byte(s) Data            Format          Comments
            1-2     header          -               fixed header 0xFFFF
            3       command code    byte            0x2C
            4       size            byte
            5       channel 1       byte            fixed 00
            6       hum offset      signed byte     -10 to +10
            7       temp offset     signed byte     -100 to +100 in tenths C (-10.0 to +10.0)
            8       channel 2       byte            fixed 01
            9       hum offset      signed byte     -10 to +10
            10      temp offset     signed byte     -100 to +100 in tenths C (-10.0 to +10.0)
            ....
            26      channel 8       byte            fixed 07
            27      hum offset      signed byte     -10 to +10
            28      temp offset     signed byte     -100 to +100 in tenths C (-10.0 to +10.0)
            29      checksum        byte            LSB of the sum of the command, size and data bytes
        """

        # determine the size of the mulch offset data
        size = response[3]
        # extract the actual data
        data = response[4:4 + size - 3]
        # initialise a counter
        index = 0
        # initialise a dict to hold our parsed data
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

    @staticmethod
    def parse_get_mulch_t_offset(response):
        """Parse data from a CMD_GET_MulCH_T_OFFSET API response.

        Response consists of a variable number of bytes determined by the connected sensors. Decode as follows:
            Byte(s)     Data            Format          Comments
            1-2         header          -               fixed header 0xFFFF
            3           command code    byte            0x59
            4-5         size            unsigned big
                                        endian short
            ....
            6-2nd last byte
                three bytes per connected WN34 sensor:
                        address         byte            sensor address, 0x63 to 0x6A incl
                        temp offset     signed big      -100 to +100 in tenths C (-10.0 to +10.0)
                                        endian short
            ....
            last byte   checksum        byte            LSB of the sum of the command, size and data bytes
        """

        # obtain the payload size, it's a big endian short (two byte) integer
        size = struct.unpack(">H", response[3:5])[0]
        # extract the actual data
        data = response[5:5 + size - 4]
        # initialise a counter
        index = 0
        # initialise a dict to hold our parsed data
        offset_dict = {}
        # iterate over the data
        while index < len(data):
            try:
                channel = byte_to_int(data[index])
            except TypeError:
                channel = data[index]
            try:
                offset_dict[channel] = struct.unpack(">h", data[index + 1:index + 3])[0] / 10.0
            except TypeError:
                offset_dict[channel] = struct.unpack(">h", int_to_bytes(data[index + 1:index + 3]))[0] / 10.0

            index += 3
        return offset_dict

    @staticmethod
    def parse_get_pm25_offset(response):
        """Parse data from a CMD_GET_PM25_OFFSET API response.

        Response consists of 17 bytes as follows:
            Byte(s) Data            Format          Comments
            1-2     header          -               fixed header 0xFFFF
            3       command code    byte            0x2E
            4       size            byte
            5       channel 1       byte            fixed 00
            6-7     pm25 offset     signed short    -200 to +200 in tenths µg/m³ (-20.0 to +20.0)
            ....
            14      channel 1       byte            fixed 00
            15-16   pm25 offset     signed short    -200 to +200 in tenths µg/m³ (-20.0 to +20.0)
            17      checksum        byte            LSB of the sum of the command, size and data bytes
        """

        # determine the size of the PM2.5 offset data
        size = response[3]
        # extract the actual data
        data = response[4:4 + size - 3]
        # initialise a counter
        index = 0
        # initialise a dict to hold our parsed data
        offset_dict = {}
        # iterate over the data
        while index < len(data):
            try:
                channel = byte_to_int(data[index])
            except TypeError:
                channel = data[index]
            offset_dict[channel] = struct.unpack(">h", data[index + 1:index + 3])[0] / 10.0
            index += 3
        return offset_dict

    @staticmethod
    def parse_get_co2_offset(response):
        """Parse data from a CMD_GET_CO2_OFFSET API response.

        Response consists of 11 bytes as follows:
            Byte(s) Data            Format          Comments
            1-2     header          -               fixed header 0xFFFF
            3       command code    byte            0x53
            4       size            byte
            5-6     co2 offset      signed short    -600 to +10000 in tenths µg/m³
            7-8     pm25 offset     signed short    -200 to +200 in tenths µg/m³ (-20.0 to +20.0)
            9-10    pm10 offset     signed short    -200 to +200 in tenths µg/m³ (-20.0 to +20.0)
            17      checksum        byte            LSB of the sum of the command, size and data bytes
        """

        # determine the size of the WH45 offset data
        size = response[3]
        # extract the actual data
        data = response[4:4 + size - 3]
        # initialise a dict to hold our parsed data
        offset_dict = dict()
        # and decode/store the offset data
        # bytes 0 and 1 hold the CO2 offset
        offset_dict['co2'] = struct.unpack(">h", data[0:2])[0]
        # bytes 2 and 3 hold the PM2.5 offset
        offset_dict['pm25'] = struct.unpack(">h", data[2:4])[0] / 10.0
        # bytes 4 and 5 hold the PM10 offset
        offset_dict['pm10'] = struct.unpack(">h", data[4:6])[0] / 10.0
        return offset_dict

    @staticmethod
    def parse_read_gain(response):
        """Parse a CMD_READ_GAIN API response.

        Response consists of 17 bytes as follows:
            Byte(s) Data            Format          Comments
            1-2     header          -               fixed header 0xFFFF
            3       command code    byte            0x36
            4       size            byte
            5-6     fixed           short           fixed value 1267
            7-8     uvGain          unsigned short  10 to 500 in hundredths (0.10 to 5.00)
            9-10    solarRadGain    unsigned short  10 to 500 in hundredths (0.10 to 5.00)
            11-12   windGain        unsigned short  10 to 500 in hundredths (0.10 to 5.00)
            13-14   rainGain        unsigned short  10 to 500 in hundredths (0.10 to 5.00)
            15-16   reserved                        reserved
            17      checksum        byte            LSB of the sum of the command, size and data bytes
        """

        # determine the size of the calibration data
        size = response[3]
        # extract the actual data
        data = response[4:4 + size - 3]
        # initialise a dict to hold our parsed data
        gain_dict = dict()
        # and decode/store the calibration data; bytes 0 and 1 are reserved (lux to solar radiation conversion gain (126.7))
        gain_dict['uv'] = struct.unpack(">H", data[2:4])[0] / 100.0
        gain_dict['solar'] = struct.unpack(">H", data[4:6])[0] / 100.0
        gain_dict['wind'] = struct.unpack(">H", data[6:8])[0] / 100.0
        gain_dict['rain'] = struct.unpack(">H", data[8:10])[0] / 100.0
        # return the parsed response
        return gain_dict

    @staticmethod
    def parse_read_calibration(response):
        """Parse a CMD_READ_CALIBRATION API response.

        Response consists of 21 bytes as follows:
            Byte(s) Data            Format          Comments
            1-2     header          -               fixed header 0xFFFF
            3       command code    byte            0x38
            4       size            byte
            5-6     intemp offset   signed short    -100 to +100 in tenths C (-10.0 to +10.0)
            7       inhum offset    signed byte     -10 to +10 %
            8-11    abs offset      signed long     -800 to +800 in tenths hPa (-80.0 to +80.0)
            12-15   rel offset      signed long     -800 to +800 in tenths hPa (-80.0 to +80.0)
            16-17   outtemp offset  signed short    -100 to +100 in tenths C (-10.0 to +10.0)
            18      outhum offset   signed byte     -10 to +10 %
            19-20   wind dir offset signed short    -180 to +180 degrees
            21      checksum        byte            LSB of the sum of the command, size and data bytes
        """

        # determine the size of the calibration data
        size = response[3]
        # extract the actual data
        data = response[4:4 + size - 3]
        # initialise a dict to hold our parsed data
        cal_dict = dict()
        # and decode/store the offset calibration data
        cal_dict['intemp'] = struct.unpack(">h", data[0:2])[0] / 10.0
        try:
            cal_dict['inhum'] = struct.unpack("b", data[2])[0]
        except TypeError:
            cal_dict['inhum'] = struct.unpack("b", int_to_bytes(data[2]))[0]
        cal_dict['abs'] = struct.unpack(">l", data[3:7])[0] / 10.0
        cal_dict['rel'] = struct.unpack(">l", data[7:11])[0] / 10.0
        cal_dict['outtemp'] = struct.unpack(">h", data[11:13])[0] / 10.0
        try:
            cal_dict['outhum'] = struct.unpack("b", data[13])[0]
        except TypeError:
            cal_dict['outhum'] = struct.unpack("b", int_to_bytes(data[13]))[0]
        cal_dict['dir'] = struct.unpack(">h", data[14:16])[0]
        # return the parsed response
        return cal_dict

    @staticmethod
    def parse_get_soilhumiad(response):
        """Parse a CMD_GET_SOILHUMIAD API response.

        Response consists of a variable number of bytes determined by the
        number of WH51 soil moisture sensors. Number of bytes = 5 + (n x 9)
        where n is the number of connected WH51 sensors. Decode as follows:
        Byte(s) Data            Format          Comments
        1-2     header          -               fixed header 0xFFFF
        3       command code    byte            0x29
        4       size            byte
        5       channel         byte            channel number (0 to 8)
        6       current hum     byte            from sensor
        7-8     current ad      unsigned short  from sensor
        9       custom cal      byte            0 = sensor, 1 = enabled
        10      min ad          unsigned byte   0% ad setting (70 to 200)
        11-12   max ad          unsigned short  100% ad setting (80 to 1000)
        ....
        structure of bytes 5 to 12 incl repeated for each WH51 sensor
        ....
        21      checksum        byte            LSB of the sum of the
                                                command, size and data
                                                bytes
        """

        # determine the size of the calibration data
        size = response[3]
        # extract the actual data
        data = response[4:4 + size - 3]
        # initialise a dict to hold our final data
        cal_dict = {}
        # initialise a counter
        index = 0
        # iterate over the data
        while index < len(data):
            try:
                channel = byte_to_int(data[index])
            except TypeError:
                channel = data[index]
            cal_dict[channel] = {}
            try:
                humidity = byte_to_int(data[index + 1])
            except TypeError:
                humidity = data[index + 1]
            cal_dict[channel]['humidity'] = humidity
            cal_dict[channel]['ad'] = struct.unpack(">h", data[index + 2:index + 4])[0]
            try:
                ad_select = byte_to_int(data[index + 4])
            except TypeError:
                ad_select = data[index + 4]
            # get 'Customize' setting 1 = enable, 0 = customised
            cal_dict[channel]['ad_select'] = ad_select
            try:
                min_ad = byte_to_int(data[index + 5])
            except TypeError:
                min_ad = data[index + 5]
            cal_dict[channel]['adj_min'] = min_ad
            cal_dict[channel]['adj_max'] = struct.unpack(">h", data[index + 6:index + 8])[0]
            index += 8
        # return the parsed response
        return cal_dict

    def parse_read_ssss(self, response):
        """Parse a CMD_READ_SSSS API response.

        Response consists of 13 bytes as follows:
            Byte(s) Data            Format          Comments
            1-2     header          -               fixed header 0xFFFF
            3       command code    byte            0x30
            4       size            byte
            5       frequency       byte            0=433, 1=868, 2=915, 3=920
            6       sensor type     byte            0=WH24, 1=WH65
            7-10    utc time        unsigned long
            11      timezone index  byte
            12      dst status      byte            0=False, 1=True
            13      checksum        byte            LSB of the sum of the command, size and data bytes
        """

        FREQUENCIES = ['433 MHz', '866 MHz', '915 MHz', '920 MHz']
        SENSOR_TYPES = ['WH24', 'WH65']

        # determine the size of the system parameters data
        size = response[3]
        # extract the actual system parameters data
        data = response[4:4 + size - 3]
        # initialise a dict to hold our final data
        data_dict = dict()
        data_dict['frequency'] = FREQUENCIES[data[0]]
        data_dict['sensor type'] = SENSOR_TYPES[data[1]]
        # ToDo: Zeitrechnung falsch
        data_dict['utc'] = datetime.fromtimestamp(self.decode_utc(data[2:6])).replace(tzinfo=timezone.utc)
        data_dict['timezone_index'] = data[6]
        data_dict['dst_status'] = data[7] != 0
        # return the parsed response
        return data_dict

    @staticmethod
    def parse_read_ecowitt(response):
        """Parse a CMD_READ_ECOWITT API response.

        Response consists of six bytes as follows:
        Byte(s) Data            Format          Comments
        1-2     header          -               fixed header 0xFFFF
        3       command code    byte            0x1E
        4       size            byte
        5       upload interval byte            1-5 minutes, 0=off
        6       checksum        byte            LSB of the sum of the
                                                command, size and data
                                                bytes
        """

        # determine the size of the system parameters data
        size = response[3]
        # extract the actual system parameters data
        data = response[4:4 + size - 3]
        # initialise a dict to hold our final data
        data_dict = dict()
        data_dict['interval'] = data[0]
        # return the parsed response
        return data_dict

    @staticmethod
    def parse_read_wunderground(response):
        """Parse a CMD_READ_WUNDERGROUND API response.

        Response consists of a variable number of bytes. Number of
        bytes = 8 + i + p where i = length of the Wunderground ID in
        characters and p is the length of the Wunderground password in
        characters. Decode as follows:
        Byte(s) Data            Format          Comments
        1-2     header          -               fixed header 0xFFFF
        3       command code    byte            0x20
        4       size            byte
        5       ID size         unsigned byte   length of Wunderground ID
                                                in characters
        6-6+i   ID              i x bytes       ASCII, max 32 characters
        7+i     password size   unsigned byte   length of Wunderground
                                                password in characters
        8+i-    password        p x bytes       ASCII, max 32 characters
        8+i+p
        9+i+p   fixed           1               fixed value 1
        10+i+p  checksum        byte            LSB of the sum of the
                                                command, size and data
                                                bytes
        """

        # determine the size of the system parameters data
        size = response[3]
        # extract the actual system parameters data
        data = response[4:4 + size - 3]
        # initialise a dict to hold our final data
        data_dict = dict()
        # obtain the required data from the response decoding any bytestrings
        id_size = data[0]
        data_dict['id'] = data[1:1 + id_size].decode()
        password_size = data[1 + id_size]
        data_dict['password'] = data[2 + id_size:2 + id_size + password_size].decode()
        # return the parsed response
        return data_dict

    @staticmethod
    def parse_read_wow(response):
        """Parse a CMD_READ_WOW API response.

        Response consists of a variable number of bytes. Number of
        bytes = 9 + i + p + s where i = length of the WOW ID in characters,
        p is the length of the WOW password in characters and s is the
        length of the WOW station number in characters. Decode as follows:
        Byte(s) Data            Format          Comments
        1-2     header          -               fixed header 0xFFFF
        3       command code    byte            0x22
        4       size            byte
        5       ID size         unsigned byte   length of WOW ID in
                                                characters
        6-6+i   ID              i x bytes       ASCII, max 39 characters
        7+i     password size   unsigned byte   length of WOW password in
                                                characters
        8+i-    password        p x bytes       ASCII, max 32 characters
        8+i+p
        9+i+p   station num     unsigned byte   length of WOW station num
                size                            (unused)
        10+i+p- station num     s x bytes       ASCII, max 32 characters
        10+i+p+s                                (unused)
        11+i+p+s fixed          1               fixed value 1
        12+i+p+s checksum       byte            LSB of the sum of the
                                                command, size and data
                                                bytes
        """

        # determine the size of the system parameters data
        size = response[3]
        # extract the actual system parameters data
        data = response[4:4 + size - 3]
        # initialise a dict to hold our final data
        data_dict = dict()
        # obtain the required data from the response decoding any bytestrings
        id_size = data[0]
        data_dict['id'] = data[1:1 + id_size].decode()
        pw_size = data[1 + id_size]
        data_dict['password'] = data[2 + id_size:2 + id_size + pw_size].decode()
        stn_num_size = data[1 + id_size]
        data_dict['station_num'] = data[3 + id_size + pw_size:3 + id_size + pw_size + stn_num_size].decode()
        # return the parsed response
        return data_dict

    @staticmethod
    def parse_read_weathercloud(response):
        """Parse a CMD_READ_WEATHERCLOUD API response.

        Response consists of a variable number of bytes. Number of
        bytes = 8 + i + k where i = length of the Weathercloud ID in
        characters and p is the length of the Weathercloud key in
        characters. Decode as follows:
        Byte(s) Data            Format          Comments
        1-2     header          -               fixed header 0xFFFF
        3       command code    byte            0x24
        4       size            byte
        5       ID size         unsigned byte   length of Weathercloud ID
                                                in characters
        6-6+i   ID              i x bytes       ASCII, max 32 characters
        7+i     key size        unsigned byte   length of Weathercloud key
                                                in characters
        8+i-    key             k x bytes       ASCII, max 32 characters
        8+i+k
        9+i+k   fixed           1               fixed value 1
        10+i+k  checksum        byte            LSB of the sum of the
                                                command, size and data
                                                bytes
        """

        # determine the size of the system parameters data
        size = response[3]
        # extract the actual system parameters data
        data = response[4:4 + size - 3]
        # initialise a dict to hold our final data
        data_dict = dict()
        # obtain the required data from the response decoding any bytestrings
        id_size = data[0]
        data_dict['id'] = data[1:1 + id_size].decode()
        key_size = data[1 + id_size]
        data_dict['key'] = data[2 + id_size:2 + id_size + key_size].decode()
        # return the parsed response
        return data_dict

    @staticmethod
    def parse_read_customized(response):
        """Parse a CMD_READ_CUSTOMIZED API response.

        Response consists of a variable number of bytes. Number of
        bytes = 14 + i + p + s where i = length of the ID in characters,
        p is the length of the password in characters and s is the length
        of the server address in characters. Decode as follows:
        Byte(s)   Data            Format          Comments
        1-2       header          -               fixed header 0xFFFF
        3         command code    byte            0x2A
        4         size            byte
        5         ID size         unsigned byte   length of ID in characters
        6-5+i     ID              i x bytes       ASCII, max 40 characters
        6+i       password size   unsigned byte   length of password in
                                                  characters
        7+i-      password        p x bytes       ASCII, max 40 characters
        6+i+p
        7+i+p     server address  unsigned byte   length of server address in
                  size                            characters
        8+i+p-    server address  s x bytes       ASCII, max 64 characters
        7+i+p+s
        8+i+p+s-  port number     unsigned short  0 to 65535
        9+i+p+s
        10+i+p+s- interval        unsigned short  16 to 600 seconds
        11+i+p+s
        12+i+p+s  type            byte            0 = Ecowitt, 1 = WU
        13+i+p+s  active          byte            0 = disable, 1 = enable
        14+i+p+s  checksum        byte            LSB of the sum of the
                                                  command, size and data
                                                  bytes
        """

        # determine the size of the system parameters data
        size = response[3]
        # extract the actual system parameters data
        data = response[4:4 + size - 3]
        # initialise a dict to hold our final data
        data_dict = dict()
        # obtain the required data from the response decoding any bytestrings
        index = 0
        id_size = data[index]
        index += 1
        data_dict['id'] = data[index:index + id_size].decode()
        index += id_size
        password_size = data[index]
        index += 1
        data_dict['password'] = data[index:index + password_size].decode()
        index += password_size
        server_size = data[index]
        index += 1
        data_dict['server'] = data[index:index + server_size].decode()
        index += server_size
        data_dict['port'] = struct.unpack(">h", data[index:index + 2])[0]
        index += 2
        data_dict['interval'] = struct.unpack(">h", data[index:index + 2])[0]
        index += 2
        data_dict['type'] = data[index]
        index += 1
        data_dict['active'] = data[index]
        # return the parsed response
        return data_dict

    @staticmethod
    def parse_read_usr_path(response):
        """Parse a CMD_READ_USR_PATH API response.

        Response consists of a variable number of bytes. Number of
        bytes = 7 + e + w where e = length of the 'Ecowitt path' in
        characters and w is the length of the 'Weather Underground path'.
        Decode as follows:
        Byte(s)     Data            Format          Comments
        1-2         header          -               fixed header 0xFFFF
        3           command code    byte            0x51
        4           size            byte
        5           Ecowitt size    unsigned byte   length of Ecowitt path
                                                    in characters
        6-5+e       Ecowitt path    e x bytes       ASCII, max 64 characters
        6+e         WU size         unsigned byte   length of WU path in
                                                    characters
        7+e-6+e+w   WU path         w x bytes       ASCII, max 64 characters
        7+e+w       checksum        byte            LSB of the sum of the
                                                    command, size and data
                                                    bytes
        """

        # determine the size of the user path data
        size = response[3]
        # extract the actual system parameters data
        data = response[4:4 + size - 3]
        # initialise a dict to hold our final data
        data_dict = dict()
        index = 0
        ecowitt_size = data[index]
        index += 1
        data_dict['ecowitt_path'] = data[index:index + ecowitt_size].decode()
        index += ecowitt_size
        wu_size = data[index]
        index += 1
        data_dict['wu_path'] = data[index:index + wu_size].decode()
        # return the parsed response
        return data_dict

    @staticmethod
    def parse_read_station_mac(response):
        """Parse a CMD_READ_STATION_MAC API response.

        Response consists of 11 bytes as follows:
        Byte(s) Data            Format          Comments
        1-2     header          -               fixed header 0xFFFF
        3       command code    byte            0x26
        4       size            byte
        5-12    station MAC     6 x byte
        13      checksum        byte            LSB of the sum of the
                                                command, size and data
                                                bytes
        """

        # return the parsed response, in this case we simply return the
        # bytes as a semicolon separated hex string
        return bytes_to_hex(response[4:10], separator=":")

    @staticmethod
    def parse_read_firmware_version(response):
        """Parse a CMD_READ_FIRMWARE_VERSION API response.

        Response consists of a variable number of bytes. Number of
        bytes = 6 + f where f = length of the firmware version string in
        characters. Decode as follows:
        Byte(s) Data            Format          Comments
        1-2     header          -               fixed header 0xFFFF
        3       command code    byte            0x50
        4       size            byte
        5       fw size         byte            length of firmware version
                                                string in characters
        6-5+f   fw string       f x byte        firmware version string
                                                (ASCII ?)
        6+f     checksum        byte            LSB of the sum of the
                                                command, size and data
                                                bytes
        """

        # create a format string so the firmware string can be unpacked into
        # its bytes
        firmware_format = "B" * len(response)
        # unpack the firmware response bytestring, we now have a tuple of
        # integers representing each of the bytes
        firmware_t = struct.unpack(firmware_format, response)
        # get the length of the firmware string, it is in byte 4
        str_length = firmware_t[4]
        # the firmware string starts at byte 5 and is str_length bytes long,
        # convert the sequence of bytes to unicode characters and assemble as a
        # string and return the result
        return ''.join([chr(x) for x in firmware_t[5:5 + str_length]])

    @staticmethod
    def decode_reserved(data, field='reserved'):
        """Decode data that is marked 'reserved'.

        Occasionally some fields are marked as 'reserved' in the API
        documentation. In such cases the decode routine should return the
        value None which will cause the data to be ignored.
        """

        return None

    @staticmethod
    def decode_temp(data, field=None):
        """Decode temperature data.

        Data is contained in a two byte big endian signed integer and
        represents tenths of a degree. If field is not None return the
        result as a dict in the format {field: decoded value} otherwise
        return just the decoded value.
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

        Data is contained in a single unsigned byte and represents whole
        units. If field is not None return the result as a dict in the
        format {field: decoded value} otherwise return just the decoded
        value.
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
        """Decode direction data.

        Data is contained in a two byte big endian integer and represents
        whole degrees. If field is not None return the result as a dict in
        the format {field: decoded value} otherwise return just the decoded
        value.
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

        Data is contained in a four byte big endian integer and represents
        tenths of a unit. If field is not None return the result as a dict
        in the format {field: decoded value} otherwise return just the
        decoded value.
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

        Unknown format but length is six bytes. If field is not None return the result as a dict in the format {field: decoded value} otherwise
        return just the decoded value.
        """

        self.logger.debug(f"decode_datetime called")

        if len(data) == 6:
            value = struct.unpack("BBBBBB", data)[0]
        else:
            value = None

        if value and value.isdigit():
            value = int(value)

        self.logger.debug(f"decode_datetime: value={value}")

        if field is not None:
            return {field: value}
        else:
            return value

    def decode_datetime_as_dt(self, data, field=None):
        """Decode date-time data and return datetime object"""

        self.logger.debug(f"decode_datetime_as_dt called")

        timestamp = self.decode_datetime(data, None)
        self.logger.debug(f"decode_datetime_as_dt: timestamp={timestamp}")

        if timestamp and isinstance(timestamp, int):
            value = datetime.fromtimestamp(timestamp).replace(tzinfo=timezone.utc)
        else:
            value = None

        if field is not None:
            return {field: value}
        else:
            return value

    @staticmethod
    def decode_distance(data, field=None):
        """Decode lightning distance.

        Data is contained in a single byte integer and represents a value
        from 0 to 40km. If field is not None return the result as a dict in
        the format {field: decoded value} otherwise return just the decoded
        value.
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

        The API documentation claims to provide 'UTC time' as a 4 byte big endian integer. The 4 byte integer is a unix epoch timestamp;
        however, the timestamp is offset by the station's timezone. So for a station in the +10 hour timezone, the timestamp returned is the
        present epoch timestamp plus 10 * 3600 seconds.

        When decoded in localtime the decoded date-time is off by the station time zone, when decoded as GMT the date and time figures
        are correct but the timezone is incorrect.

        In any case decode the 4 byte big endian integer as is and any further use of this timestamp needs to take the above time zone
        offset into account when using the timestamp.

        If field is not None return the result as a dict in the format {field: decoded value} otherwise return just the decoded value.
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
        """Decode lightning count.

        Count is an integer stored in a four byte big endian integer. If
        field is not None return the result as a dict in the format
        {field: decoded value} otherwise return just the decoded value.
        """

        if len(data) == 4:
            value = struct.unpack(">L", data)[0]
        else:
            value = None
        if field is not None:
            return {field: value}
        else:
            return value

    @staticmethod
    def decode_gain_100(data, field=None):
        """Decode a sensor gain expressed in hundredths.

        Gain is stored in a four byte big endian integer and represents
        hundredths of a unit.
        """

        if len(data) == 2:
            value = struct.unpack(">H", data)[0] / 100.0
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
    decode_int = decode_humid

    def decode_wn34(self, data, field=None):
        """Decode WN34 sensor data.

        Data consists of three bytes:

        Byte    Field               Comments
        1-2     temperature         standard Ecowitt temperature data, two
                                    byte big endian signed integer
                                    representing tenths of a degree
        3       battery voltage     0.02 * value Volts

        WN34 battery state data is included in the WN34 sensor data (along
        with temperature) as well as in the complete sensor ID data. In
        keeping with other sensors we do not use the sensor data battery
        state, rather we obtain it from the sensor ID data.

        If field is not None return the result as a dict in the format
        {field: decoded value} otherwise return just the decoded value.
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
                6-7    PM10 24-hour avg   unsigned short  ug/m3 x10
                8-9    PM2.5              unsigned short  ug/m3 x10
                10-11  PM2.5 24-hour avg  unsigned short  ug/m3 x10
                12-13  CO2                unsigned short  ppm
                14-15  CO2 24-hour avg    unsigned short  ppm
                16     battery state      unsigned byte   0-5 <=1 is low

        WH45 battery state data is included in the WH45 sensor data (along
        with temperature) as well as in the complete sensor ID data. In
        keeping with other sensors we do not use the sensor data battery
        state, rather we obtain it from the sensor ID data.
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

    def decode_rain_gain(self, data, fields=None):
        """Decode piezo rain gain data.

        Piezo rain gain data is 20 bytes of data comprising 10 two byte big
        endian fields with each field representing a value in hundredths of
        a unit.

        The 20 bytes of piezo rain gain data is allocated as follows:
        Byte(s) #      Data      Format            Comments
        bytes   1-2    gain1     unsigned short    gain x 100
                3-4    gain2     unsigned short    gain x 100
                5-6    gain3     unsigned short    gain x 100
                7-8    gain4     unsigned short    gain x 100
                9-10   gain5     unsigned short    gain x 100
                11-12  gain6     unsigned short    gain x 100, reserved
                13-14  gain7     unsigned short    gain x 100, reserved
                15-16  gain8     unsigned short    gain x 100, reserved
                17-18  gain9     unsigned short    gain x 100, reserved
                19-20  gain10    unsigned short    gain x 100, reserved

        As of device firmware v2.1.3 gain6-gain10 inclusive are unused and
        reserved for future use.
        """

        if len(data) == 20:
            results = dict()
            for gain in range(10):
                results['gain%d' % gain] = self.decode_gain_100(data[gain * 2:gain * 2 + 2])
            return results
        return {}

    @staticmethod
    def decode_rain_reset(data, fields=None):
        """Decode rain reset data.

        Rain reset data is three bytes of data comprising three unsigned
        byte fields with each field representing an integer.

        The three bytes of rain reset data is allocated as follows:
        Byte  #  Data               Format         Comments
        byte  1  day reset time     unsigned byte  hour of the day to reset day
                                                   rain, eg 7 = 07:00
              2  week reset time    unsigned byte  day of week to reset week rain,
                                                   allowed values are 0 or 1. 0=Sunday, 1=Monday
              3  annual reset time  unsigned byte  month of year to reset annual
                                                   rain, allowed values are 0-11, eg 2 = March
        """

        if len(data) == 3:
            results = dict()
            results['day_reset'] = struct.unpack("B", data[0:1])[0]
            results['week_reset'] = struct.unpack("B", data[1:2])[0]
            results['annual_reset'] = struct.unpack("B", data[2:3])[0]
            return results
        return {}

    @staticmethod
    def decode_batt(data, field=None):
        """Decode battery status data.

        GW1000 firmware version 1.6.4 and earlier supported 16 bytes of
        battery state data at response field x4C for the following sensors:
            WH24, WH25, WH26(WH32), WH31 ch1-8, WH40, WH41/WH43 ch1-4,
            WH51 ch1-8, WH55 ch1-4, WH57, WH68 and WS80

        As of GW1000 firmware version 1.6.5 the 16 bytes of battery state
        data is no longer returned at all (GW1100, GW2000 and later devices
        never provided this battery state data in this format).
        CMD_READ_SENSOR_ID_NEW or CMD_READ_SENSOR_ID must be used to obtain
        battery state information for connected sensors. The decode_batt()
        method has been retained to support devices using firmware
        version 1.6.4 and earlier.

        Since the gateway driver now obtains battery state information via
        CMD_READ_SENSOR_ID_NEW or CMD_READ_SENSOR_ID only the decode_batt()
        method now returns None so that firmware versions before 1.6.5
        continue to be supported.
        """

        return None


class Sensors(object):
    """Class to manage device sensor ID data.

    Class Sensors allows access to various elements of sensor ID data via a number of properties and methods when the class is initialised with the
    device response to a CMD_READ_SENSOR_ID_NEW or CMD_READ_SENSOR_ID API command.

    A Sensors object can be initialised with sensor ID data on instantiation or an existing Sensors object can be updated by calling
    the set_sensor_id_data() method and passing the sensor ID data to be used as the only parameter.
    """

    # map of sensor ids to short name, long name and battery byte decode
    # function
    sensor_ids = {
        b'\x00': {'name': 'wh65', 'long_name': 'WH65', 'batt_fn': 'batt_binary'},
        b'\x01': {'name': 'wh68', 'long_name': 'WH68', 'batt_fn': 'batt_volt'},
        b'\x02': {'name': 'ws80', 'long_name': 'WS80', 'batt_fn': 'batt_volt'},
        b'\x03': {'name': 'wh40', 'long_name': 'WH40', 'batt_fn': 'wh40_batt_volt'},
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
        b'\x0e': {'name': 'wh51_ch1', 'long_name': 'WH51 ch1', 'batt_fn': 'batt_volt_tenth'},
        b'\x0f': {'name': 'wh51_ch2', 'long_name': 'WH51 ch2', 'batt_fn': 'batt_volt_tenth'},
        b'\x10': {'name': 'wh51_ch3', 'long_name': 'WH51 ch3', 'batt_fn': 'batt_volt_tenth'},
        b'\x11': {'name': 'wh51_ch4', 'long_name': 'WH51 ch4', 'batt_fn': 'batt_volt_tenth'},
        b'\x12': {'name': 'wh51_ch5', 'long_name': 'WH51 ch5', 'batt_fn': 'batt_volt_tenth'},
        b'\x13': {'name': 'wh51_ch6', 'long_name': 'WH51 ch6', 'batt_fn': 'batt_volt_tenth'},
        b'\x14': {'name': 'wh51_ch7', 'long_name': 'WH51 ch7', 'batt_fn': 'batt_volt_tenth'},
        b'\x15': {'name': 'wh51_ch8', 'long_name': 'WH51 ch8', 'batt_fn': 'batt_volt_tenth'},
        b'\x16': {'name': 'wh41_ch1', 'long_name': 'WH41 ch1', 'batt_fn': 'batt_int'},
        b'\x17': {'name': 'wh41_ch2', 'long_name': 'WH41 ch2', 'batt_fn': 'batt_int'},
        b'\x18': {'name': 'wh41_ch3', 'long_name': 'WH41 ch3', 'batt_fn': 'batt_int'},
        b'\x19': {'name': 'wh41_ch4', 'long_name': 'WH41 ch4', 'batt_fn': 'batt_int'},
        b'\x1a': {'name': 'wh57', 'long_name': 'WH57', 'batt_fn': 'batt_int'},
        b'\x1b': {'name': 'wh55_ch1', 'long_name': 'WH55 ch1', 'batt_fn': 'batt_int'},
        b'\x1c': {'name': 'wh55_ch2', 'long_name': 'WH55 ch2', 'batt_fn': 'batt_int'},
        b'\x1d': {'name': 'wh55_ch3', 'long_name': 'WH55 ch3', 'batt_fn': 'batt_int'},
        b'\x1e': {'name': 'wh55_ch4', 'long_name': 'WH55 ch4', 'batt_fn': 'batt_int'},
        b'\x1f': {'name': 'wn34_ch1', 'long_name': 'WN34 ch1', 'batt_fn': 'batt_volt'},
        b'\x20': {'name': 'wn34_ch2', 'long_name': 'WN34 ch2', 'batt_fn': 'batt_volt'},
        b'\x21': {'name': 'wn34_ch3', 'long_name': 'WN34 ch3', 'batt_fn': 'batt_volt'},
        b'\x22': {'name': 'wn34_ch4', 'long_name': 'WN34 ch4', 'batt_fn': 'batt_volt'},
        b'\x23': {'name': 'wn34_ch5', 'long_name': 'WN34 ch5', 'batt_fn': 'batt_volt'},
        b'\x24': {'name': 'wn34_ch6', 'long_name': 'WN34 ch6', 'batt_fn': 'batt_volt'},
        b'\x25': {'name': 'wn34_ch7', 'long_name': 'WN34 ch7', 'batt_fn': 'batt_volt'},
        b'\x26': {'name': 'wn34_ch8', 'long_name': 'WN34 ch8', 'batt_fn': 'batt_volt'},
        b'\x27': {'name': 'wh45', 'long_name': 'WH45', 'batt_fn': 'batt_int'},
        b'\x28': {'name': 'wn35_ch1', 'long_name': 'WN35 ch1', 'batt_fn': 'batt_volt'},
        b'\x29': {'name': 'wn35_ch2', 'long_name': 'WN35 ch2', 'batt_fn': 'batt_volt'},
        b'\x2a': {'name': 'wn35_ch3', 'long_name': 'WN35 ch3', 'batt_fn': 'batt_volt'},
        b'\x2b': {'name': 'wn35_ch4', 'long_name': 'WN35 ch4', 'batt_fn': 'batt_volt'},
        b'\x2c': {'name': 'wn35_ch5', 'long_name': 'WN35 ch5', 'batt_fn': 'batt_volt'},
        b'\x2d': {'name': 'wn35_ch6', 'long_name': 'WN35 ch6', 'batt_fn': 'batt_volt'},
        b'\x2e': {'name': 'wn35_ch7', 'long_name': 'WN35 ch7', 'batt_fn': 'batt_volt'},
        b'\x2f': {'name': 'wn35_ch8', 'long_name': 'WN35 ch8', 'batt_fn': 'batt_volt'},
        b'\x30': {'name': 'ws90', 'long_name': 'WS90', 'batt_fn': 'batt_volt', 'low_batt': 3}
    }
    # sensors for which there is no low battery state
    no_low = ['ws80', 'ws90']

    # Tuple of sensor ID values for sensors that are not registered with the device.
    # 'fffffffe' means the sensor is disabled, 'ffffffff' means the sensor is registering.
    not_registered = ('fffffffe', 'ffffffff')

    def __init__(self,
                 sensor_id_data=None,
                 ignore_wh40_batt=True,
                 show_battery=False,
                 use_wh32=True,
                 is_wh24=False,
                 debug=None,
                 plugin_instance=None):
        """Initialise myself"""

        # get instance
        self._plugin_instance = plugin_instance
        self.logger = self._plugin_instance.logger

        # are we using a WH32 sensor, if so tell our sensor id decoding we have a WH32, otherwise it will default to WH26.
        if use_wh32:
            # set the WH24 sensor id decode dict entry
            self.sensor_ids[b'\x05']['name'] = 'wh32'
            self.sensor_ids[b'\x05']['long_name'] = 'WH32'
        # Tell our sensor id decoding whether we have a WH24 or a WH65. By default, we are coded to use a WH65. Is there a WH24 connected?
        if is_wh24:
            # set the WH24 sensor id decode dict entry
            self.sensor_ids[b'\x00']['name'] = 'wh24'
            self.sensor_ids[b'\x00']['long_name'] = 'WH24'

        # do we ignore battery state data from legacy WH40 sensors that do not provide valid battery state data
        self.ignore_wh40_batt = ignore_wh40_batt
        # set the show_battery property
        self.show_battery = show_battery
        # initialise legacy WH40 flag
        self.legacy_wh40 = None
        # initialise a dict to hold the parsed sensor data
        self.sensor_data = dict()
        # parse the raw sensor ID data and store the results in my parsed sensor data dict
        self.set_sensor_id_data(sensor_id_data)
        # debug sensors
        self.debug = debug if debug is not None else DebugOptions()

    def set_sensor_id_data(self, id_data):
        """Parse the raw sensor ID data and store the results.

        id_data: bytestring of sensor ID data
        """

        # initialise our parsed sensor ID data dict
        self.sensor_data = {}
        # do we have any raw sensor ID data
        if id_data is not None and len(id_data) > 0:
            # determine the size of the sensor id data, it's a big endian short (two byte) integer at bytes 4 and 5
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
                if address in Sensors.sensor_ids.keys():
                    # get the sensor ID
                    sensor_id = bytes_to_hex(data[index + 1: index + 5], separator='', caps=False)
                    # get the method to be used to decode the battery state
                    # data
                    batt_fn = Sensors.sensor_ids[data[index:index + 1]]['batt_fn']
                    # get the raw battery state data
                    batt = data[index + 5]
                    # if we are not showing all battery state data then the battery state for any sensor with signal == 0 must be set
                    # to None, otherwise parse the raw battery state data as applicable
                    if not self.show_battery and data[index + 6] == 0:
                        batt_state = None
                    else:
                        # parse the raw battery state data
                        batt_state = getattr(self, batt_fn)(batt)
                    # now add the sensor to our sensor data dict
                    self.sensor_data[address] = {'id': sensor_id,
                                                 'battery': batt_state,
                                                 'signal': data[index + 6]
                                                 }
                else:
                    if self.debug.sensors:
                        self.logger.info(f"Unknown sensor ID '{bytes_to_hex(address)}'")
                # each sensor entry is seven bytes in length so skip to the start of the next sensor
                index += 7

    @property
    def addresses(self):
        """Obtain a list of sensor addresses.

        This includes all sensor addresses reported by the device, this
        includes:
        - sensors that are actually connected to the device
        - sensors that are attempting to connect to the device
        - device sensor addresses that are searching for a sensor
        - device sensor addresses that are disabled

        Tested by SensorsTestCase.test_properties
        """

        # this is simply the list of keys to our sensor data dict
        return self.sensor_data.keys()

    @property
    def connected_addresses(self):
        """Obtain a list of sensor addresses for connected sensors only.

        Sometimes we only want a list of addresses for sensors that are
        actually connected to the gateway device. We can filter out those
        addresses that do not have connected sensors by looking at the
        sensor ID. If the sensor ID is 'fffffffe' either the sensor is
        connecting to the device or the device is searching for a sensor
        for that address. If the sensor ID is 'ffffffff' the device sensor
        address is disabled.

        Tested by SensorsTestCase.test_properties
        """

        # initialise a list to hold our connected sensor addresses
        connected_list = list()
        # iterate over all sensors
        for address, data in self.sensor_data.items():
            # if the sensor ID is neither 'fffffffe' or 'ffffffff' then it
            # must be connected
            if data['id'] not in self.not_registered:
                connected_list.append(address)
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
        """Obtain a dict of sensor battery state and signal level data.

        Iterate over the list of connected sensors and obtain a dict of sensor battery state data for each connected sensor.
        """

        # initialise a dict to hold the battery state data
        data = {}
        # iterate over our connected sensors
        for sensor in self.connected_addresses:
            # get the sensor name
            sensor_name = Sensors.sensor_ids[sensor]['name']
            # create the sensor battery state field for this sensor
            data[''.join([sensor_name, '_batt'])] = self.battery_state(sensor)
            # create the sensor signal level field for this sensor
            data[''.join([sensor_name, '_sig'])] = self.signal_level(sensor)
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
            sensor_name = self.sensor_ids[sensor]['name']
            # create the sensor battery state description field for this sensor
            data[sensor_name] = self.batt_state_desc(sensor, self.battery_state(sensor))

        # return our data
        return data

    @staticmethod
    def batt_state_desc(address, value):
        """Determine the battery state description for a given sensor.

        Given a sensor address and battery state value determine appropriate battery state descriptive text, eg 'low', 'OK' etc.
        Descriptive text is based on Ecowitt API documentation. None is returned for sensors for which the API documentation provides no
        suitable battery state data, or for which descriptive battery state text cannot be inferred.

        A battery state value of None should not occur but if received the descriptive text 'unknown' is returned.
        """

        if value is not None:
            if Sensors.sensor_ids[address].get('name') in Sensors.no_low:
                # we have a sensor for which no low battery cut-off
                # data exists
                return None
            else:
                batt_fn = Sensors.sensor_ids[address].get('batt_fn')
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
                elif batt_fn in ['batt_volt', 'batt_volt_tenth', 'wh40_batt_volt']:
                    if value <= 1.2:
                        return "low"
                    else:
                        return "OK"
        else:
            return 'Unknown'

    @staticmethod
    def batt_binary(batt):
        """Decode a binary battery state.

        Battery state is stored in bit 0 as either 0 or 1. If 1 the battery is low, if 0 the battery is normal. We need to mask off bits 1 to 7 as
        they are not guaranteed to be set in any particular way.
        """

        return batt & 1

    @staticmethod
    def batt_int(batt):
        """Decode a integer battery state.

        According to the API documentation battery state is stored as an integer from 0 to 5 with <=1 being considered low. Experience with
        WH43 has shown that battery state 6 also exists when the device is run from DC. This does not appear to be documented in the API
        documentation.
        """

        return batt

    @staticmethod
    def batt_volt(batt):
        """Decode a voltage battery state in 2mV increments.

        Battery state is stored as integer values of battery voltage/0.02 with <=1.2V considered low.
        """

        return round(0.02 * batt, 2)

    def wh40_batt_volt(self, batt):
        """Decode WH40 battery state.

        Initial WH40 devices did not provide battery state information. API versions up to and including v.1.6.4 reported WH40 battery state
        via a single bit. API v1.6.5 and later report WH40 battery state in a single byte in 100mV increments. It appears that API v1.6.5 and
        later return a fixed value of 0x10 (decodes to 1.6V) for WH40 battery state for WH40 devices that do not report battery state.
        WH40 devices that do report battery state appear to return a value in a single byte in 10mV increments rather than 100mV increments as
        documented in the Ecowitt LAN/Wi-Fi Gateway API documentation v1.6.4. There is no known way to identify via the API
        whether a given WH40 reports battery state information or not.

        Consequently, decoding of WH40 battery state data is handled as follows:

        -   the WH40 battery state data is decoded as per the API documentation as a value in 100mV increments
        -   if the decoded value is <2.0V the device is assumed to be a non-battery state reporting WH40 and the value None is returned
        -   if the decoded value is >=2.0V the device is assumed to be a battery state reporting WH40 and the value returned is the WH40
            battery state data decoded in 10mV increments

        For WH40 that report battery state data a decoded value of <=1.2V is considered low.
        """

        if round(0.1 * batt, 1) < 2.0:
            # assume we have a non-battery state reporting WH40
            # first set the legacy_wh40 flag
            self.legacy_wh40 = True
            # then do we ignore the result or pass it on
            if self.ignore_wh40_batt:
                # we are ignoring the result so return None
                return None
            else:
                # we are not ignoring the result so return the result
                return round(0.1 * batt, 1)
        else:
            # assume we have a battery state reporting WH40
            # first reset the legacy_wh40 flag
            self.legacy_wh40 = False
            return round(0.01 * batt, 2)

    @staticmethod
    def batt_volt_tenth(batt):
        """Decode a voltage battery state in 100mV increments.

        Battery state is stored as integer values of battery voltage/0.1 with <=1.2V considered low.
        """

        return round(0.1 * batt, 1)


class GatewayApi(object):
    """Class to interact with a gateway device via the Ecowitt LAN/Wi-Fi Gateway API.

    A GatewayApi object knows how to:
    1.  discover a device via UDP broadcast
    2.  send a command to the API
    3.  receive a response from the API
    4.  verify the response as valid

    A GatewayApi object needs an IP address and port as well as a network broadcast address and port.

    A GatewayApi object uses the following classes:
    - class ApiParser. Parses and decodes the validated gateway API response data returning observational and parametric data.
    - class Sensors.   Decodes raw sensor data obtained from validated gateway API response data
    """

    # Ecowitt LAN/Wi-Fi Gateway API api_commands
    API_COMMANDS = {
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
        'CMD_SET_CO2_OFFSET': b'\x54',
        'CMD_READ_RSTRAIN_TIME': b'\x55',
        'CMD_WRITE_RSTRAIN_TIME': b'\x56',
        'CMD_READ_RAIN': b'\x57',
        'CMD_WRITE_RAIN': b'\x58',
        'CMD_GET_MulCH_T_OFFSET': b'\x59'
    }
    # header used in each API command and response packet
    HEADER = b'\xff\xff'
    
    def __init__(self,
                 ip_address=None,
                 port=None,
                 broadcast_address=None,
                 broadcast_port=None,
                 socket_timeout=None,
                 broadcast_timeout=None,
                 max_tries=None,
                 retry_wait=None,
                 mac=None,
                 debug=None,
                 plugin_instance=None):

        # get instance
        self._plugin_instance = plugin_instance
        self.logger = self._plugin_instance.logger

        # get interface config
        self.interface_config = self._plugin_instance.interface_config

        # get a parser object to parse any API data
        self.parser = ApiParser(log_unknown_fields=self.interface_config.log_unknown_fields,
                                plugin_instance=plugin_instance)

        # define network parameters
        self.broadcast_address = broadcast_address if broadcast_address is not None else self.interface_config.broadcast_address
        self.broadcast_port = broadcast_port if broadcast_port is not None else self.interface_config.broadcast_port
        self.socket_timeout = socket_timeout if socket_timeout is not None else self.interface_config.socket_timeout
        self.broadcast_timeout = broadcast_timeout if broadcast_timeout is not None else self.interface_config.broadcast_timeout

        # initialise flags to indicate if IP address or port were discovered
        self.ip_discovered = ip_address is None
        self.port_discovered = port is None

        # if IP address or port was not specified (None) then attempt to
        # discover the device with a UDP broadcast
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
                    # did we find any devices
                    if len(self.device_list) > 0:
                        # we have at least one, arbitrarily choose the first one found as the one to use
                        disc_ip = self.device_list[0]['ip_address']
                        disc_port = self.device_list[0]['port']
                        # log the fact as well as what we found
                        gw1000_str = ', '.join([':'.join(['%s:%d' % (d['ip_address'], d['port'])]) for d in self.device_list])
                        if len(self.device_list) == 1:
                            stem = f"{self.device_list[0]['model']} was"
                        else:
                            stem = "Multiple devices were"
                        self.logger.info(f"{stem} found: {gw1000_str}. First one selected for plugin. To use dedicated one, define IP of dedicated Gateway in Plugin Setup.")
                        ip_address = disc_ip if ip_address is None else ip_address
                        port = disc_port if port is None else port
                        break
                    else:
                        # did not discover any device so log it
                        self.logger.debug(f"Failed to detect device IP address and/or port after {attempt + 1,} attempts")
                        # do we try again or raise an exception
                        if attempt < max_tries - 1:
                            # we still have at least one more try left so sleep and try again
                            time.sleep(retry_wait)
                        else:
                            # we've used all our tries, log it and raise an exception
                            _msg = f"Failed to detect device IP address and/or port after {attempt + 1,} attempts"
                            self.logger.error(_msg)
                            raise GatewayIOError(_msg)

        # set our ip_address property but encode it first, it saves doing  it repeatedly later
        self.ip_address = ip_address.encode()
        self.port = port
        self.max_tries = max_tries if max_tries is not None else self.interface_config.max_tries
        self.retry_wait = retry_wait if retry_wait is not None else self.interface_config.retry_wait

        # start off logging failures
        self.log_failures = True

        # Get my MAC address to use later if we have to rediscover. Within class GatewayApi the MAC address is stored as a bytestring.
        if mac is None:
            self.mac = self.get_mac_address()
        else:
            self.mac = mac
        # get my device model
        self.model = self.get_model_from_firmware(self.get_firmware_version())

        # Do we have a WH24 attached? First obtain our system parameters.
        _sys_params = self.get_system_params()
        is_wh24 = _sys_params.get('sensor_type', 0) == 'WH24'

        # get a Sensors object to parse any API sensor state data
        self.sensors = Sensors(use_wh32=self.interface_config.use_wh32,
                               ignore_wh40_batt=self.interface_config.ignore_wh40_batt,
                               show_battery=self.interface_config.show_battery_warning,
                               is_wh24=is_wh24,
                               debug=debug,
                               plugin_instance=plugin_instance)
        # update the sensors object
        self.update_sensor_id_data()

    def discover(self):
        """Discover any devices on the local network.

        Send a UDP broadcast and check for replies. Decode each reply to obtain details of any devices on the local network. Create a dict
        of details for each device including a derived model name.
        Construct a list of dicts with details of unique (MAC address) devices that responded. When complete return the list of devices found.
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
        
        # initialise a list for the results as multiple devices may respond
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
                # if we time out then we are done
                break
            except socket.error as e:
                self.logger.warning(f"Socket Error {e!r} occurred.")
                # raise any other socket error
                raise
            else:
                # check the response is valid
                try:
                    self.check_response(response, self.API_COMMANDS['CMD_BROADCAST'])
                except InvalidChecksum as e:
                    # the response was not valid, log it and attempt again if we haven't had too many attempts already
                    self.logger.debug(f"Invalid response to command 'CMD_BROADCAST': {e}")
                except UnknownApiCommand:
                    # most likely we have encountered a device that does not understand the command, possibly due to an old or
                    # outdated firmware version, raise the exception for our caller to deal with
                    raise
                except Exception as e:
                    # Some other error occurred in check_response(), perhaps the response was malformed. Log the stack
                    # trace but continue.
                    self.logger.error(f"Unexpected exception occurred while checking response to command 'CMD_BROADCAST': {e}")
                else:
                    # we have a valid response so decode the response and obtain a dict of device data
                    device = self.decode_broadcast_response(response)
                    # if we haven't seen this MAC before attempt to obtain and save the device model then add the device to our
                    # results list
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

        A device response to a CMD_BROADCAST API command consists of a number of control structures around a payload of a data. The API
        response is structured as follows:
            bytes 0-1 incl                  preamble, literal 0xFF 0xFF
            byte 2                          literal value 0x12
            bytes 3-4 incl                  payload size (big endian short integer)
            bytes 5-5+payload size incl     data payload (details below)
            byte 6+payload size             checksum

        The data payload is structured as follows:
            bytes 0-5 incl      device MAC address
            bytes 6-9 incl      device IP address
            bytes 10-11 incl    device port number
            bytes 11-           device AP SSID

        Note: The device AP SSID for a given device is fixed in size but this size can vary from device to device and across firmware versions.

        There also seems to be a peculiarity in the CMD_BROADCAST response data payload whereby the first character of the device AP SSID is a
        non-printable ASCII character. The WSView app appears to ignore or not display this character nor does it appear to be used elsewhere.
        Consequently, this character is ignored.

        raw_data:   a bytestring containing a validated (structure and checksum verified) raw data response to the CMD_BROADCAST API command

        Returns a dict with decoded data keyed as follows:
            'mac':          device MAC address (string)
            'ip_address':   device IP address (string)
            'port':         device port number (integer)
            'ssid':         device AP SSID (string)
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

        To date device firmware versions have included the device model in the firmware version string returned via the device API. Whilst
        this is not guaranteed to be the case for future firmware releases, in the absence of any other direct means of obtaining the device
        model number it is a useful means for determining the device model.

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

        To date the device SSID has included the device model in the SSID returned via the device API. Whilst this is not guaranteed to be
        the case for future firmware releases, in the absence of any other direct means of obtaining the device model number it is a useful
        means for determining the device model. This is particularly the case when using UDP broadcast to discover devices on the local
        network.

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

        To date firmware versions have included the device model in the firmware version string or the device SSID. Both the firmware
        version string and device SSID are available via the device API so checking the firmware version string or SSID provides a de facto
        method of determining the device model.

        This method uses a simple check to see if a known model name is contained in the string concerned.

        Known model strings are contained in a tuple Station.known_models.

        If a known model is found in the string the model is returned as a string. None is returned if a known model is not found in the string.
        """

        # do we have a string to check
        if t is not None:
            # we have a string, now do we have a know model in the string, if so return the model string
            for model in self.interface_config.known_models:
                if model in t.upper():
                    return model
            # we don't have a known model so return None
            return None
        else:
            # we have no string so return None
            return None

    def get_livedata(self):
        """Obtain parsed live data.

        Sends the API command to the device to obtain live data with retries
        If the device cannot be contacted re-discovery is attempted. If rediscovery is successful the command is sent again otherwise the lost
        contact timestamp is set and a GWIOError exception raised. Any code that calls this method should be prepared to handle this exception.

        If a valid response is received the received data is parsed and the parsed data returned.
        """

        # send the API command to obtain live data from the device, be prepared to catch the exception raised if the device cannot be contacted
        try:
            # get the validated API response
            response = self.send_cmd_with_retries('CMD_GW1000_LIVEDATA')
        except GatewayIOError:
            # there was a problem contacting the device, it could be it has changed IP address so attempt to rediscover
            if not self.rediscover():
                # we could not re-discover so raise the exception
                raise
            else:
                # we did rediscover successfully so try again, if it fails we get another GWIOError exception which will be raised
                response = self.send_cmd_with_retries('CMD_GW1000_LIVEDATA')
        # if we arrived here we have a non-None response so parse it and return the parsed data
        return self.parser.parse_livedata(response)

    def read_raindata(self):
        """Get traditional gauge rain data.

        Sends the API command to obtain traditional gauge rain data from the device with retries. If the device cannot be contacted a
        GWIOError will have been raised by send_cmd_with_retries() which will be passed through by read_raindata(). Any code calling
        read_raindata() should be prepared to handle this exception.
        """

        # get the validated API response
        response = self.send_cmd_with_retries('CMD_READ_RAINDATA')
        # now return the parsed response
        return self.parser.parse_read_raindata(response)

    def get_system_params(self):
        """Read system parameters.

        Sends the API command to obtain system parameters from the device with retries. If the device cannot be contacted a GWIOError will
        have been raised by send_cmd_with_retries() which will be passed through by get_system_params(). Any code calling
        get_system_params() should be prepared to handle this exception.
        """

        # get the validated API response
        response = self.send_cmd_with_retries('CMD_READ_SSSS')
        # now return the parsed response
        return self.parser.parse_read_ssss(response)

    def get_ecowitt_net_params(self):
        """Get Ecowitt.net parameters.

        Sends the API command to obtain the device Ecowitt.net parameters with retries. If the device cannot be contacted a GWIOError will
        have been raised by send_cmd_with_retries() which will be passed through by get_ecowitt_net_params(). Any code calling
        get_ecowitt_net_params() should be prepared to handle this exception.
        """

        # get the validated API response
        response = self.send_cmd_with_retries('CMD_READ_ECOWITT')
        # parse the response
        ecowitt = self.parser.parse_read_ecowitt(response)
        # add the device MAC address to the parsed data
        ecowitt['mac'] = self.get_mac_address()
        return ecowitt

    def get_wunderground_params(self):
        """Get Weather Underground parameters.

        Sends the API command to obtain the device Weather Underground parameters with retries. If the device cannot be contacted a
        GWIOError will have been raised by send_cmd_with_retries() which will be passed through by get_wunderground_params(). Any code
        calling get_wunderground_params() should be prepared to handle this exception.
        """

        # get the validated API response
        response = self.send_cmd_with_retries('CMD_READ_WUNDERGROUND')
        # now return the parsed response
        return self.parser.parse_read_wunderground(response)

    def get_weathercloud_params(self):
        """Get Weathercloud parameters.

        Sends the API command to obtain the device Weathercloud parameters with retries. If the device cannot be contacted a GWIOError will
        have been raised by send_cmd_with_retries() which will be passed through by get_weathercloud_params(). Any code calling
        get_weathercloud_params() should be prepared to handle this exception.
        """

        # get the validated API response
        response = self.send_cmd_with_retries('CMD_READ_WEATHERCLOUD')
        # now return the parsed response
        return self.parser.parse_read_weathercloud(response)

    def get_wow_params(self):
        """Get Weather Observations Website parameters.

        Sends the API command to obtain the device Weather Observations Website parameters with retries. If the device cannot be contacted
        a GWIOError will have been raised by send_cmd_with_retries() which will be passed through by get_wow_params(). Any code calling
        get_wow_params() should be prepared to handle this exception.
        """

        # get the validated API response
        response = self.send_cmd_with_retries('CMD_READ_WOW')
        # now return the parsed response
        return self.parser.parse_read_wow(response)

    def get_custom_params(self):
        """Get custom server parameters.

        Sends the API command to obtain the device custom server parameters with retries. If the device cannot be contacted a GWIOError will
        have been raised by send_cmd_with_retries() which will be passed through by get_custom_params(). Any code calling
        get_custom_params() should be prepared to handle this exception.
        """

        # get the validated API response
        response = self.send_cmd_with_retries('CMD_READ_CUSTOMIZED')
        # obtain the parsed response
        data_dict = self.parser.parse_read_customized(response)
        # the user path is obtained separately, get the user path and add it to
        # our response
        data_dict.update(self.get_usr_path())
        # return the resulting parsed data
        return data_dict

    def set_custom_params(self, custom_server_id, custom_password, custom_host, custom_port, custom_interval, custom_type, custom_enabled):
        """
        Set GW1000/GW1100 custom server parameters.

        Sends the command to obtain the GW1000/GW1100 custom server parameters to the API with retries. If the GW1000/GW1100 cannot be
        contacted a GW1000IOError will have been raised by send_cmd_with_retries() which will be passed through by
        get_custom_params(). Any code calling set_custom_params() should be prepared to handle this exception.
        """

        payload = bytearray(
            chr(len(custom_server_id)) + custom_server_id + chr(len(custom_password)) + custom_password + chr(
                len(custom_host)) + custom_host + chr(int(int(custom_port) / 256)) + chr(
                int(int(custom_port) % 256)) + chr(int(int(custom_interval) / 256)) + chr(
                int(int(custom_interval) % 256)) + chr(int(custom_type)) + chr(int(custom_enabled)), 'latin-1')
        self.logger.debug(f"Customized Server: payload={payload}")
        return self.send_cmd_with_retries('CMD_WRITE_CUSTOMIZED', payload)

    def get_usr_path(self):
        """Get user defined custom path.

        Sends the API command to obtain the device user defined custom path with retries. If the device cannot be contacted a GWIOError will
        have been raised by send_cmd_with_retries() which will be passed through by get_usr_path(). Any code calling get_usr_path() should
        be prepared to handle this exception.
        """

        # get the validated API response
        response = self.send_cmd_with_retries('CMD_READ_USR_PATH')
        # now return the parsed response
        return self.parser.parse_read_usr_path(response)

    def set_usr_path(self, custom_ecowitt_path, custom_wu_path):
        """
        Get GW1000/GW1100 user defined custom path.

        Sends the command to set the GW1000/GW1100 user defined custom path to the API with retries. If the GW1000/GW1100 cannot be
        contacted a GW1000IOError will have been raised by send_cmd_with_retries() which will be passed through by
        set_usr_path(). Any code calling set_usr_path() should be prepared to handle this exception.
        """
        self.logger.debug(f"set_usr_path: set user path called with custom_ecowitt_path={custom_ecowitt_path} and custom_wu_path={custom_wu_path}")

        payload = bytearray()
        payload.extend(int_to_bytes(len(custom_ecowitt_path), 1))
        payload.extend(str.encode(custom_ecowitt_path))
        payload.extend(int_to_bytes(len(custom_wu_path), 1))
        payload.extend(str.encode(custom_wu_path))
        self.logger.debug(f"Customized Path: payload={payload}")
        return self.send_cmd_with_retries('CMD_WRITE_USR_PATH', payload)

    def get_mac_address(self):
        """Get device MAC address.

        Sends the API command to obtain the device MAC address with retries. If the device cannot be contacted a GWIOError will have
        been raised by send_cmd_with_retries() which will be passed through by get_mac_address(). Any code calling get_mac_address() should be
        prepared to handle this exception.
        """

        # get the validated API response
        response = self.send_cmd_with_retries('CMD_READ_STATION_MAC')
        # now return the parsed response
        return self.parser.parse_read_station_mac(response)

    def get_firmware_version(self):
        """Get device firmware version.

        Sends the API command to obtain device firmware version with retries. If the device cannot be contacted a GWIOError will have
        been raised by send_cmd_with_retries() which will be passed through by get_firmware_version(). Any code calling get_firmware_version()
        should be prepared to handle this exception.
        """

        # get the validated API response
        response = self.send_cmd_with_retries('CMD_READ_FIRMWARE_VERSION')
        # now return the parsed response
        return self.parser.parse_read_firmware_version(response)

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
        """Get sensor ID data.

        Sends the API command to obtain sensor ID data from the device with retries. If the device cannot be contacted re-discovery is
        attempted. If rediscovery is successful the command is tried again otherwise the lost contact timestamp is set and the exception
        raised. Any code that calls this method should be prepared to handle a GWIOError exception.
        """

        # send the API command to obtain sensor ID data from the device, be prepared to catch the exception raised if the device cannot be contacted
        try:
            # get the validated API response
            response = self.send_cmd_with_retries('CMD_READ_SENSOR_ID_NEW')
        except GatewayIOError:
            # there was a problem contacting the device, it could be it has changed IP address so attempt to rediscover
            if not self.rediscover():
                # we could not re-discover so raise the exception
                raise
            else:
                # we did rediscover successfully so try again, if it fails we get another GWIOError exception which will be raised
                response = self.send_cmd_with_retries('CMD_READ_SENSOR_ID_NEW')
        # if we made it here we have a validated response so return it
        return response

    def get_current_sensor_state(self):
        """Get parsed current sensor state data."""

        # first get the current sensor state data
        current_sensor_data = self.get_sensor_id()
        # now update our Sensors object with the current data
        self.sensors.set_sensor_id_data(current_sensor_data)
        # and return the parsed
        return self.sensors.battery_and_signal_data

    def get_mulch_offset(self):
        """Get multichannel temperature and humidity offset data.

        Sends the API command to obtain the multichannel temperature and humidity offset data with retries. If the device cannot be
        contacted a GWIOError will have been raised by send_cmd_with_retries() which will be passed through by
        get_mulch_offset(). Any code calling get_mulch_offset() should be prepared to handle this exception.
        """

        # get the validated API response
        response = self.send_cmd_with_retries('CMD_GET_MulCH_OFFSET')
        # now return the parsed response
        return self.parser.parse_get_mulch_offset(response)

    def get_mulch_t_offset(self):
        """Get multichannel temperature (WN34) offset data.

        Sends the API command to obtain the multichannel temperature (WN34) offset data with retries. If the device cannot be contacted a
        GWIOError will have been raised by send_cmd_with_retries() which will be passed through by get_mulch_t_offset(). Any code calling
        get_mulch_t_offset() should be prepared to handle this exception.
        """

        # get the validated API response
        response = self.send_cmd_with_retries('CMD_GET_MulCH_T_OFFSET')
        # now return the parsed response
        return self.parser.parse_get_mulch_t_offset(response)

    def get_pm25_offset(self):
        """Get PM2.5 offset data.

        Sends the API command to obtain the PM2.5 sensor offset data with retries. If the device cannot be contacted a GWIOError will have
        been raised by send_cmd_with_retries() which will be passed through by get_pm25_offset(). Any code calling get_pm25_offset() should be
        prepared to handle this exception.
        """

        # get the validated API response
        response = self.send_cmd_with_retries('CMD_GET_PM25_OFFSET')
        # now return the parsed response
        return self.parser.parse_get_pm25_offset(response)

    def get_calibration_coefficient(self):
        """Get calibration coefficient data.

        Sends the API command to obtain the calibration coefficient data with retries. If the device cannot be contacted a GWIOError will
        have been raised by send_cmd_with_retries() which will be passed through by get_calibration_coefficient(). Any code calling
        get_calibration_coefficient() should be prepared to handle this exception.
        """

        # get the validated API response
        response = self.send_cmd_with_retries('CMD_READ_GAIN')
        # now return the parsed response
        return self.parser.parse_read_gain(response)

    def get_soil_calibration(self):
        """Get soil moisture sensor calibration data.

        Sends the API command to obtain the soil moisture sensor calibration data with retries. If the device cannot be contacted a
        GWIOError will have been raised by send_cmd_with_retries() which will be passed through by get_soil_calibration(). Any code calling
        get_soil_calibration() should be prepared to handle this exception.
        """

        # get the validated API response
        response = self.send_cmd_with_retries('CMD_GET_SOILHUMIAD')
        # now return the parsed response
        return self.parser.parse_get_soilhumiad(response)

    def get_offset_calibration(self):
        """Get offset calibration data.

        Sends the API command to obtain the offset calibration data with retries. If the device cannot be contacted a GWIOError will have
        been raised by send_cmd_with_retries() which will be passed through by get_offset_calibration(). Any code calling
        get_offset_calibration() should be prepared to handle this exception.
        """

        # get the validated API response
        response = self.send_cmd_with_retries('CMD_READ_CALIBRATION')
        # now return the parsed response
        return self.parser.parse_read_calibration(response)

    def get_co2_offset(self):
        """Get WH45 CO2, PM10 and PM2.5 offset data.

        Sends the API command to obtain the WH45 CO2, PM10 and PM2.5 sensor offset data with retries. If the device cannot be contacted a
        GWIOError will have been raised by send_cmd_with_retries() which will be passed through by get_co2_offset(). Any code calling
        get_co2_offset() should be prepared to handle this exception.
        """

        # get the validated API response
        response = self.send_cmd_with_retries('CMD_GET_CO2_OFFSET')
        # now return the parsed response
        return self.parser.parse_get_co2_offset(response)

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

    def read_rain(self) -> dict:
        """Get traditional gauge and piezo gauge rain data.

        Sends the API command to obtain the traditional gauge and piezo gauge rain data with retries. If the device cannot be contacted a
        GWIOError will have been raised by send_cmd_with_retries() which will be passed through by get_piezo_rain_(). Any code calling
        get_piezo_rain_() should be prepared to handle this exception.
        """

        # get the validated API response
        response = self.send_cmd_with_retries('CMD_READ_RAIN')
        # now return the parsed response
        return self.parser.parse_read_rain(response)

    def send_cmd_with_retries(self, cmd: str, payload: bytes = b'') -> bytes:
        """Send an API command to the device with retries and return the response.

        Send a command to the device and obtain the response. If the response is valid return the response. If the response is invalid
        an appropriate exception is raised and the command resent up to self.max_tries times after which the value None is returned.

        cmd: A string containing a valid API command,
             eg: 'CMD_READ_FIRMWARE_VERSION'
        payload: The data to be sent with the API command, byte string.

        Returns the response as a byte string or the value None.
        """

        # construct the message packet
        packet = self.build_cmd_packet(cmd, payload)
        response = None
        # attempt to send up to 'self.max_tries' times
        for attempt in range(self.max_tries):
            # wrap in  try..except so we can catch any errors
            try:
                response = self.send_cmd(packet)
            except socket.timeout as e:
                # a socket timeout occurred, log it
                self.logger.debug(f"Failed to obtain response to attempt {attempt + 1} to send command '{cmd}': {e}")
            except Exception as e:
                # an exception was encountered, log it
                self.logger.debug(f"Failed attempt {attempt + 1} to send command '{cmd}':{e!r}")
            else:
                # check the response is valid
                try:
                    self.check_response(response, self.API_COMMANDS[cmd])
                except InvalidChecksum as e:
                    # the response was not valid, log it and attempt again if we haven't had too many attempts already
                    self.logger.debug(f"Invalid response to attempt {attempt + 1} to send command '{cmd}':{e}")
                except UnknownApiCommand:
                    # most likely we have encountered a device that does not understand the command, possibly due to an old or
                    # outdated firmware version, raise the exception for our caller to deal with
                    raise
                except Exception as e:
                    # Some other error occurred in check_response(), perhaps the response was malformed. Log the stack trace but continue.
                    self.logger.error(f"Unexpected exception occurred while checking response to attempt {attempt + 1} to send command '{cmd}':{e}")
                else:
                    # our response is valid so return it
                    return response
            # sleep before our next attempt, but skip the sleep if we have just made our last attempt
            if attempt < self.max_tries - 1:
                time.sleep(self.retry_wait)
        # if we made it here we failed after self.max_tries attempts first log it
        _msg = f"Failed to obtain response to command '{cmd}' after {self.max_tries} attempts"
        if response is not None or self.log_failures:
            self.logger.error(_msg)
        # then finally, raise a GWIOError exception
        raise GatewayIOError(_msg)

    def build_cmd_packet(self, cmd: str, payload: bytes = b'') -> bytes:
        """Construct an API command packet.

        An API command packet looks like: fixed header, command, size, data 1, data 2...data n, checksum
        where:
            fixed header is 2 bytes = 0xFFFF
            command is a 1 byte API command code
            size is 1 byte being the number of bytes of command to checksum
            data 1, data 2 ... data n is the data being transmitted and is n bytes long
            checksum is a byte checksum of command + size + data 1 + data 2 ... + data n

        cmd:     A string containing a valid API command,  eg: 'CMD_READ_FIRMWARE_VERSION'
        payload: The data to be sent with the API command, byte string.

        Returns an API command packet as a bytestring.
        """

        # calculate size
        try:
            size = len(self.API_COMMANDS[cmd]) + 1 + len(payload) + 1
        except KeyError:
            raise UnknownApiCommand(f"Unknown API command '{cmd}'")
        # construct the portion of the message for which the checksum is calculated
        body = b''.join([self.API_COMMANDS[cmd], struct.pack('B', size), payload])
        # calculate the checksum
        checksum = self.calc_checksum(body)
        # return the constructed message packet
        return b''.join([self.HEADER, body, struct.pack('B', checksum)])

    def send_cmd(self, packet: bytes) -> bytes:
        """Send a command to the API and return the response.

        Send a command to the API and return the response. Socket related errors are trapped and raised, code calling send_cmd should be
        prepared to handle such exceptions.

        cmd: A valid API command

        Returns the response as a byte string.
        """

        # create a socket object for sending api_commands and broadcasting to the network, would normally do this using a with statement but
        # with statement support for socket.socket did not appear until python 3.
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        # set the socket timeout
        s.settimeout(self.socket_timeout)
        # wrap our connect in a try..except, so we can catch any socket related exceptions
        try:
            s.connect((self.ip_address, self.port))
            # self.logger.debug(f"Sending packet '{bytes_to_hex(packet)}' to {self.ip_address.decode()}:{self.port}")
            s.sendall(packet)
            # obtain the response, we assume here the response will be less than 1024 characters
            response = s.recv(1024)
            self.logger.debug(f"Received response '{bytes_to_hex(response)}'")
            return response
        except socket.error as e:
            # we received a socket error, raise it
            self.logger.warning(f"Socket Error {e!r} occurred.")
            raise
        except Exception as e:
            # we received a socket error, raise it
            self.logger.warning(f"Error {e!r} occurred.")
            raise
        finally:
            # make sure we close our socket
            s.close()

    def send_cmd_1(self, packet: bytes) -> bytes:
        """Send a command to the API and return the response.

        Send a command to the API and return the response. Socket related errors are trapped and raised, code calling send_cmd should be
        prepared to handle such exceptions.

        cmd: A valid API command

        Returns the response as a byte string.
        """

        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(self.socket_timeout)
        s.connect((self.ip_address, self.port))

        # keep track of connection status
        self.socket_connected = True
        self.logger.debug("connected to server")

        while True:
            # attempt to send and receive wave, otherwise reconnect
            try:
                s.sendall(packet)
                response = s.recv(1024)
                self.logger.debug(f"Received response '{bytes_to_hex(response)}'")
                return response
            except socket.error:
                # set connection status and recreate socket
                self.socket_connected = False
                s = socket.socket()
                self.logger.debug("connection lost... reconnecting")
                while not self.socket_connected:
                    # attempt to reconnect, otherwise sleep for 2 seconds
                    try:
                        s.connect((self.ip_address, self.port))
                        self.socket_connected = True
                        self.logger.debug("re-connection successful")
                    except socket.error:
                        time.sleep(2)
            finally:
                s.close()

    def check_response(self, response: bytes, cmd_code: bytes) -> None:
        """Check the validity of an API response.

        Checks the validity of an API response. Two checks are performed:

        1.  the third byte of the response is the same as the command code used in the API call
        2.  the calculated checksum of the data in the response matches the checksum byte in the response

        If any check fails an appropriate exception is raised, if all checks pass the method exits without raising an exception.

        There are three likely scenarios:
        1. all checks pass, in which case the method returns with no value and no exception raised
        2. checksum check passes but command code check fails. This is most likely due to the device not understanding the command, possibly
        due to an old or outdated firmware version. An UnknownApiCommand exception is raised.
        3. checksum check fails. An InvalidChecksum exception is raised.

        response: Response received from the API call. Byte string.
        cmd_code: Command code sent to the API. Byte string of length one.
        """

        # first check the checksum is valid
        calc_checksum = self.calc_checksum(response[2:-1])
        resp_checksum = response[-1]
        if calc_checksum == resp_checksum:
            # checksum check passed, now check the response command code by checkin the 3rd byte of the response matches the command code
            # that was issued
            if response[2] == byte_to_int(cmd_code):
                # we have a valid command code in the response, so the response is valid and all we need do is return
                return
            else:
                # command code check failed, since we have a valid checksum this is most likely due to the device not understanding
                # the command, possibly due to an old or outdated firmware version. Raise an UnknownApiCommand exception.
                exp_int = byte_to_int(cmd_code)
                resp_int = response[2]
                _msg = "Unknown command code in API response. Expected '%s' (0x%s), received '%s' (0x%s)." % (exp_int, "{:02X}".format(exp_int), resp_int, "{:02X}".format(resp_int))
                raise UnknownApiCommand(_msg)
        else:
            # checksum check failed, raise an InvalidChecksum exception
            _msg = "Invalid checksum in API response. Expected '%s' (0x%s), received '%s' (0x%s)." % (calc_checksum, "{:02X}".format(calc_checksum), resp_checksum, "{:02X}".format(resp_checksum))
            raise InvalidChecksum(_msg)

    @staticmethod
    def calc_checksum(data: bytes) -> int:
        """Calculate the checksum for an API call or response.

        The checksum used in an API response is simply the LSB of the sum of the command, size and data bytes. The fixed header and checksum
        bytes are excluded.

        data: The data on which the checksum is to be calculated. Byte string.

        Returns the checksum as an integer.
        """

        checksum = sum(data)
        # we are only interested in the least significant byte
        return checksum % 256

    def rediscover(self) -> bool:
        """Attempt to rediscover a lost device.

        Use UDP broadcast to discover a device that may have changed to a new IP or contact has otherwise been lost. We should not be
        re-discovering a device for which the user specified an IP, only for those for which we discovered the IP address on startup. If a
        device is discovered then change my ip_address and port properties as necessary to use the device in the future. If the rediscovery
        was successful return True otherwise return False.
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
                    device_list = self.discover()
                except socket.error as e:
                    # log the error
                    self.logger.debug(f"Failed attempt {attempt + 1} to detect any devices: {e} {type(e)}")
                else:
                    # did we find any devices
                    if len(device_list) > 0:
                        # we have at least one, log the fact as well as what we found
                        gw1000_str = ', '.join([':'.join(['%s:%d' % (d['ip_address'], d['port'])]) for d in device_list])
                        if len(device_list) == 1:
                            stem = f"{device_list[0]['model']} was"
                        else:
                            stem = "Multiple devices were"
                        self.logger.info(f"{stem} found at {gw1000_str}")
                        # iterate over each candidate checking their MAC address against my mac property. This way we know
                        # we will be connecting to the device we were previously using.
                        for device in device_list:
                            # do the MACs match, if so we have our old device and we can exit the loop
                            if self.mac == device['mac']:
                                self.ip_address = device['ip_address'].encode()
                                self.port = device['port']
                                break
                        else:
                            # we have exhausted the device list without a match so continue the outer loop if we have
                            # any attempts left
                            continue
                        # log the new IP address and port
                        self.logger.info(f"{self.model} at address {self.ip_address.decode()}:{self.port} will be used")
                        # return True indicating the re-discovery was successful
                        return True
                    else:
                        # did not discover any devices so log it
                        if self.log_failures:
                            self.logger.debug(f"Failed attempt {attempt + 1} to detect any devices")
            else:
                # we exhausted our attempts at re-discovery so log it
                if self.log_failures:
                    self.logger.info(f"Failed to detect original {self.model} after {self.max_tries} attempts")
        else:
            # an IP address was specified, so we cannot go searching, log it
            if self.log_failures:
                self.logger.debug("IP address specified in 'weewx.conf', re-discovery was not attempted")
        # if we made it here re-discovery was unsuccessful so return False
        return False

    def update_sensor_id_data(self) -> None:
        """Update the Sensors object with current sensor ID data."""

        # first get the current sensor ID data
        # TODO. This should return a value
        sensor_id_data = self.get_sensor_id()
        # now use the sensor ID data to re-initialise our sensors object
        self.sensors.set_sensor_id_data(sensor_id_data)


class GatewayDevice(object):
    """Class to directly interact with an Ecowitt gateway device.

    An Ecowitt gateway device can be interrogated directly in two ways:
    1. via the Ecowitt LAN/Wi-Fi Gateway API
    2. via a HTTP request

    The API uses a library of api_commands for reading and setting various parameters in the gateway device. The WeeWX Ecowitt gateway device
    driver uses a small subset of these api_commands to obtain sensor data which is presented to WeeWX via loop packets emitted by the driver. API
    communications is socket based and involves exchange of data that must be encoded/decoded at the byte/bit level.

    The HTTP request approach provides the ability to read various device and sensor data. It does not provide the ability to set and device
    parameters. HTTP request communications is HTTP GET based and involves the decoding of JSON format message data.

    A GatewayDevice object uses the following classes for interacting with the gateway device:

    - class GatewayApi.  Communicates directly with the gateway device via the gateway device API and obtains, validates and parses
                         gateway device responses.
    - class GatewayHttp. Communicates directly with the gateway device via HTTP requests to obtain and validates (as far as possible)
                         gateway device HTTP request responses.
    """

    # list of dicts of weather services that I know about
    services = [{'name': 'ecowitt_net_params', 'long_name': 'Ecowitt.net'},
                {'name': 'wunderground_params', 'long_name': 'Wunderground'},
                {'name': 'weathercloud_params', 'long_name': 'Weathercloud'},
                {'name': 'wow_params', 'long_name': 'Weather Observations Website'},
                {'name': 'custom_params', 'long_name': 'Customized'}]

    def __init__(self,
                 ip_address=None,
                 port=None,
                 broadcast_address=None,
                 broadcast_port=None,
                 debug=None,
                 plugin_instance=None):
        """Initialise a GatewayDevice object."""

        # get instance
        self._plugin_instance = plugin_instance
        self.logger = self._plugin_instance.logger
        
        # get interface config
        self.interface_config = self._plugin_instance.interface_config

        # get a GatewayApi object to handle the interaction with the API
        self.api = GatewayApi(ip_address=ip_address,
                              port=port,
                              broadcast_address=broadcast_address,
                              broadcast_port=broadcast_port,
                              debug=debug,
                              plugin_instance=plugin_instance)

        # start off logging failures
        self.log_failures = True

    @property
    def ip_address(self):
        """The gateway device IP address."""

        return self.api.ip_address

    @property
    def port(self):
        """The gateway device port number."""

        return self.api.port

    @property
    def model(self):
        """Gateway device model."""

        return self.api.model

    @property
    def livedata(self):
        """Gateway device live data."""

        return self.api.get_livedata()

    @property
    def raindata(self):
        """Gateway device traditional rain gauge data."""

        return self.api.read_raindata()

    @property
    def system_params(self):
        """Gateway device system parameters."""

        return self.api.get_system_params()

    @property
    def ecowitt_net_params(self):
        """Gateway device Ecowitt.net parameters."""

        return self.api.get_ecowitt_net_params()

    @property
    def wunderground_params(self):
        """Gateway device Weather Underground parameters."""

        return self.api.get_wunderground_params()

    @property
    def weathercloud_params(self):
        """Gateway device Weathercloud parameters."""

        return self.api.get_weathercloud_params()

    @property
    def wow_params(self):
        """Gateway device Weather Observations Website parameters."""

        return self.api.get_wow_params()

    @property
    def custom_params(self):
        """Gateway device custom server parameters."""

        return self.api.get_custom_params()

    @property
    def usr_path(self):
        """Gateway device user defined custom path parameters."""

        return self.api.get_usr_path()

    @property
    def mac_address(self):
        """Gateway device MAC address."""

        return self.api.get_mac_address()

    @property
    def firmware_version(self):
        """Gateway device firmware version."""

        return self.api.get_firmware_version()

    @property
    def sensor_id(self):
        """Gateway device sensor ID data."""

        return self.api.get_sensor_id()

    @property
    def mulch_offset(self):
        """Gateway device multichannel temperature and humidity offset data."""

        return self.api.get_mulch_offset()

    @property
    def mulch_t_offset(self):
        """Gateway device multichannel temperature (WN34) offset data."""

        return self.api.get_mulch_t_offset()

    @property
    def pm25_offset(self):
        """Gateway device PM2.5 offset data."""

        return self.api.get_pm25_offset()

    @property
    def calibration_coefficient(self):
        """Gateway device calibration coefficient data."""

        return self.api.get_calibration_coefficient()

    @property
    def soil_calibration(self):
        """Gateway device soil calibration data."""

        return self.api.get_soil_calibration()

    @property
    def offset_calibration(self):
        """Gateway device offset calibration data."""

        return self.api.get_offset_calibration()

    @property
    def co2_offset(self):
        """Gateway device CO2 offset data."""

        return self.api.get_co2_offset()

    @property
    def rain(self):
        """Gateway device traditional gauge and piezo gauge rain data."""

        return self.api.read_rain()

    @property
    def sensor_state(self):
        """Sensor battery state and signal level data."""

        return self.api.get_current_sensor_state()

    @property
    def discovered_devices(self):
        """List of discovered gateway devices.

        Each list element is a dict keyed by 'ip_address', 'port', 'model', 'mac' and 'ssid'."""

        return self.api.discover()

    @property
    def firmware_update_available(self) -> bool:
        """Whether a device firmware update is available or not.

        Return True if a device firmware update is available or False otherwise."""

        # version = self.http.get_version()
        # if version is not None and 'newVersion' in version:
        #     return True if version['newVersion'] == '1' else False
        # return False

        return self.check_firmware_update()[0]

    @property
    def calibration(self):
        """Device device calibration data."""

        # obtain the calibration data via the API
        parsed_cal_coeff = self.api.get_calibration_coefficient()
        # obtain the offset calibration data via the API
        parsed_offset = self.api.get_offset_calibration()
        # update our parsed gain data with the parsed offset calibration data
        parsed_cal_coeff.update(parsed_offset)
        # return the parsed data
        return parsed_cal_coeff

    @property
    def ws90_firmware_version(self):
        """Provide the WH90 firmware version.

        Return the WS90 installed firmware version. If no WS90 is available the
        value None is returned.
        """

        # sensors = self.http.get_sensors_info()
        # for sensor in sensors:
        #     if sensor.get('img') == 'wh90':
        #         return sensor.get('version', 'not available')
        return None

    def reboot(self):
        """Reboot the GW1000/GW1100."""

        response = self.api.set_reboot()
        return 'SUCCESS' if response[4] == 0 else 'FAIL'

    def reset(self):
        """Reset the GW1000/GW1100."""

        response = self.api.set_reset()
        return 'SUCCESS' if response[4] == 0 else 'FAIL'

    def do_firmware_update(self):
        """Update the GW1000/GW1100 firmware."""

        response = self.api.set_firmware_upgrade()
        return 'SUCCESS' if response[4] == 0 else 'FAIL'

    def set_usr_path(self, custom_ecowitt_path, custom_wu_path) -> str:
        """Set the customized path.

        current is read to determine, whether writing new configuration is needed
        """

        current_usr_path = self.usr_path
        _ecowitt_path = current_usr_path['ecowitt_path']
        _wu_path = current_usr_path['wu_path']

        self.logger.debug(f"To be set customized path: Ecowitt: current='{_ecowitt_path}' vs. new='{custom_ecowitt_path}' and WU: current='{_wu_path}' vs. new='{custom_wu_path}'")

        if not (_ecowitt_path == custom_ecowitt_path and _wu_path == custom_wu_path):
            self.logger.debug(f"Need to set customized path: Ecowitt: current='{_ecowitt_path}' vs. new='{custom_ecowitt_path}' and WU: current='{_wu_path}' vs. new='{custom_wu_path}'")
            response = self.api.set_usr_path(custom_ecowitt_path, custom_wu_path)
            result = 'SUCCESS' if response[4] == 0 else 'FAIL'
        else:
            self.logger.debug(f"Customized Path settings already correct; No need to write it")
            result = 'NO NEED'
        return result

    def set_custom_params(self, custom_server_id, custom_password, custom_host, custom_port, custom_interval, custom_type, custom_enabled) -> str:
        """
        Set the customized parameters.

        current configuration is read to determine, whether writing of new configuration is needed
        """

        current_custom_params = self.custom_params
        new_custom_params = {'server id': custom_server_id, 'password': custom_password, 'server': custom_host, 'port': custom_port, 'interval': custom_interval, 'protocol type': ['Ecowitt', 'WU'][int(custom_type)], 'active': bool(int(custom_enabled))}

        if new_custom_params.items() <= current_custom_params.items():
            self.logger.debug(f"Customized Server settings already correct; No need to do it again")
            result = 'NO NEED'
        else:
            self.logger.debug(f"Request to set customized server: current setting={current_custom_params}")
            self.logger.debug(f"Request to set customized server:     new setting={new_custom_params}")
            response = self.api.set_custom_params(custom_server_id, custom_password, custom_host, custom_port, custom_interval, custom_type, custom_enabled)
            result = 'SUCCESS' if response[4] == 0 else 'FAIL'
        return result

    def check_firmware_update(self) -> tuple:
        """
        Check if firmware update is available
        """

        # firmware update url
        FW_UPDATE_URL = 'http://download.ecowitt.net/down/filewave?v=FirwaveReadme.txt'.replace("\"", "")

        fw_info = requests.get(FW_UPDATE_URL)
        self.logger.debug(f"check_firmware_update: getting firmware update info from {FW_UPDATE_URL} results in status={fw_info.status_code}")

        if fw_info.status_code == 200:
            # get current firmware version
            current_firmware = self.firmware_version

            model = "unknown"
            for i in self.interface_config.known_models:
                if i in current_firmware.upper():
                    model = i

            # establish configparser
            fw_update_info = configparser.ConfigParser(allow_no_value=True, strict=False)
            # read response text
            fw_update_info.read_string(fw_info.text)

            # extract information for given model
            latest_firmware = fw_update_info.get(model, "VER", fallback="unknown")

            if ver_str_to_num(latest_firmware) and ver_str_to_num(current_firmware) and (ver_str_to_num(latest_firmware) > ver_str_to_num(current_firmware)):
                remote_firmware_notes = fw_update_info.get(model, "NOTES", fallback="")
                if ';' in remote_firmware_notes:
                    remote_firmware_notes = remote_firmware_notes.split(";")
                else:
                    remote_firmware_notes = [remote_firmware_notes]
                self.logger.debug(f"remote_firmware_notes={remote_firmware_notes}")
                return True, latest_firmware, remote_firmware_notes
            else:
                return False, latest_firmware, []


# ============================================================================
#                        Gateway TCP/ECOWITT classes
# ============================================================================


class GatewayTcpDriver(Gateway):

    def __init__(self, tcp_server_address, tcp_server_port, data_cycle, gateway_address, plugin_instance):
        """Initialise an Ecowitt Gateway API driver object."""

        # init instance
        self._plugin_instance = plugin_instance
        self.logger = self._plugin_instance.logger

        # get interface config
        self.interface_config = self._plugin_instance.interface_config

        # log the relevant settings/parameters we are using
        self.logger.debug("Starting GatewayTcpDriver")
        self.debug = DebugOptions()

        # now initialize my superclasses
        super().__init__(data_cycle, self.debug, plugin_instance)

        # log all found sensors since beginning of plugin as a set
        self.sensors = []

        # log sensors, that were missed with count of cycles
        self.sensors_missed = {}

        # get ECOWITT client
        self.client = GatewayTcpClient(tcp_server_address=tcp_server_address,
                                       tcp_server_port=tcp_server_port,
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

                client_ip = queue_data.get('client_ip')

                if client_ip and client_ip == self.ip_selected_gateway:

                    self.client.sensors.update_sensor_data(queue_data)

                    # put timestamp of now to packet
                    packet = {'timestamp': int(time.time() + 0.5)}

                    if 'datetime' not in queue_data:
                        packet['datetime'] = datetime.now().replace(microsecond=0)

                    # if not already determined, determine which cumulative rain field will be used to determine the per period rain field
                    if not self.rain_mapping_confirmed:
                        self.get_cumulative_rain_field(queue_data)

                    # get the rainfall for this period from total
                    self.calculate_rain(queue_data)

                    # get the lightning strike count for this period from total
                    self.calculate_lightning_count(queue_data)

                    # add calculated data to queue_data
                    self.add_calculated_data(queue_data)

                    # add battery warning data field and log entry if enabled
                    if self.interface_config.show_sensor_warning:
                        self.check_battery(queue_data, self.client.sensors.battery_description_data)

                    # add sensor warning data field and log entry if enabled
                    if self.interface_config.show_sensor_warning:
                        self.check_sensors(queue_data, self.client.sensors.connected_sensors)

                    # add the queue_data to the empty packet
                    packet.update(queue_data)

                    # log the packet if necessary, there are several debug settings that may require this, start from the highest (most encompassing) and work to the lowest (least encompassing)
                    if self.debug.loop:
                        self.logger.info(f"TCP. genLoopPackets: packet={natural_sort_dict(packet)}")
                    # yield the loop packet
                    yield packet
                # else:
                    # self.logger.debug(f"TCP. genLoopPackets: Received message was from client_ip={client_ip} and therefore not from selected  gateway={self.ip_selected_gateway}. Message will be ignored.")


class GatewayTcpClient:
    """
    Use the ecowitt protocol (not WU protocol) to capture data

    Capture data from devices that transmit using ecowitt protocol, such as the Fine Offset GW1000 bridge.

    * the bridge attempts to upload to rtpdate.ecowitt.net using HTTP GET
    * the protocol is called 'ecowitt' - it is similar to but incompatible with WU

    The ecowitt.net server responds with HTTP 200.  However, the payload varies depending on the configuration.
    When the device is not registered, the ecowitt.net server replies with:
        {"errcode":"40001","errmsg":"invalid passkey"}
    When the device has been registered, the ecowitt.net server replies with:
        {"errcode":"0","errmsg":"ok","UTC_offset":"-18000"}
    The device is a bit chatty - every 2 seconds it does a UDP broadcast.  Every 10 seconds it does an ARP broadcast.
    The UDP broadcast packet is 35 bytes.  It contains the MAC address, IP address, and SSID of the GW1000.  For example:
        FFFF120021807D5A3D537AC0A84C08AFC810475731303030422D5749464935333741B3
    which breaks down to:
        FFFF 120021 807D5A3D537A C0A84C08 AFC810 475731303030422D5749464935333741
             ------ ------------ -------- ------ --------------------------------
             ?      MAC          IPADDR   ?       G W 1 0 0 0 B - W I F I 5 3 7 A

    Here the IPADDR is 192.168.76.8, and the SSID uses the last 4 digits of the MAC address.

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

    def __init__(self, tcp_server_address, tcp_server_port, show_battery=False, debug_sensors=False, plugin_instance=None):

        # get instance
        self._plugin_instance = plugin_instance
        self.logger = self._plugin_instance.logger
        
        # get interface config
        self.interface_config = self._plugin_instance.interface_config

        self._server_thread = None
        self.collect_data = False

        # log the relevant settings/parameters we are using
        self.logger.debug("Starting GatewayTcpClient")

        # get tcp server object
        self.tcp_server = GatewayTcpClient.TCPServer(tcp_server_address, tcp_server_port, GatewayTcpClient.Handler, plugin_instance)

        # get a sensors object to handle sensor data
        self.sensors = GatewayTcpClient.Sensors(show_battery=show_battery, debug_sensors=debug_sensors, plugin_instance=plugin_instance)

    def run_server(self):
        self.tcp_server.run()

    def stop_server(self):
        self.tcp_server.stop()
        self.tcp_server = None

    def startup(self):
        """Start a thread that collects data from the Ecowitt Gateway TCP."""

        try:
            self._server_thread = threading.Thread(target=self.run_server)
            self._server_thread.setDaemon(True)
            _name = 'plugins.' + self._plugin_instance.get_fullname() + '.Gateway-TCP-Server'
            self._server_thread.setName(_name)
            self._server_thread.start()
        except threading.ThreadError:
            self.logger.error("Unable to launch GatewayApiClient thread")
            self._server_thread = None

    def shutdown(self):
        """Shut down the thread that collects data from the Ecowitt Gateway TCP."""

        if self._server_thread:
            self.collect_data = False
            self._server_thread.join(10)
            if self._server_thread.is_alive():
                self.logger.error("Unable to shut down GatewayApiClient thread")
            else:
                self.logger.info("GatewayApiClient thread has been terminated")
        self._server_thread = None

    @property
    def battery_desc(self):

        return self.sensors.battery_description_data

    @property
    def firmware_version(self):
        """Obtain the Ecowitt Gateway firmware version string."""

        return self.sensors.sensor_data['firmware']

    @property
    def model(self):
        """Obtain the model."""

        t = self.sensors.sensor_data['model']
        if t is not None:
            # we have a string, now do we have a know model in the string, if so return the model string
            for model in self.interface_config.known_models:
                if model in t.upper():
                    return model
            # we don't have a known model so return None
            return None
        else:
            # we have no string so return None
            return None

    @property
    def frequency(self):
        """Obtain the Ecowitt Gateway frequency."""

        return self.sensors.sensor_data['frequency']

    @property
    def device_id(self):
        """Generate device_id from passkey"""

        return str(hash(self.sensors.sensor_data['passkey']))[1:13]

    @property
    def gateway_ip(self):
        """Obtain the Ecowitt Gateway IP."""

        return self.sensors.sensor_data['client_ip']

    class TCPServer(socketserver.TCPServer):

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
            self.logger = logging.getLogger(__name__)
            # get the payload from an HTTP POST
            length = int(self.headers["Content-Length"])
            post_data = self.rfile.read(length).decode()
            self.reply()
            self.logger.debug(f"TCP. raw_post_data={obfuscate_passwords(str(post_data))}")
            data_dict = self.parse_post(post_data)
            data_dict.update({'client_ip': self.client_address[0]})
            self.logger.debug(f"TCP. data for queue: data_dict={data_dict}")
            GatewayTcpClient.data_queue.put(data_dict)

        def do_PUT(self):
            pass

        def do_GET(self):
            logger = logging.getLogger(__name__)
            # get the query string from an HTTP GET
            data = urlparse.urlparse(self.path).query
            logger.debug(f"GET: {obfuscate_passwords(data)}")
            self.reply()

        def parse_post(self, data):
            """Parse the ecowitt data and add it to a dictionary."""
            data_dict = {}
            line = data.splitlines()[0]
            if ':' in line and '&' in line:
                for item in line.split('&'):
                    key, value = item.split('=', 1)
                    try:
                        value = float(value)
                        if value % 1 == 0:
                            value = int(value)
                    except ValueError:
                        value = value.lstrip()
                    data_dict[key] = value
            self.logger.debug(f"TCP. parse_post data_dict={data_dict}")
            return self.convert_data(data_dict)

        def convert_data(self, data):
            """
            Harmonize key names and convert into metric units

            response_struct:
            'original_key': (decoder, 'new_key'); if new_key == None; ignore transfer to new dict
            """

            response_struct = {
                # Generic
                'client_ip': (None, 'client_ip'),
                'PASSKEY': (None, None),
                'stationtype': (None, 'firmware'),
                'freq': (None, 'frequency'),
                'model': (None, 'model'),
                'dateutc': (str_to_datetimeutc, 'datetime'),
                'runtime': (None, 'runtime'),
                'interval': (None, 'interval'),
                # Indoor
                'tempinf': (f_to_c, 'intemp'),
                'humidityin': (None, 'inhumid'),
                'baromrelin': (in_to_hpa, 'relbarometer'),
                'baromabsin': (in_to_hpa, 'absbarometer'),
                # WH 65 / WH24
                'tempf': (f_to_c, 'outtemp'),
                'humidity': (None, 'outhumid'),
                'winddir': (None, 'winddir'),
                'windspeedmph': (mph_to_ms, 'windspeed'),
                'windgustmph': (mph_to_ms, 'gustspeed'),
                'maxdailygust': (mph_to_ms, 'winddaymax'),
                'solarradiation': (solar, 'light'),
                'uv': (None, 'uvi'),
                'rainratein': (in_to_mm, 'rainrate'),
                'eventrainin': (in_to_mm, 'rainevent'),
                'hourlyrainin': (in_to_mm, 'rainhour'),
                'dailyrainin': (in_to_mm, 'rainday'),
                'weeklyrainin': (in_to_mm, 'rainweek'),
                'monthlyrainin': (in_to_mm, 'rainmonth'),
                'yearlyrainin': (in_to_mm, 'rainyear'),
                'totalrainin': (in_to_mm, 'raintotal'),
                'wh65batt': (None, 'wh65_batt'),
                # WH31
                'temp1f': (f_to_c, 'temp1'),
                'humidity1': (None, 'humid1'),
                'batt1': (None, 'wh31_ch1_batt'),
                'temp2f': (f_to_c, 'temp2'),
                'humidity2': (None, 'humid2'),
                'batt2': (None, 'wh31_ch2_batt'),
                'temp3f': (f_to_c, 'temp3'),
                'humidity3': (None, 'humid3'),
                'batt3': (None, 'wh31_ch3_batt'),
                'temp4f': (f_to_c, 'temp4'),
                'humidity4': (None, 'humid4'),
                'batt4': (None, 'wh31_ch4_batt'),
                'temp5f': (f_to_c, 'temp5'),
                'humidity5': (None, 'humid5'),
                'batt5': (None, 'wh31_ch5_batt'),
                'temp6f': (f_to_c, 'temp6'),
                'humidity6': (None, 'humid6'),
                'batt6': (None, 'wh31_ch6_batt'),
                'temp7f': (f_to_c, 'temp7'),
                'humidity7': (None, 'humid7'),
                'batt7': (None, 'wh31_ch7_batt'),
                'temp8f': (f_to_c, 'temp8'),
                'humidity8': (None, 'humid8'),
                'batt8': (None, 'wh31_ch8_batt'),
                # WN51
                'soilmoisture1': (None, 'soilmoist1'),
                'soilbatt1': (None, 'wh51_ch1_batt'),
                'soilmoisture2': (None, 'soilmoist2'),
                'soilbatt2': (None, 'wh51_ch2_batt'),
                'soilmoisture3': (None, 'soilmoist3'),
                'soilbatt3': (None, 'wh51_ch3_batt'),
                'soilmoisture4': (None, 'soilmoist4'),
                'soilbatt4': (None, 'wh51_ch4_batt'),
                'soilmoisture5': (None, 'soilmoist5'),
                'soilbatt5': (None, 'wh51_ch5_batt'),
                'soilmoisture6': (None, 'soilmoist6'),
                'soilbatt6': (None, 'wh51_ch6_batt'),
                'soilmoisture7': (None, 'soilmoist7'),
                'soilbatt7': (None, 'wh51_ch7_batt'),
                'soilmoisture8': (None, 'soilmoist8'),
                'soilbatt8': (None, 'wh51_ch8_batt'),
                # WH34
                'tf_ch1': (f_to_c, 'temp_tf_ch1'),
                'tf_ch2': (f_to_c, 'temp_tf_ch2'),
                'tf_ch3': (f_to_c, 'temp_tf_ch3'),
                'tf_ch4': (f_to_c, 'temp_tf_ch4'),
                'tf_ch5': (f_to_c, 'temp_tf_ch5'),
                'tf_ch6': (f_to_c, 'temp_tf_ch6'),
                'tf_ch7': (f_to_c, 'temp_tf_ch7'),
                'tf_ch8': (f_to_c, 'temp_tf_ch8'),
                # WH45
                'tf_co2': (f_to_c, 'temp17'),
                'humi_co2': (None, 'humid17'),
                'pm10_co2': (None, 'pm10'),
                'pm10_24h_co2': (None, 'pm10_24h_avg'),
                'pm25_co2': (None, 'pm255'),
                'pm25_24h_co2': (None, 'pm255_24h_avg'),
                'co2': (None, 'co2'),
                'co2_24h': (None, 'co2_24h_avg'),
                'co2_batt': (None, 'wh45_batt'),
                # WH41 / WH43
                'pm25_ch1': (None, 'pm251'),
                'pm25_avg_24h_ch1': (None, 'pm251_24h_avg'),
                'pm25batt1': (to_bool, 'pm251_batt'),
                'pm25_ch2': (None, 'pm252'),
                'pm25_avg_24h_ch2': (None, 'pm252_24h_avg'),
                'pm25batt2': (to_bool, 'pm252_batt'),
                'pm25_ch3': (None, 'pm253'),
                'pm25_avg_24h_ch3': (None, 'pm253_24h_avg'),
                'pm25batt3': (to_bool, 'pm253_batt'),
                'pm25_ch4': (None, 'pm254'),
                'pm25_avg_24h_ch4': (None, 'pm254_24h_avg'),
                'pm25batt4': (to_bool, 'pm254_batt'),
                # WH55
                'leak_ch1': (to_bool, 'leak_ch1'),
                'leak_ch2': (to_bool, 'leak_ch2'),
                'leak_ch3': (to_bool, 'leak_ch3'),
                'leak_ch4': (to_bool, 'leak_ch4'),
                'leakbatt1': (None, 'wh55_ch1_batt'),
                'leakbatt2': (None, 'wh55_ch2_batt'),
                'leakbatt3': (None, 'wh55_ch3_batt'),
                'leakbatt4': (None, 'wh55_ch4_batt'),
                # WH25
                'wh25batt': (to_bool, 'wh25_batt'),
                # WH26
                'wh26batt': (to_bool, 'wh26_batt'),
                # WH57
                'lightning_day': (None, 'lightning_num'),
                'lightning_distance': (None, 'lightning'),
                'lightning_time': (None, 'lightning_time'),
                # WH68
                'wh68batt': (to_float, 'wh68_batt'),
                # WH40
                'wh40batt': (to_float, 'wh40_batt'),
                # others
                'cloudf': (f_to_m, 'cloud_ceiling'),
                'indoortempf': (f_to_m, 'indoortemp'),
                'windchillf': (f_to_m, 'windchill'),
                'feelslikef': (f_to_m, 'feelslike'),
                'dewptf': (f_to_m, 'dewpt'),
                'heatindexf': (f_to_m, 'heatindex'),
                'baromin': (in_to_hpa, 'baromin'),
                'absbaro': (in_to_hpa, 'baromin'),
            }

            data_dict = {}
            for key in data:
                try:
                    decoder, field = response_struct[key]
                except KeyError:
                    self.logger.warning(f"Unknown key '{key}' with value '{data[key]}'detected. Try do decode remaining sensor data.")
                    pass
                else:
                    if field is None:
                        continue

                    if decoder:
                        data_dict[field] = decoder(data[key])
                    else:
                        data_dict[field] = data[key]
            self.logger.debug(f"TCP. convert_data data_dict={data_dict}")
            return data_dict

        @staticmethod
        def clean_data(data):
            """Delete unused keys"""

            _unused_keys = ['passkey', 'firmware', 'frequency', 'model', 'client_ip']

            for key in data:
                if key.lower() in _unused_keys:
                    data.pop(key)
            return data

    class Sensors(object):
        """Class to manage Ecowitt Gateway sensor ID data."""

        def __init__(self, show_battery=False, debug_sensors=False, plugin_instance=None):

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

        def update_sensor_data(self, data):
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
                batt_fn = GatewayTcpClient.sensor_ids[address].get('batt_fn')
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
#                        Gateway HTTP get request classes
# ============================================================================

# class GatewayHttpDriver(Gateway):
#     """Ecowitt Gateway driver class for HTTP get request.
#     """
#
#     def __init__(self,
#                  gateway_address=None,
#                  gateway_port=None,
#                  poll_interval=20,
#                  use_th32=False,
#                  plugin_instance=None):
#         """
#         Initialise an Ecowitt Gateway driver object.
#         """
#
#         # get instance
#         self._plugin_instance = plugin_instance
#         self.logger = self._plugin_instance.logger
#
#         # get data poll cycle
#         self.poll_interval = poll_interval
#
#         self.driver_alive = False
#
#         # now initialize my superclasses
#         super().__init__(self.poll_interval, self._plugin_instance)
#
#         # set the IP address property to the Ecowitt Gateway IP address
#         self.gateway_address = gateway_address
#
#         # set the port property from obtain the Ecowitt Gateway port from the config dict for port number we have a default value we can use, so if port is not specified use the default
#         self.gateway_port = gateway_port
#
#         # log the relevant settings/parameters we are using
#         self.logger.debug("Starting GatewayApiDriver")
#
#         # Is a WH32 in use. WH32 TH sensor can override/provide outdoor TH data to the Ecowitt Gateway. In terms of TH data the process is transparent
#         # and we do not need to know if a WH32 or other sensor is providing outdoor TH data but in terms of battery state we need to know so the
#         # battery state data can be reported against the correct sensor.
#         use_th32 = use_th32
#
#         # log all found sensors since beginning of plugin as a set
#         self.sensors = []
#
#         # log sensors, that were missed with count of cycles
#         self.sensors_missed = {}
#
#         # create an GatewayApiClient object to interact with the Ecowitt Gateway API
#         self.client = GatewayHttpClient(gateway_address=self.gateway_address,
#                                            gateway_port=self.gateway_port,
#                                            poll_interval=self.poll_interval,
#                                            use_th32=use_th32,
#                                            show_battery=self.show_battery,
#                                            debug_rain=self.debug_rain,
#                                            debug_wind=self.debug_wind,
#                                            debug_sensors=self.debug_sensors,
#                                            plugin_instance=self._plugin_instance)
#
#         self.logger.info(f'{self.client.station.model} address is {self.client.station.ip_address.decode()}:{self.client.station.port}')
#         self.logger.info(f'poll interval is {self.poll_interval} seconds')
#
#         self.driver_alive = True
#
#     def genLoopPackets(self):
#         """
#         Generator function that returns loop packets.
#
#         Run a continuous loop checking the GatewayApiClient queue for data. When data arrives map the raw data to a loop packet and yield the packet.
#         """
#
#         # generate loop packets forever
#         while self.driver_alive:
#             # wrap in a try to catch any instances where the queue is empty
#             try:
#                 # get any data from the collector queue
#                 queue_data = self.client.data_queue.get(True, 10)
#             except queue.Empty:
#                 # self.logger.debug("API. genLoopPackets: there was nothing in the queue so continue")
#                 # there was nothing in the queue so continue
#                 pass
#             else:
#                 # We received something in the queue, it will be one of three things:
#                 # 1. a dict containing sensor data
#                 # 2. an exception
#                 # 3. the value None signalling a serious error that means the Collector needs to shut down
#
#                 # if the data is of instance dict, it must have data
#                 if isinstance(queue_data, dict):
#                     self.logger.debug(f"API. genLoopPackets: queue_data={queue_data}")
#                     # Now start to create a loop packet.
#
#                     # put timestamp of now to packet
#                     packet = {'timestamp': int(time.time() + 0.5)}
#
#                     if 'datetime' in queue_data and isinstance(queue_data['datetime'], datetime):
#                         packet['datetime_utc'] = queue_data['datetime']
#                     else:
#                         # we don't have a datetime at utc so create one
#                         packet['datetime_utc'] = datetime.utcnow().replace(tzinfo=timezone.utc, microsecond=0)
#
#                     if self.debug_loop:
#                         self.logger.debug(f"Received {self.client.station.model} data (debug_loop): {datetime_to_string(packet['datetime_utc'])} {natural_sort_dict(queue_data)}")
#
#                     # if not already determined, determine which cumulative rain field will be used to determine the per period rain field
#                     if not self.rain_mapping_confirmed:
#                         self.get_cumulative_rain_field(queue_data)
#
#                     # get the rainfall for this period from total
#                     self.calculate_rain(queue_data)
#
#                     # get the lightning strike count for this period from total
#                     self.calculate_lightning_count(queue_data)
#
#                     # add calculated data to queue_data
#                     self.add_calculated_data(queue_data)
#
#                     # add sensor warning data field and log entry if enabled
#                     if self._plugin_instance.sensorwarning:
#                         self.check_sensors(queue_data)
#
#                     # add battery warning data field and log entry if enabled
#                     if self._plugin_instance.batterywarning:
#                         self.check_battery(queue_data)
#
#                     # add the queue_data to the empty packet
#                     packet.update(queue_data)
#
#                     # log the packet if necessary, there are several debug settings that may require this, start from the highest (most encompassing) and work to the lowest (least encompassing)
#                     if self.debug_loop:
#                         self.logger.info(f"API. genLoopPackets: Packet {datetime_to_string(packet['datetime_utc'])}: {natural_sort_dict(packet)}")
#                     # yield the loop packet
#                     yield packet
#                     # time.sleep(self.poll_interval)
#
#                 # if it's a tuple then it's a tuple with an exception and exception text
#                 elif isinstance(queue_data, BaseException):
#                     # We have an exception. The collector did not deem it serious enough to want to shutdown or it would have sent None instead. If it is anything else we log it and then raise it.
#
#                     # first extract our exception
#                     e = queue_data
#                     # and process it if we have something
#                     if e:
#                         # is it a GatewayError
#                         self.logger.error(f"Caught unexpected exception {e.__class__.__name__}: {e}")
#                         # then raise it
#                         raise e
#
#                 # if it's None then its a signal, the Collector needs to shutdown
#                 elif queue_data is None:
#                     # if debug_loop log what we received
#                     if self.debug_loop:
#                         self.logger.info("Received 'None'")
#                     # we received the signal to shutdown, so call closePort()
#                     self.closePort()
#                     # and raise an exception to cause the engine to shutdown
#                     raise GatewayIOError("GatewayApiClient needs to shutdown")
#                 # if it's none of the above (which it should never be) we don't know what to do with it so pass and wait for the next item in the queue
#
#     def check_battery(self, data):
#         """
#         Check if batteries states are critical, create log entry and add a separate field for battery warning.
#         """
#
#         # get battery data
#         raw_data = self.client.battery_desc
#         # init string to collect message
#         batterycheck = ''
#         # iterate over data to look for critical battery
#         for key in raw_data:
#             if raw_data[key] != 'OK':
#                 if batterycheck != '':
#                     batterycheck += ', '
#                 batterycheck += key
#         # check result, create log entry data field
#         if batterycheck != "":
#             data['battery_warning'] = 0
#             if not self.battery_warning:
#                 self.logger.warning(f"<WARNING> Battery level for sensor(s) {batterycheck} is critical - please swap battery")
#                 self.battery_warning = True
#                 data['battery_warning'] = 1
#         elif self.battery_warning:
#             self.logger.info("<OK> Battery level for all sensors is ok again")
#             self.battery_warning = False
#             data['battery_warning'] = 0
#
#     def check_sensors(self, data: dict, missing_count: int = 2):
#         """
#         Check if all know sensors are still connected, create log entry and add a separate field for sensor warning.
#         """
#
#         # get currently connected sensors
#         connected_sensors = self.client.sensors.connected_sensors
#         # self.logger.debug(f"check_sensors: connected_sensors={connected_sensors}")
#         # log all found sensors during runtime
#         self.sensors = list(set(self.sensors + connected_sensors))
#         # check if all sensors are still connected, create log entry data field
#         if set(connected_sensors) == set(self.sensors):
#             # self.logger.debug(f"check_sensors: All sensors are still connected!")
#             self.sensor_warning = False
#             data['sensor_warning'] = 0
#         else:
#             missing_sensors = list(set(self.sensors).difference(set(connected_sensors)))
#             self.update_missing_sensor_dict(missing_sensors)
#
#             blacklist = set()
#             for sensor in self.sensors_missed:
#                 if self.sensors_missed[sensor] >= missing_count:
#                     blacklist.add(sensor)
#
#             if blacklist:
#                 self.logger.error(f"API: check_sensors: The following sensors where lost (more than {missing_count} data cycles): {list(blacklist)}")
#                 self.sensor_warning = True
#                 data['sensor_warning'] = 1
#             else:
#                 self.sensor_warning = False
#                 data['sensor_warning'] = 0
#
#     def update_missing_sensor_dict(self, missing_sensors: list):
#         """
#         Get list of sensors, which were lost/missed in last data cycle and udpate missing_sensor_dict with count of missing cycles.
#         """
#
#         for sensor in missing_sensors:
#             if sensor not in self.sensors_missed:
#                 self.sensors_missed[sensor] = 1
#             else:
#                 self.sensors_missed[sensor] += 1
#
#         self.logger.debug(f"sensors_missed={self.sensors_missed}")
#
#     @property
#     def hardware_name(self):
#         """
#         Return the hardware name.
#
#         Use the device model from our Collector's Station object, but if this
#         is None use the driver name.
#         """
#
#         if self.client.station.model is not None:
#             return self.client.station.model
#
#     @property
#     def mac_address(self):
#         """
#         Return the Ecowitt Gateway MAC address.
#         """
#
#         return self.client.mac_address
#
#     @property
#     def firmware_version(self):
#         """
#         Return the Ecowitt Gateway firmware version string.
#         """
#
#         return self.client.firmware_version
#
#     @property
#     def sensor_id_data(self):
#         """
#         Return the Ecowitt Gateway sensor identification data.
#
#         The sensor ID data is available via the data property of the Collector objects' sensors property.
#         """
#
#         return self.client.sensors.data
#
#     def closePort(self):
#         """
#         Close down the driver port.
#         """
#
#         # in this case there is no port to close, just shutdown the collector
#         self.driver_alive = False


# class GatewayHttpClient:
#     """
#     Class to poll the Ecowitt Gateway API, decode and return data to the driver.
#     """
#
#     # map of sensor ids to short name, long name and battery byte decode function
#     sensor_ids = {
#         b'\x00': {'name': 'wh65', 'long_name': 'WH65', 'batt_fn': 'batt_binary'},
#         b'\x01': {'name': 'wh68', 'long_name': 'WH68', 'batt_fn': 'batt_volt'},
#         b'\x02': {'name': 'ws80', 'long_name': 'WS80', 'batt_fn': 'batt_volt'},
#         b'\x03': {'name': 'wh40', 'long_name': 'WH40', 'batt_fn': 'batt_binary'},
#         b'\x04': {'name': 'wh25', 'long_name': 'WH25', 'batt_fn': 'batt_binary'},
#         b'\x05': {'name': 'wh26', 'long_name': 'WH26', 'batt_fn': 'batt_binary'},
#         b'\x06': {'name': 'wh31_ch1', 'long_name': 'WH31 ch1', 'batt_fn': 'batt_binary'},
#         b'\x07': {'name': 'wh31_ch2', 'long_name': 'WH31 ch2', 'batt_fn': 'batt_binary'},
#         b'\x08': {'name': 'wh31_ch3', 'long_name': 'WH31 ch3', 'batt_fn': 'batt_binary'},
#         b'\x09': {'name': 'wh31_ch4', 'long_name': 'WH31 ch4', 'batt_fn': 'batt_binary'},
#         b'\x0a': {'name': 'wh31_ch5', 'long_name': 'WH31 ch5', 'batt_fn': 'batt_binary'},
#         b'\x0b': {'name': 'wh31_ch6', 'long_name': 'WH31 ch6', 'batt_fn': 'batt_binary'},
#         b'\x0c': {'name': 'wh31_ch7', 'long_name': 'WH31 ch7', 'batt_fn': 'batt_binary'},
#         b'\x0d': {'name': 'wh31_ch8', 'long_name': 'WH31 ch8', 'batt_fn': 'batt_binary'},
#         b'\x0e': {'name': 'wh51_ch1', 'long_name': 'WH51 ch1', 'batt_fn': 'batt_binary'},
#         b'\x0f': {'name': 'wh51_ch2', 'long_name': 'WH51 ch2', 'batt_fn': 'batt_binary'},
#         b'\x10': {'name': 'wh51_ch3', 'long_name': 'WH51 ch3', 'batt_fn': 'batt_binary'},
#         b'\x11': {'name': 'wh51_ch4', 'long_name': 'WH51 ch4', 'batt_fn': 'batt_binary'},
#         b'\x12': {'name': 'wh51_ch5', 'long_name': 'WH51 ch5', 'batt_fn': 'batt_binary'},
#         b'\x13': {'name': 'wh51_ch6', 'long_name': 'WH51 ch6', 'batt_fn': 'batt_binary'},
#         b'\x14': {'name': 'wh51_ch7', 'long_name': 'WH51 ch7', 'batt_fn': 'batt_binary'},
#         b'\x15': {'name': 'wh51_ch8', 'long_name': 'WH51 ch8', 'batt_fn': 'batt_binary'},
#         b'\x16': {'name': 'wh41_ch1', 'long_name': 'WH41 ch1', 'batt_fn': 'batt_int'},
#         b'\x17': {'name': 'wh41_ch2', 'long_name': 'WH41 ch2', 'batt_fn': 'batt_int'},
#         b'\x18': {'name': 'wh41_ch3', 'long_name': 'WH41 ch3', 'batt_fn': 'batt_int'},
#         b'\x19': {'name': 'wh41_ch4', 'long_name': 'WH41 ch4', 'batt_fn': 'batt_int'},
#         b'\x1a': {'name': 'wh57', 'long_name': 'WH57', 'batt_fn': 'batt_int'},
#         b'\x1b': {'name': 'wh55_ch1', 'long_name': 'WH55 ch1', 'batt_fn': 'batt_int'},
#         b'\x1c': {'name': 'wh55_ch2', 'long_name': 'WH55 ch2', 'batt_fn': 'batt_int'},
#         b'\x1d': {'name': 'wh55_ch3', 'long_name': 'WH55 ch3', 'batt_fn': 'batt_int'},
#         b'\x1e': {'name': 'wh55_ch4', 'long_name': 'WH55 ch4', 'batt_fn': 'batt_int'},
#         b'\x1f': {'name': 'wh34_ch1', 'long_name': 'WH34 ch1', 'batt_fn': 'batt_volt'},
#         b'\x20': {'name': 'wh34_ch2', 'long_name': 'WH34 ch2', 'batt_fn': 'batt_volt'},
#         b'\x21': {'name': 'wh34_ch3', 'long_name': 'WH34 ch3', 'batt_fn': 'batt_volt'},
#         b'\x22': {'name': 'wh34_ch4', 'long_name': 'WH34 ch4', 'batt_fn': 'batt_volt'},
#         b'\x23': {'name': 'wh34_ch5', 'long_name': 'WH34 ch5', 'batt_fn': 'batt_volt'},
#         b'\x24': {'name': 'wh34_ch6', 'long_name': 'WH34 ch6', 'batt_fn': 'batt_volt'},
#         b'\x25': {'name': 'wh34_ch7', 'long_name': 'WH34 ch7', 'batt_fn': 'batt_volt'},
#         b'\x26': {'name': 'wh34_ch8', 'long_name': 'WH34 ch8', 'batt_fn': 'batt_volt'},
#         b'\x27': {'name': 'wh45', 'long_name': 'WH45', 'batt_fn': 'batt_int'},
#         b'\x28': {'name': 'wh35_ch1', 'long_name': 'WH35 ch1', 'batt_fn': 'batt_volt'},
#         b'\x29': {'name': 'wh35_ch2', 'long_name': 'WH35 ch2', 'batt_fn': 'batt_volt'},
#         b'\x2a': {'name': 'wh35_ch3', 'long_name': 'WH35 ch3', 'batt_fn': 'batt_volt'},
#         b'\x2b': {'name': 'wh35_ch4', 'long_name': 'WH35 ch4', 'batt_fn': 'batt_volt'},
#         b'\x2c': {'name': 'wh35_ch5', 'long_name': 'WH35 ch5', 'batt_fn': 'batt_volt'},
#         b'\x2d': {'name': 'wh35_ch6', 'long_name': 'WH35 ch6', 'batt_fn': 'batt_volt'},
#         b'\x2e': {'name': 'wh35_ch7', 'long_name': 'WH35 ch7', 'batt_fn': 'batt_volt'},
#         b'\x2f': {'name': 'wh35_ch8', 'long_name': 'WH35 ch8', 'batt_fn': 'batt_volt'}
#     }
#
#     # create queue object
#     data_queue = queue.Queue()
#
#     def __init__(self,
#                  gateway_address=None,
#                  gateway_port=None,
#                  timeout=None,
#                  poll_interval=0,
#                  use_th32=False,
#                  show_battery=False,
#                  debug_rain=False,
#                  debug_wind=False,
#                  debug_sensors=False,
#                  plugin_instance=None):
#         """
#         Initialise class.
#         """
#
#         # handle plugin instance
#         self._plugin_instance = plugin_instance
#         self.logger = self._plugin_instance.logger
#
#         self.logger.debug("Init Gateway HTTP Client")
#
#         # interval between polls of the API, use a default
#         self.poll_interval = poll_interval
#
#         # are we using a th32 sensor
#         self.use_th32 = use_th32
#
#         timeout = 10
#
#         # get a station object to do the handle the interaction with the Ecowitt Gateway API
#         self.station = GatewayHttpClient.Station(gateway_address=gateway_address,
#                                                  gateway_port=gateway_port,
#                                                  timeout=timeout,
#                                                  plugin_instance=plugin_instance)
#
#         # Do we have a WH24 attached? First obtain our system parameters.
#         _sys_params = self.station.get_system_params()
#
#         # WH24 is indicated by the 6th byte being 0
#         is_wh24 = _sys_params[5] == 0
#
#         # get a parser object to parse any data from the station
#         self.parser = GatewayHttpClient.Parser(is_wh24=is_wh24,
#                                                debug_rain=debug_rain,
#                                                debug_wind=debug_wind,
#                                                plugin_instance=plugin_instance)
#
#         # get a sensors object to handle sensor ID data
#         self.sensors_obj = GatewayHttpClient.Sensors(show_battery=show_battery,
#                                                      debug_sensors=debug_sensors,
#                                                      plugin_instance=plugin_instance)
#
#         # we start off not collecting data, it will be turned on later when we are threaded
#         self.collect_data = False
#
#     def collect_sensor_data(self):
#         """
#         Collect sensor data by polling the API.
#
#         Loop forever waking periodically to see if it is time to quit or collect more data.
#         """
#
#         # initialise ts of last time API was polled
#         last_poll = 0
#         # collect data continuously while we are told to collect data
#         while self.collect_data:
#             # store the current time
#             now = time.time()
#             # is it time to poll?
#             if now - last_poll > self.poll_interval:
#                 # it is time to poll, wrap in a try..except in case we get a GatewayIOError exception
#                 try:
#                     queue_data = self.get_live_sensor_data()
#                 except GatewayIOError as e:
#                     # a GatewayIOError occurred, most likely because the Station object could not contact the Ecowitt Gateway
#                     # first up log the event, but only if we are logging failures
#                     self.logger.error('Unable to obtain live sensor data')
#                     # assign the GatewayIOError exception so it will be sent in the queue to our controlling object
#                     queue_data = e
#                 # put the queue data in the queue
#                 self.data_queue.put(queue_data)
#                 # debug log when we will next poll the API
#                 # self.logger.debug(f'Next update in {self.poll_interval} seconds')
#                 # reset the last poll ts
#                 last_poll = now
#             # sleep for a second and then see if its time to poll again
#             time.sleep(1)
#
#     def get_live_sensor_data(self):
#         """
#         Get all current sensor data.
#
#         Obtain live sensor data from the Ecowitt Gateway API then parse the API response to create a timestamped data dict keyed by internal
#         Ecowitt Gateway field name. Add current sensor battery state and signal level data to the data dict. If no data was obtained from the API the
#         value None is returned.
#         """
#
#         # obtain the raw data via the Ecowitt Gateway API, we may get a GatewayIOError exception, if we do let it bubble up (the raw data is
#         # the data returned from the Ecowitt Gateway inclusive of the fixed header, command, payload length, payload and checksum bytes)
#         raw_data = self.station.get_livedata()
#         # if we made it here our raw data was validated by checksum get a timestamp to use in case our data does not come with one
#         _timestamp = int(time.time())
#         # parse the raw data (the parsed data is a dict keyed by internal Ecowitt Gateway field names and containing the decoded raw sensor data)
#         parsed_data = self.parser.parse(raw_data, _timestamp)
#         # self.logger.debug(f"Parsed data: {parsed_data}")
#         # The parsed live data does not contain any sensor battery state or signal level data. The battery state and signal level data for each
#         # sensor can be obtained from the Ecowitt Gateway API via our Sensors object.
#         # first we need to update our Sensors object with current sensor ID data
#         self.update_sensor_id_data()
#         # now add any sensor battery state and signal level data to the parsed data
#         parsed_data.update(self.sensors_obj.battery_and_signal_data)
#         # self.logger.debug(f"Processed parsed data: {parsed_data}")
#         return parsed_data
#
#     def update_sensor_id_data(self):
#         """
#         Update the Sensors object with current sensor ID data.
#         """
#
#         # get the current sensor ID data
#         sensor_id_data = self.station.get_sensor_id()
#         # now use the sensor ID data to re-initialise our sensors object
#         self.sensors_obj.set_sensor_id_data(sensor_id_data)
#
#     class Station(object):
#         """
#         Class to interact directly with the Ecowitt Gateway API.
#
#         A Station object knows how to:
#         2.  send a command to the Ecowitt Gateway API
#         3.  receive a response from the Ecowitt Gateway API
#
#         A Station object needs an IP address and port as well as a network broadcast address and port.
#         """
#
#         # Ecowitt Gateway API commands
#         commands = ["get_version", "get_livedata_info", "get_ws_settings", "get_calibraion_data", "get_rain_totals",
#                 "get_device_info", "get_sensors_info", "get_network_info", "get_units_info", "get_cli_soilad",
#                 "get_cli_multiCh", "get_cli_pm25", "get_cli_co2", "get_piezo_rain"]
#
#         def __init__(self, ip_address=None, port=None, timeout: int = 10, plugin_instance=None):
#
#             # get instance
#             self._plugin_instance = plugin_instance
#             self.logger = self._plugin_instance.logger
#
#             self.host = ip_address
#             self.port = port
#             self.timeout = timeout
#
#             self._session = requests.Session()
#
#         def get_model_from_firmware(self, firmware_string):
#             """
#             Determine the device model from the firmware version.
#
#             To date Ecowitt Gateway firmware versions have included the device model in the firmware version string returned via the device
#             API. Whilst this is not guaranteed to be the case for future firmware releases, in the absence of any other direct means of
#             obtaining the device model number it is a useful means for determining the device model.
#
#             The check is a simple check to see if the model name is contained in the firmware version string returned by the device API.
#
#             If a known model is found in the firmware version string the model is returned as a string. None is returned if (1) the firmware
#             string is None or (2) a known model is not found in the firmware version string.
#             """
#
#             # do we have a firmware string
#             if firmware_string is not None:
#                 # we have a firmware string so look for a known model in the string and return the result
#                 return self.get_model(firmware_string)
#             else:
#                 # for some reason we have no firmware string, so return None
#                 return None
#
#         def get_model_from_ssid(self, ssid_string):
#             """
#             Determine the device model from the device SSID.
#
#             To date the Ecowitt gateway device SSID has included the device
#             model in the SSID returned via the device API. Whilst this is not
#             guaranteed to be the case for future firmware releases, in the
#             absence of any other direct means of obtaining the device model
#             number it is a useful means for determining the device model. This
#             is particularly the case when using UDP broadcast to discover
#             devices on the local network.
#
#             Note that it may be possible to alter the SSID used by the device
#             in which case this method may not provide an accurate result.
#             However, as the device SSID is only used during initial device
#             configuration and since altering the device SSID is not a normal
#             part of the initial device configuration, this method of
#             determining the device model is considered adequate for use during
#             discovery by UDP broadcast.
#
#             The check is a simple check to see if the model name is contained
#             in the SSID returned by the device API.
#
#             If a known model is found in the SSID the model is returned as a
#             string. None is returned if (1) the SSID is None or (2) a known
#             model is not found in the SSID.
#             """
#
#             return self.get_model(ssid_string)
#
#         @staticmethod
#         def get_model(t):
#             """
#             Determine the device model from a string.
#
#             To date Ecowitt Gateway firmware versions have included the
#             device model in the firmware version string or the device SSID.
#             Both the firmware version string and device SSID are available via
#             the device API so checking the firmware version string or SSID
#             provides a de facto method of determining the device model.
#
#             This method uses a simple check to see if a known model name is
#             contained in the string concerned.
#
#             Known model strings are contained in a tuple Station.KNOWN_MODELS.
#
#             If a known model is found in the string the model is returned as a
#             string. None is returned if a known model is not found in the
#             string.
#             """
#
#             # do we have a string to check
#             if t is not None:
#                 # we have a string, now do we have a know model in the string, if so return the model string
#                 for model in KNOWN_MODELS:
#                     if model in t.upper():
#                         return model
#                 # we don't have a known model so return None
#                 return None
#             else:
#                 # we have no string so return None
#                 return None
#
#         def get_version(self):
#             """
#             Get Ecowitt Gateway version.
#             """
#
#             return self._request('get_version')
#
#         def get_livedata(self):
#             """
#             Get Ecowitt Gateway live data.
#
#             “common_list”: {
#             id :  ITEM_XXXX_list
#             val :
#             unit :
#             Battery :
#             }
#
#             ITEM_XXXX_list: {
#             #define ITEM_INTEMP          0x01//Indoor Temperature (℃)            2
#             #define ITEM_OUTTEMP         0x02//Outdoor Temperature (℃)           2
#             #define ITEM_DEWPOINT        0x03//Dew point (℃)                    2
#             #define ITEM_WINDCHILL       0x04//Wind chill (℃)                   2
#             #define ITEM_HEATINDEX       0x05//Heat index (℃)                   2
#             #define ITEM_INHUMI          0x06//Indoor Humidity (%)               1
#             #define ITEM_OUTHUMI         0x07//Outdoor Humidity (%)              1
#             #define ITEM_ABSBARO         0x08//Absolutely Barometric (hpa)        2
#             #define ITEM_RELBARO         0x09//Relative Barometric (hpa)          2
#             #define ITEM_WINDDIRECTION   0x0A//Wind Direction (360°)            2
#             #define ITEM_WINDSPEED       0x0B//Wind Speed (m/s)                  2
#             #define ITEM_GUSTSPEED       0x0C//Gust Speed (m/s)                  2
#             #define ITEM_RAINEVENT       0x0D//Rain Event (mm)                   2
#             #define ITEM_RAINRATE        0x0E//Rain Rate (mm/h)                  2
#             #define ITEM_RAIN_GAIN       0x0F//Rain gain (mm)                    2
#             #define ITEM_RAINDAY         0x10//Rain Day (mm)                     2
#             #define ITEM_RAINWEEK        0x11//Rain Week (mm)                    2
#             #define ITEM_RAINMONTH       0x12//Rain Month (mm)                   4
#             #define ITEM_RAINYEAR        0x13//Rain Year (mm)                    4
#             #define ITEM_RAINTOTALS      0x14//Rain Totals (mm)                  4
#             #define ITEM_LIGHT           0x15//Light (lux)                       4
#             #define ITEM_UV              0x16//UV (uW/m2)                        2
#             #define ITEM_UVI             0x17//UVI (0-15 index)                  1
#             #define ITEM_TIME            0x18//Date and time                     6
#             #define ITEM_DAYLWINDMAX     0X19//Day max wind(m/s)                 2
#             }
#
#             """
#
#             return self._request('get_livedata_info')
#
#         def get_ws_settings(self):
#             """
#             Get Ecowitt Gateway settings.
#             """
#
#             return self._request('get_ws_settings')
#
#         def get_calibration_data(self):
#             """
#             Get Ecowitt Gateway calibraion_data.
#             """
#
#             return self._request('get_calibraion_data')
#
#         def get_rain_totals(self):
#             """
#             Get Ecowitt Gateway rain_totals.
#             """
#
#             return self._request('get_rain_totals')
#
#         def get_device_info(self):
#             """
#             Get Ecowitt Gateway device_info.
#             """
#
#             return self._request('get_device_info')
#
#         def get_sensors_info(self):
#             """
#             Get Ecowitt Gateway sensors_info.
#             """
#
#             return self._request('get_sensors_info')
#
#         def get_network_info(self):
#             """
#             Get Ecowitt Gateway network_info.
#             """
#
#             return self._request('get_network_info')
#
#         def get_units_info(self):
#             """
#             Get Ecowitt Gateway units_info.
#             """
#
#             return self._request('get_units_info')
#
#         def get_cli_soilad(self):
#             """
#             Get Ecowitt Gateway cli_soilad.
#             """
#
#             return self._request('get_cli_soilad')
#
#         def get_cli_multiCh(self):
#             """
#             Get Ecowitt Gateway cli_multiCh.
#             """
#
#             return self._request('get_cli_multiCh')
#
#         def get_cli_pm25(self):
#             """
#             Get Ecowitt Gateway cli_pm25.
#             """
#
#             return self._request('get_cli_pm25')
#
#         def get_cli_co2(self):
#             """
#             Get Ecowitt Gateway cli_co2.
#             """
#
#             return self._request('get_cli_co2')
#
#         def get_piezo_rain(self):
#             """
#             Get Ecowitt Gateway piezo_rain.
#             """
#
#             return self._request('get_piezo_rain')
#
#         def _build_url(self, cmd) -> str:
#             """
#             Builds a request url
#             :return: string of the url, dependent on settings of the FritzDevice
#             """
#             return f"http://{self.host}:{self.port}/{cmd}?"
#
#         def _request(self, cmd: str, params=None, result: str = 'json'):
#             """
#             Send a request with parameters.
#             :param cmd:          cmd to be requested
#             :param params:       params for request
#             :param result:       type of result
#             :return:             request response
#             """
#
#             url = self._build_url(cmd)
#
#             try:
#                 rsp = self._session.get(url, params=params, timeout=self.timeout)
#             except Exception as e:
#                 self.logger.error(f"Error during GET request {e} occurred.")
#             else:
#                 status_code = rsp.status_code
#                 if status_code == 200:
#                     self.logger.debug("Sending HTTP request successful")
#                     if result == 'json':
#                         try:
#                             data = rsp.json()
#                         except JSONDecodeError:
#                             self.logger.error('Error occurred during parsing request response to json')
#                         else:
#                             return data
#                     else:
#                         return rsp.text.strip()
#                 elif status_code == 403:
#                     self.logger.debug("HTTP access denied.")
#                 else:
#                     self.logger.error(f"HTTP request error code: {status_code}")
#                     rsp.raise_for_status()
#                     self.logger.debug(f"Url: {url}, Params: {params}")
#
#     class Parser(object):
#         """Class to parse Ecowitt Gateway sensor data."""
#
#         sensor_ids = {
#             'common_list': 'wh34',
#             'piezoRain': 'ws90',
#             'lightning': 'wh57',
#             'co2': 'wh45',
#             'wh25': 'wh25',
#             'ch_pm25': 'wh41',
#             'ch_leak': 'wh55',
#             'ch_aisle': 'wh31',
#             'ch_soil': 'wh51',
#             'ch_temp': 'wh30',
#             'ch_leaf': 'wh35',
#         }
#
#         response_struct = {
#             '0x01': ('decode_temp', 2, 'intemp'),
#             '0x02': ('decode_temp', 2, 'outtemp'),
#             '0x03': ('decode_temp', 2, 'dewpoint'),
#             '0x04': ('decode_temp', 2, 'windchill'),
#             '0x05': ('decode_temp', 2, 'heatindex'),
#             '0x06': ('decode_humid', 1, 'inhumid'),
#             '0x07': ('decode_humid', 1, 'outhumid'),
#             '0x08': ('decode_press', 2, 'absbarometer'),
#             '0x09': ('decode_press', 2, 'relbarometer'),
#             '0x0A': ('decode_dir', 2, 'winddir'),
#             '0x0B': ('decode_speed', 2, 'windspeed'),
#             '0x0C': ('decode_speed', 2, 'gustspeed'),
#             '0x0D': ('decode_rain', 2, 'rainevent'),
#             '0x0E': ('decode_rainrate', 2, 'rainrate'),
#             '0x0F': ('decode_rain', 2, 'rainhour'),
#             '0x10': ('decode_rain', 2, 'rainday'),
#             '0x11': ('decode_rain', 2, 'rainweek'),
#             '0x12': ('decode_big_rain', 4, 'rainmonth'),
#             '0x13': ('decode_big_rain', 4, 'rainyear'),
#             '0x14': ('decode_big_rain', 4, 'raintotals'),
#             '0x15': ('decode_light', 4, 'light'),
#             '0x16': ('decode_uv', 2, 'solarradiation'),
#             '0x17': ('decode_uvi', 1, 'uvi'),
#             '0x18': ('decode_datetime', 6, 'datetime'),
#             '0x19': ('decode_speed', 2, 'winddaymax'),
#             '0x1A': ('decode_temp', 2, 'temp1'),
#             '0x1B': ('decode_temp', 2, 'temp2'),
#             '0x1C': ('decode_temp', 2, 'temp3'),
#             '0x1D': ('decode_temp', 2, 'temp4'),
#             '0x1E': ('decode_temp', 2, 'temp5'),
#             '0x1F': ('decode_temp', 2, 'temp6'),
#             '0x20': ('decode_temp', 2, 'temp7'),
#             '0x21': ('decode_temp', 2, 'temp8'),
#             '0x22': ('decode_humid', 1, 'humid1'),
#             '0x23': ('decode_humid', 1, 'humid2'),
#             '0x24': ('decode_humid', 1, 'humid3'),
#             '0x25': ('decode_humid', 1, 'humid4'),
#             '0x26': ('decode_humid', 1, 'humid5'),
#             '0x27': ('decode_humid', 1, 'humid6'),
#             '0x28': ('decode_humid', 1, 'humid7'),
#             '0x29': ('decode_humid', 1, 'humid8'),
#             '0x2A': ('decode_pm25', 2, 'pm251'),
#             '0x2B': ('decode_temp', 2, 'soiltemp1'),
#             '0x2C': ('decode_moist', 1, 'soilmoist1'),
#             '0x2D': ('decode_temp', 2, 'soiltemp2'),
#             '0x2E': ('decode_moist', 1, 'soilmoist2'),
#             '0x2F': ('decode_temp', 2, 'soiltemp3'),
#             '0x30': ('decode_moist', 1, 'soilmoist3'),
#             '0x31': ('decode_temp', 2, 'soiltemp4'),
#             '0x32': ('decode_moist', 1, 'soilmoist4'),
#             '0x33': ('decode_temp', 2, 'soiltemp5'),
#             '0x34': ('decode_moist', 1, 'soilmoist5'),
#             '0x35': ('decode_temp', 2, 'soiltemp6'),
#             '0x36': ('decode_moist', 1, 'soilmoist6'),
#             '0x37': ('decode_temp', 2, 'soiltemp7'),
#             '0x38': ('decode_moist', 1, 'soilmoist7'),
#             '0x39': ('decode_temp', 2, 'soiltemp8'),
#             '0x3A': ('decode_moist', 1, 'soilmoist8'),
#             '0x3B': ('decode_temp', 2, 'soiltemp9'),
#             '0x3C': ('decode_moist', 1, 'soilmoist9'),
#             '0x3D': ('decode_temp', 2, 'soiltemp10'),
#             '0x3E': ('decode_moist', 1, 'soilmoist10'),
#             '0x3F': ('decode_temp', 2, 'soiltemp11'),
#             '0x40': ('decode_moist', 1, 'soilmoist11'),
#             '0x41': ('decode_temp', 2, 'soiltemp12'),
#             '0x42': ('decode_moist', 1, 'soilmoist12'),
#             '0x43': ('decode_temp', 2, 'soiltemp13'),
#             '0x44': ('decode_moist', 1, 'soilmoist13'),
#             '0x45': ('decode_temp', 2, 'soiltemp14'),
#             '0x46': ('decode_moist', 1, 'soilmoist14'),
#             '0x47': ('decode_temp', 2, 'soiltemp15'),
#             '0x48': ('decode_moist', 1, 'soilmoist15'),
#             '0x49': ('decode_temp', 2, 'soiltemp16'),
#             '0x4A': ('decode_moist', 1, 'soilmoist16'),
#             '0x4C': ('decode_batt', 16, 'lowbatt'),
#             '0x4D': ('decode_pm25', 2, 'pm251_24h_avg'),
#             '0x4E': ('decode_pm25', 2, 'pm252_24h_avg'),
#             '0x4F': ('decode_pm25', 2, 'pm253_24h_avg'),
#             '0x50': ('decode_pm25', 2, 'pm254_24h_avg'),
#             '0x51': ('decode_pm25', 2, 'pm252'),
#             '0x52': ('decode_pm25', 2, 'pm253'),
#             '0x53': ('decode_pm25', 2, 'pm254'),
#             '0x58': ('decode_leak', 1, 'leak1'),
#             '0x59': ('decode_leak', 1, 'leak2'),
#             '0x5A': ('decode_leak', 1, 'leak3'),
#             '0x5B': ('decode_leak', 1, 'leak4'),
#             '0x60': ('decode_distance', 1, 'lightningdist'),
#             '0x61': ('decode_utc', 4, 'lightningdettime'),
#             '0x62': ('decode_count', 4, 'lightningcount'),
#             '0x63': ('decode_wh34', 3, 'temp9'),
#             '0x64': ('decode_wh34', 3, 'temp10'),
#             '0x65': ('decode_wh34', 3, 'temp11'),
#             '0x66': ('decode_wh34', 3, 'temp12'),
#             '0x67': ('decode_wh34', 3, 'temp13'),
#             '0x68': ('decode_wh34', 3, 'temp14'),
#             '0x69': ('decode_wh34', 3, 'temp15'),
#             '0x6A': ('decode_wh34', 3, 'temp16'),
#             '0x70': (
#                 'decode_wh45', 16,
#                 ('temp17', 'humid17', 'pm10', 'pm10_24h_avg', 'pm255', 'pm255_24h_avg', 'co2', 'co2_24h_avg')),
#             '0x71': (None, None, None),
#             '0x72': ('decode_wet', 1, 'leafwet1'),
#             '0x73': ('decode_wet', 1, 'leafwet2'),
#             '0x74': ('decode_wet', 1, 'leafwet3'),
#             '0x75': ('decode_wet', 1, 'leafwet4'),
#             '0x76': ('decode_wet', 1, 'leafwet5'),
#             '0x77': ('decode_wet', 1, 'leafwet6'),
#             '0x78': ('decode_wet', 1, 'leafwet7'),
#             '0x79': ('decode_wet', 1, 'leafwet8')
#         }
#
#         def __init__(self, is_wh24=False, debug_rain=False, debug_wind=False, plugin_instance=None):
#
#             # get instance
#             self._plugin_instance = plugin_instance
#             self.logger = self._plugin_instance.logger
#
#             # Tell our battery state decoding whether we have a WH24 or a WH65 (they both share the same battery state bit). By default we are
#             # coded to use a WH65. But is there a WH24 connected?
#             if is_wh24:
#                 # We have a WH24. On startup we are set for a WH65 but if it is a restart we will likely already be setup for a WH24. We need
#                 # to handle both cases.
#                 if 'wh24' not in self.multi_batt.keys():
#                     # we don't have a 'wh24' entry so create one, it's the same as the 'wh65' entry
#                     self.multi_batt['wh24'] = self.multi_batt['wh65']
#             else:
#                 # We don't have a WH24 but a WH65. On startup we are set for a WH65 but if it is a restart it is possible we have already
#                 # been setup for a WH24. We need to handle both cases.
#                 if 'wh65' not in self.multi_batt.keys():
#                     # we don't have a 'wh65' entry so create one, it's the same as the 'wh24' entry
#                     self.multi_batt['wh65'] = self.multi_batt['wh24']
#             # get debug_rain and debug_wind
#             self.debug_rain = debug_rain
#             self.debug_wind = debug_wind
#
#         def parse(self, data: dict, timestamp=None):
#             """
#             Parse raw sensor data.
#
#             Parse the raw sensor data and create a dict of sensor observations/status data. Add a timestamp to the data if one does not already exist.
#
#             Returns a dict of observations/status data."""
#
#             data_dict = {}
#             for entry in data:
#                 # print(entry)
#                 if entry in ['common_list', 'rain', 'piezoRain']:
#                     for sensor in data[entry]:
#                         # print(sensor['id'], int(sensor['id'], 16), decode_common.get(sensor['id'], "unknown"))
#                         key = self.response_struct.get(sensor['id'], "unknown")[2]
#
#                         val = self.parse_value_w_unit(sensor.get('val'), sensor.get('unit'))
#                         data_dict.update({key: val})
#
#                         battery = sensor.get('battery')
#                         if battery:
#                             data_dict.update({f"{key}_batt": self.parse_value(battery)})
#
#                 elif entry in ['wh25']:
#                     for sensor in data[entry]:
#                         intemp = self.parse_value_w_unit(sensor.get('intemp'), sensor.get('unit'))
#                         data_dict.update({'intemp': intemp})
#
#                         for e in ["inhumi", "abs", "rel"]:
#                             data_dict.update({f"{e.lower()}": self.parse_value(sensor.get(e))})
#
#                 elif entry in ['lightning']:
#                     for sensor in data[entry]:
#                         key = 'lightning'
#                         for e in ["distance", "timestamp", "count"]:
#                             data_dict.update({f"{key}_{e.lower()}": self.parse_value(sensor.get(e))})
#
#                         battery = sensor.get('battery')
#                         if battery:
#                             data_dict.update({f'{key}batt': self.parse_value(battery)})
#
#                 elif entry in ['co2']:
#                     for sensor in data[entry]:
#                         key = 'co2'
#                         co2_temp = self.parse_value_w_unit(sensor.get('temp'), sensor.get('unit'))
#                         data_dict.update({f'{key}_temp': co2_temp})
#
#                         for e in ["humidity", "PM25", "PM25_RealAQI", "PM25_24HAQI", "PM10", "PM10_RealAQI",
#                                   "PM10_24HAQI", "CO2", "CO2_24H"]:
#                             data_dict.update({f"{key}_{e.lower()}": self.parse_value(sensor.get(e))})
#
#                         battery = sensor.get('battery')
#                         if battery:
#                             data_dict.update({f"{key}_batt": self.parse_value(battery)})
#
#                 elif entry in ['ch_pm25']:
#                     for sensor in data[entry]:
#                         channel = self.parse_value(sensor.get("channel"))
#                         key = f'pm25_{channel}'
#
#                         for e in ["PM25", "PM25_RealAQI", "PM25_24HAQI"]:
#                             data_dict.update({f"{key}_{e.lower()}": self.parse_value(sensor.get(e))})
#
#                         battery = sensor.get('battery')
#                         if battery:
#                             data_dict.update({f"{key}_batt": self.parse_value(battery)})
#
#                 elif entry in ['ch_leak']:
#                     for sensor in data[entry]:
#                         channel = self.parse_value(sensor.get("channel"))
#                         key = f'leak_{channel}'
#
#                         for e in ["name", "status"]:
#                             data_dict.update({f"{key}_{e.lower()}": self.parse_value(sensor.get(e))})
#
#                         battery = sensor.get('battery')
#                         if battery:
#                             data_dict.update({f"{key}_batt": self.parse_value(battery)})
#                 elif entry in ['ch_aisle']:
#                     for sensor in data[entry]:
#                         channel = self.parse_value(sensor.get("channel"))
#                         key = f'aisle_{channel}'
#
#                         temp = self.parse_value_w_unit(sensor.get('temp'), sensor.get('unit'))
#                         data_dict.update({f'{key}_temp': temp})
#
#                         for e in ["name", "humidity"]:
#                             data_dict.update({f"{key}_{e.lower()}": self.parse_value(sensor.get(e))})
#
#                         battery = sensor.get('battery')
#                         if battery:
#                             data_dict.update({f"{key}_batt": self.parse_value(battery)})
#                 elif entry in ['ch_soil']:
#                     for sensor in data[entry]:
#                         channel = self.parse_value(sensor.get("channel"))
#                         key = f'aisle_{channel}'
#
#                         for e in ["name", "humidity"]:
#                             data_dict.update({f"{key}_{e.lower()}": self.parse_value(sensor.get(e))})
#
#                         battery = sensor.get('battery')
#                         if battery:
#                             data_dict.update({f"{key}_batt": self.parse_value(battery)})
#
#                 elif entry in ['ch_temp']:
#                     for sensor in data[entry]:
#                         channel = self.parse_value(sensor.get("channel"))
#                         key = f'temp_{channel}'
#
#                         temp = self.parse_value_w_unit(sensor.get('temp'), sensor.get('unit'))
#                         data_dict.update({f'{key}_temp': temp})
#
#                         for e in ["name"]:
#                             data_dict.update({f"{key}_{e.lower()}": self.parse_value(sensor.get(e))})
#
#                         battery = sensor.get('battery')
#                         if battery:
#                             data_dict.update({f"{key}_batt": self.parse_value(battery)})
#
#                 elif entry in ['ch_leaf']:
#                     for sensor in data[entry]:
#                         channel = self.parse_value(sensor.get("channel"))
#                         key = f'leaf_{channel}'
#
#                         for e in ["name", 'humidity']:
#                             data_dict.update({f"{key}_{e.lower()}": self.parse_value(sensor.get(e))})
#                         battery = sensor.get('battery')
#
#                         if battery:
#                             data_dict.update({f"{key}_batt": self.parse_value(battery)})
#
#             return data_dict
#
#         def parse_value_w_unit(self, value: str, unit: str = None):
#             if unit:
#                 return self.parse_value(f"{value} {unit}")
#             else:
#                 return self.parse_value(value)
#
#         def parse_value(self, val: str):
#             try:
#                 value = float(val)
#                 if value % 1 == 0:
#                     value = int(value)
#             except ValueError:
#                 value = val.lstrip()
#                 if value == 'None':
#                     return
#                 elif value.endswith('%'):
#                     value = self.parse_value(value[:-1])
#                 elif ' ' in value:
#                     value_var = value.split(' ')
#                     value = self.parse_value(value_var[0])
#                     unit = value_var[1].lower()
#                     if unit == 'mph':
#                         value = mph_to_ms(value)
#                     elif unit == 'in':
#                         value = in_to_mm(value)
#                     elif unit == 'inHg':
#                         value = in_to_hpa(value)
#                     elif unit == 'f':
#                         value = f_to_c(value)
#                     elif unit == 'mph':
#                         value = mph_to_ms(value)
#             return value
#
#     class Sensors(object):
#         """
#         Class to manage Ecowitt Gateway sensor ID data.
#
#         Class Sensors allows access to various elements of sensor ID data via a number of properties and methods when the class is initialised with the
#         Ecowitt Gateway API response to a CMD_READ_SENSOR_ID_NEW or CMD_READ_SENSOR_ID command.
#
#         A Sensors object can be initialised with sensor ID data on instantiation or an existing Sensors object can be updated by calling
#         the set_sensor_id_data() method passing the sensor ID data to be used as the only parameter.
#         """
#
#         # Tuple of sensor ID values for sensors that are not registered with the Ecowitt Gateway. 'fffffffe' means the sensor is disabled, 'ffffffff' means the sensor is registering.
#         not_registered = ('fffffffe', 'ffffffff')
#
#         def __init__(self, sensor_id_data=None, show_battery=False, debug_sensors=False, plugin_instance=None):
#
#             # get instance
#             self._plugin_instance = plugin_instance
#             self.logger = self._plugin_instance.logger
#
#             # set the show_battery property
#             self.show_battery = show_battery
#
#             # initialise a dict to hold the parsed sensor data
#             self.sensor_data = {}
#
#             # parse the raw sensor ID data and store the results in my parsed sensor data dict
#             self.set_sensor_id_data(sensor_id_data)
#
#             # debug sensors
#             self.debug_sensors = debug_sensors
#
#         def set_sensor_id_data(self, id_data):
#             """Parse the raw sensor ID data and store the results."""
#
#             # initialise our parsed sensor ID data dict
#             self.sensor_data = {}
#             # do we have any raw sensor ID data
#             if id_data is not None and len(id_data) > 0:
#                 # determine the size of the sensor id data, it's a big endian
#                 # short (two byte) integer at bytes 4 and 5
#                 data_size = struct.unpack(">H", id_data[3:5])[0]
#                 # extract the actual sensor id data
#                 data = id_data[5:5 + data_size - 4]
#                 # initialise a counter
#                 index = 0
#                 # iterate over the data
#                 while index < len(data):
#                     # get the sensor address
#                     address = data[index:index + 1]
#                     # do we know how to decode this address
#                     if address in GatewayApiClient.sensor_ids.keys():
#                         # get the sensor ID
#                         sensor_id = bytes_to_hex(data[index + 1: index + 5], separator='', caps=False)
#                         # get the method to be used to decode the battery state data
#                         batt_fn = GatewayApiClient.sensor_ids[data[index:index + 1]]['batt_fn']
#                         # get the raw battery state data
#                         batt = data[index + 5]
#                         # if we are not showing all battery state data then the battery state for any sensor with signal == 0 must be set to None, otherwise parse the raw battery state data as applicable
#                         if not self.show_battery and data[index + 6] == 0:
#                             batt_state = None
#                         else:
#                             # parse the raw battery state data
#                             batt_state = getattr(self, batt_fn)(batt)
#                         # now add the sensor to our sensor data dict
#                         self.sensor_data[address] = {'id': sensor_id, 'battery': batt_state, 'signal': data[index + 6]}
#                     else:
#                         if self.debug_sensors:
#                             self.logger.info("Unknown sensor ID '%s'" % bytes_to_hex(address))
#                     # each sensor entry is seven bytes in length so skip to the
#                     # start of the next sensor
#                     index += 7
#
#         @property
#         def addresses(self):
#             """
#             Obtain a list of sensor addresses.
#
#             This includes all sensor addresses reported by the Ecowitt Gateway, this includes:
#             - sensors that are actually connected to the Ecowitt Gateway
#             - sensors that are attempting to connect to the Ecowitt Gateway
#             - Ecowitt Gateway sensor addresses that are searching for a sensor
#             - Ecowitt Gateway sensor addresses that are disabled
#             """
#
#             # this is simply the list of keys to our sensor data dict
#             return self.sensor_data.keys()
#
#         @property
#         def connected_addresses(self):
#             """
#             Obtain a list of sensor addresses for connected sensors only.
#
#             Sometimes we only want a list of addresses for sensors that are actually connected to the Ecowitt Gateway. We can filter out those
#             addresses that do not have connected sensors by looking at the sensor ID. If the sensor ID is 'fffffffe' either the sensor is
#             connecting to the Ecowitt Gateway or the Ecowitt Gateway is searching for a sensor for that address. If the sensor ID is 'ffffffff' the
#             Ecowitt Gateway sensor address is disabled.
#             """
#
#             # initialise a list to hold our connected sensor addresses
#             connected_list = list()
#             # iterate over all sensors
#             for address, data in self.sensor_data.items():
#                 # if the sensor ID is neither 'fffffffe' or 'ffffffff' then it must be connected
#                 if data['id'] not in self.not_registered:
#                     connected_list.append(address)
#             return connected_list
#
#         @property
#         def connected_sensors(self):
#             """
#             Obtain a list of sensor types for connected sensors only.
#
#             Sometimes we only want a list of sensors that are actually connected to the Ecowitt Gateway.
#             """
#
#             # initialise a list to hold our connected sensors
#             connected_list = list()
#             # iterate over our connected sensors
#             for sensor in self.connected_addresses:
#                 # get the sensor name
#                 connected_list.append(GatewayApiClient.sensor_ids[sensor]['name'])
#             return connected_list
#
#         @property
#         def data(self):
#             """Obtain the data dict for all known sensors."""
#
#             return self.sensor_data
#
#         def id(self, address):
#             """Obtain the sensor ID for a given sensor address."""
#
#             return self.sensor_data[address]['id']
#
#         def battery_state(self, address):
#             """Obtain the sensor battery state for a given sensor address."""
#
#             return self.sensor_data[address]['battery']
#
#         def signal_level(self, address):
#             """Obtain the sensor signal level for a given sensor address."""
#
#             return self.sensor_data[address]['signal']
#
#         @property
#         def battery_and_signal_data(self):
#             """
#             Obtain a dict of sensor battery state and signal level data.
#
#             Iterate over the list of connected sensors and obtain a dict of sensor battery state data for each connected sensor.
#             """
#
#             # initialise a dict to hold the battery state data
#             data = {}
#             # iterate over our connected sensors
#             for sensor in self.connected_addresses:
#                 # get the sensor name
#                 sensor_name = GatewayApiClient.sensor_ids[sensor]['name']
#                 # create the sensor battery state field for this sensor
#                 data[f"{sensor_name}_batt"] = self.battery_state(sensor)
#                 # create the sensor signal level field for this sensor
#                 data[f"{sensor_name}_sig"] = self.signal_level(sensor)
#
#             # return our data
#             return data
#
#         @property
#         def battery_description_data(self):
#             """
#             Obtain a dict of sensor battery state description data.
#
#             Iterate over the list of connected sensors and obtain a dict of sensor battery state description data for each connected sensor.
#             """
#
#             # initialise a dict to hold the battery state description data
#             data = {}
#             for sensor in self.connected_addresses:
#                 # get the sensor name
#                 sensor_name = GatewayApiClient.sensor_ids[sensor]['name']
#                 # create the sensor battery state description field for this sensor
#                 data[sensor_name] = self.battery_desc(sensor, self.battery_state(sensor))
#
#             # return our data
#             return data
#
#         @staticmethod
#         def battery_desc(address, value):
#             """
#             Determine the battery state description for a given sensor.
#
#             Given the address...
#             """
#
#             if value is not None:
#                 batt_fn = GatewayApiClient.sensor_ids[address].get('batt_fn')
#                 if batt_fn == 'batt_binary':
#                     if value == 0:
#                         return "OK"
#                     elif value == 1:
#                         return "low"
#                     else:
#                         return 'Unknown'
#                 elif batt_fn == 'batt_int':
#                     if value <= 1:
#                         return "low"
#                     elif value == 6:
#                         return "DC"
#                     elif value <= 5:
#                         return "OK"
#                     else:
#                         return 'Unknown'
#                 elif batt_fn == 'batt_volt' or batt_fn == 'batt_volt_tenth':
#                     if value <= 1.2:
#                         return "low"
#                     else:
#                         return "OK"
#             else:
#                 return 'Unknown'
#
#         @staticmethod
#         def batt_binary(batt):
#             """
#             Decode a binary battery state.
#
#             Battery state is stored in bit 0 as either 0 or 1. If 1 the battery is low, if 0 the battery is normal. We need to mask off bits 1 to 7 as
#             they are not guaranteed to be set in any particular way.
#             """
#
#             return batt & 1
#
#         @staticmethod
#         def batt_int(batt):
#             """
#             Decode a integer battery state.
#
#             According to the API documentation battery state is stored as an integer from 0 to 5 with <=1 being considered low. Experience with
#             WH43 has shown that battery state 6 also exists when the device is run from DC. This does not appear to be documented in the API
#             documentation.
#             """
#
#             return batt
#
#         @staticmethod
#         def batt_volt(batt):
#             """
#             Decode a voltage battery state in 2mV increments.
#
#             Battery state is stored as integer values of battery voltage/0.02 with <=1.2V considered low.
#             """
#
#             return round(0.02 * batt, 2)
#
#         @staticmethod
#         def batt_volt_tenth(batt):
#             """
#             Decode a voltage battery state in 100mV increments.
#
#             Battery state is stored as integer values of battery voltage/0.1
#             with <=1.2V considered low.
#             """
#
#             return round(0.1 * batt, 1)

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


def bytes_to_hex(iterable: bytes, separator: str = ' ', caps: bool = True) -> str:
    """Produce a hex string representation of a sequence of bytes."""

    try:
        hex_str = iterable.hex()
        if caps:
            hex_str = hex_str.upper()
        return separator.join(hex_str[i:i + 2] for i in range(0, len(hex_str), 2))
    except (TypeError, AttributeError):
        # TypeError - 'iterable' is not iterable
        # AttributeError - likely because separator is None either way we can't represent as a string of hex bytes
        return f"cannot represent '{iterable}' as hexadecimal bytes"


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


def to_bool(value) -> bool:
    """convert numeric str to bool"""

    return bool(to_int(value))


def to_int(value) -> int:
    try:
        return int(value)
    except (ValueError, TypeError):
        return 0


def to_float(value) -> float:
    """convert numeric str to float"""

    try:
        return float(value)
    except (ValueError, TypeError):
        return 0


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
    """Convert solar radiation in W/m² to Lux using 1W/m² = 126.7 lux"""
    return round(float(f)*126.7, n)


MAGNUS_COEFFICIENTS = dict(
    positive=dict(a=7.5, b=17.368, c=238.88),
    negative=dict(a=7.6, b=17.966, c=247.15),
)
