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
import logging

from .webif import WebInterface

import socket
import sys
import datetime
import math
import threading
import json
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
import socketserver as SocketServer
import re
import queue

from datetime import datetime


DRIVER_NAME = 'ecowitt'
DRIVER_VERSION = '1.2'

DEFAULT_ADDR = ''
DEFAULT_PORT = 8000

class ecowittDriver():

    my_queue = queue.Queue()

    def __init__(self, host, port, handler, plugin_instance):
    
        self._plugin_instance = plugin_instance
        self._plugin_instance.logger.debug("starting ecowittDriver")
        self.poll_interval = 2.5

        self._server = self.TCPServer(host, port, handler)
        self._server_thread = \
            threading.Thread(target=self.run_server)
        self._server_thread.setDaemon(True)
        self._server_thread.setName('ServerThread')
        self._server_thread.start()
        self._queue_timeout = 10

    def run_server(self):
        self._server.run()

    def stop_server(self):
        self._server.stop()
        self._server = None

    def get_queue(self):
        return self.my_queue

    class Server(object):

        def run(self):
            pass

        def stop(self):
            pass

    class Handler(BaseHTTPRequestHandler):

        def reply(self):
            # standard reply is HTTP code of 200 and the response string
            OKanswer = "OK\n"
            self.send_response(200)
            self.send_header('Content-Type','text/html')
            self.send_header('Content-Length',str(len(OKanswer)))
            self.send_header('Connection','Close')
            self.end_headers()

        def do_POST(self):
            # get the payload from an HTTP POST
            length = int(self.headers['Content-Length'])
            data = str(self.rfile.read(length))
            self._plugin_instance.logger.debug('POST: %s' % self._obfuscate_passwords(data))
            self.my_queue.put(data)
            self.reply()

        def do_PUT(self):
            pass

        def do_GET(self):
            # get the query string from an HTTP GET
            data = urlparse.urlparse(self.path).query
            self._plugin_instance.logger.debug('GET: %s' % self._obfuscate_passwords(data))
            self.my_queue.put(data)
            self.reply()

    class TCPServer(Server, SocketServer.TCPServer):

        daemon_threads = True
        allow_reuse_address = True

        def __init__(self, address, port, handler, ):
            if handler is None:
                handler = ecowittDriver.Handler
            # self._plugin_instance.logger.info('listen on %s:%s' % (address, port))
            SocketServer.TCPServer.__init__(self, (address, int(port)), handler)

        def run(self):
            # self._plugin_instance.logger.debug('start tcp server')
            self.serve_forever()

        def stop(self):
            # self._plugin_instance.logger.debug('stop tcp server')
            self.shutdown()
            self.server_close()

    def genLoopPackets(self):
        while True:
            try:
                self._plugin_instance.logger.debug(datetime.now())
                pkt = {}
                data = self.get_queue().get(True, self._queue_timeout)
                self._plugin_instance.logger.debug(f"data: {data}")
                parts = data.split('&')
                self._plugin_instance.logger.debug(f"parts: {parts}")
            except queue.Empty:
                pass

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

        # get the parameters for the plugin (as defined in metadata plugin.yaml):
        self._socket_addr = self.get_parameter_value('Server_IP')
        self._socket_port = self.get_parameter_value('Port')
        # self._cycle = self.get_parameter_value('cycle')

        # Initialization code goes here
        self.data_dict_im = {}                             # dict to hold all information gotten from weatherstation gateway in imperial units
        self.data_dict_me = {}                             # dict to hold all information gotten from weatherstation gateway in metric units

        self._socket = None
        self.connection = None
        self.adress = None

        self.alive = None
        self.is_connected = 'False'
        self.battery_warning = False
        self._altitude = 435
        self._handler = None
        
        

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
        # self.scheduler_add('poll_device', self.poll_device, cycle=self._cycle)

        self.alive = True
        # if you need to create child threads, do not make them daemon = True!
        # They will not shutdown properly. (It's a python bug)

        driver = ecowittDriver(self._socket_addr, self._socket_port, self._handler, self)
        self.logger.debug(f"driver: {driver}")
        
        driver.genLoopPackets()
        
        # self.connect()
        # if self.is_connected is True:
            # self.listing()

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

        self.disconnect()

    def connect(self):
        self.logger.debug(f"{self.get_shortname()}: Try to create socket at {self._socket_addr}:{self._socket_port}")
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.logger.debug(f"{self.get_shortname()}: Socket created")

        try:
            self._socket.bind((self._socket_addr, self._socket_port))
            self.logger.debug(f"{self.get_shortname()}: Binding to {self._socket_addr}:{self._socket_port} established.")
            self.is_connected = True
        except socket.error as message:
            self.is_connected = False
            self.logger.debug(f"{self.get_shortname()}: Bind failed; ErrorMessage: {message}")
            sys.exit()
        self.logger.debug(f"{self.get_shortname()}: Socket binding operation completed")

    def listing(self):
        self._socket.listen(9)
        self.logger.debug(f"{self.get_shortname()}: Listening on socket")
        while self.is_connected is True:
            self.connection, self.adress = self._socket.accept()
            self.logger.debug(f"{self.get_shortname()}: Connected with: {self.adress[0]}:{self.adress[1]}")
            with self.connection:
                while True:
                    data = self.connection.recv(1024)
                    if not data:
                        break
                    # self.logger.debug(f"{self.get_shortname()}: data={data}")
                    self._parse_ecowitt_data_to_dict(data)

    def disconnect(self):
        if self.is_connected is True:
            self.connection.close()
            self.logger.debug(f"{self.get_shortname()}: Connection closed")

            socket.socket(socket.AF_INET, socket.SOCK_STREAM).connect((self._socket_addr, self._socket_port))
            self._socket.close()
            self.logger.debug(f"{self.get_shortname()}: Socket closed")

            self.is_connected = False

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
        
    def _obfuscate_passwords(self, msg):
        return re.sub(r'(PASSWORD|PASSKEY)=[^&]+', r'\1=XXXX', msg)

    def _get_as_float(self, d, s):
        v = None
        if s in d:
            try:
                v = float(d[s])
            except ValueError as e:
                self.logger.error("cannot read value for '%s': %s" % (s, e))
        return v

    def loader(self, config_dict, engine):
        return ecowittDriver(**config_dict[DRIVER_NAME])

