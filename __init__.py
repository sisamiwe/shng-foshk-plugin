#!/usr/bin/env python3
# vim: set encoding=utf-8 tabstop=4 softtabstop=4 shiftwidth=4 expandtab
#########################################################################
#  Copyright 2022-      Michael Wenzel              wenzel_michael@web.de
#########################################################################
#  This file is part of SmartHomeNG.
#  https://www.smarthomeNG.de
#  https://knx-user-forum.de/forum/supportforen/smarthome-py
#
#  Plugin to connect to Foshk / Ecowitt Weather Gateway.
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
# ToDo Extension
# ToDo: thunderstorm_warning
# ToDo: set CMD_WRITE_CALIBRATION
# ToDo: set CMD_WRITE_RAINDATA
# ToDo: set CMD_WRITE_GAIN
# ToDo: Wert für UV / solar radiation vom POST ist genauer als der, über API; ggf. überschreiben des API Wertes
########################################

# API: https://osswww.ecowitt.net/uploads/20220407/WN1900%20GW1000,1100%20WH2680,2650%20telenet%20v1.6.4.pdf

import lib.env as env
from lib.model.smartplugin import SmartPlugin
from lib.utils import Utils
from lib.shtime import Shtime
from .webif import WebInterface
from .datapoints import DataPoints, MasterKeys, SensorKeys
from .meteocalcs import *

import os
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
import pickle

from collections import deque
from typing import Union
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler
from json import JSONDecodeError
from dataclasses import dataclass
import urllib.parse as urlparse


class Foshk(SmartPlugin):
    """Main class of the Plugin. Does all plugin specific stuff and provides the update functions for the items.

    Data Items must be defined in ./data_items.py.
    """

    PLUGIN_VERSION = '1.2.4'

    def __init__(self, sh):
        """Initializes the plugin"""

        # call init code of parent class (SmartPlugin)
        super().__init__()

        # define variables and attributes
        self.data_queue = queue.Queue()                                    # Queue containing all polled data
        self.data_dict = dict()                                            # dict to hold all live data gotten from weather station gateway via post, api and http
        self.gateway_connected = False                                     # is gateway connected; driver established
        self.gateway = None                                                # driver object
        self.alive = False                                                 # plugin alive
        self.pickle_filepath = f"{os.getcwd()}/var/plugin_data/{self.get_shortname()}"
        self.shtime = Shtime.get_instance()

        # get the parameters for the plugin (as defined in metadata plugin.yaml):
        gateway_address = self.get_parameter_value('Gateway_IP')
        if gateway_address in ['127.0.0.1', '0.0.0.0']:
            gateway_address = None

        gateway_port = self.get_parameter_value('Gateway_Port')
        if gateway_port == 0 or not is_port_valid(gateway_port):
            gateway_port = None

        api_update_cycle = self.get_parameter_value('Gateway_Poll_Cycle')
        if api_update_cycle == 0:
            api_update_cycle = None
        api_update_crontab = self.get_parameter_value('Gateway_Poll_Cycle_Crontab')
        if not api_update_crontab:
            api_update_crontab = None
        if not (api_update_cycle or api_update_crontab):
            self.logger.warning(f"{self.get_fullname()}: no update cycle or crontab set. The data will not be polled automatically")

        fw_check_crontab = self.get_parameter_value('FW_Update_Check_Crontab')
        if not fw_check_crontab:
            fw_check_crontab = None

        interface_config = {'ip_address': gateway_address,
                            'port': gateway_port,
                            'api_data_cycle': api_update_cycle,
                            'api_data_crontab': api_update_crontab,
                            'fw_check_crontab': fw_check_crontab,
                            'use_wh32': self.get_parameter_value('Use_of_WH32'),
                            'ignore_wh40_batt': self.get_parameter_value('Ignore_WH40_Battery'),
                            'lat': self.get_sh()._lat,
                            'lon': self.get_sh()._lon,
                            'alt': self.get_sh()._elev,
                            'lang': self.get_sh().get_defaultlanguage(),
                            }

        # get parameters for TCP Server for HTTP Post
        _ecowitt_data_cycle = self.get_parameter_value('Ecowitt_Data_Cycle')
        self.use_customer_server = bool(_ecowitt_data_cycle)
        if self.use_customer_server:
            post_server_ip = Utils.get_local_ipv4_address()
            post_server_port = self._select_port_for_tcp_server(8080)
            post_server_cycle = max(_ecowitt_data_cycle, 16)
            self.logger.debug(f"Receiving ECOWITT data has been enabled. Data upload to {post_server_ip}:{post_server_port} with an interval of {post_server_cycle}s will be set.")

            interface_config.update({'post_server_ip': post_server_ip,
                                     'post_server_port': post_server_port,
                                     'post_server_cycle': post_server_cycle})

            if not post_server_ip or not post_server_port:
                self.logger.error(f"Receiving ECOWITT data has been enabled, but not able to define server ip or port with setting {post_server_ip}:{post_server_port}")
                self._init_complete = False

        # init Config Classes
        self.interface_config = InterfaceConfig(**interface_config)

        # get a GatewayDriver object
        try:
            self.logger.debug(f"Start interrogating.....")
            self.gateway = GatewayDriver(plugin_instance=self)
            self.logger.debug(f"Interrogating {self.gateway.gateway_model} at {self.gateway.ip_address}:{self.gateway.port}")
            self.gateway_connected = True
        except GatewayIOError as e:
            self.logger.error(f"Unable to connect to device: {e}")
            self._init_complete = False

        # get webinterface
        if not self.init_webinterface(WebInterface):
            self.logger.warning("Webinterface not initialized")

    def run(self):
        """Run method for the plugin"""

        self.logger.debug("Run method called")

        # set class property to selected IP
        self.interface_config.ip_address = self.gateway.ip_address
        self.interface_config.port = self.gateway.port

        # add scheduler
        self.scheduler_add('poll_api', self.gateway.get_current_api_data, cycle=self.interface_config.api_data_cycle, cron=self.interface_config.api_data_crontab)
        if self.interface_config.fw_check_crontab is not None:
            self.scheduler_add('check_fw_update', self.is_firmware_update_available, cron=self.interface_config.fw_check_crontab)

        # if customer server is used, set parameters accordingly
        if self.use_customer_server:
            self._set_custom_params()
            self._set_usr_path()
            self.gateway.tcp.startup()
            
        self.alive = True
        self._update_gateway_meta_data()

        self.logger.debug('Start consuming queue')
        self._work_data_queue()

    def stop(self):
        """Stop method for the plugin"""

        self.alive = False
        self.gateway_connected = False
        self.scheduler_remove('poll_api')
        self.scheduler_remove('check_fw_update')

        # if customer server is used, set parameters accordingly
        if self.use_customer_server:
            self.gateway.tcp.stop_server()
            self.gateway.tcp.shutdown()

        self.gateway.save_all_relevant_data()

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

            # ignore item for showing fw_update_available, if FW-Update Check is not enabled.
            if foshk_attribute == DataPoints.FIRMWARE_UPDATE_AVAILABLE[0] and not self.interface_config.fw_check_crontab:
                self.logger.warning(f" Item {item.path()} is configured to show {DataPoints.FIRMWARE_UPDATE_AVAILABLE[0]} but FW-Update Check not enabled. Item ignored")
                return

            # define data_source
            if self.has_iattr(item.conf, 'foshk_datasource'):
                foshk_datasource = (self.get_iattr_value(item.conf, 'foshk_datasource')).lower()
                if foshk_datasource == 'post' and not self.use_customer_server:
                    self.logger.warning(f" Item {item.path()} should use datasource {foshk_datasource} as per item.yaml, but 'ECOWITT'-protocol not enabled. Item ignored")
                    return
                elif foshk_datasource == 'http' and not self.gateway.http:
                    self.logger.warning(f" Item {item.path()} should use datasource {foshk_datasource} as per item.yaml, but gateway does not support http requests. Item ignored")
                    return

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

                if foshk_attribute == DataPoints.RESET[0]:
                    self.reset()
                elif foshk_attribute == DataPoints.REBOOT[0]:
                    self.reboot()

    #############################################################
    #  Data Collections and Update Methods
    #############################################################

    def _update_gateway_meta_data(self) -> None:
        """Generates as paket with meta information of connected gateway and starts item update"""

        data = dict()
        data[DataPoints.MODEL[0]] = self.gateway_model
        data[DataPoints.FREQ[0]] = self.system_parameters.get('frequency')
        data[DataPoints.FIRMWARE[0]] = self.firmware_version
        if DebugLogConfig.main_class:
            self.logger.debug(f"meta_data {data=}")
        self._update_data_dict(data=data, source='api')
        self._update_item_values(data=data, source='api')

    def _work_data_queue(self) -> None:
        """Works the data-queue where all gathered data were placed"""

        while self.alive:
            try:
                queue_entry = self.data_queue.get(True, 10)
            except queue.Empty:
                pass
            else:
                source, data = queue_entry
                if DebugLogConfig.main_class:
                    self.logger.debug(f"{source=}, {data=}")
                self._update_data_dict(data=data, source=source)
                self._update_item_values(data=data, source=source)

    def _update_item_values(self, data: dict, source: str) -> None:
        """
        Updates the value of connected items

        :param data: data to be used for update
        :param source: source the data come from
        """

        self.logger.debug(f"Called with {source=}")

        for foshk_attribute in data:
            item_list = self.get_item_list(filter_key='match', filter_value=f'{source}.{foshk_attribute}')

            if DebugLogConfig.main_class:
                self.logger.debug(f"Working {foshk_attribute=}")

            if not item_list:
                if DebugLogConfig.main_class:
                    self.logger.debug(f"No item found for foshk_attribute={foshk_attribute!r} at datasource={source!r} has been found.")
                continue

            if DebugLogConfig.main_class:
                self.logger.debug(f"Got corresponding items: {item_list=}")

            for item in item_list:
                value = data[foshk_attribute]
                if DebugLogConfig.main_class:
                    self.logger.debug(f"Item={item.path()} with {foshk_attribute=}, {source=} will be set to {value=}")
                # update plg_item_dict
                item_config = self.get_item_config(item)
                item_config.update({'value': value})
                # update item value
                item(value, self.get_shortname(), source)

        if DebugLogConfig.main_class:
            self.logger.debug(f"Updating item values finished")

    def _update_data_dict(self, data: dict, source: str):
        """Updates the plugin internal data dicts"""

        self.logger.debug(f"Called with source={source}")

        for entry in data:
            if entry not in self.data_dict:
                self.data_dict[entry] = {}

            self.data_dict[entry].update({source: data[entry]})

    #############################################################
    #  Config Methods
    #############################################################

    def _set_usr_path(self, custom_ecowitt_path: str = "/data/report/", custom_wu_path: str = "/weatherstation/updateweatherstation.php?"):
        """
        Set user path for Ecowitt data to receive

        :param custom_ecowitt_path: path for ecowitt data upload
        :param custom_wu_path: path for wu data upload
        """

        self.interface_config.usr_path = self.gateway.api.get_usr_path()

        result = self.gateway.set_usr_path(custom_ecowitt_path, custom_wu_path)
        if result in ['SUCCESS', 'NO NEED']:
            self.logger.debug(f"set_usr_path: {result}")
        else:
            self.logger.error(f"Error during setting set_usr_path: {result=}")

        return result

    def _set_custom_params(self, custom_server_id: str = '', custom_password: str = '', custom_host: str = None, custom_port: int = None, custom_interval: int = None, custom_type: bool = False, custom_enabled: bool = True):
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

        self.interface_config.custom_params = self.gateway.api.get_custom_params()

        if not custom_host:
            custom_host = self.interface_config.post_server_ip
        if not custom_port:
            custom_port = self.interface_config.post_server_port
        if not custom_interval:
            custom_interval = self.interface_config.post_server_cycle

        result = self.gateway.set_custom_params(custom_server_id, custom_password, custom_host, custom_port, custom_interval, custom_type, custom_enabled)
        if result in ['SUCCESS', 'NO NEED']:
            self.logger.debug(f"set_custom_params: {result}")
        else:
            self.logger.error(f"Error during setting custom params: {result=}")

        return result

    def _select_port_for_tcp_server(self, port: int) -> int:
        """
        Check if default port for tcp server is free and can be used

        :param port: port number to be used
        :return: selected port
        """

        for attempt in range(20):
            port = port + attempt
            # self.logger.debug(f"try port={port}")
            if is_port_in_use(port):
                self.logger.debug(f"select_port_for_tcp_server: Port {port} is already in use. Trying next one...")
            else:
                # self.logger.debug(f"select_port_for_tcp_server: Port {port} can be used")
                return port

    def save_pickle(self, filename: str, data) -> None:
        """Saves received data as pickle to given file"""

        # save pickle
        if data and len(data) > 0:
            self.logger.debug(f"Start writing data to {filename}")
            filename = f"{self.pickle_filepath}/{filename}.pkl"
            os.makedirs(os.path.dirname(filename), exist_ok=True)
            try:
                with open(filename, "wb") as output:
                    try:
                        pickle.dump(data, output, pickle.HIGHEST_PROTOCOL)
                        self.logger.debug(f"Successfully wrote data to {filename}")
                    except Exception as e:
                        self.logger.debug(f"Unable to write data to {filename}: {e}")
                        pass
            except OSError as e:
                self.logger.debug(f"Unable to write data to {filename}: {e}")
                pass

    def read_pickle(self, filename: str):

        filename = f"{self.pickle_filepath}/{filename}.pkl"
        if os.path.exists(filename):
            with open(filename, 'rb') as data:
                try:
                    data = pickle.load(data)
                    self.logger.debug(f"Successfully read data from {filename}")
                    return data
                except Exception as e:
                    self.logger.debug(f"Unable to read data from {filename}: {e}")
                    return None

        self.logger.debug(f"Unable to read data from {filename}: 'File/Path not existing'")
        return None

    #############################################################
    #  Public Methods
    #############################################################

    def reboot(self):
        """Reboot device"""

        return self.gateway.reboot()

    def reset(self):
        """Reset device"""

        return self.gateway.reset()

    def is_firmware_update_available(self):
        """Check, if firmware update is available"""

        return self.gateway.is_firmware_update_available()

    def update_firmware(self):
        """Run firmware update"""

        return self.gateway.update_firmware()

    @property
    def gateway_model(self) -> str:
        return self.gateway.gateway_model

    @property
    def firmware_version(self) -> str:
        return self.gateway.firmware_version

    @property
    def system_parameters(self) -> dict:
        return self.gateway.api.get_system_params()

    @property
    def log_level(self) -> int:
        return self.logger.getEffectiveLevel()


# ============================================================================
#                           Config classes
# ============================================================================


@dataclass
class InterfaceConfig:
    """Class to simplify use and handling of gateway config."""

    # known device models
    known_models = ('GW1000', 'GW1100', 'GW2000', 'WH2650', 'WH2680', 'WN1900')
    
    # models supporting get-request
    known_models_with_get_request = ('GW1100', 'GW2000')

    # Gateway IP for api communication
    ip_address: str = None

    # Gateway port for api communication
    port: int = 45000

    # Gateway mac address
    mac: str = None

    # network broadcast address - the address that network broadcasts are sent to
    broadcast_address: str = '255.255.255.255'

    # network broadcast port - the port that network broadcasts are sent to
    broadcast_port: int = 46000

    # default socket timeout in sec
    socket_timeout: int = 2

    # default request timeout in sec
    request_timeout: int = 2

    # default broadcast timeout in sec
    broadcast_timeout: int = 5

    # default retry/wait time in sec
    retry_wait: int = 10

    # default max tries when polling the API
    max_tries: int = 3

    # When run as a service the default age in seconds after which API data is considered stale and will not be used to augment loop packets
    max_age: int = 60

    # default device poll interval in sec via api
    api_data_cycle: int = 20

    # default device poll crontab via api
    api_data_crontab: str = None

    # default period between lost contact log entries during an extended period of lost contact when run as a Service  in sec
    lost_contact_log_period: int = 21600

    # default battery state filtering
    show_battery: bool = False

    # default firmware update check interval in sec
    fw_check_crontab: str = None

    # show availability of firmware update
    show_fw_update_available: bool = False

    # availability of firmware update
    fw_update_available: bool = False

    # log unknown fields
    log_unknown_fields: bool = False

    # create a separate field for summarized battery warning
    show_battery_warning: bool = True

    # create a separate field for summarized sensor warning
    show_sensor_warning: bool = True

    # create a separate field for strom warning
    show_storm_warning: bool = True

    # create a separate field for weatherstation warning
    show_weatherstation_warning: bool = True

    # create a separate field for leakage warning
    show_leakage_warning: bool = True

    # is WH32 in use
    use_wh32: bool = True

    # is WH24 attached
    is_wh24: bool = False

    # should WH40 batt be ignored
    ignore_wh40_batt: bool = True

    # ip-address of http server for uploading ecowitt protocol
    post_server_ip: str = None

    # port of http server for uploading ecowitt protocol
    post_server_port: int = None

    # data cycle for uploading ecowitt protocol
    post_server_cycle: int = None

    # usr path for data server upload
    usr_path: str = None

    # custom params for data server upload
    custom_params: dict = None

    # postion of local installation
    lat: float = None
    lon: float = None
    alt: float = None

    # language of installation
    lang: str = 'de'

    def __post_init__(self):
        if self.fw_check_crontab is not None:
            self.show_fw_update_available = True


@dataclass
class DebugLogConfig:
    """Class to define debug log options gateway config."""

    main_class: bool = False
    gateway: bool = True
    api: bool = True
    tcp: bool = True
    http: bool = True


@dataclass
class Constants:

    FW_UPDATE_URL: str = 'http://download.ecowitt.net/down/filewave?v=FirwaveReadme.txt'.replace("\"", "")

    STORM_WARNDIFF_1H: float = 1.75         # Druckunterschied in 1h zur Auslösung der Sturmwarnung: 1.75hPa
    STORM_WARNDIFF_3H: float = 3.75         # Druckunterschied in 3h zur Auslösung der Sturmwarnung: 3.75hPa
    STORM_EXPIRE: int = 60                # Auflauf der Sturmwarnung: 60 Minuten
    TSTORM_WARNCOUNT: int = 1             # Auslösen der Gewitterwarnung nach: 1 Blitz
    TSTORM_WARNDIST: int = 30             # Auslösen der Gewitterwarnung bei Gewitterabstand: 30km
    TSTORM_EXPIRE: int = 15               # Auflauf der Gewitterwarnung: 15 Minuten
    CO2_WARNLEVEL: int = 1200             # Auslösen der CO2 Warnung: ab 1200
    SUN_MIN: float = 0
    SUN_COEF: float = 0.8                   # Sonnenkoeffizient


# ============================================================================
#                           Gateway Error classes
# ============================================================================


class InvalidApiResponse(Exception):
    """Exception raised when an API call response is invalid."""


class InvalidChecksum(Exception):
    """Exception raised when an API call response contains an invalid checksum."""


class GatewayIOError(Exception):
    """Exception raised when an input/output error with the Ecowitt Gateway is encountered."""


class UnknownApiCommand(Exception):
    """Exception raised when an unknown API command is used."""


class UnknownHttpCommand(Exception):
    """Exception raised when an unknown HTTP command was selected."""


# ============================================================================
#                         Gateway classes
# ============================================================================


class Gateway(object):
    """Class containing common properties and self-calculated data based on received data"""

    PICKLE_FILENAME_AIRPRESSURE_3H = 'foshk_air_pressure_3h'
    PICKLE_FILENAME_AIRPRESSURE_LAST = 'foshk_air_pressure_last'
    PICKLE_FILENAME_SUNTIME = 'foshk_sun_time'

    def __init__(self, plugin_instance):
        """Initialise a Gateway object."""

        # get instance and init logger
        self._plugin_instance = plugin_instance
        self.logger = self._plugin_instance.logger
        self.logger.debug("Init Gateway Object")

        # get interface config
        self.interface_config = self._plugin_instance.interface_config

        # define data structures
        self.pickle_data_validity_time = 600                                                                # seconds after which the data saved in pickle are not valid anymore
        self.wind_avg10m = deque(maxlen=(int(10 * 60 / self.interface_config.api_data_cycle)))              # deque to hold 10 minutes of wind speed, wind direction and windgust
        self.pressure_3h = self._init_pressure_3h()                                                         # deque to hold air pressure date
        self.pressure_last = self._init_pressure_last()                                                     # dict to hold last air_pressure_values
        self.sun_time = self._init_sun_time_dict()                                                          # dict to hold sun time data

        # all found sensors since beginning of plugin
        self.sensors_all = []

        # sensors, that were missed with count of cycles
        self.sensors_missed = {}

        # initialise last lightning count, last rain, etc properties
        self.sensor_warning = None
        self.battery_warning = None
        self.last_lightning = None
        self.last_rain = None
        self.piezo_last_rain = None
        self.rain_mapping_confirmed = False
        self.rain_total_field = None
        self.piezo_rain_mapping_confirmed = False
        self.piezo_rain_total_field = None
        self.storm_warning = None
        self.storm_time = None
        self.storm_warning_start_time = None
        self.leakage_warning = None

    def _init_pressure_3h(self):
        """Try to load data from pickle. if not successful create new empty deque"""

        raw_data = self._plugin_instance.read_pickle(self.PICKLE_FILENAME_AIRPRESSURE_3H)
        if isinstance(raw_data, dict):
            data = raw_data.get('data')
            stop_time = raw_data.get('stop_time')
        else:
            data = None
            stop_time = None

        if stop_time and (int(time.time()) - stop_time) > self.pickle_data_validity_time:
            self.logger.info("Saved pressure data from pickle are expired. Start from scratch.")
            data = None

        if data and isinstance(data, deque):
            return data

        self.logger.info("Unable to load pressure data from pickle. Start with empty deque.")
        return deque(maxlen=(int(3 * 3600 / self.interface_config.api_data_cycle + 5)))

    def _init_pressure_last(self):
        """Try to load data from pickle. if not successful create new dict"""

        raw_data = self._plugin_instance.read_pickle(self.PICKLE_FILENAME_AIRPRESSURE_LAST)
        if isinstance(raw_data, dict):
            data = raw_data.get('data')
            stop_time = raw_data.get('stop_time')
        else:
            data = None
            stop_time = None

        if stop_time and (int(time.time()) - stop_time) > self.pickle_data_validity_time:
            self.logger.info("Saved pressure data from pickle are expired. Start from scratch.")
            data = None

        if data and isinstance(data, dict) and 'diff' in data and 'trend' in data:
            return data

        self.logger.info("Unable to load last pressure data from pickle. Start with empty dict.")
        return {'diff': {}, 'trend': {}}

    def _init_sun_time_dict(self):
        """Try to load data from pickle. if not successful create new dict"""

        raw_data = self._plugin_instance.read_pickle(self.PICKLE_FILENAME_SUNTIME)
        if isinstance(raw_data, dict):
            data = raw_data.get('data')
            stop_time = raw_data.get('stop_time')
        else:
            data = None
            stop_time = None

        if stop_time and (int(time.time()) - stop_time) > self.pickle_data_validity_time:
            self.logger.info("Saved pressure data from pickle are expired. Start from scratch.")
            data = None

        if data and isinstance(data, dict):
            return data

        self.logger.info("Unable to load sun_time data from pickle. Start with empty dict.")
        ts = int(time.time())
        year = self._plugin_instance.shtime.current_year(offset=0)
        month = self._plugin_instance.shtime.current_month(offset=0)
        week = self._plugin_instance.shtime.calendar_week(offset=0)
        day = self._plugin_instance.shtime.current_day(offset=0)
        hour = self._plugin_instance.shtime.now().hour
        start_value = 0
        sun_times = {'hour': (hour, start_value), 'day': (day, start_value), 'week': (week, start_value), 'month': (month, start_value), 'year': (year, start_value), 'last': (ts, start_value)}
        return sun_times

    def save_all_relevant_data(self):

        stop_time = int(time.time())
        self._plugin_instance.save_pickle(self.PICKLE_FILENAME_AIRPRESSURE_3H, {'data': self.pressure_3h, 'stop_time': stop_time})
        self._plugin_instance.save_pickle(self.PICKLE_FILENAME_AIRPRESSURE_LAST, {'data': self.pressure_last, 'stop_time': stop_time})
        self._plugin_instance.save_pickle(self.PICKLE_FILENAME_SUNTIME, {'data': self.sun_time, 'stop_time': stop_time})

    @staticmethod
    def add_temp_data(data: dict) -> None:
        """
        Add calculated data to dict

        :param data: dict of parsed Ecowitt Gateway data
        """

        if DataPoints.OUTTEMP[0] in data:

            if DataPoints.WINDSPEED[0] in data:
                data[DataPoints.WINDCHILL[0]] = get_windchill(data[DataPoints.OUTTEMP[0]], data[DataPoints.WINDSPEED[0]], units='metric')

            if DataPoints.OUTHUMI[0] in data:
                data[DataPoints.OUTDEWPT[0]] = get_dew_point(data[DataPoints.OUTTEMP[0]], data[DataPoints.OUTHUMI[0]])
                data[DataPoints.CLOUD_CEILING[0]] = get_cloud_ceiling(data[DataPoints.OUTTEMP[0]], data[DataPoints.OUTHUMI[0]])
                data[DataPoints.OUTABSHUM[0]] = get_abs_hum(data[DataPoints.OUTTEMP[0]], data[DataPoints.OUTHUMI[0]])
                data[DataPoints.HEATINDEX[0]] = get_heat_index(data[DataPoints.OUTTEMP[0]], data[DataPoints.OUTHUMI[0]], units='metric')
                data[DataPoints.COMFORT[0]] = get_comfort_from_dewpoint(data[DataPoints.OUTDEWPT[0]])
                data[DataPoints.CONDENSATION[0]] = condensation(data[DataPoints.OUTTEMP[0]], data[DataPoints.OUTHUMI[0]])[1]

            if DataPoints.WINDSPEED[0] in data and DataPoints.OUTHUMI[0] in data:
                data[DataPoints.FEELS_LIKE[0]] = get_feels_like_temperature(data[DataPoints.OUTTEMP[0]], data[DataPoints.OUTHUMI[0]], data[DataPoints.WINDSPEED[0]], units='metric')
                data[DataPoints.THERMOPHYSIOLOGICAL_STRAIN[0]] = get_thermophysiological_strain(data[DataPoints.FEELS_LIKE[0]])[1]

        if DataPoints.INTEMP[0] in data and DataPoints.INHUMI[0] in data:
            data[DataPoints.INDEWPPOINT[0]] = get_dew_point(data[DataPoints.INTEMP[0]], data[DataPoints.INHUMI[0]])
            data[DataPoints.INABSHUM[0]] = get_abs_hum(data[DataPoints.INTEMP[0]], data[DataPoints.INHUMI[0]])

        for i in range(1, 9):
            if f'{MasterKeys.TEMP}{i}' in data and f'{MasterKeys.HUMID}{i}' in data:
                data[f'{MasterKeys.DEWPT}{i}'] = get_dew_point(data[f'{MasterKeys.TEMP}{i}'], data[f'{MasterKeys.HUMID}{i}'])
                data[f'{MasterKeys.ABSHUM}{i}'] = get_abs_hum(data[f'{MasterKeys.TEMP}{i}'], data[f'{MasterKeys.HUMID}{i}'])

    def add_wind_data(self, data: dict) -> None:
        """
        Add calculated wind data to dict

        :param data: dict of parsed Ecowitt Gateway data
        """
        
        if DataPoints.WINDDIRECTION[0] in data:
            data[DataPoints.WINDDIR_TEXT[0]] = env.degrees_to_direction_16(data[DataPoints.WINDDIRECTION[0]])

        if DataPoints.WINDSPEED[0] in data:
            windspeed_bft = env.ms_to_bft(data[DataPoints.WINDSPEED[0]])
            data[DataPoints.WINDSPEED_BFT[0]] = windspeed_bft
            data[DataPoints.WINDSPEED_BFT_TEXT[0]] = env.bft_to_text(windspeed_bft, self.interface_config.lang)

        if DataPoints.ABSBARO[0] in data:
            data[DataPoints.WEATHER_TEXT[0]] = get_weather_now(data[DataPoints.ABSBARO[0]], self.interface_config.lang)
                
    def add_wind_avg(self, data: dict) -> None:
        """
        Add calculated wind_avg to dict

        :param data: dict of parsed Ecowitt Gateway data
        """

        if any(k in data for k in (DataPoints.WINDDIRECTION[0], DataPoints.WINDSPEED[0], DataPoints.GUSTSPEED[0])):
            self.wind_avg10m.append([int(time.time()), data[DataPoints.WINDSPEED[0]], data[DataPoints.WINDDIRECTION[0]], data[DataPoints.GUSTSPEED[0]]])

            if DataPoints.WINDSPEED_AVG10M[0] not in data:
                data[DataPoints.WINDSPEED_AVG10M[0]] = self.get_avg_wind(self.wind_avg10m, 1)

            if DataPoints.WINDDIR_AVG10M[0] not in data:
                data[DataPoints.WINDDIR_AVG10M[0]] = self.get_avg_wind(self.wind_avg10m, 2)

            if DataPoints.GUSTSPEED_AVG10M[0] not in data:
                data[DataPoints.GUSTSPEED_AVG10M[0]] = self.get_max_wind(self.wind_avg10m, 3)

    def add_pressure_trend(self, data: dict) -> None:
        """Fill deque for pressure trend and determine pressure trends etc"""

        VALUES = {-2: 'stark fallend', -1: 'fallend', 0: 'gleichbleibend', 1: 'steigend', 2: 'stark steigend'}

        # feed deque
        air_pressure_rel = data.get(DataPoints.RELBARO[0])
        if air_pressure_rel is not None:
            self.pressure_3h.append([int(time.time()), air_pressure_rel])

            # get index of current position of deque
            pos_current = len(self.pressure_3h)

            # calculate values für 1h and 3h ago
            for x in [1, 3]:
                # get position of data x hour before
                pos_xh_ago = pos_current - int(x * 3600 / self.interface_config.api_data_cycle)

                # calculation for x hour
                if pos_xh_ago >= 0:
                    self.logger.debug(f"calculate {x}h ago with {pos_xh_ago=}")
                    time_xh_ago, air_pressure_rel_xh_ago = self.pressure_3h[pos_xh_ago]
                    air_pressure_rel_diff_xh_ago = round(air_pressure_rel - air_pressure_rel_xh_ago, 1)
                    air_pressure_rel_trend_xh_ago = self.get_trend(self.pressure_3h, pos_xh_ago, pos_current)
                    air_pressure_rel_trend_xh_ago_str = VALUES[air_pressure_rel_trend_xh_ago]

                    data[f'{DataPoints.AIR_PRESSURE_REL_DIFF_xh[0]}_{x}h'] = air_pressure_rel_diff_xh_ago
                    data[f'{DataPoints.AIR_PRESSURE_REL_TREND_xh[0]}_{x}h'] = air_pressure_rel_trend_xh_ago_str

                    self.pressure_last['diff'].update({f'{x}': air_pressure_rel_diff_xh_ago})
                    self.pressure_last['trend'].update({f'{x}': air_pressure_rel_trend_xh_ago_str})

                    # add weather forecast
                    if x == 3:
                        data[DataPoints.WEATHER_FORECAST_TEXT[0]] = get_weather_forecast(air_pressure_rel_diff_xh_ago, self.interface_config.lang)

    def add_sun_duration(self, data) -> None:
        """
        Add calculated sun duration fields to dict

        :param data: dict of parsed Ecowitt Gateway data
        """

        sun_time = self.calculate_sun_duration(data)

        if sun_time:
            data[DataPoints.SUN_DURATION_HOUR[0]] = sun_time[0]
            data[DataPoints.SUN_DURATION_DAY[0]] = sun_time[1]
            data[DataPoints.SUN_DURATION_WEEK[0]] = sun_time[2]
            data[DataPoints.SUN_DURATION_MONTH[0]] = sun_time[3]
            data[DataPoints.SUN_DURATION_YEAR[0]] = sun_time[4]

    @staticmethod
    def check_ws_warning(data: dict, set_flag: bool) -> None:
        """
        Add field for weather station warning to dict

        :param data: dict of parsed Ecowitt Gateway data
        :param set_flag: should the warning flag be set
        """

        ws_warning = data.get(DataPoints.WEATHERSTATION_WARNING[0])

        if ws_warning and not set_flag:
            del data[DataPoints.WEATHERSTATION_WARNING[0]]
        elif not ws_warning and set_flag:
            data[DataPoints.WEATHERSTATION_WARNING[0]] = False

    @staticmethod
    def add_light_data(data: dict) -> None:
        """
        Add calculated light to dict

        :param data: dict of parsed Ecowitt Gateway data
        """

        if DataPoints.LIGHT[0] not in data and DataPoints.UV[0] in data:
            data.update({DataPoints.LIGHT[0]: solar_rad_to_brightness(data[DataPoints.UV[0]])})

    def get_cumulative_rain_field(self, data: dict) -> None:
        """Determine the cumulative rain field used to derive field 'rain'.

        Ecowitt gateway devices emit various rain totals but WeeWX needs a per period value for field rain. Try the 'big' (four byte) counters
        starting at the longest period and working our way down. This should only need be done once.

        This is further complicated by the introduction of 'piezo' rain with the WS90. Do a second round of checks on the piezo rain equivalents and
        create piezo equivalent properties.

        data: dic of parsed device API data
        """

        # Do we have a confirmed field to use for calculating rain? If we do we can skip this otherwise we need to look for one.
        if not self.rain_mapping_confirmed:
            # We have no field for calculating rain so look for one, if device field DataPoints.RAINTOTALS[0] is present used that as our first choice.
            # Otherwise, work down the list in order of descending period.
            if DataPoints.RAINTOTALS[0] in data:
                self.rain_total_field = DataPoints.RAINTOTALS[0]
                self.rain_mapping_confirmed = True
            # raintotals is not present so now try rainyear
            elif DataPoints.RAINYEAR[0] in data:
                self.rain_total_field = DataPoints.RAINYEAR[0]
                self.rain_mapping_confirmed = True
            # rainyear is not present so now try rainmonth
            elif DataPoints.RAINMONTH[0] in data:
                self.rain_total_field = DataPoints.RAINMONTH[0]
                self.rain_mapping_confirmed = True
            # do nothing, we can try again next packet
            else:
                self.rain_total_field = None
            # if we found a field log what we are using
            if self.rain_mapping_confirmed:
                self.logger.info(f"Using '{self.rain_total_field}' for rain total")
            else:
                self.logger.info("No suitable field found for rain")

        # Do we have a confirmed field to use for calculating piezo rain? If we do we can skip this otherwise we need to look for one.
        if not self.piezo_rain_mapping_confirmed:
            # We have no field for calculating piezo rain so look for one, if device field 'p_rainyear' is present used that as our first
            # choice. Otherwise, work down the list in order of descending period.
            if DataPoints.PIEZO_RAINYEAR in data:
                self.piezo_rain_total_field = DataPoints.PIEZO_RAINYEAR
                self.piezo_rain_mapping_confirmed = True
            # rainyear is not present so now try rainmonth
            elif DataPoints.PIEZO_RAINMONTH in data:
                self.piezo_rain_total_field = DataPoints.PIEZO_RAINMONTH
                self.piezo_rain_mapping_confirmed = True
            # do nothing, we can try again next packet
            else:
                self.piezo_rain_total_field = None
            # if we found a field log what we are using
            if self.piezo_rain_mapping_confirmed:
                self.logger.info(f"Using '{self.piezo_rain_total_field}' for piezo rain total")
            else:
                self.logger.info("No suitable field found for piezo rain")

    def calculate_rain(self, data: dict) -> None:
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
            data[DataPoints.RAIN[0]] = self.delta_rain(new_total, self.last_rain)

            self.logger.info(f"calculate_rain: last_rain={self.last_rain} new_total={new_total} calculated rain={data['rain']}")
            # save the new total as the old total for next time
            self.last_rain = new_total

        # now do the same for piezo rain

        # have we decided on a field to use for piezo rain and is the field  present
        if self.piezo_rain_mapping_confirmed and self.piezo_rain_total_field in data:
            # yes on both counts, so get the new total
            piezo_new_total = data[self.piezo_rain_total_field]
            # now calculate field p_rain as the difference between the new and old totals
            data[DataPoints.PIEZO_RAIN[0]] = self.delta_rain(piezo_new_total, self.piezo_last_rain, descriptor='piezo rain')

            # log some pertinent values
            self.logger.info(f"calculate_rain: piezo_last_rain={self.piezo_last_rain} piezo_new_total={piezo_new_total} calculated p_rain={data['p_rain']}")
            # save the new total as the old total for next time
            self.piezo_last_rain = piezo_new_total

    def calculate_lightning_count(self, data: dict) -> None:
        """
        Calculate total lightning strike count for a period.

        'lightning_strike_count' is calculated as the change in field DataPoints.LIGHTNING_POWER between successive periods. 'lightning_strike_count'
        is only calculated if DataPoints.LIGHTNING_POWER exists.

        :param data: dict of parsed Ecowitt Gateway API data
        :type data: dict
        """

        if DataPoints.LIGHTNING_COUNT[0] in data:
            # yes, so get the new total
            new_total = data[DataPoints.LIGHTNING_COUNT[0]]
            # now calculate field lightning_strike_count as the difference between the new and old totals
            data[DataPoints.LIGHTNING_COUNT[0]] = self.delta_lightning(new_total, self.last_lightning)
            # save the new total as the old total for next time
            self.last_lightning = new_total

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
            self.logger.info(f"skipping {descriptor} measurement: no current rain")
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
    def get_avg_wind(d: deque, w: int) -> float:
        """get avg from deque d , field w"""

        s = sinSum = cosSum = 0
        for i in range(len(d)):

            # for winddir only - average wind dir (field 2)
            if w == 2:  # for winddir only - average wind dir
                sinSum += math.sin(math.radians(d[i][w]))
                cosSum += math.cos(math.radians(d[i][w]))

            # for windspeed and windgust
            else:
                s = s + d[i][w]

        return round((math.degrees(math.atan2(sinSum, cosSum)) + 360) % 360, 1) if w == 2 else round(s / len(d), 1)

    @staticmethod
    def get_max_wind(d: deque, w: int) -> float:
        """
        get max from deque d, field w
        """

        s = 0
        for i in range(len(d)):
            if d[i][w] > s:
                s = d[i][w]
        return round(s, 1)

    def get_trend(self, d: deque, start_pos: int, end_pos: int) -> int:
        """Ermittelt den Trend des Luftdrucks auf Basis der Anzahl der Werte die kleine/equal/größer des Startwertes sind

        :param d: deque mit tuple (timestamp, value)
        :param start_pos: start pos in deque for evaluation
        :param end_pos: end pos in deque for evaluation
        :return trend: Trend: 2-stark steigend, 1-steigend, 0-equal, -1-fallend, -2-stark fallend

        bigger: Anzahl der Werte im Betrachtungszeitraum, die größer alse der Startwert sind
        smaller: Anzahl der Werte im Betrachtungszeitraum, die smaller alse der Startwert sind
        equal: Anzahl der Werte im Betrachtungszeitraum, die equal dem Startwert sind
        """

        bigger = smaller = 0
        equal = 1
        end_pos -= 1
        is3h = True if (end_pos - start_pos) * self.interface_config.api_data_cycle > 3600 else False

        # get start value
        start_value = d[start_pos][1]

        # get diff value between start and end
        diff_value = round(d[end_pos][1] - d[start_pos][1], 1)

        for i in range(start_pos, end_pos):
            # get value to compare
            vergleichswert = d[i][1]
            # count all values which > first entry
            if vergleichswert > start_value:
                bigger += 1
            # count all values which < first entry
            elif vergleichswert < start_value:
                smaller += 1
            # count all values which = first entry
            else:
                equal += 1

        # if most values are bigger than first entry then rising
        if bigger > smaller and bigger > equal:
            trend = 1
            if (is3h and diff_value > 2) or (not is3h and diff_value > 0.7):
                trend = 2
        # if most values are smaller than first entry then falling
        elif smaller > bigger and smaller > equal:
            trend = -1
            if (is3h and diff_value < -2) or (not is3h and diff_value < -0.7):
                trend = -2
        # if most values are equal to first entry then steady
        else:
            trend = 0

        s3hstr = "3h" if is3h else "1h"
        self.logger.debug(f" {s3hstr} diff: {diff_value} hPa trend: {trend} // ({start_pos=} to {end_pos=}: {bigger=}, {smaller=},  {equal=}) ")

        return trend

    def get_storm_warning(self):
        """Create storm warning flag based on pressure differences"""

        def what(_pressure_diff):
            return "dropped" if _pressure_diff < 0 else "risen"

        storm_warning_1h = storm_warning_3h = False
        air_pressure_rel_diff_1h_ago = self.pressure_last['diff'].get('1', 0)
        air_pressure_rel_diff_3h_ago = self.pressure_last['diff'].get('3', 0)
        now = int(time.time())

        if abs(air_pressure_rel_diff_1h_ago) > Constants.STORM_WARNDIFF_1H:
            storm_warning_1h = True
        if abs(air_pressure_rel_diff_3h_ago) > Constants.STORM_WARNDIFF_3H:
            storm_warning_3h = True

        if storm_warning_3h or storm_warning_1h:
            if self.storm_warning_start_time == 0:
                self.storm_warning_start_time = now
            self.logger.info(f"storm warning active since air pressure difference is above warning limit.")
            self.logger.debug(f"{storm_warning_1h=}, {storm_warning_3h=}")
            self.logger.debug(f"Air pressure has {what(air_pressure_rel_diff_1h_ago)} by {air_pressure_rel_diff_1h_ago} within last hour and {what(air_pressure_rel_diff_3h_ago)} by {air_pressure_rel_diff_3h_ago} within last 3 hours.")

        elif self.storm_warning_start_time and now >= self.storm_warning_start_time + Constants.STORM_EXPIRE * 60:
            storm_warning_duration = int((now - self.storm_warning_start_time) / 60)
            self.storm_warning_start_time = 0
            self.logger.info(f"storm warning cancelled after {storm_warning_duration} minutes.")

        return bool(self.storm_warning_start_time)

    def get_tstorm_warning(self, data):
        """Create storm warning flag based on lightning"""

        # ToDo

    def get_leakage_warning(self, data):
        """Create leakage warning flag based on leakage sensors"""

        def check_leakage():
            outstr = ""
            for i in [DataPoints.LEAK1[0], DataPoints.LEAK2[0], DataPoints.LEAK3[0], DataPoints.LEAK4[0]]:
                value = data.get(i)
                if value:
                    outstr += i + ","
                if len(outstr) > 0 and outstr[-1] == ",":
                    outstr = outstr[:-1]
            return outstr.strip()

        leakage = check_leakage()
        if leakage != "":
            if not self.leakage_warning:
                self.logger.warning(f"<WARNING> leakage reported for sensor(s) {leakage}!")
                self.leakage_warning = True
        elif self.leakage_warning:
            self.logger.warning("<OK> leakage remedied - leakage warning for all sensors cancelled")
            self.leakage_warning = False

        return self.leakage_warning

    def check_battery(self, data: dict, battery_data: dict) -> None:
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
            data['battery_warning'] = False
            if not self.battery_warning:
                self.logger.warning(f"<WARNING> Battery level for sensor(s) {batterycheck} is critical - please swap battery")
                self.battery_warning = True
                data['battery_warning'] = True
        elif self.battery_warning:
            self.logger.info("<OK> Battery level for all sensors is ok again")
            self.battery_warning = False
            data['battery_warning'] = False

    def check_sensors(self, data: dict, connected_sensors: list, missing_count: int = 2) -> None:
        """
        Check if all know sensors are still connected, create log entry and add a separate field for sensor warning.
        """

        # log all found sensors during runtime
        self.sensors_all = list(set(self.sensors_all + connected_sensors))
        # check if all sensors are still connected, create log entry data field
        if set(connected_sensors) == set(self.sensors_all):
            if DebugLogConfig.gateway:
                self.logger.debug(f"check_sensors: All sensors are still connected!")
            self.sensor_warning = False
            data['sensor_warning'] = False
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
                data['sensor_warning'] = True
            else:
                self.sensor_warning = False
                data['sensor_warning'] = False

    def calculate_sun_duration(self, data: dict):
        """
        :param data: data dict having sensor information
        """

        solar_radiation = data.get(DataPoints.UV[0])
        if not solar_radiation:
            return

        # get basic values
        day_of_year = self._plugin_instance.shtime.day_of_year()
        azimut_radians, elevation_radians = self._plugin_instance.get_sh().sun.pos()
        elevation_degrees = math.degrees(elevation_radians)
        timestamp = int(time.time())
        last_timestamp, last_sun_sec_last = self.sun_time['last']

        # evaluate sun shine and calc sun sec since last call
        if elevation_degrees <= 3 or solar_radiation < Constants.SUN_MIN:
            sun_sec = 0
        else:
            solar_threshold = int(
                    (0.73 + 0.06 * math.cos((math.pi / 180) * 360 * day_of_year / 365))
                    * 1080
                    * pow((math.sin(math.pi / 180 * elevation_degrees)), 1.25)
                    * Constants.SUN_COEF
                    )

            if solar_radiation > solar_threshold:
                sun_sec = timestamp - last_timestamp
                self.logger.debug(f"Sonnenschein mit solar_radiation: {solar_radiation} solar_threshold: {solar_threshold} SUN_COEF: {Constants.SUN_COEF}, sun seconds: {sun_sec}")
            else:
                sun_sec = 0
                self.logger.debug(f"kein Sonnenschein mit solar_radiation: {solar_radiation} solar_threshold: {solar_threshold} SUN_COEF: {Constants.SUN_COEF}, sun seconds: {sun_sec}")

        # update data dict
        sun_sec_last = last_sun_sec_last + sun_sec
        if sun_sec == 0:
            new_dict = {'last': (timestamp, sun_sec_last)}
            result = None
        else:
            year = self._plugin_instance.shtime.current_year(offset=0)
            month = self._plugin_instance.shtime.current_month(offset=0)
            week = self._plugin_instance.shtime.calendar_week(offset=0)
            day = self._plugin_instance.shtime.current_day(offset=0)
            hour = self._plugin_instance.shtime.now().hour

            last_hour, last_sun_sec_hour = self.sun_time['hour']
            last_day, last_sun_sec_day = self.sun_time['day']
            last_week, last_sun_sec_week = self.sun_time['week']
            last_month, last_sun_sec_month = self.sun_time['month']
            last_year, last_sun_sec_year = self.sun_time['year']

            if hour == last_hour:
                sun_sec_hour = last_sun_sec_hour + sun_sec
            else:
                sun_sec_hour = sun_sec

            if day == last_day:
                sun_sec_day = last_sun_sec_day + sun_sec
            else:
                sun_sec_day = sun_sec

            if week == last_week:
                sun_sec_week = last_sun_sec_week + sun_sec
            else:
                sun_sec_week = sun_sec

            if month == last_month:
                sun_sec_month = last_sun_sec_month + sun_sec
            else:
                sun_sec_month = sun_sec

            if year == last_year:
                sun_sec_year = last_sun_sec_year + sun_sec
            else:
                sun_sec_year = sun_sec

            new_dict = {'hour': (hour, sun_sec_hour), 'day': (day, sun_sec_day), 'week': (week, sun_sec_week),
                        'month': (month, sun_sec_month), 'year': (year, sun_sec_year), 'last': (timestamp, sun_sec_last)}

            result = (int(sun_sec_hour / 60), round(sun_sec_day / 3600, 1), round(sun_sec_week / 3600, 1), round(sun_sec_month / 3600, 1), round(sun_sec_year / 3600, 1))

        self.sun_time.update(new_dict)
        return result

    def update_missing_sensor_dict(self, missing_sensors: list) -> None:
        """
        Get list of sensors, which were lost/missed in last data cycle and udpate missing_sensor_dict with count of missing cycles.
        """

        for sensor in missing_sensors:
            if sensor not in self.sensors_missed:
                self.sensors_missed[sensor] = 1
            else:
                self.sensors_missed[sensor] += 1

        if DebugLogConfig.gateway:
            self.logger.debug(f"sensors_missed={self.sensors_missed}")


class GatewayDriver(Gateway):

    def __init__(self, plugin_instance):

        # get instance
        self._plugin_instance = plugin_instance
        self.logger = self._plugin_instance.logger

        # get interface config
        self.interface_config = self._plugin_instance.interface_config

        # now initialize my superclasses
        super().__init__(plugin_instance)

        # get a GatewayApi object to handle the interaction with the API
        try:
            self.logger.info('Init connection to Ecowitt Gateway via API')
            self.api = GatewayApi(plugin_instance)
        except:
            self.api = None
            raise GatewayIOError

        # get a GatewayHttp object to handle any HTTP requests
        if self.gateway_model in self.interface_config.known_models_with_get_request:
            self.logger.info('Init connection to Ecowitt Gateway via HTTP requests')
            self.http = GatewayHttp(plugin_instance)
        else:
            if DebugLogConfig.gateway:
                self.logger.debug('Ecowitt Gateway does not support interface via HTTP requests')
            self.http = None

        # get a GatewayTCP object to handle data from server upload
        if self.interface_config.post_server_ip and self.interface_config.post_server_port:
            self.logger.info('Init connection to Ecowitt Gateway via HTTP Post')
            self.tcp = GatewayTcp(plugin_instance, self.get_current_tcp_data)
        else:
            if DebugLogConfig.gateway:
                self.logger.debug('Interface via HTTP Post not activated')
            self.tcp = None

        # do we have a legacy WH40 and how are we handling its battery state data
        if b'\x03' in self.api.sensors.get_connected_addresses() and self.api.sensors.legacy_wh40:
            # we have a connected legacy WH40
            if self.interface_config.ignore_wh40_batt:
                _msg = 'Legacy WH40 detected, WH40 battery state data will be ignored'
            else:
                _msg = 'Legacy WH40 detected, WH40 battery state data will be reported'
            self.logger.info(_msg)

    #############################################################
    #  Data Collections and Update Methods
    #############################################################

    def get_current_api_data(self) -> None:
        """Get all current sensor data from API and put it to queue.

        Return current sensor data, battery state data and signal state data for each sensor. The current sensor data consists of sensor data
        available through multiple API api_commands. Each API command response is parsed and the results accumulated in a dictionary. Battery and signal
        state for each sensor is added to this dictionary. The dictionary is timestamped and the timestamped accumulated data is returned. If the
        API does not return any data a suitable exception will have been raised.
        """

        # Now obtain the bulk of the current sensor data via the API. If the data cannot be obtained we will see a GWIOError exception
        parsed_data = self.api.get_livedata()
        if DebugLogConfig.gateway:
            self.logger.debug(f"live_api_data={parsed_data}")
        # add the datetime to the data dict in case our data does not come with one
        if DataPoints.TIME[0] not in parsed_data:
            parsed_data[DataPoints.TIME[0]] = datetime.now().replace(microsecond=0)
        # add the timestamp to the data dict in case our data does not come with one
        if MasterKeys.TIMESTAMP not in parsed_data:
            parsed_data[MasterKeys.TIMESTAMP] = int(time.time())

        # now update our parsed data with the parsed rain data if we have any
        try:
            parsed_rain_data = self.api.read_rain()
        except UnknownApiCommand:
            parsed_rain_data = None
        except GatewayIOError:
            parsed_rain_data = None
            pass

        if DebugLogConfig.gateway:
            self.logger.debug(f"{parsed_rain_data=}")
        if parsed_rain_data is not None:
            parsed_data.update(parsed_rain_data)

        # add sensor battery data
        try:
            parsed_sensor_state_data = self.api.get_current_sensor_state()
        except GatewayIOError:
            parsed_sensor_state_data = None
            pass

        if DebugLogConfig.gateway:
            self.logger.debug(f"{parsed_sensor_state_data=}")
        if parsed_sensor_state_data is not None:
            parsed_data.update(parsed_sensor_state_data)

        # log the parsed data
        if DebugLogConfig.gateway:
            self.logger.debug(f"{parsed_data=}")

        # put parsed data to queue
        self._plugin_instance.data_queue.put(('api', self._post_process_data(parsed_data, True)))

    def get_current_http_data(self) -> None:
        """Get all current sensor data from HTTP Get request and put it to queue."""
        
        parsed_data = self.http.get_livedata()
        if DebugLogConfig.gateway:
            self.logger.debug(f"live_http_data={parsed_data}")

        self._plugin_instance.data_queue.put(('http', self._post_process_data(parsed_data)))

    def get_current_tcp_data(self, parsed_data: dict) -> None:
        """callback function for already parsed live data from tcp upload and put it to queue."""

        if DebugLogConfig.gateway:
            self.logger.debug(f"POST: {parsed_data=}")
        self._plugin_instance.data_queue.put(('post', self._post_process_data(parsed_data)))
        
    def _post_process_data(self, data: dict, master: bool = False) -> dict:

        packet = {}

        # put timestamp and datetime to paket if not present
        if MasterKeys.TIMESTAMP not in data:
            packet[MasterKeys.TIMESTAMP] = int(time.time())
        if DataPoints.TIME[0] not in data:
            packet[DataPoints.TIME[0]] = datetime.now().replace(microsecond=0)
            
        if master:    
            # if not already determined, determine which cumulative rain field will be used to determine the per period rain field
            if not self.rain_mapping_confirmed:
                self.get_cumulative_rain_field(data)

            # get the rainfall for this period from total
            self.calculate_rain(data)

            # get the lightning strike count for this period from total
            self.calculate_lightning_count(data)
            
            # add wind_avg
            self.add_wind_avg(data)

            # add sun duration
            self.add_sun_duration(data)

            # add pressure trend
            self.add_pressure_trend(data)

        # add calculated data
        self.add_temp_data(data)
        self.add_wind_data(data)
        self.add_light_data(data)

        if self.interface_config.show_sensor_warning:
            # add sensor warning data field
            self.check_sensors(data, self.api.sensors.get_connected_addresses())

        if self.interface_config.show_battery_warning:
            # add battery warning data field
            self.check_battery(data, self.api.sensors.get_battery_description_data())

        if self.interface_config.show_storm_warning:
            # add storm warning data field
            data[DataPoints.STORM_WARNING[0]] = self.get_storm_warning()

        if self.interface_config.show_leakage_warning:
            # add leakage warning data field
            data[DataPoints.LEAKAGE_WARNING[0]] = self.get_leakage_warning(data)

        if self.interface_config.show_fw_update_available:
            # add show_fw_update_available field
            data[DataPoints.FIRMWARE_UPDATE_AVAILABLE[0]] = self.interface_config.fw_update_available

        # check data
        self.check_ws_warning(data, self.interface_config.show_weatherstation_warning)

        # add the data to the empty packet
        packet.update(data)

        # log the packet
        self.logger.info(f"postprocessed packet={natural_sort_dict(packet)}")

        return packet

    #############################################################
    #  Gateway Device Properties
    #############################################################

    @property
    def ip_address(self):
        """The gateway device IP address."""

        return self.api.ip_address

    @property
    def port(self):
        """The gateway device port number."""

        return self.api.port

    @property
    def gateway_model(self):
        """Gateway device model."""

        return self.api.model

    @property
    def mac_address(self):
        """Gateway device MAC address."""

        return self.api.get_mac_address()

    @property
    def firmware_version(self):
        """Gateway device firmware version."""

        return self.api.get_firmware_version()
        
    @property
    def ws90_firmware_version(self):

        """Provide the WH90 firmware version.

        Return the WS90 installed firmware version. If no WS90 is available the value None is returned.
        """

        if not self.http:
            return None

        sensors = self.http.get_sensors_info()
        for sensor in sensors:
            if sensor.get('img') == 'wh90':
                return sensor.get('version', 'not available')

    #############################################################
    #  Gateway Device Methods
    #############################################################

    def get_sensor_id(self):
        """Gateway device sensor ID data."""

        return self.api.get_sensor_id()

    def get_calibration(self):
        """Device device calibration data."""

        # obtain the calibration data via the API
        parsed_cal_coeff = self.api.get_calibration_coefficient()
        # obtain the offset calibration data via the API
        parsed_offset = self.api.get_offset_calibration()
        # update our parsed gain data with the parsed offset calibration data
        parsed_cal_coeff.update(parsed_offset)
        # return the parsed data
        return parsed_cal_coeff

    def reboot(self):
        """Reboot the Gateway"""

        response = self.api.set_reboot()
        return 'SUCCESS' if response[4] == 0 else 'FAIL'

    def reset(self):
        """Reset the Gateway"""

        response = self.api.set_reset()
        return 'SUCCESS' if response[4] == 0 else 'FAIL'

    def update_firmware(self):
        """Update the Gateway firmware."""

        response = self.api.set_firmware_update()
        return 'SUCCESS' if response[4] == 0 else 'FAIL'

    def set_usr_path(self, custom_ecowitt_path, custom_wu_path) -> str:
        """Check od usr_path need to be set and set if required."""

        current_usr_path = self.interface_config.usr_path
        _ecowitt_path = current_usr_path['ecowitt_path']
        _wu_path = current_usr_path['wu_path']

        if DebugLogConfig.gateway:
            self.logger.debug(f"To be set customized path: Ecowitt: current='{_ecowitt_path}' vs. new='{custom_ecowitt_path}' and WU: current='{_wu_path}' vs. new='{custom_wu_path}'")

        if not (_ecowitt_path == custom_ecowitt_path and _wu_path == custom_wu_path):
            if DebugLogConfig.gateway:
                self.logger.debug(f"Need to set customized path: Ecowitt: current='{_ecowitt_path}' vs. new='{custom_ecowitt_path}' and WU: current='{_wu_path}' vs. new='{custom_wu_path}'")
            response = self.api.set_usr_path(custom_ecowitt_path, custom_wu_path)
            return 'SUCCESS' if response[4] == 0 else 'FAIL'
        else:
            if DebugLogConfig.gateway:
                self.logger.debug(f"Customized Path settings already correct; No need to write it")
            return 'NO NEED'

    def set_custom_params(self, custom_server_id, custom_password, custom_host, custom_port, custom_interval, custom_type, custom_enabled) -> str:
        """Check od custom_params need to be set and set if required."""

        current_custom_params = self.interface_config.custom_params
        new_custom_params = {'id': custom_server_id, 'password': custom_password, 'server': custom_host, 'port': custom_port, 'interval': custom_interval, 'protocol type': ['Ecowitt', 'WU'][int(custom_type)], 'active': bool(int(custom_enabled))}

        if new_custom_params.items() <= current_custom_params.items():
            if DebugLogConfig.gateway:
                self.logger.debug(f"Customized Server settings already correct; No need to do it again")
            return 'NO NEED'
        else:
            if DebugLogConfig.gateway:
                self.logger.debug(f"Request to set customized server: current setting={current_custom_params}")
                self.logger.debug(f"Request to set customized server:     new setting={new_custom_params}")
            response = self.api.set_custom_params(custom_server_id, custom_password, custom_host, custom_port, custom_interval, custom_type, custom_enabled)
            return 'SUCCESS' if response[4] == 0 else 'FAIL'

    def is_firmware_update_available_file(self) -> tuple:
        """Check if firmware update is available for Gateways not support http requests"""

        fw_info = requests.get(Constants.FW_UPDATE_URL)
        if DebugLogConfig.gateway:
            self.logger.debug(f"check_firmware_update: getting firmware update info from {Constants.FW_UPDATE_URL} results in status={fw_info.status_code}")

        if fw_info.status_code == 200:

            # establish configparser, read response text and extract information for given model
            fw_update_info = configparser.ConfigParser(allow_no_value=True, strict=False)
            fw_update_info.read_string(fw_info.text)
            latest_firmware = fw_update_info.get(self.gateway_model, "VER", fallback="unknown")

            if latest_firmware == 'unknown':
                self.logger.debug(f"No information for {self.gateway_model} within firmware information file.")
                return None, latest_firmware, []

            if ver_str_to_num(latest_firmware) and ver_str_to_num(self.firmware_version) and (ver_str_to_num(latest_firmware) > ver_str_to_num(self.firmware_version)):
                remote_firmware_notes = fw_update_info.get(self.gateway_model, "NOTES", fallback="")
                remote_firmware_notes = remote_firmware_notes.split(";")

                if DebugLogConfig.gateway:
                    self.logger.debug(f"{remote_firmware_notes=}")

                return True, latest_firmware, remote_firmware_notes

            else:
                return False, latest_firmware, []

    def is_firmware_update_available(self) -> bool:
        """Whether a device firmware update is available or not.

        Return True if a device firmware update is available or False otherwise."""

        result = self.http.is_new_firmware_available() if self.http else self.is_firmware_update_available_file()[0]
        self.interface_config.fw_update_available = result
        return result


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
    
    def __init__(self, plugin_instance):

        # get instance
        self._plugin_instance = plugin_instance
        self.logger = self._plugin_instance.logger

        # get interface config
        self.interface_config = self._plugin_instance.interface_config
        ip_address = self.interface_config.ip_address
        port = self.interface_config.port
        self.max_tries = self.interface_config.max_tries
        self.retry_wait = self.interface_config.retry_wait
        self.broadcast_address = self.interface_config.broadcast_address
        self.broadcast_port = self.interface_config.broadcast_port
        self.socket_timeout = self.interface_config.socket_timeout
        self.broadcast_timeout = self.interface_config.broadcast_timeout

        # get a parser object to parse any API data
        self.parser = ApiParser(plugin_instance)

        # initialise flags to indicate if IP address were discovered
        self.ip_discovered = ip_address is None

        # if IP address or port was not specified (None) then attempt to discover the device with a UDP broadcast
        if ip_address is None or port is None:
            for attempt in range(self.max_tries):
                try:
                    # discover devices on the local network, the result is a list of dicts in IP address order with each dict containing data for a unique discovered device
                    self.device_list = self.discover()
                except socket.error as e:
                    self.logger.error(f"Unable to detect device IP address and port: {e} ({type(e)})")
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
                        if DebugLogConfig.api:
                            self.logger.debug(f"Failed to detect device IP address and/or port after {attempt + 1,} attempts")
                        # do we try again or raise an exception
                        if attempt < self.max_tries - 1:
                            # we still have at least one more try left so sleep and try again
                            time.sleep(self.retry_wait)
                        else:
                            # we've used all our tries, log it and raise an exception
                            _msg = f"Failed to detect device IP address and/or port after {attempt + 1,} attempts"
                            self.logger.error(_msg)
                            raise GatewayIOError(_msg)

            # update interface config
            self.interface_config.ip_address = ip_address.encode()
            self.interface_config.port = port

        # set our ip_address property but encode it first, it saves doing it repeatedly later
        self.ip_address = self.interface_config.ip_address
        self.port = self.interface_config.port

        # Get my MAC address to use later if we have to rediscover. Within class GatewayApi the MAC address is stored as a bytestring.
        self.interface_config.mac = self.get_mac_address()

        # get my device model
        self.model = self.get_model_from_firmware(self.get_firmware_version())

        # Do we have a WH24 attached? First obtain our system parameters.
        _sys_params = self.get_system_params()
        self.interface_config.is_wh24 = _sys_params.get('sensor_type', 0) == 'WH24'

        # get a Sensors object to parse any API sensor state data
        self.sensors = Sensors(plugin_instance=plugin_instance)

        # update the sensors object
        self.update_sensor_id_data()

    def discover(self):
        """Discover any devices on the local network.

        Send a UDP broadcast and check for replies. Decode each reply to obtain details of any devices on the local network. Create a dict
        of details for each device including a derived model name.
        Construct a list of dicts with details of unique (MAC address) devices that responded. When complete return the list of devices found.
        """

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

        # create a socket object to broadcast to the network via IPv4 UDP
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        s.settimeout(self.broadcast_timeout)
        # set TTL to 1 to so messages do not go past the local network segment
        ttl = struct.pack('b', 1)
        s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, ttl)
        packet = self._build_cmd_packet('CMD_BROADCAST')
        if DebugLogConfig.api:
            self.logger.debug(f"Sending broadcast packet <{packet}> in Hex: '{bytes_to_hex(packet)}' to '{self.broadcast_address}:{self.broadcast_port}'")
        
        # initialise a list for the results as multiple devices may respond
        result_list = []
        s.sendto(packet, (self.broadcast_address, self.broadcast_port))
        while True:
            try:
                response = s.recv(1024)
                if DebugLogConfig.api:
                    self.logger.debug(f"Received broadcast response in HEX '{bytes_to_hex(response)}' and in Bytes {response}")
            except socket.timeout:
                break
            except socket.error as e:
                self.logger.warning(f"Socket Error {e!r} occurred.")
                raise
            else:
                try:
                    self._check_response(response, self.API_COMMANDS['CMD_BROADCAST'])
                except InvalidChecksum as e:
                    if DebugLogConfig.api:
                        self.logger.debug(f"Invalid response to command 'CMD_BROADCAST': {e}")
                except UnknownApiCommand:
                    raise
                except Exception as e:
                    self.logger.error(f"Unexpected exception occurred while checking response to command 'CMD_BROADCAST': {e}")
                else:
                    device = decode_broadcast_response(response)
                    if not any((d['mac'] == device['mac']) for d in result_list):
                        device['model'] = self.get_model_from_ssid(device.get('ssid'))
                        result_list.append(device)
        s.close()
        return result_list

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
                    if DebugLogConfig.api:
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
                        # iterate over each candidate checking their MAC address against my mac property. This way we know we will be connecting to the device we were previously using.
                        for device in device_list:
                            # do the MACs match, if so we have our old device and we can exit the loop
                            if self.interface_config.mac == device['mac']:
                                self.ip_address = device['ip_address'].encode()
                                self.port = device['port']
                                break
                        else:
                            # we have exhausted the device list without a match so continue the outer loop if we have any attempts left
                            continue
                        # log the new IP address and port
                        self.logger.info(f"{self.model} at address {self.ip_address}:{self.port} will be used")
                        # return True indicating the re-discovery was successful
                        return True
                    else:
                        if DebugLogConfig.api:
                            self.logger.debug(f"Failed attempt {attempt + 1} to detect any devices")
            else:
                # we exhausted our attempts at re-discovery so log it
                self.logger.info(f"Failed to detect original {self.model} after {self.max_tries} attempts")
        else:
            # an IP address was specified, so we cannot go searching, log it
            if DebugLogConfig.api:
                self.logger.debug("IP address specified in 'weewx.conf', re-discovery was not attempted")
        # if we made it here re-discovery was unsuccessful so return False
        return False

    def update_sensor_id_data(self) -> None:
        """Update the Sensors object with current sensor ID data."""

        # first get the current sensor ID data
        sensor_id_data = self.get_sensor_id()
        # now use the sensor ID data to re-initialise our sensors object
        self.sensors.set_sensor_id_data(sensor_id_data)

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
            response = self._send_cmd_with_retries('CMD_GW1000_LIVEDATA')
        except GatewayIOError:
            # there was a problem contacting the device, it could be it has changed IP address so attempt to rediscover
            if not self.rediscover():
                # we could not re-discover so raise the exception // return dict containing weather_station warning
                return {DataPoints.WEATHERSTATION_WARNING[0]: True}
            else:
                # we did rediscover successfully so try again, if it fails we get another GatewayIOError exception which will be raised
                response = self._send_cmd_with_retries('CMD_GW1000_LIVEDATA')
        # if we arrived here we have a non-None response so parse it and return the parsed data
        return self.parser.parse_livedata(response)

    def read_raindata(self):
        """Get traditional gauge rain data.

        Sends the API command to obtain traditional gauge rain data from the device with retries. If the device cannot be contacted a
        GWIOError will have been raised by _send_cmd_with_retries() which will be passed through by read_raindata(). Any code calling
        read_raindata() should be prepared to handle this exception.
        """

        # get the validated API response
        response = self._send_cmd_with_retries('CMD_READ_RAINDATA')
        # now return the parsed response
        return self.parser.parse_read_raindata(response)

    def get_system_params(self):
        """Read system parameters.

        Sends the API command to obtain system parameters from the device with retries. If the device cannot be contacted a GWIOError will
        have been raised by _send_cmd_with_retries() which will be passed through by get_system_params(). Any code calling
        get_system_params() should be prepared to handle this exception.
        """

        # get the validated API response
        response = self._send_cmd_with_retries('CMD_READ_SSSS')
        # now return the parsed response
        return self.parser.parse_read_ssss(response)

    def get_ecowitt_net_params(self):
        """Get Ecowitt.net parameters.

        Sends the API command to obtain the device Ecowitt.net parameters with retries. If the device cannot be contacted a GWIOError will
        have been raised by _send_cmd_with_retries() which will be passed through by get_ecowitt_net_params(). Any code calling
        get_ecowitt_net_params() should be prepared to handle this exception.
        """

        # get the validated API response
        response = self._send_cmd_with_retries('CMD_READ_ECOWITT')
        # parse the response
        ecowitt = self.parser.parse_read_ecowitt(response)
        # add the device MAC address to the parsed data
        ecowitt['mac'] = self.get_mac_address()
        return ecowitt

    def get_wunderground_params(self):
        """Get Weather Underground parameters.

        Sends the API command to obtain the device Weather Underground parameters with retries. If the device cannot be contacted a
        GWIOError will have been raised by _send_cmd_with_retries() which will be passed through by get_wunderground_params(). Any code
        calling get_wunderground_params() should be prepared to handle this exception.
        """

        # get the validated API response
        response = self._send_cmd_with_retries('CMD_READ_WUNDERGROUND')
        # now return the parsed response
        return self.parser.parse_read_wunderground(response)

    def get_weathercloud_params(self):
        """Get Weathercloud parameters.

        Sends the API command to obtain the device Weathercloud parameters with retries. If the device cannot be contacted a GWIOError will
        have been raised by _send_cmd_with_retries() which will be passed through by get_weathercloud_params(). Any code calling
        get_weathercloud_params() should be prepared to handle this exception.
        """

        # get the validated API response
        response = self._send_cmd_with_retries('CMD_READ_WEATHERCLOUD')
        # now return the parsed response
        return self.parser.parse_read_weathercloud(response)

    def get_wow_params(self):
        """Get Weather Observations Website parameters.

        Sends the API command to obtain the device Weather Observations Website parameters with retries. If the device cannot be contacted
        a GWIOError will have been raised by _send_cmd_with_retries() which will be passed through by get_wow_params(). Any code calling
        get_wow_params() should be prepared to handle this exception.
        """

        # get the validated API response
        response = self._send_cmd_with_retries('CMD_READ_WOW')
        # now return the parsed response
        return self.parser.parse_read_wow(response)

    def get_custom_params(self):
        """Get custom server parameters.

        Sends the API command to obtain the device custom server parameters with retries. If the device cannot be contacted a GWIOError will
        have been raised by _send_cmd_with_retries() which will be passed through by get_custom_params(). Any code calling
        get_custom_params() should be prepared to handle this exception.
        """

        # get the validated API response
        response = self._send_cmd_with_retries('CMD_READ_CUSTOMIZED')
        # obtain the parsed response
        data_dict = self.parser.parse_read_customized(response)
        # the user path is obtained separately, get the user path and add it to
        # our response
        data_dict.update(self.get_usr_path())
        # return the resulting parsed data
        return data_dict

    def set_custom_params(self, custom_server_id, custom_password, custom_host, custom_port, custom_interval, custom_type, custom_enabled):
        """
        Set Gateway custom server parameters.

        Sends the command to obtain the Gateway custom server parameters to the API with retries. If the Gateway cannot be
        contacted a GatewayIOError will have been raised by _send_cmd_with_retries() which will be passed through by
        get_custom_params(). Any code calling set_custom_params() should be prepared to handle this exception.
        """

        payload = bytearray(
            chr(len(custom_server_id)) + custom_server_id + chr(len(custom_password)) + custom_password + chr(
                len(custom_host)) + custom_host + chr(int(int(custom_port) / 256)) + chr(
                int(int(custom_port) % 256)) + chr(int(int(custom_interval) / 256)) + chr(
                int(int(custom_interval) % 256)) + chr(int(custom_type)) + chr(int(custom_enabled)), 'latin-1')
        if DebugLogConfig.api:
            self.logger.debug(f"Customized Server: payload={payload}")
        return self._send_cmd_with_retries('CMD_WRITE_CUSTOMIZED', payload)

    def get_usr_path(self):
        """Get user defined custom path.

        Sends the API command to obtain the device user defined custom path with retries. If the device cannot be contacted a GWIOError will
        have been raised by _send_cmd_with_retries() which will be passed through by get_usr_path(). Any code calling get_usr_path() should
        be prepared to handle this exception.
        """

        # get the validated API response
        response = self._send_cmd_with_retries('CMD_READ_USR_PATH')
        # now return the parsed response
        return self.parser.parse_read_usr_path(response)

    def set_usr_path(self, custom_ecowitt_path, custom_wu_path):
        """
        Get Gateway user defined custom path.

        Sends the command to set the Gateway user defined custom path to the API with retries. If the Gateway cannot be
        contacted a GatewayIOError will have been raised by _send_cmd_with_retries() which will be passed through by
        set_usr_path(). Any code calling set_usr_path() should be prepared to handle this exception.
        """

        if DebugLogConfig.api:
            self.logger.debug(f"set_usr_path: set user path called with custom_ecowitt_path={custom_ecowitt_path} and custom_wu_path={custom_wu_path}")

        payload = bytearray()
        payload.extend(int_to_bytes(len(custom_ecowitt_path), 1))
        payload.extend(str.encode(custom_ecowitt_path))
        payload.extend(int_to_bytes(len(custom_wu_path), 1))
        payload.extend(str.encode(custom_wu_path))
        if DebugLogConfig.api:
            self.logger.debug(f"Customized Path: payload={payload}")
        return self._send_cmd_with_retries('CMD_WRITE_USR_PATH', payload)

    def get_mac_address(self):
        """Get device MAC address.

        Sends the API command to obtain the device MAC address with retries. If the device cannot be contacted a GWIOError will have
        been raised by _send_cmd_with_retries() which will be passed through by get_mac_address(). Any code calling get_mac_address() should be
        prepared to handle this exception.
        """

        # get the validated API response
        response = self._send_cmd_with_retries('CMD_READ_STATION_MAC')
        # now return the parsed response
        return self.parser.parse_read_station_mac(response)

    def get_firmware_version(self):
        """Get device firmware version.

        Sends the API command to obtain device firmware version with retries. If the device cannot be contacted a GWIOError will have
        been raised by _send_cmd_with_retries() which will be passed through by get_firmware_version(). Any code calling get_firmware_version()
        should be prepared to handle this exception.
        """

        # get the validated API response
        response = self._send_cmd_with_retries('CMD_READ_FIRMWARE_VERSION')
        # now return the parsed response
        return self.parser.parse_read_firmware_version(response)

    def set_firmware_update(self):
        """
        Starts Gateway firmware update.

        Sends the command to upgrade Gateway firmware version to the API with retries. If the Gateway cannot be contacted a
        GatewayIOError will have been raised by _send_cmd_with_retries() which will be passed through by get_firmware_version(). Any code
        calling get_firmware_version() should be prepared to handle this exception.
        """

        if DebugLogConfig.api:
            self.logger.debug(f"Firmware update called for {self.ip_address}:{self.port}")
        payload = bytearray()
        payload.extend(socket.inet_aton(self.ip_address))
        payload.extend(int_to_bytes(self.port, 2))
        if DebugLogConfig.api:
            self.logger.debug(f"payload={payload}")
        return self._send_cmd_with_retries('CMD_WRITE_UPDATE', payload)

    def get_sensor_id(self):
        """Get sensor ID data.

        Sends the API command to obtain sensor ID data from the device with retries. If the device cannot be contacted re-discovery is
        attempted. If rediscovery is successful the command is tried again otherwise the lost contact timestamp is set and the exception
        raised. Any code that calls this method should be prepared to handle a GWIOError exception.
        """

        # send the API command to obtain sensor ID data from the device, be prepared to catch the exception raised if the device cannot be contacted
        try:
            # get the validated API response
            response = self._send_cmd_with_retries('CMD_READ_SENSOR_ID_NEW')
        except GatewayIOError:
            # there was a problem contacting the device, it could be it has changed IP address so attempt to rediscover
            if not self.rediscover():
                # we could not re-discover so raise the exception
                raise
            else:
                # we did rediscover successfully so try again, if it fails we get another GWIOError exception which will be raised
                response = self._send_cmd_with_retries('CMD_READ_SENSOR_ID_NEW')
        # if we made it here we have a validated response so return it
        return response

    def get_current_sensor_state(self):
        """Get parsed current sensor state data."""

        # first get the current sensor state data
        current_sensor_data = self.get_sensor_id()
        # now update our Sensors object with the current data
        self.sensors.set_sensor_id_data(current_sensor_data)
        # and return the parsed
        return self.sensors.get_battery_and_signal_data()

    def get_mulch_offset(self):
        """Get multichannel temperature and humidity offset data.

        Sends the API command to obtain the multichannel temperature and humidity offset data with retries. If the device cannot be
        contacted a GWIOError will have been raised by _send_cmd_with_retries() which will be passed through by
        get_mulch_offset(). Any code calling get_mulch_offset() should be prepared to handle this exception.
        """

        # get the validated API response
        response = self._send_cmd_with_retries('CMD_GET_MulCH_OFFSET')
        # now return the parsed response
        return self.parser.parse_get_mulch_offset(response)

    def get_mulch_t_offset(self):
        """Get multichannel temperature (WN34) offset data.

        Sends the API command to obtain the multichannel temperature (WN34) offset data with retries. If the device cannot be contacted a
        GWIOError will have been raised by _send_cmd_with_retries() which will be passed through by get_mulch_t_offset(). Any code calling
        get_mulch_t_offset() should be prepared to handle this exception.
        """

        # get the validated API response
        response = self._send_cmd_with_retries('CMD_GET_MulCH_T_OFFSET')
        # now return the parsed response
        return self.parser.parse_get_mulch_t_offset(response)

    def get_pm25_offset(self):
        """Get PM2.5 offset data.

        Sends the API command to obtain the PM2.5 sensor offset data with retries. If the device cannot be contacted a GWIOError will have
        been raised by _send_cmd_with_retries() which will be passed through by get_pm25_offset(). Any code calling get_pm25_offset() should be
        prepared to handle this exception.
        """

        # get the validated API response
        response = self._send_cmd_with_retries('CMD_GET_PM25_OFFSET')
        # now return the parsed response
        return self.parser.parse_get_pm25_offset(response)

    def get_calibration_coefficient(self):
        """Get calibration coefficient data.

        Sends the API command to obtain the calibration coefficient data with retries. If the device cannot be contacted a GWIOError will
        have been raised by _send_cmd_with_retries() which will be passed through by get_calibration_coefficient(). Any code calling
        get_calibration_coefficient() should be prepared to handle this exception.
        """

        # get the validated API response
        response = self._send_cmd_with_retries('CMD_READ_GAIN')
        # now return the parsed response
        return self.parser.parse_read_gain(response)

    def get_soil_calibration(self):
        """Get soil moisture sensor calibration data.

        Sends the API command to obtain the soil moisture sensor calibration data with retries. If the device cannot be contacted a
        GWIOError will have been raised by _send_cmd_with_retries() which will be passed through by get_soil_calibration(). Any code calling
        get_soil_calibration() should be prepared to handle this exception.
        """

        # get the validated API response
        response = self._send_cmd_with_retries('CMD_GET_SOILHUMIAD')
        # now return the parsed response
        return self.parser.parse_get_soilhumiad(response)

    def get_offset_calibration(self):
        """Get offset calibration data.

        Sends the API command to obtain the offset calibration data with retries. If the device cannot be contacted a GWIOError will have
        been raised by _send_cmd_with_retries() which will be passed through by get_offset_calibration(). Any code calling
        get_offset_calibration() should be prepared to handle this exception.
        """

        # get the validated API response
        response = self._send_cmd_with_retries('CMD_READ_CALIBRATION')
        # now return the parsed response
        return self.parser.parse_read_calibration(response)

    def get_co2_offset(self):
        """Get WH45 CO2, PM10 and PM2.5 offset data.

        Sends the API command to obtain the WH45 CO2, PM10 and PM2.5 sensor offset data with retries. If the device cannot be contacted a
        GWIOError will have been raised by _send_cmd_with_retries() which will be passed through by get_co2_offset(). Any code calling
        get_co2_offset() should be prepared to handle this exception.
        """

        # get the validated API response
        response = self._send_cmd_with_retries('CMD_GET_CO2_OFFSET')
        # now return the parsed response
        return self.parser.parse_get_co2_offset(response)

    def set_reboot(self):
        """
        Reboot Gateway .

        Sends the command to reboot Gateway to the API with retries. If the Gateway cannot be contacted a
        GatewayIOError will have been raised by _send_cmd_with_retries() which will be passed through by set_reboot(). Any code
        calling set_reboot() should be prepared to handle this exception.
        """
        if DebugLogConfig.api:
            self.logger.debug(f"set_reboot: Reboot called for {self.ip_address}:{self.port}")
        return self._send_cmd_with_retries('CMD_WRITE_REBOOT')

    def set_reset(self):
        """
        Reset Gateway .

        Sends the command to reboot Gateway to the API with retries. If the Gateway cannot be contacted a
        GatewayIOError will have been raised by _send_cmd_with_retries() which will be passed through by set_reboot(). Any code
        calling set_reboot() should be prepared to handle this exception.
        """
        if DebugLogConfig.api:
            self.logger.debug(f"set_reboot: Reset called for {self.ip_address}:{self.port}")
        return self._send_cmd_with_retries('CMD_WRITE_RESET')

    def read_rain(self) -> dict:
        """Get traditional gauge and piezo gauge rain data.

        Sends the API command to obtain the traditional gauge and piezo gauge rain data with retries. If the device cannot be contacted a
        GWIOError will have been raised by _send_cmd_with_retries() which will be passed through by get_piezo_rain_(). Any code calling
        get_piezo_rain_() should be prepared to handle this exception.
        """

        # get the validated API response
        response = self._send_cmd_with_retries('CMD_READ_RAIN')
        # now return the parsed response
        return self.parser.parse_read_rain(response)

    def _send_cmd_with_retries(self, cmd: str, payload: bytes = b'') -> bytes:
        """Send an API command to the device with retries and return the response.

        Send a command to the device and obtain the response. If the response is valid return the response. If the response is invalid
        an appropriate exception is raised and the command resent up to self.max_tries times after which the value None is returned.

        cmd: A string containing a valid API command, eg: 'CMD_READ_FIRMWARE_VERSION'
        payload: The data to be sent with the API command, byte string.

        Returns the response as a byte string or the value None.
        """

        if DebugLogConfig.api:
            self.logger.debug(f"Send {cmd=} with {payload=}")

        packet = self._build_cmd_packet(cmd, payload)
        response = None
        for attempt in range(self.max_tries):
            try:
                response = self._send_cmd(packet)
            except socket.timeout as e:
                if DebugLogConfig.api:
                    self.logger.debug(f"Failed to obtain response to attempt {attempt + 1} to send command '{cmd}': {e}")
            except Exception as e:
                if DebugLogConfig.api:
                    self.logger.debug(f"Failed attempt {attempt + 1} to send command '{cmd}':{e!r}")
            else:
                try:
                    self._check_response(response, self.API_COMMANDS[cmd])
                except InvalidChecksum as e:
                    if DebugLogConfig.api:
                        self.logger.debug(f"Invalid response to attempt {attempt + 1} to send command '{cmd}':{e}")
                except UnknownApiCommand:
                    raise
                except Exception as e:
                    self.logger.error(f"Unexpected exception occurred while checking response to attempt {attempt + 1} to send command '{cmd}':{e}")
                else:
                    return response

            # sleep before our next attempt, but skip the sleep if we have just made our last attempt
            if attempt < self.max_tries - 1:
                time.sleep(self.retry_wait)

        # if we made it here we failed after self.max_tries attempts first log it
        _msg = f"Failed to obtain response to command '{cmd}' after {self.max_tries} attempts"
        if response is not None:
            self.logger.error(_msg)
        raise GatewayIOError(_msg)

    def _build_cmd_packet(self, cmd: str, payload: bytes = b'') -> bytes:
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
        checksum = self._calc_checksum(body)
        # return the constructed message packet
        return b''.join([self.HEADER, body, struct.pack('B', checksum)])

    def _send_cmd(self, packet: bytes) -> bytes:
        """Send a command to the API and return the response.

        Send a command to the API and return the response. Socket related errors are trapped and raised, code calling _send_cmd should be prepared to handle such exceptions.

        cmd: A valid API command

        Returns the response as a byte string.
        """

        # create a socket object for sending api_commands and broadcasting to the network
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(self.socket_timeout)
            try:
                s.connect((self.ip_address, self.port))
                s.sendall(packet)
                response = s.recv(1024)
                if DebugLogConfig.api:
                    self.logger.debug(f"Received response '{bytes_to_hex(response)}'")
                return response
            except socket.error as e:
                self.logger.warning(f"Socket Error {e!r} occurred.")
                raise
            except Exception as e:
                self.logger.warning(f"Error {e!r} occurred.")
                raise

    def _check_response(self, response: bytes, cmd_code: bytes) -> None:
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
        _calc_checksum = self._calc_checksum(response[2:-1])
        resp_checksum = response[-1]
        if _calc_checksum == resp_checksum:
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
            _msg = "Invalid checksum in API response. Expected '%s' (0x%s), received '%s' (0x%s)." % (_calc_checksum, "{:02X}".format(_calc_checksum), resp_checksum, "{:02X}".format(resp_checksum))
            raise InvalidChecksum(_msg)

    @staticmethod
    def _calc_checksum(data: bytes) -> int:
        """Calculate the checksum for an API call or response.

        The checksum used in an API response is simply the LSB of the sum of the command, size and data bytes. The fixed header and checksum
        bytes are excluded.

        data: The data on which the checksum is to be calculated. Byte string.

        Returns the checksum as an integer.
        """

        checksum = sum(data)
        # we are only interested in the least significant byte
        return checksum % 256


class ApiParser(object):
    """Class to parse and decode device API response payload data.

    The main function of class Parser is to parse and decode the payloads of the device response to the following API calls:
    - CMD_GW1000_LIVEDATA
    - CMD_READ_RAIN

    By virtue of its ability to decode fields in the above API responses the decode methods of class Parser are also used individually
    elsewhere in the driver to decode simple responses received from the device, eg when reading device configuration settings.
    """

    # Dictionary of 'address' based data. Dictionary is keyed by device data field 'address' containing various parameters for each
    # 'address'. Dictionary tuple format is: (decode fn, size, field name) where:
    #   decode fn:  the decode function name to be used for the field
    #   size:       the size of field data in bytes
    #   field name: the name of the device field to be used for the decoded data

    api_live_data_struct = {
        b'\x01': ('decode_temp', 2, DataPoints.INTEMP[0]),
        b'\x02': ('decode_temp', 2, DataPoints.OUTTEMP[0]),
        b'\x03': ('decode_temp', 2, DataPoints.DEWPOINT[0]),
        b'\x04': ('decode_temp', 2, DataPoints.WINDCHILL[0]),
        b'\x05': ('decode_temp', 2, DataPoints.HEATINDEX[0]),
        b'\x06': ('decode_humid', 1, DataPoints.INHUMI[0]),
        b'\x07': ('decode_humid', 1, DataPoints.OUTHUMI[0]),
        b'\x08': ('decode_press', 2, DataPoints.ABSBARO[0]),
        b'\x09': ('decode_press', 2, DataPoints.RELBARO[0]),
        b'\x0A': ('decode_dir', 2, DataPoints.WINDDIRECTION[0]),
        b'\x0B': ('decode_speed', 2, DataPoints.WINDSPEED[0]),
        b'\x0C': ('decode_speed', 2, DataPoints.GUSTSPEED[0]),
        b'\x0D': ('decode_rain', 2, DataPoints.RAINEVENT[0]),
        b'\x0E': ('decode_rainrate', 2, DataPoints.RAINRATE[0]),
        b'\x0F': ('decode_gain_100', 2, DataPoints.RAINHOUR[0]),
        b'\x10': ('decode_rain', 2, DataPoints.RAINDAY[0]),
        b'\x11': ('decode_rain', 2, DataPoints.RAINWEEK[0]),
        b'\x12': ('decode_big_rain', 4, DataPoints.RAINMONTH[0]),
        b'\x13': ('decode_big_rain', 4, DataPoints.RAINYEAR[0]),
        b'\x14': ('decode_big_rain', 4, DataPoints.RAINTOTALS[0]),
        b'\x15': ('decode_light', 4, DataPoints.LIGHT[0]),
        b'\x16': ('decode_uv', 2, DataPoints.UV[0]),
        b'\x17': ('decode_uvi', 1, DataPoints.UVI[0]),
        b'\x18': ('decode_datetime_as_dt', 6, DataPoints.TIME[0]),
        b'\x19': ('decode_speed', 2, DataPoints.DAYLWINDMAX[0]),
        b'\x1A': ('decode_temp', 2, DataPoints.TEMP1[0]),
        b'\x1B': ('decode_temp', 2, DataPoints.TEMP2[0]),
        b'\x1C': ('decode_temp', 2, DataPoints.TEMP3[0]),
        b'\x1D': ('decode_temp', 2, DataPoints.TEMP4[0]),
        b'\x1E': ('decode_temp', 2, DataPoints.TEMP5[0]),
        b'\x1F': ('decode_temp', 2, DataPoints.TEMP6[0]),
        b'\x20': ('decode_temp', 2, DataPoints.TEMP7[0]),
        b'\x21': ('decode_temp', 2, DataPoints.TEMP8[0]),
        b'\x22': ('decode_humid', 1, DataPoints.HUMI1[0]),
        b'\x23': ('decode_humid', 1, DataPoints.HUMI2[0]),
        b'\x24': ('decode_humid', 1, DataPoints.HUMI3[0]),
        b'\x25': ('decode_humid', 1, DataPoints.HUMI4[0]),
        b'\x26': ('decode_humid', 1, DataPoints.HUMI5[0]),
        b'\x27': ('decode_humid', 1, DataPoints.HUMI6[0]),
        b'\x28': ('decode_humid', 1, DataPoints.HUMI7[0]),
        b'\x29': ('decode_humid', 1, DataPoints.HUMI8[0]),
        b'\x2A': ('decode_pm25', 2, DataPoints.PM251[0]),
        b'\x2B': ('decode_temp', 2, DataPoints.SOILTEMP1[0]),
        b'\x2C': ('decode_moist', 1, DataPoints.SOILMOISTURE1[0]),
        b'\x2D': ('decode_temp', 2, DataPoints.SOILTEMP2[0]),
        b'\x2E': ('decode_moist', 1, DataPoints.SOILMOISTURE2[0]),
        b'\x2F': ('decode_temp', 2, DataPoints.SOILTEMP3[0]),
        b'\x30': ('decode_moist', 1, DataPoints.SOILMOISTURE3[0]),
        b'\x31': ('decode_temp', 2, DataPoints.SOILTEMP4[0]),
        b'\x32': ('decode_moist', 1, DataPoints.SOILMOISTURE4[0]),
        b'\x33': ('decode_temp', 2, DataPoints.SOILTEMP5[0]),
        b'\x34': ('decode_moist', 1, DataPoints.SOILMOISTURE5[0]),
        b'\x35': ('decode_temp', 2, DataPoints.SOILTEMP6[0]),
        b'\x36': ('decode_moist', 1, DataPoints.SOILMOISTURE6[0]),
        b'\x37': ('decode_temp', 2, DataPoints.SOILTEMP7[0]),
        b'\x38': ('decode_moist', 1, DataPoints.SOILMOISTURE7[0]),
        b'\x39': ('decode_temp', 2, DataPoints.SOILTEMP8[0]),
        b'\x3A': ('decode_moist', 1, DataPoints.SOILMOISTURE8[0]),
        b'\x3B': ('decode_temp', 2, DataPoints.SOILTEMP9[0]),
        b'\x3C': ('decode_moist', 1, DataPoints.SOILMOISTURE9[0]),
        b'\x3D': ('decode_temp', 2, DataPoints.SOILTEMP10[0]),
        b'\x3E': ('decode_moist', 1, DataPoints.SOILMOISTURE10[0]),
        b'\x3F': ('decode_temp', 2, DataPoints.SOILTEMP11[0]),
        b'\x40': ('decode_moist', 1, DataPoints.SOILMOISTURE11[0]),
        b'\x41': ('decode_temp', 2, DataPoints.SOILTEMP12[0]),
        b'\x42': ('decode_moist', 1, DataPoints.SOILMOISTURE12[0]),
        b'\x43': ('decode_temp', 2, DataPoints.SOILTEMP13[0]),
        b'\x44': ('decode_moist', 1, DataPoints.SOILMOISTURE13[0]),
        b'\x45': ('decode_temp', 2, DataPoints.SOILTEMP14[0]),
        b'\x46': ('decode_moist', 1, DataPoints.SOILMOISTURE14[0]),
        b'\x47': ('decode_temp', 2, DataPoints.SOILTEMP15[0]),
        b'\x48': ('decode_moist', 1, DataPoints.SOILMOISTURE15[0]),
        b'\x49': ('decode_temp', 2, DataPoints.SOILTEMP16[0]),
        b'\x4A': ('decode_moist', 1, DataPoints.SOILMOISTURE16[0]),
        b'\x4C': ('decode_batt', 16, DataPoints.LOWBATT[0]),
        b'\x4D': ('decode_pm25', 2, DataPoints.PM25_24H_AVG1[0]),
        b'\x4E': ('decode_pm25', 2, DataPoints.PM25_24H_AVG2[0]),
        b'\x4F': ('decode_pm25', 2, DataPoints.PM25_24H_AVG3[0]),
        b'\x50': ('decode_pm25', 2, DataPoints.PM25_24H_AVG4[0]),
        b'\x51': ('decode_pm25', 2, DataPoints.PM252[0]),
        b'\x52': ('decode_pm25', 2, DataPoints.PM253[0]),
        b'\x53': ('decode_pm25', 2, DataPoints.PM254[0]),
        b'\x58': ('decode_leak', 1, DataPoints.LEAK1[0]),
        b'\x59': ('decode_leak', 1, DataPoints.LEAK2[0]),
        b'\x5A': ('decode_leak', 1, DataPoints.LEAK3[0]),
        b'\x5B': ('decode_leak', 1, DataPoints.LEAK4[0]),
        b'\x60': ('decode_distance', 1, DataPoints.LIGHTNING_DIST[0]),
        b'\x61': ('decode_utc', 4, DataPoints.LIGHTNING_TIME[0]),
        b'\x62': ('decode_count', 4, DataPoints.LIGHTNING_COUNT[0]),
        b'\x63': ('decode_wn34', 3, DataPoints.TF_USR1[0]),                   # WN34 battery data is not obtained from live data rather it is obtained from sensor ID data
        b'\x64': ('decode_wn34', 3, DataPoints.TF_USR2[0]),
        b'\x65': ('decode_wn34', 3, DataPoints.TF_USR3[0]),
        b'\x66': ('decode_wn34', 3, DataPoints.TF_USR4[0]),
        b'\x67': ('decode_wn34', 3, DataPoints.TF_USR5[0]),
        b'\x68': ('decode_wn34', 3, DataPoints.TF_USR6[0]),
        b'\x69': ('decode_wn34', 3, DataPoints.TF_USR7[0]),
        b'\x6A': ('decode_wn34', 3, DataPoints.TF_USR8[0]),
        b'\x70': ('decode_wh45', 16, DataPoints.SENSOR_CO2[0]),               # WH45 battery data is not obtained from live data rather it is obtained from sensor ID data
        b'\x71': (None, None, None),                                          # placeholder for unknown field 0x71
        b'\x72': ('decode_wet', 1, DataPoints.LEAF_WETNESS1[0]),
        b'\x73': ('decode_wet', 1, DataPoints.LEAF_WETNESS2[0]),
        b'\x74': ('decode_wet', 1, DataPoints.LEAF_WETNESS3[0]),
        b'\x75': ('decode_wet', 1, DataPoints.LEAF_WETNESS4[0]),
        b'\x76': ('decode_wet', 1, DataPoints.LEAF_WETNESS5[0]),
        b'\x77': ('decode_wet', 1, DataPoints.LEAF_WETNESS6[0]),
        b'\x78': ('decode_wet', 1, DataPoints.LEAF_WETNESS7[0]),
        b'\x79': ('decode_wet', 1, DataPoints.LEAF_WETNESS8[0])
    }
    rain_data_struct = {
        b'\x0D': ('decode_rain', 2, DataPoints.RAINEVENT[0]),
        b'\x0E': ('decode_rainrate', 2, DataPoints.RAINRATE[0]),
        b'\x0F': ('decode_gain_100', 2, DataPoints.RAINHOUR[0]),
        b'\x10': ('decode_big_rain', 4, DataPoints.RAINDAY[0]),
        b'\x11': ('decode_big_rain', 4, DataPoints.RAINWEEK[0]),
        b'\x12': ('decode_big_rain', 4, DataPoints.RAINMONTH[0]),
        b'\x13': ('decode_big_rain', 4, DataPoints.RAINYEAR[0]),
        b'\x7A': ('decode_int', 1, DataPoints.RAIN_PRIO[0]),
        b'\x7B': ('decode_int', 1, DataPoints.RAD_COMP[0]),
        b'\x80': ('decode_rainrate', 2, DataPoints.PIEZO_RAINRATE[0]),
        b'\x81': ('decode_rain', 2, DataPoints.PIEZO_RAINEVENT[0]),
        b'\x82': ('decode_reserved', 2, DataPoints.PIEZO_RAINHOUR[0]),
        b'\x83': ('decode_big_rain', 4, DataPoints.PIEZO_RAINDAY[0]),
        b'\x84': ('decode_big_rain', 4, DataPoints.PIEZO_RAINWEEK[0]),
        b'\x85': ('decode_big_rain', 4, DataPoints.PIEZO_RAINMONTH[0]),
        b'\x86': ('decode_big_rain', 4, DataPoints.PIEZO_RAINYEAR[0]),
        b'\x87': ('decode_rain_gain', 20, DataPoints.PIEZO_RAINGAIN[0]),               # field 0x87 hold device parameter data that is not included in the loop packets, hence the device field is not used (None).
        b'\x88': ('decode_rain_reset', 3, DataPoints.RAIN_RST_TIME[0])                 # field 0x88 hold device parameter data that is not included in the loop packets, hence the device field is not used (None).
    }
    # tuple of field codes for device rain related fields in the live data so we can isolate these fields
    # rain_field_codes = (b'\x0D', b'\x0E', b'\x0F', b'\x10', b'\x11', b'\x12', b'\x13', b'\x14', b'\x80', b'\x81', b'\x83', b'\x84', b'\x85', b'\x86')
    # tuple of field codes for wind related fields in the device live data so we can isolate these fields
    # wind_field_codes = (b'\x0A', b'\x0B', b'\x0C', b'\x19')
        
    def __init__(self, plugin_instance):

        # get instance
        self._plugin_instance = plugin_instance
        self.logger = self._plugin_instance.logger

        # get interface config
        self.interface_config = self._plugin_instance.interface_config

        # do we log unknown fields at info or leave at debug
        self.log_unknown_fields = self.interface_config.log_unknown_fields

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

        data = dict()
        if len(payload) > 0:
            # set a counter to keep track of where we are in the payload
            index = 0
            while index < len(payload) - 1:
                # obtain the decode function, field size and field name for the current field
                try:
                    decode_fn_str, field_size, field = structure[payload[index:index + 1]]
                    if DebugLogConfig.api:
                        self.logger.debug(f"Decode id={payload[index:index + 1]} with {field=}")
                except KeyError:
                    _msg = f"Unknown field address '{bytes_to_hex(payload[index:index + 1])}' detected. Remaining data '{bytes_to_hex(payload[index + 1:])}' ignored."
                    if self.log_unknown_fields:
                        self.logger.info(_msg)
                    else:
                        if DebugLogConfig.api:
                            self.logger.debug(_msg)
                    break
                else:
                    _field_data = getattr(self, decode_fn_str)(payload[index + 1:index + 1 + field_size], field)
                    if _field_data is not None:
                        data.update(_field_data)
                    else:
                        # we received None from the decode function, this usually indicates a field marked as 'reserved' in the API documentation
                        pass
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
        # this is addressed data, so we can call parse_addressed_data() and return the result
        return self.parse_addressed_data(payload, self.api_live_data_struct)

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
        # this is addressed data, so we can call parse_addressed_data() and return the result
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
        data_dict[DataPoints.RAINRATE[0]] = self.decode_big_rain(data[0:4])
        data_dict[DataPoints.RAINDAY[0]] = self.decode_big_rain(data[4:8])
        data_dict[DataPoints.RAINWEEK[0]] = self.decode_big_rain(data[8:12])
        data_dict[DataPoints.RAINMONTH[0]] = self.decode_big_rain(data[12:16])
        data_dict[DataPoints.RAINYEAR[0]] = self.decode_big_rain(data[16:20])
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
                offset_dict[channel][MasterKeys.HUMID] = struct.unpack("b", data[index + 1])[0]
            except TypeError:
                offset_dict[channel][MasterKeys.HUMID] = struct.unpack("b", int_to_bytes(data[index + 1]))[0]
            try:
                offset_dict[channel][MasterKeys.TEMP] = struct.unpack("b", data[index + 2])[0] / 10.0
            except TypeError:
                offset_dict[channel][MasterKeys.TEMP] = struct.unpack("b", int_to_bytes(data[index + 2]))[0] / 10.0
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
        offset_dict[MasterKeys.CO2] = struct.unpack(">h", data[0:2])[0]
        # bytes 2 and 3 hold the PM2.5 offset
        offset_dict[MasterKeys.PM25] = struct.unpack(">h", data[2:4])[0] / 10.0
        # bytes 4 and 5 hold the PM10 offset
        offset_dict[MasterKeys.PM10] = struct.unpack(">h", data[4:6])[0] / 10.0
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
        gain_dict[MasterKeys.UV] = struct.unpack(">H", data[2:4])[0] / 100.0
        gain_dict[MasterKeys.SOLAR] = struct.unpack(">H", data[4:6])[0] / 100.0
        gain_dict[MasterKeys.WIND] = struct.unpack(">H", data[6:8])[0] / 100.0
        gain_dict[MasterKeys.RAIN] = struct.unpack(">H", data[8:10])[0] / 100.0
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
        cal_dict[DataPoints.INTEMP[0]] = struct.unpack(">h", data[0:2])[0] / 10.0
        try:
            cal_dict[DataPoints.INHUMI[0]] = struct.unpack("b", data[2])[0]
        except TypeError:
            cal_dict[DataPoints.INHUMI[0]] = struct.unpack("b", int_to_bytes(data[2]))[0]
        cal_dict[DataPoints.ABSBARO[0]] = struct.unpack(">l", data[3:7])[0] / 10.0
        cal_dict[DataPoints.RELBARO[0]] = struct.unpack(">l", data[7:11])[0] / 10.0
        cal_dict[DataPoints.OUTTEMP[0]] = struct.unpack(">h", data[11:13])[0] / 10.0
        try:
            cal_dict[DataPoints.OUTHUMI[0]] = struct.unpack("b", data[13])[0]
        except TypeError:
            cal_dict[DataPoints.OUTHUMI[0]] = struct.unpack("b", int_to_bytes(data[13]))[0]
        cal_dict[DataPoints.WINDDIRECTION[0]] = struct.unpack(">h", data[14:16])[0]
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

        FREQUENCIES = ['433 MHz', '868 MHz', '915 MHz', '920 MHz']
        SENSOR_TYPES = ['WH24', 'WH65']

        # determine the size of the system parameters data
        size = response[3]
        # extract the actual system parameters data
        data = response[4:4 + size - 3]
        # initialise a dict to hold our final data
        data_dict = dict()
        data_dict['frequency'] = FREQUENCIES[data[0]]
        data_dict['sensor_type'] = SENSOR_TYPES[data[1]]
        utc_dt = datetime.fromtimestamp(self.decode_utc(data[2:6])).replace(tzinfo=timezone.utc)
        data_dict['utc'] = utc_dt
        data_dict['dt'] = utc_dt.astimezone(tz=None)
        data_dict['timezone_index'] = data[6]
        data_dict['dst_status'] = data[7] != 0
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

        # return the parsed response, in this case we simply return the bytes as a semicolon separated hex string
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

        # create a format string so the firmware string can be unpacked into its bytes
        firmware_format = "B" * len(response)
        # unpack the firmware response bytestring, we now have a tuple of integers representing each of the bytes
        firmware_t = struct.unpack(firmware_format, response)
        # get the length of the firmware string, it is in byte 4
        str_length = firmware_t[4]
        # the firmware string starts at byte 5 and is str_length bytes long, convert the sequence of bytes to unicode characters and assemble as a
        # string and return the result
        return ''.join([chr(x) for x in firmware_t[5:5 + str_length]])

    @staticmethod
    def decode_reserved(data, field='reserved'):
        """Decode data that is marked 'reserved'.

        Occasionally some fields are marked as 'reserved' in the API documentation. In such cases the decode routine should return the
        value None which will cause the data to be ignored.
        """

        return None

    @staticmethod
    def decode_temp(data, field=None):
        """Decode temperature data.

        Data is contained in a two byte big endian signed integer and represents tenths of a degree. If field is not None return the
        result as a dict in the format {field: decoded value} otherwise return just the decoded value.
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

        Data is contained in a single unsigned byte and represents whole units. If field is not None return the result as a dict in the
        format {field: decoded value} otherwise return just the decoded value.
        """

        if len(data) == 1:
            value = struct.unpack("B", data)[0]
        else:
            value = None
        if field is not None:
            return {field: value}
        else:
            return value

    def decode_uv(self, data, field=None):

        self.logger.debug(f"decode_uv: {data=}, {field=}")

        if len(data) == 2:
            value = struct.unpack(">H", data)[0]
            self.logger.debug(f"decode_uv: {data=}, {value=}")
        else:
            value = None
        if field is not None:
            return {field: value}
        else:
            return value

    @staticmethod
    def decode_press(data, field=None):
        """Decode pressure data.

        Data is contained in a two byte big endian integer and represents tenths of a unit. If data contains more than two bytes take the
        last two bytes. If field is not None return the result as a dict in the format {field: decoded value} otherwise return just the decoded
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

        Data is contained in a two byte big endian integer and represents whole degrees. If field is not None return the result as a dict in
        the format {field: decoded value} otherwise return just the decoded value.
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

        Data is contained in a four byte big endian integer and represents tenths of a unit. If field is not None return the result as a dict
        in the format {field: decoded value} otherwise return just the decoded value.
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

        Unknown format but length is six bytes. If field is not None return the result as a dict in the format {field: decoded value} otherwise
        return just the decoded value.
        """

        if len(data) == 6:
            value = struct.unpack("BBBBBB", data)[0]
        else:
            value = None

        if value and value.isdigit():
            value = int(value)

        if field is not None:
            return {field: value}
        else:
            return value

    def decode_datetime_as_dt(self, data, field=None):
        """Decode date-time data and return datetime object"""

        timestamp = self.decode_datetime(data, None)

        if timestamp and isinstance(timestamp, int):
            dt = datetime.fromtimestamp(timestamp).replace(tzinfo=timezone.utc).astimezone(tz=None)
        else:
            dt = None

        if field is not None:
            return {field: dt}
        else:
            return dt

    @staticmethod
    def decode_distance(data, field=None):
        """Decode lightning distance.

        Data is contained in a single byte integer and represents a value from 0 to 40km. If field is not None return the result as a dict in
        the format {field: decoded value} otherwise return just the decoded value.
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
            value = struct.unpack(">L", data)[0]
            # when processing the last lightning strike time if the value is 0xFFFFFFFF it means we have never seen a strike so return None
            value = value if value != 0xFFFFFFFF else None
        else:
            value = None

        if field is not None:
            return {field: value}

        return value

    @staticmethod
    def decode_count(data, field=None):
        """Decode lightning count.

        Count is an integer stored in a four byte big endian integer. If field is not None return the result as a dict in the format
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

        Gain is stored in a four byte big endian integer and represents hundredths of a unit.
        """

        if len(data) == 2:
            value = struct.unpack(">H", data)[0] / 100.0
        else:
            value = None
        if field is not None:
            return {field: value}
        else:
            return value

    def decode_leak(self, data, field=None):
        """Decode a leakage sensor data"""

        value = bool(int(self.decode_humid(data)))
        if field is not None:
            return {field: value}
        else:
            return value

    # alias' for other decodes
    decode_speed = decode_press
    decode_rain = decode_press
    decode_rainrate = decode_press
    decode_light = decode_big_rain
    # decode_uv = decode_press
    decode_uvi = decode_humid
    decode_moist = decode_humid
    decode_pm25 = decode_press
    # decode_leak = decode_humid
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

        WN34 battery state data is included in the WN34 sensor data (along with temperature) as well as in the complete sensor ID data. In
        keeping with other sensors we do not use the sensor data battery state, rather we obtain it from the sensor ID data.

        If field is not None return the result as a dict in the format {field: decoded value} otherwise return just the decoded value.
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
                6-7    PM10 24-hour avg   unsigned short  ug/m3 x10
                8-9    PM2.5              unsigned short  ug/m3 x10
                10-11  PM2.5 24-hour avg  unsigned short  ug/m3 x10
                12-13  CO2                unsigned short  ppm
                14-15  CO2 24-hour avg    unsigned short  ppm
                16     battery state      unsigned byte   0-5 <=1 is low

        WH45 battery state data is included in the WH45 sensor data (along with temperature) as well as in the complete sensor ID data. In
        keeping with other sensors we do not use the sensor data battery state, rather we obtain it from the sensor ID data.
        """

        if len(data) != 16 or fields is None:
            return {}

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

    def decode_rain_gain(self, data, fields=None):
        """Decode piezo rain gain data.

        Piezo rain gain data is 20 bytes of data comprising 10 two byte big endian fields with each field representing a value in hundredths of a unit.

        The 20 bytes of piezo rain gain data is allocated as follows:
        Byte(s) #      Data      Format            Comments
        bytes   1-2    gain0     unsigned short    gain x 100
                3-4    gain1     unsigned short    gain x 100
                5-6    gain2     unsigned short    gain x 100
                7-8    gain3     unsigned short    gain x 100
                9-10   gain4     unsigned short    gain x 100
                11-12  gain5     unsigned short    gain x 100, reserved
                13-14  gain6     unsigned short    gain x 100, reserved
                15-16  gain7     unsigned short    gain x 100, reserved
                17-18  gain8     unsigned short    gain x 100, reserved
                19-20  gain9     unsigned short    gain x 100, reserved

        As of device firmware v2.1.3 gain6-gain10 inclusive are unused and reserved for future use.
        """

        if len(data) != 20:
            return {}

        results = dict()
        if fields is None:
            field = f"{MasterKeys.PIEZO}{MasterKeys.RAIN_GAIN}"
            for gain in range(10):
                results[f"{field}{gain}"] = self.decode_gain_100(data[gain * 2:gain * 2 + 2])
        else:
            gain = 0
            for field in fields:
                results[field] = self.decode_gain_100(data[gain * 2:gain * 2 + 2])
                gain += 1
        return results

    @staticmethod
    def decode_rain_reset(data, fields=None):
        """Decode rain reset data.

        Rain reset data is three bytes of data comprising three unsigned
        byte fields with each field representing an integer.

        The three bytes of rain reset data is allocated as follows:
        Byte  #  Data               Format         Comments
        byte  1  day reset time     unsigned byte  hour of the day to reset day rain, eg 7 = 07:00
              2  week reset time    unsigned byte  day of week to reset week rain, allowed values are 0 or 1. 0=Sunday, 1=Monday
              3  annual reset time  unsigned byte  month of year to reset annual rain, allowed values are 0-11, eg 2 = March
        """

        if len(data) != 3:
            return {}

        results = dict()
        if fields is None:
            field1 = DataPoints.RAIN_RST_DAY[0]
            field2 = DataPoints.RAIN_RST_WEEK[0]
            field3 = DataPoints.RAIN_RST_YEAR[0]
        else:
            field1 = fields[0]
            field2 = fields[1]
            field3 = fields[2]

        value1 = struct.unpack("B", data[0:1])[0]
        value2 = struct.unpack("B", data[1:2])[0]
        value3 = struct.unpack("B", data[2:3])[0]

        results[field1] = to_int(value1)
        results[field2] = ['Sunday', 'Monday'][to_int(value2)]
        results[field3] = to_int(value3) + 1
        return results

    @staticmethod
    def decode_batt(data, field=None):
        """Decode battery status data.

        GW1000 firmware version 1.6.4 and earlier supported 16 bytes of
        battery state data at response field x4C for the following sensors:
            WH24, WH25, WH26(WH32), WH31 ch1-8, WH40, WH41/WH43 ch1-4,
            WH51 ch1-8, WH55 ch1-4, WH57, WH68 and WS80

        As of GW1000 firmware version 1.6.5 the 16 bytes of battery state data is no longer returned at all (GW1100, GW2000 and later devices
        never provided this battery state data in this format).
        CMD_READ_SENSOR_ID_NEW or CMD_READ_SENSOR_ID must be used to obtain battery state information for connected sensors. The decode_batt()
        method has been retained to support devices using firmware version 1.6.4 and earlier.

        Since the gateway driver now obtains battery state information via CMD_READ_SENSOR_ID_NEW or CMD_READ_SENSOR_ID only the decode_batt()
        method now returns None so that firmware versions before 1.6.5 continue to be supported.
        """

        return None


class GatewayHttp(object):
    """Class to interact with a gateway device via HTTP requests."""

    # HTTP request commands
    commands = ['get_version', 'get_livedata_info', 'get_ws_settings', 'get_calibration_data', 'get_rain_totals', 'get_device_info',
                'get_sensors_info', 'get_network_info', 'get_units_info', 'get_cli_soilad', 'get_cli_multiCh',
                'get_cli_pm25', 'get_cli_co2', 'get_piezo_rain']

    def __init__(self, plugin_instance):
        """Initialise a HttpRequest object."""

        # get instance
        self._plugin_instance = plugin_instance
        self.logger = self._plugin_instance.logger

        # get interface config
        self.interface_config = self._plugin_instance.interface_config
        self.host = self.interface_config.ip_address
        self.port = self.interface_config.port
        self.timeout = self.interface_config.request_timeout
        self._session = requests.Session()

        self.parser = HttpParser(plugin_instance)

    def request(self, cmd: str, params: dict = None, result: str = 'json'):
        """Send a HTTP request to the device and return the response.

        Create a HTTP request with optional data and headers. Send the HTTP request to the device as a GET request and obtain the response. The
        JSON deserialized response is returned. If the response cannot be deserialized the value None is returned. URL or timeout errors are
        logged and raised.

        :param cmd:          cmd to be requested
        :param params:       params for request
        :param result:       type of result
        :return:             request response
        """

        def build_url() -> str:
            """
            Builds a request url
            :return: string of the url, dependent on settings of the FritzDevice
            """
            return f"http://{self.host}/{cmd}?"

        # an invalid command
        if cmd not in GatewayHttp.commands:
            raise UnknownHttpCommand(f"Unknown HTTP command '{cmd}'")

        url = build_url()

        try:
            rsp = self._session.get(url, params=params, timeout=self.timeout)
        except Exception as e:
            self.logger.error(f"Error during GET request {e} occurred.")
        else:
            status_code = rsp.status_code
            if status_code == 200:
                if DebugLogConfig.http:
                    self.logger.debug("Sending HTTP request successful")
                if result == 'json':
                    try:
                        data = rsp.json()
                    except JSONDecodeError:
                        self.logger.error('Error occurred during parsing request response to json')
                    else:
                        return data
                else:
                    return rsp.text.strip()
            elif status_code == 403:
                if DebugLogConfig.http:
                    self.logger.debug("HTTP access denied.")
            else:
                self.logger.error(f"HTTP request error code: {status_code}")
                rsp.raise_for_status()
                if DebugLogConfig.http:
                    self.logger.debug(f"Url: {url}, Params: {params}")

    def get_version(self):
        """Get the device firmware related information.

        Returns a dict or None if no valid data was returned by the device.

        {   "version":	"Version: GW1100A_V2.1.4",
            "newVersion":	"0",
            "platform":	"ecowitt"
        }
        """

        try:
            return self.request('get_version')
        except requests.exceptions.Timeout:
            return None

    def get_livedata_info(self):
        """Get live sensor data from the device.

        Returns a dict or None if no valid data was returned by the device."""

        try:
            return self.request('get_livedata_info')
        except requests.exceptions.Timeout:
            return None

    def get_ws_settings(self):
        """Get weather services settings from the device.

        Returns a dict or None if no valid data was returned by the device."""

        try:
            return self.request('get_ws_settings')
        except requests.exceptions.Timeout:
            return None

    def get_calibration_data(self):
        """Get calibration settings from the device.

        Returns a dict or None if no valid data was returned by the device."""

        try:
            return self.request('get_calibration_data')
        except requests.exceptions.Timeout:
            return None

    def get_rain_totals(self):
        """Get rainfall totals and settings from the device.

        Returns a dict or None if no valid data was returned by the device."""

        try:
            return self.request('get_rain_totals')
        except requests.exceptions.Timeout:
            return None

    def get_device_info(self):
        """Get device settings from the device.

        Returns a parsed dict or None if no valid data was returned by the device."""

        try:
            return self.parser.parse_device_info(self.get_device_info())
        except requests.exceptions.Timeout:
            return None

    def get_sensors_info(self):
        """Get sensor ID data from the device.

        Combines all pages of available data and returns a single dict or None if no valid data was returned by the device."""

        try:
            page_1 = self.request(cmd='get_sensors_info', params={'page': 1})
        except requests.exceptions.Timeout:
            page_1 = None
        try:
            page_2 = self.request(cmd='get_sensors_info', params={'page': 2})
        except requests.exceptions.Timeout:
            page_2 = None
        if page_1 is not None and page_2 is not None:
            return page_1 + page_2
        elif page_1 is None:
            return page_2
        else:
            return page_1

    def get_network_info(self):
        """Get network related data/settings from the device.

        Returns a dict or None if no valid data was returned by the device."""

        try:
            return self.request('get_network_info')
        except requests.exceptions.Timeout:
            return None

    def get_units_info(self):
        """Get units settings from the device.

        Returns a dict or None if no valid data was returned by the device."""

        try:
            return self.request('get_units_info')
        except requests.exceptions.Timeout:
            return None

    def get_cli_soilad(self):
        """Get multichannel soil moisture sensor calibration data from the device.

        Returns a list of dicts or None if no valid data was returned by the device."""

        try:
            return self.request('get_cli_soilad')
        except requests.exceptions.Timeout:
            return None

    def get_cli_multiCh(self):
        """Get multichannel temperature/humidity sensor calibration data from
        the device.

        Returns a list of dicts or None if no valid data was returned by the device."""

        try:
            return self.request('get_cli_multiCh')
        except requests.exceptions.Timeout:
            pass

    def get_cli_pm25(self):
        """Get PM2.5 sensor offset data from the device.

        Returns a list of dicts or None if no valid data was returned by the device."""

        try:
            return self.request('get_cli_pm25')
        except requests.exceptions.Timeout:
            return None

    def get_cli_co2(self):
        """Get CO2 sensor offset data from the device.

        Returns a list of dicts or None if no valid data was returned by the device."""

        try:
            return self.request('get_cli_co2')
        except requests.exceptions.Timeout:
            return None

    def get_piezo_rain(self):
        """Get piezo rain sensor data/settings from the device.

        Returns a dict or None if no valid data was returned by the device."""

        try:
            return self.request('get_piezo_rain')
        except requests.exceptions.Timeout:
            return None

    def get_model(self):
        """Get model and firmware information"""
        return self.parser.parse_version(self.get_version())

    def is_new_firmware_available(self):
        """Get information whether a new firmware is available."""

        return self.parser.parse_new_version(self.get_version())

    def get_livedata(self) -> dict:
        """Get live data and return parsed data as dict"""
        return self.parser.parse_livedata(self.get_livedata_info())


class HttpParser(object):
    """Class to parse Ecowitt Gateway sensor data."""

    # dict to match channels to senors
    sensor_names = {
        'common_list': {'name': MasterKeys.WN34, 'batt_fn': 'batt_int'},
        'piezoRain':   {'name': MasterKeys.WS90, 'batt_fn': 'batt_int'},
        'lightning':   {'name': MasterKeys.WH57, 'batt_fn': 'batt_int'},
        'co2':         {'name': MasterKeys.WH45, 'batt_fn': 'batt_int'},
        'wh25':        {'name': MasterKeys.WH25, 'batt_fn': 'batt_int'},
        'ch_pm25':     {'name': MasterKeys.WH41, 'batt_fn': 'batt_int'},
        'ch_leak':     {'name': MasterKeys.WH55, 'batt_fn': 'batt_int'},
        'ch_aisle':    {'name': MasterKeys.WH31, 'batt_fn': 'batt_int'},
        'ch_soil':     {'name': MasterKeys.WH51, 'batt_fn': 'batt_int'},
        'ch_temp':     {'name': MasterKeys.WN30, 'batt_fn': 'batt_int'},
        'ch_leaf':     {'name': MasterKeys.WN35, 'batt_fn': 'batt_int'},
        'rain':        {'name': MasterKeys.WH65, 'batt_fn': 'batt_int'},
    }

    http_live_data_struct = {
        '0x01': DataPoints.INTEMP[0],
        '0x02': DataPoints.OUTTEMP[0],
        '0x03': DataPoints.DEWPOINT[0],
        '0x04': DataPoints.WINDCHILL[0],
        '0x05': DataPoints.HEATINDEX[0],
        '0x06': DataPoints.INHUMI[0],
        '0x07': DataPoints.OUTHUMI[0],
        '0x08': DataPoints.ABSBARO[0],
        '0x09': DataPoints.RELBARO[0],
        '0x0A': DataPoints.WINDDIRECTION[0],
        '0x0B': DataPoints.WINDSPEED[0],
        '0x0C': DataPoints.GUSTSPEED[0],
        '0x0D': DataPoints.RAINEVENT[0],
        '0x0E': DataPoints.RAINRATE[0],
        '0x0F': DataPoints.RAINHOUR[0],
        '0x10': DataPoints.RAINDAY[0],
        '0x11': DataPoints.RAINWEEK[0],
        '0x12': DataPoints.RAINMONTH[0],
        '0x13': DataPoints.RAINYEAR[0],
        '0x14': DataPoints.RAINTOTALS[0],
        '0x15': DataPoints.LIGHT[0],
        '0x16': DataPoints.UV[0],
        '0x17': DataPoints.UVI[0],
        '0x18': DataPoints.TIME[0],
        '0x19': DataPoints.DAYLWINDMAX[0],
        'humidity': MasterKeys.HUMID,
        'temp': MasterKeys.TEMP,
        'status': MasterKeys.LEAK,
        'PM25': MasterKeys.PM25,
        'PM25_24HAQI': MasterKeys.PM25_AVG,
        'PM25_RealAQI': DataPoints.PM25_AQI[0],
        'CO2': DataPoints.SENSOR_CO2_CO2[0],
        'CO2_24H': DataPoints.SENSOR_CO2_CO2_24[0],
        'PM10': DataPoints.SENSOR_CO2_PM10[0],
        'PM10_24HAQI': DataPoints.SENSOR_CO2_PM10_24[0],
        'count': DataPoints.LIGHTNING_COUNT[0],
        'distance': DataPoints.LIGHTNING_DIST[0],
        'timestamp': DataPoints.LIGHTNING_TIME[0],
        'abs': DataPoints.ABSBARO[0],
        'inhumi': DataPoints.INHUMI[0],
        'intemp': DataPoints.INTEMP[0],
        'rel': DataPoints.RELBARO[0],
        'unit': None,
        'name': None,
        'PM10_RealAQI': None,
        'channel': None,
        'battery': None,
    }

    def __init__(self, plugin_instance):

        # get instance
        self._plugin_instance = plugin_instance
        self.logger = self._plugin_instance.logger

        # get interface config
        self.interface_config = self._plugin_instance.interface_config

        # do we log unknown fields at info or leave at debug
        self.log_unknown_fields = self.interface_config.log_unknown_fields

    def parse_livedata(self, data: dict):
        """
        Parse raw sensor live data from get_request.
        Parse the raw sensor data and create a dict of sensor observations/status data. Add a timestamp to the data if one does not already exist.
        """

        def parse_value(_val: str, unit: str = None, convert_to_si: bool = True):

            if unit:
                _val = f"{_val} {unit}"

            try:
                _value = float(_val)
                if _value % 1 == 0:
                    _value = int(_value)
            except ValueError:
                _value = _val.lstrip()
                if _value == 'None':
                    return
                elif _value.endswith('%'):
                    _value = parse_value(_value[:-1])
                elif ' ' in _value:
                    _value_var = _value.split(' ')
                    _value = parse_value(_value_var[0])
                    _unit = _value_var[1].lower()

                    if convert_to_si:
                        if _unit == 'mph':
                            _value = mph_to_ms(_value)
                        elif _unit == 'in':
                            _value = in_to_mm(_value)
                        elif _unit == 'inHg':
                            _value = in_to_hpa(_value)
                        elif _unit == 'f':
                            _value = f_to_c(_value)
                        elif _unit == 'mph':
                            _value = mph_to_ms(_value)
            return _value

        data_dict = dict()

        for entry in data:
            # parse sensor using sensor id
            if entry in ['common_list', 'rain', 'piezoRain']:
                for sensor in data[entry]:
                    key = self.http_live_data_struct.get(sensor['id'])
                    value = parse_value(sensor.get('val'), sensor.get('unit'))
                    if key:
                        data_dict.update({key: value})
                    else:
                        self.logger.info(f"Parsing for {sensor['id']=} not defined. {key=}, {value=}")

                    battery = sensor.get('battery')
                    if battery:
                        data_dict.update({f"{self.sensor_names[entry]['name'][0]}{MasterKeys.BATTERY_EXTENTION}": parse_value(battery)})

            # parse wh25
            elif entry in ['wh25']:
                for sensor in data[entry]:
                    for detail in sensor:
                        key = self.http_live_data_struct.get(detail)
                        if detail == 'intemp':
                            value = parse_value(sensor[detail], sensor.get('unit'))
                        else:
                            value = parse_value(sensor[detail])

                        if key and value is not None:
                            data_dict.update({key: value})
                        else:
                            self.logger.info(f"Parsing for {detail=} not defined. {key=}, {value=}")

            # parse sensors without channel
            elif entry in ['lightning', 'co2']:
                for sensor in data[entry]:
                    for detail in sensor:
                        if 'battery' in detail:
                            key = f"{self.sensor_names[entry]['name'][0]}{MasterKeys.BATTERY_EXTENTION}"
                            raw_value = parse_value(sensor[detail])
                            batt_fn = self.sensor_names[entry]['batt_fn']
                            value = getattr(self, batt_fn)(raw_value)
                        else:
                            key = self.http_live_data_struct[detail]
                            if detail in ['temp']:
                                value = parse_value(sensor[detail], sensor.get('unit'))
                            else:
                                value = parse_value(sensor[detail])

                        if key and value is not None:
                            data_dict.update({key: value})
                        else:
                            self.logger.info(f"Parsing for {detail=} not defined. {key=}, {value=}")

            # parse sensors with channels
            elif entry in ['ch_pm25', 'ch_leak', 'ch_soil', 'ch_temp', 'ch_leaf', 'ch_aisle']:
                for sensor in data[entry]:
                    channel = parse_value(sensor.get("channel"))
                    for detail in sensor:
                        value = None
                        if 'battery' in detail:
                            key = f"{self.sensor_names[entry]['name'][0]}{channel}{MasterKeys.BATTERY_EXTENTION}"
                            raw_value = parse_value(sensor[detail])
                            batt_fn = self.sensor_names[entry]['batt_fn']
                            value = getattr(self, batt_fn)(raw_value)
                        else:
                            key = self.http_live_data_struct.get(detail)
                            if key:
                                key = f"{key}{channel}"
                                if 'temp' in detail:
                                    value = parse_value(sensor[detail], sensor.get('unit'))
                                else:
                                    value = parse_value(sensor[detail])

                        if key and value is not None:
                            data_dict.update({key: value})
                        else:
                            self.logger.info(f"Parsing for {detail=} not defined. {key=}, {value=}")

        data_dict.update({'timestamp': int(time.time())})

        return data_dict

    @staticmethod
    def parse_version(data: dict) -> str:
        """extract current firmware version"""

        if isinstance(data, dict):
            version = data.get('version')
            if version and isinstance(version, str):
                return version.split(' ')[1]

    @staticmethod
    def parse_new_version(data: dict) -> bool:
        """extract availability of new firmware version"""

        if isinstance(data, dict):
            new_version = data.get('newVersion')
            if new_version:
                return bool(int(new_version))

    @staticmethod
    def batt_int(batt) -> int:
        """Decode an integer battery state."""

        return batt

    @staticmethod
    def parse_device_info(data):
        """Parse a get_device_info API response.

        Response consists of:
            "sensorType":	"1",
            "rf_freq":	"1",
            "tz_auto":	"0",
            "tz_name":	"Europe/Berlin",
            "tz_index":	"39",
            "dst_stat":	"1",
            "date":	"2023-08-12T18:56",
            "upgrade":	"0",
            "apAuto":	"1",
            "newVersion":	"1",
            "curr_msg":	"New version:V3.0.5\r\n1.Supports IOT device WFC01.\r\n2.Fixed an issue with incorrect rainfall.\r\n3.Support smart scene funtion.\r\n4.Fixed some known bug.",
            "apName":	"GW2000A-WIFI8BF3",
            "GW1100APpwd":	"",
            "time":	"20"
        """

        FREQUENCIES = ['433 MHz', '868 MHz', '915 MHz', '920 MHz']
        SENSOR_TYPES = ['WH24', 'WH65']

        data_dict = dict()
        data_dict['frequency'] = FREQUENCIES[int(data['rf_freq'])]
        data_dict['sensor_type'] = SENSOR_TYPES[int(data['sensorType'])]
        data_dict['dt'] = datetime.strptime(data['date'], '%Y-%m-%dT%H:%M')
        data_dict['timezone_index'] = data['tz_index']
        data_dict['dst_status'] = bool(int(data['dst_stat']))
        data_dict['upgrade'] = bool(int(data['upgrade']))
        data_dict['ap_auto'] = bool(int(data['apAuto']))
        data_dict['new_fw_version'] = bool(int(data['newVersion']))
        data_dict['new_fw_version_dec'] = data.get('curr_msg')
        data_dict['gw_name'] = data['apName']
        data_dict['gw_pwd'] = data['GW1100APpwd']
        data_dict['time'] = int(data['time'])
        return data_dict


class GatewayTcp(object):
    def __init__(self, plugin_instance, callback):

        # get instance
        self._plugin_instance = plugin_instance
        self.logger = self._plugin_instance.logger
        self.parser = TcpParser(plugin_instance)
        self.callback = callback

        # get interface config
        self.interface_config = self._plugin_instance.interface_config

        # define server thread
        self._server_thread = None

        # log the relevant settings/parameters we are using
        if DebugLogConfig.tcp:
            self.logger.debug("Starting GatewayTcp")

        # get tcp server object
        self.tcp_server = GatewayTcp.TCPServer(self.make_handler(self.parse_tcp_live_data), plugin_instance)
        
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
            self._server_thread.join(10)
            if self._server_thread.is_alive():
                self.logger.error("Unable to shut down Gateway-TCP-Server thread")
            else:
                self.logger.info("Gateway-TCP-Server thread has been shutdown.")
        self._server_thread = None

    def parse_tcp_live_data(self, data: str, client_ip: str) -> None:

        if DebugLogConfig.tcp:
            self.logger.debug(f"raw post_data={data}")

        data_dict = self.parser.parse_live_data(data, client_ip)

        if DebugLogConfig.tcp:
            self.logger.debug(f"parsed post_data={data_dict}")

        self.callback(data_dict)

    def make_handler(self, parse_method):

        class RequestHandler(BaseHTTPRequestHandler):
            def reply(self):
                ok_answer = "OK\n"
                self.send_response(200)
                self.send_header("Content-Length", str(len(ok_answer)))
                self.end_headers()
                self.wfile.write(ok_answer.encode())

            def do_POST(self):
                length = int(self.headers["Content-Length"])
                post_data = self.rfile.read(length).decode()
                self.reply()
                parse_method(post_data,  self.client_address[0])

            def do_PUT(self):
                pass

            def do_GET(self):
                data = urlparse.urlparse(self.path).query
                self.reply()

        return RequestHandler

    class TCPServer(socketserver.TCPServer):

        daemon_threads = True
        allow_reuse_address = True

        def __init__(self, handler, plugin_instance):
            # init instance
            self._plugin_instance = plugin_instance
            self.logger = self._plugin_instance.logger

            # get interface config
            self.interface_config = self._plugin_instance.interface_config
            address = self.interface_config.post_server_ip
            port = self.interface_config.post_server_port

            # init TCP Server
            self.logger.info(f"Init FoshkPlugin TCP Server at {address}:{port}")
            socketserver.TCPServer.__init__(self, (address, int(port)), handler)

        def run(self):
            if DebugLogConfig.tcp:
                self.logger.debug("Start FoshkPlugin TCP Server")
            self.serve_forever()

        def stop(self):
            if DebugLogConfig.tcp:
                self.logger.debug("Stop FoshkPlugin TCP Server")
            self.shutdown()
            self.server_close()


class TcpParser(object):
    """Class to parse Ecowitt Gateway sensor data coming via HTTP Post."""

    def __init__(self, plugin_instance):

        # get instance
        self._plugin_instance = plugin_instance
        self.logger = self._plugin_instance.logger

        # get interface config
        self.interface_config = self._plugin_instance.interface_config

        # do we log unknown fields at info or leave at debug
        self.log_unknown_fields = self.interface_config.log_unknown_fields

    def parse_live_data(self, data, client_ip):
        """Parse the ecowitt data and add it to a dictionary."""

        tcp_live_data_struct = {
            # Generic
            'client_ip': (None, None),
            'PASSKEY': (None, None),
            'stationtype': (None, DataPoints.FIRMWARE[0]),
            'freq': ('decode_freq', DataPoints.FREQ[0]),
            'model': (None, DataPoints.MODEL[0]),
            'dateutc': (utcdatetimestr_to_datetime, DataPoints.TIME[0]),
            'runtime': (None, DataPoints.RUNTIME[0]),
            'interval': (None, DataPoints.INTERVAL[0]),
            # Indoor
            'tempinf': (f_to_c, DataPoints.INTEMP[0]),
            'humidityin': (None, DataPoints.INHUMI[0]),
            'baromrelin': (in_to_hpa, DataPoints.RELBARO[0]),
            'baromabsin': (in_to_hpa, DataPoints.ABSBARO[0]),
            # WH 65 / WH24
            'tempf': (f_to_c, DataPoints.OUTTEMP[0]),
            'humidity': (None, DataPoints.OUTHUMI[0]),
            'winddir': (None, DataPoints.WINDDIRECTION[0]),
            'windspeedmph': (mph_to_ms, DataPoints.WINDSPEED[0]),
            'windgustmph': (mph_to_ms, DataPoints.GUSTSPEED[0]),
            'maxdailygust': (mph_to_ms, DataPoints.DAYLWINDMAX[0]),
            'solarradiation': (None, DataPoints.UV[0]),
            'uv': (None, DataPoints.UVI[0]),
            'rainratein': (in_to_mm, DataPoints.RAINRATE[0]),
            'eventrainin': (in_to_mm, DataPoints.RAINEVENT[0]),
            'hourlyrainin': (in_to_mm, DataPoints.RAINHOUR[0]),
            'dailyrainin': (in_to_mm, DataPoints.RAINDAY[0]),
            'weeklyrainin': (in_to_mm, DataPoints.RAINWEEK[0]),
            'monthlyrainin': (in_to_mm, DataPoints.RAINMONTH[0]),
            'yearlyrainin': (in_to_mm, DataPoints.RAINYEAR[0]),
            'totalrainin': (in_to_mm, DataPoints.RAINTOTALS[0]),
            'wh65batt': (None, f'wh65{MasterKeys.BATTERY_EXTENTION}'),
            # WH31
            'temp1f': (f_to_c, DataPoints.TEMP1[0]),
            'humidity1': (None, DataPoints.HUMI1[0]),
            'batt1': (None, f'wh31_ch1{MasterKeys.BATTERY_EXTENTION}'),
            'temp2f': (f_to_c, DataPoints.TEMP2[0]),
            'humidity2': (None, DataPoints.HUMI2[0]),
            'batt2': (None, f'wh31_ch2{MasterKeys.BATTERY_EXTENTION}'),
            'temp3f': (f_to_c, DataPoints.TEMP3[0]),
            'humidity3': (None, DataPoints.HUMI3[0]),
            'batt3': (None, f'wh31_ch3{MasterKeys.BATTERY_EXTENTION}'),
            'temp4f': (f_to_c, DataPoints.TEMP4[0]),
            'humidity4': (None, DataPoints.HUMI4[0]),
            'batt4': (None, f'wh31_ch4{MasterKeys.BATTERY_EXTENTION}'),
            'temp5f': (f_to_c, DataPoints.TEMP5[0]),
            'humidity5': (None, DataPoints.HUMI5[0]),
            'batt5': (None, f'wh31_ch5{MasterKeys.BATTERY_EXTENTION}'),
            'temp6f': (f_to_c, DataPoints.TEMP6[0]),
            'humidity6': (None, DataPoints.HUMI6[0]),
            'batt6': (None, f'wh31_ch6{MasterKeys.BATTERY_EXTENTION}'),
            'temp7f': (f_to_c, DataPoints.TEMP7[0]),
            'humidity7': (None, DataPoints.HUMI7[0]),
            'batt7': (None, f'wh31_ch7{MasterKeys.BATTERY_EXTENTION}'),
            'temp8f': (f_to_c, DataPoints.TEMP8[0]),
            'humidity8': (None, DataPoints.HUMI8[0]),
            'batt8': (None, f'wh31_ch8{MasterKeys.BATTERY_EXTENTION}'),
            # WN51
            'soilmoisture1': (None, DataPoints.SOILMOISTURE1[0]),
            'soilmoisture2': (None, DataPoints.SOILMOISTURE2[0]),
            'soilmoisture3': (None, DataPoints.SOILMOISTURE3[0]),
            'soilmoisture4': (None, DataPoints.SOILMOISTURE4[0]),
            'soilmoisture5': (None, DataPoints.SOILMOISTURE5[0]),
            'soilmoisture6': (None, DataPoints.SOILMOISTURE6[0]),
            'soilmoisture7': (None, DataPoints.SOILMOISTURE7[0]),
            'soilmoisture8': (None, DataPoints.SOILMOISTURE8[0]),
            'soilbatt1': (None, f'wh51_ch1{MasterKeys.BATTERY_EXTENTION}'),
            'soilbatt2': (None, f'wh51_ch2{MasterKeys.BATTERY_EXTENTION}'),
            'soilbatt3': (None, f'wh51_ch3{MasterKeys.BATTERY_EXTENTION}'),
            'soilbatt4': (None, f'wh51_ch4{MasterKeys.BATTERY_EXTENTION}'),
            'soilbatt5': (None, f'wh51_ch5{MasterKeys.BATTERY_EXTENTION}'),
            'soilbatt6': (None, f'wh51_ch6{MasterKeys.BATTERY_EXTENTION}'),
            'soilbatt7': (None, f'wh51_ch7{MasterKeys.BATTERY_EXTENTION}'),
            'soilbatt8': (None, f'wh51_ch8{MasterKeys.BATTERY_EXTENTION}'),
            # WH34
            'tf_ch1': (f_to_c, DataPoints.TF_USR1[0]),
            'tf_ch2': (f_to_c, DataPoints.TF_USR2[0]),
            'tf_ch3': (f_to_c, DataPoints.TF_USR3[0]),
            'tf_ch4': (f_to_c, DataPoints.TF_USR4[0]),
            'tf_ch5': (f_to_c, DataPoints.TF_USR5[0]),
            'tf_ch6': (f_to_c, DataPoints.TF_USR6[0]),
            'tf_ch7': (f_to_c, DataPoints.TF_USR7[0]),
            'tf_ch8': (f_to_c, DataPoints.TF_USR8[0]),
            # WH45
            'tf_co2': (f_to_c, DataPoints.SENSOR_CO2_TEMP[0]),
            'humi_co2': (None, DataPoints.SENSOR_CO2_HUM[0]),
            'pm10_co2': (None, DataPoints.SENSOR_CO2_PM10[0]),
            'pm10_24h_co2': (None, DataPoints.SENSOR_CO2_PM10_24[0]),
            'pm25_co2': (None, DataPoints.SENSOR_CO2_PM255[0]),
            'pm25_24h_co2': (None, DataPoints.SENSOR_CO2_PM255_24[0]),
            'co2': (None, DataPoints.SENSOR_CO2_CO2[0]),
            'co2_24h': (None, DataPoints.SENSOR_CO2_CO2_24[0]),
            'co2_batt': (None, f'wh45{MasterKeys.BATTERY_EXTENTION}'),
            # WH41 / WH43
            'pm25_ch1': (None, DataPoints.PM251[0]),
            'pm25_avg_24h_ch1': (None, DataPoints.PM25_24H_AVG1[0]),
            'pm25batt1': (to_int, f'pm251{MasterKeys.BATTERY_EXTENTION}'),
            'pm25_ch2': (None, DataPoints.PM252[0]),
            'pm25_avg_24h_ch2': (None, DataPoints.PM25_24H_AVG2[0]),
            'pm25batt2': (to_int, f'pm252{MasterKeys.BATTERY_EXTENTION}'),
            'pm25_ch3': (None, DataPoints.PM253[0]),
            'pm25_avg_24h_ch3': (None, DataPoints.PM25_24H_AVG3[0]),
            'pm25batt3': (to_int, f'pm253{MasterKeys.BATTERY_EXTENTION}'),
            'pm25_ch4': (None, DataPoints.PM254[0]),
            'pm25_avg_24h_ch4': (None, DataPoints.PM25_24H_AVG4[0]),
            'pm25batt4': (to_int, f'pm254{MasterKeys.BATTERY_EXTENTION}'),
            # WH55
            'leak_ch1': (Utils.to_bool, DataPoints.LEAK1[0]),
            'leak_ch2': (Utils.to_bool, DataPoints.LEAK2[0]),
            'leak_ch3': (Utils.to_bool, DataPoints.LEAK3)[0],
            'leak_ch4': (Utils.to_bool, DataPoints.LEAK4[0]),
            'leakbatt1': (None, f'wh55_ch1{MasterKeys.BATTERY_EXTENTION}'),
            'leakbatt2': (None, f'wh55_ch2{MasterKeys.BATTERY_EXTENTION}'),
            'leakbatt3': (None, f'wh55_ch3{MasterKeys.BATTERY_EXTENTION}'),
            'leakbatt4': (None, f'wh55_ch4{MasterKeys.BATTERY_EXTENTION}'),
            # WH25
            'wh25batt': (to_int, f'wh25{MasterKeys.BATTERY_EXTENTION}'),
            # WH26
            'wh26batt': (to_int, f'wh26{MasterKeys.BATTERY_EXTENTION}'),
            # WH57
            'lightning_day': (None, DataPoints.LIGHTNING_COUNT[0]),
            'lightning_distance': (None, DataPoints.LIGHTNING_DIST[0]),
            'lightning_time': (None, DataPoints.LIGHTNING_TIME[0]),
            # WH68
            'wh68batt': (to_float, f'wh68{MasterKeys.BATTERY_EXTENTION}'),
            # WH40
            'wh40batt': (to_float, f'wh40{MasterKeys.BATTERY_EXTENTION}'),
        }

        # convert string to dict
        raw_data_dict = {}
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
                raw_data_dict[key] = value
        raw_data_dict.update({'client_ip': client_ip})

        # Harmonize key names and convert into metric units
        data_dict = {}
        for key in raw_data_dict:
            try:
                decoder, field = tcp_live_data_struct[key]
            except KeyError:
                _msg = f"Unknown key '{key}' with value '{raw_data_dict[key]}'detected. Try do decode remaining sensor data."
                if self.log_unknown_fields:
                    self.logger.info(_msg)
                else:
                    if DebugLogConfig.tcp:
                        self.logger.debug(_msg)
                pass
            else:
                if field is None:
                    continue

                if decoder:
                    if isinstance(decoder, str):
                        data_dict[field] = getattr(self, decoder)(raw_data_dict[key])
                    else:
                        data_dict[field] = decoder(raw_data_dict[key])
                else:
                    data_dict[field] = raw_data_dict[key]

        self.logger.info(f"POST: convert_data {data_dict=}")

        return data_dict

    @staticmethod
    def decode_freq(freq):
        return f"{freq[:-1]} MHz"

    @staticmethod
    def clean_data(data):
        """Delete unused keys"""

        _unused_keys = [DataPoints.PASSKEY[0], DataPoints.FIRMWARE[0], DataPoints.FREQ[0], DataPoints.MODEL[0],
                        DataPoints.CLIENT_IP[0]]

        for key in data:
            if key.lower() in _unused_keys:
                data.pop(key)
        return data


class Sensors(object):
    """Class to manage device sensor ID data.

    Class Sensors allows access to various elements of sensor ID data via a number of properties and methods when the class is initialised with the
    device response to a CMD_READ_SENSOR_ID_NEW or CMD_READ_SENSOR_ID API command.

    A Sensors object can be initialised with sensor ID data on instantiation or an existing Sensors object can be updated by calling
    the set_sensor_id_data() method and passing the sensor ID data to be used as the only parameter.
    """

    # map of sensor ids to (short name, long name) and battery byte decode function
    sensor_ids = {
        b'\x00': {'name': SensorKeys.WH65,   'batt_fn': 'batt_binary'},
        b'\x01': {'name': SensorKeys.WS68,   'batt_fn': 'batt_volt'},
        b'\x02': {'name': SensorKeys.WS80,   'batt_fn': 'batt_volt'},
        b'\x03': {'name': SensorKeys.WH40,   'batt_fn': 'wh40_batt_volt'},
        b'\x04': {'name': SensorKeys.WH25,   'batt_fn': 'batt_binary'},
        b'\x05': {'name': SensorKeys.WN26,   'batt_fn': 'batt_binary'},
        b'\x06': {'name': SensorKeys.WH31_1, 'batt_fn': 'batt_binary'},
        b'\x07': {'name': SensorKeys.WH31_2, 'batt_fn': 'batt_binary'},
        b'\x08': {'name': SensorKeys.WH31_3, 'batt_fn': 'batt_binary'},
        b'\x09': {'name': SensorKeys.WH31_4, 'batt_fn': 'batt_binary'},
        b'\x0a': {'name': SensorKeys.WH31_5, 'batt_fn': 'batt_binary'},
        b'\x0b': {'name': SensorKeys.WH31_6, 'batt_fn': 'batt_binary'},
        b'\x0c': {'name': SensorKeys.WH31_7, 'batt_fn': 'batt_binary'},
        b'\x0d': {'name': SensorKeys.WH31_8, 'batt_fn': 'batt_binary'},
        b'\x0e': {'name': SensorKeys.WH51_1, 'batt_fn': 'batt_volt_tenth'},
        b'\x0f': {'name': SensorKeys.WH51_2, 'batt_fn': 'batt_volt_tenth'},
        b'\x10': {'name': SensorKeys.WH51_3, 'batt_fn': 'batt_volt_tenth'},
        b'\x11': {'name': SensorKeys.WH51_4, 'batt_fn': 'batt_volt_tenth'},
        b'\x12': {'name': SensorKeys.WH51_5, 'batt_fn': 'batt_volt_tenth'},
        b'\x13': {'name': SensorKeys.WH51_6, 'batt_fn': 'batt_volt_tenth'},
        b'\x14': {'name': SensorKeys.WH51_7, 'batt_fn': 'batt_volt_tenth'},
        b'\x15': {'name': SensorKeys.WH51_8, 'batt_fn': 'batt_volt_tenth'},
        b'\x16': {'name': SensorKeys.WH41_1, 'batt_fn': 'batt_int'},
        b'\x17': {'name': SensorKeys.WH41_2, 'batt_fn': 'batt_int'},
        b'\x18': {'name': SensorKeys.WH41_3, 'batt_fn': 'batt_int'},
        b'\x19': {'name': SensorKeys.WH41_4, 'batt_fn': 'batt_int'},
        b'\x1a': {'name': SensorKeys.WH57,   'batt_fn': 'batt_int'},
        b'\x1b': {'name': SensorKeys.WH55_1, 'batt_fn': 'batt_int'},
        b'\x1c': {'name': SensorKeys.WH55_2, 'batt_fn': 'batt_int'},
        b'\x1d': {'name': SensorKeys.WH55_3, 'batt_fn': 'batt_int'},
        b'\x1e': {'name': SensorKeys.WH55_4, 'batt_fn': 'batt_int'},
        b'\x1f': {'name': SensorKeys.WN34_1, 'batt_fn': 'batt_volt'},
        b'\x20': {'name': SensorKeys.WN34_2, 'batt_fn': 'batt_volt'},
        b'\x21': {'name': SensorKeys.WN34_3, 'batt_fn': 'batt_volt'},
        b'\x22': {'name': SensorKeys.WN34_4, 'batt_fn': 'batt_volt'},
        b'\x23': {'name': SensorKeys.WN34_5, 'batt_fn': 'batt_volt'},
        b'\x24': {'name': SensorKeys.WN34_6, 'batt_fn': 'batt_volt'},
        b'\x25': {'name': SensorKeys.WN34_7, 'batt_fn': 'batt_volt'},
        b'\x26': {'name': SensorKeys.WN34_8, 'batt_fn': 'batt_volt'},
        b'\x27': {'name': SensorKeys.WH45,   'batt_fn': 'batt_int'},
        b'\x28': {'name': SensorKeys.WN35_1, 'batt_fn': 'batt_volt'},
        b'\x29': {'name': SensorKeys.WN35_2, 'batt_fn': 'batt_volt'},
        b'\x2a': {'name': SensorKeys.WN35_3, 'batt_fn': 'batt_volt'},
        b'\x2b': {'name': SensorKeys.WN35_4, 'batt_fn': 'batt_volt'},
        b'\x2c': {'name': SensorKeys.WN35_5, 'batt_fn': 'batt_volt'},
        b'\x2d': {'name': SensorKeys.WN35_6, 'batt_fn': 'batt_volt'},
        b'\x2e': {'name': SensorKeys.WN35_7, 'batt_fn': 'batt_volt'},
        b'\x2f': {'name': SensorKeys.WN35_8, 'batt_fn': 'batt_volt'},
        b'\x30': {'name': SensorKeys.WS90,   'batt_fn': 'batt_volt', 'low_batt': 3}
    }
    # sensors for which there is no low battery state
    no_low = ['ws80', 'ws90']

    # Tuple of sensor ID values for sensors that are not registered with the device.
    # 'fffffffe' means the sensor is disabled, 'ffffffff' means the sensor is registering.
    not_registered = ('fffffffe', 'ffffffff')

    def __init__(self, plugin_instance, sensor_id_data=None):

        # get instance
        self._plugin_instance = plugin_instance
        self.logger = self._plugin_instance.logger

        # get interface config
        self.interface_config = self._plugin_instance.interface_config

        # If WH32 sensor is used, decode that, otherwise it will decode to WH26 by default
        if self.interface_config.use_wh32:
            # set the WH24 sensor id decode dict entry
            self.sensor_ids[b'\x05']['name'] = SensorKeys.WH32

        # Tell our sensor id decoding whether we have a WH24 or a WH65. By default, we are coded to use a WH65.
        if self.interface_config.is_wh24:
            # set the WH24 sensor id decode dict entry
            self.sensor_ids[b'\x00']['name'] = SensorKeys.WH24

        # do we ignore battery state data from legacy WH40 sensors that do not provide valid battery state data
        self.ignore_wh40_batt = self.interface_config.ignore_wh40_batt

        # set the show_battery property
        self.show_battery = self.interface_config.show_battery

        # initialise legacy WH40 flag
        self.legacy_wh40 = None

        # initialise a dict to hold the parsed sensor data
        self.sensor_data = dict()

        # parse the raw sensor ID data and store the results in my parsed sensor data dict
        self.set_sensor_id_data(sensor_id_data)

    def set_sensor_id_data(self, id_data):
        """Parse the raw sensor ID data and store the results.

        id_data: bytestring of sensor ID data
        """

        self.sensor_data = {}
        # do we have any raw sensor ID data
        if id_data is not None and len(id_data) > 0:
            # determine the size of the sensor id data, it's a big endian short (two byte) integer at bytes 4 and 5
            data_size = struct.unpack(">H", id_data[3:5])[0]
            # extract the actual sensor id data
            data = id_data[5:5 + data_size - 4]
            index = 0
            # iterate over the data
            while index < len(data):
                # get the sensor address
                address = data[index:index + 1]
                # do we know how to decode this address
                if address in Sensors.sensor_ids.keys():
                    sensor_id = bytes_to_hex(data[index + 1: index + 5], separator='', caps=False)
                    batt_fn = Sensors.sensor_ids[data[index:index + 1]]['batt_fn']
                    batt = data[index + 5]
                    if not self.show_battery and data[index + 6] == 0:
                        batt_state = None
                    else:
                        batt_state = getattr(self, batt_fn)(batt)
                    self.sensor_data[address] = {'id': sensor_id,
                                                 'battery': batt_state,
                                                 'signal': data[index + 6]
                                                 }
                else:
                    self.logger.info(f"Unknown sensor ID '{bytes_to_hex(address)}'")
                # each sensor entry is seven bytes in length so skip to the start of the next sensor
                index += 7

    def get_addresses(self):
        """Obtain a list of sensor addresses.

        This includes all sensor addresses reported by the device, this includes:
        - sensors that are actually connected to the device
        - sensors that are attempting to connect to the device
        - device sensor addresses that are searching for a sensor
        - device sensor addresses that are disabled
        """

        # this is simply the list of keys to our sensor data dict
        return self.sensor_data.keys()

    def get_connected_addresses(self) -> list:
        """Obtain a list of sensor addresses for connected sensors only.

        Sometimes we only want a list of addresses for sensors that are actually connected to the gateway device. We can filter out those
        addresses that do not have connected sensors by looking at the sensor ID. If the sensor ID is 'fffffffe' either the sensor is
        connecting to the device or the device is searching for a sensor for that address. If the sensor ID is 'ffffffff' the device sensor
        address is disabled.
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

    def get_data(self):
        """Obtain the data dict for all known sensors."""

        return self.sensor_data

    def get_id(self, address):
        """Obtain the sensor ID for a given sensor address."""

        return self.sensor_data[address]['id']

    def get_battery_state(self, address):
        """Obtain the sensor battery state for a given sensor address."""

        return self.sensor_data[address]['battery']

    def get_signal_level(self, address):
        """Obtain the sensor signal level for a given sensor address."""

        return self.sensor_data[address]['signal']

    def get_battery_and_signal_data(self) -> dict:
        """Obtain a dict of sensor battery state and signal level data.

        Iterate over the list of connected sensors and obtain a dict of sensor battery state data for each connected sensor.
        """

        data = {}
        for sensor in self.get_connected_addresses():
            sensor_name = Sensors.sensor_ids[sensor]['name'][0]
            data[f'{sensor_name}{MasterKeys.BATTERY_EXTENTION}'] = self.get_battery_state(sensor)
            data[f'{sensor_name}{MasterKeys.SIGNAL_EXTENTION}'] = self.get_signal_level(sensor)
        return data

    def get_battery_description_data(self) -> dict:
        """
        Obtain a dict of sensor battery state description data.

        Iterate over the list of connected sensors and obtain a dict of sensor battery state description data for each connected sensor.
        """

        data = {}
        for sensor in self.get_connected_addresses():
            sensor_name = self.sensor_ids[sensor]['name'][0]
            data[sensor_name] = self.get_batt_state_desc(sensor, self.get_battery_state(sensor))

        return data

    @staticmethod
    def get_batt_state_desc(address, value: float) -> Union[str, None]:
        """Determine the battery state description for a given sensor.

        Given a sensor address and battery state value determine appropriate battery state descriptive text, eg 'low', 'OK' etc.
        Descriptive text is based on Ecowitt API documentation. None is returned for sensors for which the API documentation provides no
        suitable battery state data, or for which descriptive battery state text cannot be inferred.

        A battery state value of None should not occur but if received the descriptive text 'unknown' is returned.
        """

        if value is None:
            return 'Unknown'

        if Sensors.sensor_ids[address].get('name') in Sensors.no_low:
            # we have a sensor for which no low battery cut-off data exists
            return None

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

    @staticmethod
    def batt_binary(batt) -> bool:
        """Decode a binary battery state.

        Battery state is stored in bit 0 as either 0 or 1. If 1 the battery is low, if 0 the battery is normal. We need to mask off bits 1 to 7 as
        they are not guaranteed to be set in any particular way.
        """

        return batt & 1

    @staticmethod
    def batt_int(batt) -> int:
        """Decode a integer battery state.

        According to the API documentation battery state is stored as an integer from 0 to 5 with <=1 being considered low. Experience with
        WH43 has shown that battery state 6 also exists when the device is run from DC. This does not appear to be documented in the API
        documentation.
        """

        return batt

    @staticmethod
    def batt_volt(batt) -> float:
        """Decode a voltage battery state in 2mV increments.

        Battery state is stored as integer values of battery voltage/0.02 with <=1.2V considered low.
        """

        return round(0.02 * batt, 2)

    def wh40_batt_volt(self, batt) -> Union[float, None]:
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
            # assume we have a non-battery state reporting WH40 first set the legacy_wh40 flag
            self.legacy_wh40 = True
            # then do we ignore the result or pass it on
            if self.ignore_wh40_batt:
                # we are ignoring the result so return None
                return None
            else:
                # we are not ignoring the result so return the result
                return round(0.1 * batt, 1)
        else:
            # assume we have a battery state reporting WH40 first reset the legacy_wh40 flag
            self.legacy_wh40 = False
            return round(0.01 * batt, 2)

    @staticmethod
    def batt_volt_tenth(batt) -> float:
        """Decode a voltage battery state in 100mV increments.

        Battery state is stored as integer values of battery voltage/0.1 with <=1.2V considered low.
        """

        return round(0.1 * batt, 1)


# ============================================================================
#                             Utility functions
# ============================================================================


def natural_sort_dict(source_dict: dict) -> dict:
    """
    Return a dict sorted naturally by key.
    """
    return dict(sorted(source_dict.items()))


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


def byte_to_int(rawbytes: bytes, signed: bool = False) -> int:
    """
    Convert bytearray to value with respect to sign format

    :parameter rawbytes: Bytes to convert
    :parameter signed: True if result should be a signed int, False for unsigned

    """

    return int.from_bytes(rawbytes, byteorder='little', signed=signed)


def int_to_bytes(value: int, length: int = 1, signed: bool = False) -> bytes:
    """
    Convert value to bytearray with respect to defined length and sign format.
    Value exceeding limit set by length and sign will be truncated

    :parameter value: Value to convert
    :parameter length: number of bytes to create
    :parameter signed: True if result should be a signed int, False for unsigned
    :return: Converted value

    """

    value = value % (2 ** (length * 8))
    return value.to_bytes(length, byteorder='big', signed=signed)


def timestamp_to_string(ts: int, format_str: str = "%Y-%m-%d %H:%M:%S %Z") -> Union[str, None]:
    """Return a string formatted from the timestamp"""

    if ts is not None:
        return "%s (%d)" % (time.strftime(format_str, time.localtime(ts)), ts)
    else:
        return "******* N/A *******     (    N/A   )"


def ver_str_to_num(s: str) -> Union[None, int]:
    """Extract Version Number of Firmware out of String"""

    try:
        vpos = s.index("V")+1
        return int(s[vpos:].replace(".", ""))
    except ValueError:
        return


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


def utcdatetimestr_to_datetime(utc_datetime_str: str) -> Union[datetime, None]:
    """Decodes string in datetime format to datetime object"""
    try:
        dt = datetime.strptime(utc_datetime_str, "%Y-%m-%d+%H:%M:%S").replace(tzinfo=timezone.utc).astimezone(tz=None)
    except ValueError:
        return None
    else:
        return dt


def datetime_to_string(dt: datetime) -> str:
    """Converts datetime object to string"""
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def utc_to_local(utc_dt: datetime) -> datetime:
    return utc_dt.replace(tzinfo=timezone.utc).astimezone(tz=None)
