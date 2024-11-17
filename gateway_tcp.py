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

import socketserver
import threading
from http.server import BaseHTTPRequestHandler
import urllib.parse as urlparse

from lib.utils import Utils

from .config import *
from .utility import *
from .meteocalcs import *
from .datapoints import *


class GatewayTcp(object):
    def __init__(self, plugin_instance, callback):

        # get instance
        self._plugin_instance = plugin_instance
        self.logger = self._plugin_instance.logger

        # init parser
        self.parser = TcpParser(plugin_instance)

        # init callback
        self.callback = callback

        # get interface config
        self.gw_config = self._plugin_instance.gw_config

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

            # get gateway config
            self.gw_config = self._plugin_instance.gw_config
            address = self.gw_config.post_server_ip
            port = self.gw_config.post_server_port

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
    """Class to parse Ecowitt Gateway sensor data coming via HTTP Post.

    This is when a custom upload server is set up in the gateway device.
    Normally this would upload data to ecowitt.net, Wunderground, Weathercloud, WeatherObservationsWebsite but can be set up to send in ecowitt or wunderground format
    As the gateway pushes the data regularly its about the same as when polling the API.
    """

    # Dictionary of 'address' based data. Dictionary is keyed by device data field 'address' containing various parameters for each 'address'.
    # Dictionary tuple format is: (decode fn, size, field name) where:
    #   decode fn:  the decode function name to be used for the field
    #   field name: the name of the device field to be used for the decoded data

    tcp_data_struct = {
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
        'tf_co2':   (f_to_c, DataPoints.SENSOR_CO2_TEMP[0]),
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

    def __init__(self, plugin_instance):

        # get instance
        self._plugin_instance = plugin_instance
        self.logger = self._plugin_instance.logger

        # get interface config
        self.gw_config = self._plugin_instance.gw_config

        # do we log unknown fields at info or leave at debug
        self.log_unknown_fields = self.gw_config.log_unknown_fields

    def parse_live_data(self, data, client_ip):
        """Parse the ecowitt data and add it to a dictionary."""

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
                _decoder, _field = self.tcp_data_struct[key]
            except KeyError:
                _msg = f"Unknown key '{key}' with value '{raw_data_dict[key]}'detected. Try do decode remaining sensor data."
                if self.log_unknown_fields:
                    self.logger.info(_msg)
                else:
                    if DebugLogConfig.tcp:
                        self.logger.debug(_msg)
                pass
            else:
                if _field is None:
                    continue

                if _decoder:
                    if isinstance(_decoder, str):
                        data_dict[_field] = getattr(self, _decoder)(raw_data_dict[key])
                    else:
                        data_dict[_field] = _decoder(raw_data_dict[key])
                else:
                    data_dict[_field] = raw_data_dict[key]

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
