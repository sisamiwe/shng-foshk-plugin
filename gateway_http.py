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

from json import JSONDecodeError

import requests

import lib.env as env

from .exceptions import *
from .config import *
from .datapoints import *
from .utility import *
from .meteocalcs import *


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
        self.gw_config = self._plugin_instance.gw_config

        # create request session
        self._session = requests.Session()

        # init parser
        self.parser = HttpParser(plugin_instance)

    def request(self, cmd: str, params: dict = None, result: str = 'json'):
        """Send an HTTP request to the device and return the response.

        Create an HTTP request with optional data and headers. Send the HTTP request to the device as a GET request and obtain the response. The
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
            return f"http://{self.gw_config.ip_address}/{cmd}?"

        # an invalid command
        if cmd not in GatewayHttp.commands:
            raise UnknownHttpCommand(f"Unknown HTTP command '{cmd}'")

        url = build_url()

        try:
            rsp = self._session.get(url, params=params, timeout=self.gw_config.request_timeout)
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

    http_data_struct = {
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
        self.gw_config = self._plugin_instance.interface_config

        # do we log unknown fields at info or leave at debug
        self.log_unknown_fields = self.gw_config.log_unknown_fields

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
                            _value = env.f_to_c(_value)
                        elif _unit == 'mph':
                            _value = mph_to_ms(_value)
            return _value

        data_dict = dict()

        for entry in data:
            # parse sensor using sensor id
            if entry in ['common_list', 'rain', 'piezoRain']:
                for sensor in data[entry]:
                    key = self.http_data_struct.get(sensor['id'])
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
                        key = self.http_data_struct.get(detail)
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
                            key = self.http_data_struct[detail]
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
                            key = self.http_data_struct.get(detail)
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
