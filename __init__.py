#!/usr/bin/env python3
# vim: set encoding=utf-8 tabstop=4 softtabstop=4 shiftwidth=4 expandtab
#########################################################################
#  Copyright 2022-      Michael Wenzel              wenzel_michael@web.de
#########################################################################
#  This file is part of SmartHomeNG.
#  https://www.smarthomeNG.de
#  https://knx-user-forum.de/forum/supportforen/smarthome-py
#
#  Plugin to connect to Foshk Weather Gateway .
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

import logging
import re
import socket
import struct
import threading
import time
import queue

# logger = logging.getLogger(__name__)

# SET GLOBAL DEFAULTS
# default network broadcast address - the address that network broadcasts are sent to
default_broadcast_address = '255.255.255.255'
# default network broadcast port - the port that network broadcasts are sent to
default_broadcast_port = 46000
# default socket timeout
default_socket_timeout = 2
# default broadcast timeout
default_broadcast_timeout = 5
# default retry/wait time
default_retry_wait = 10
# default max tries when polling the API
default_max_tries = 3
# When run as a service the default age in seconds after which GW1000/GW1100 API data is considered stale and will not be used to augment loop packets
default_max_age = 60
# firmware update url
fw_update_url = 'http://download.ecowitt.net/down/filewave?v=FirwaveReadme.txt'.replace("\"", "")


class Foshk(SmartPlugin):
    """
    Main class of the Plugin. Does all plugin specific stuff and provides the update functions for the items

    """

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

        # Call init code of parent class (SmartPlugin)
        super().__init__()
        
        # Get the parameters for the plugin (as defined in metadata plugin.yaml):
        self._broadcast_address = None
        self._broadcast_port = None
        self._gateway_address = self.get_parameter_value('Gateway_IP') if self.get_parameter_value('Gateway_IP') != '255.255.255.255' else None
        self._gateway_port = self.get_parameter_value('Gateway_Port') if self.get_parameter_value('Gateway_Port') != 0 else None
        self._gateway_poll_interval = self.get_parameter_value('Gateway_Poll_Interval')
        
        # Define variables
        self.items = {}                                                             # dict to hold Items using Plugin attribute
        self.data_dict = {}                                                         # dict to hold all live data gotten from weatherstation gateway
        self.gateway_connected = False
        self._altitude = self.get_sh()._elev
        self.thread = None                                                          # create a thread property            

        # Initialization code goes here
        
        # get a Gw1000Driver object
        try:
            self.driver = Gw1000Driver(self)
            self.logger.debug(f"Interrogating {self.driver.collector.station.model} at {self.driver.collector.station.ip_address.decode()}:{self.driver.collector.station.port}")
            self.gateway_connected = True
        except GW1000IOError as e:
            self.logger.error(f"Unable to connect to device: {e}")
            self._init_complete = False
            return
           
        # start thread to get data from driver
        try:
            self.startup()  
        except Exception as e:
            self.logger.error(f"Unable to start thread: {e}")
            self._init_complete = False
            return
        
        if not self.init_webinterface(WebInterface):
            self.logger.error("Unable to start Webinterface")
            self._init_complete = False
        else:
            self.logger.debug(f"Init of Plugin {self.get_shortname()} complete")
            
    def startup(self):
        """Start a thread that get data from the GW1000/GW1100 driver."""

        try:
            _name = 'plugins.' + self.get_fullname() + '.get_data'
            self.thread = threading.Thread(target=self.get_data, name=_name)
            self.thread.start()
            self.logger.debug("FoshkPlugin thread has been started")
        except threading.ThreadError:
            self.logger.error("Unable to launch FoshkPlugin thread")
            self.thread = None

    def shutdown(self):
        """Shut down the thread that gets data from the GW1000/GW1100 driver."""

        # we only need do something if a thread exists
        if self.thread:
            # terminate the thread
            self.thread.join(1)
            # log the outcome
            if self.thread.is_alive():
                self.logger.error("Unable to shut down FoshkPlugin thread")
            else:
                self.logger.info("FoshkPlugin thread has been terminated")
                self.thread = None

    def run(self):
        """
        Run method for the plugin
        """
        self.logger.debug("Run method called")
        # set plugin state to alive
        self.alive = True

    def stop(self):
        """
        Stop method for the plugin
        """
        self.logger.debug("Stop method called")
        self.alive = False
        
        self.logger.debug("Shutdown von GW1000 Collector Thread called")
        self.driver.collector.shutdown()
        self.gateway_connected = False
        
        self.logger.debug("Shutdown von FoshkPlugin Thread called")
        self.shutdown()

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
            # self.logger.debug(f"parse item: {item}")
            foshk_attibute = self.get_iattr_value(item.conf, 'foshk_attibute')
            self.items[foshk_attibute] = item
            
            if foshk_attibute.lower().startswith('set'):
                return self.update_item

    # def parse_logic(self, logic):
        # """
        # Default plugin parse_logic method
        # """
        # if 'xxx' in logic.conf:
            # # self.function(logic['name'])
            # pass

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
            # code to execute if the plugin is not stopped and only, if the item has not been changed by this this plugin:
            self.logger.info(f"Update item: {item.property.path}, item has been changed outside this plugin")

            if self.has_iattr(item.conf, 'foshk_attibute'):
                self.logger.debug(f"update_item was called with item {item.property.path} from caller {caller}, source {source} and dest {dest}")
            pass

    def get_data(self):
        """
        Gets data for collector loop

        It is called within run() method.
        """
        while self.alive:
            for packet in self.driver.genLoopPackets():
                # log packet
                self.logger.debug(f"get_data: packet={packet}")
                # put packet to property
                self.data_dict = packet
                # start item update
                self.update_item_values(packet)
            if not self.gateway_connected:
                break
        
    def update_item_values(self, data):
        """
        Updates the value of connected items
        """
        for foshk_attibute in self.items:
            item = self.items[foshk_attibute]
            # self.logger.debug(f"update_item_values: foshk_attibute={foshk_attibute}; item={item.id()}")
            if foshk_attibute in data:
                value = data.get(foshk_attibute)
                if item is not None:
                    item(value, self.get_shortname())


# ============================================================================
#                          GW1000 API error classes
# ============================================================================

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
#                               class Gw1000
# ============================================================================

class Gw1000(object):
    """Base class for interacting with a GW1000/GW1100.

    There are a number of common properties and methods (eg IP address, field map, rain calculation etc) when dealing with a GW1000/GW1100 as a driver. 
    This class captures those common features.
    """

    def __init__(self, plugin_instance):
        """Initialise a GW1000 object."""
        
        # init logger
        self._plugin_instance = plugin_instance
        self._plugin_instance.logger.debug("Starting Gw1000")
        
        # network broadcast address and port
        self.broadcast_address = self._plugin_instance._broadcast_address if self._plugin_instance._broadcast_address is not None else default_broadcast_address
        self.broadcast_port = self._plugin_instance._broadcast_port if self._plugin_instance._broadcast_port is not None else default_broadcast_port
        self.socket_timeout = default_socket_timeout
        self.broadcast_timeout = default_broadcast_timeout
        
        # obtain the GW1000/GW1100 IP address
        _ip_address = self._plugin_instance._gateway_address  # will be None if it need to be auto detected
        # set the IP address property
        self.ip_address = _ip_address
        
        # obtain the GW1000/GW1100 port from the config dict for port number we have a default value we can use, so if port is not specified use the default
        _port = self._plugin_instance._gateway_port  # will be None if it need to be auto detected
        # set the port property
        self.port = _port
        
        # how many times to poll the API before giving up, default is default_max_tries
        self.max_tries = default_max_tries
        
        # wait time in seconds between retries, default is default_retry_wait seconds
        self.retry_wait = default_retry_wait
        
        # how often (in seconds) we should poll the API, use a default
        self.poll_interval = self._plugin_instance._gateway_poll_interval
        
        # Is a WH32 in use. WH32 TH sensor can override/provide outdoor TH data to the GW1000/GW1100. In terms of TH data the process is transparent
        # and we do not need to know if a WH32 or other sensor is providing outdoor TH data but in terms of battery state we need to know so the
        # battery state data can be reported against the correct sensor.
        use_th32 = False
        
        # do we show all battery state data including nonsense data or do we filter those sensors with signal state == 0
        self.show_battery = False
        
        # SET SPECIFIC LOGGERS
        # set specific debug settings rain
        self.debug_rain = False
        # set specific debug settings wind
        self.debug_wind = False
        # set specific debug settings loop data
        self.debug_loop = True
        # set specific debug settings sensors
        self.debug_sensors = True
        
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
                                         debug_sensors=self.debug_sensors)
        
        # initialise last lightning count and last rain properties
        self.last_lightning = None
        self.last_rain = None
        self.rain_mapping_confirmed = False
        self.rain_total_field = None
        
        # Finally, log any config that is not being pushed any further down. Log specific debug but only if set ie. True
        debug_list = []
        if self.debug_rain:
            debug_list.append("debug_rain is %s" % (self.debug_rain,))
        if self.debug_wind:
            debug_list.append("debug_wind is %s" % (self.debug_wind,))
        if self.debug_loop:
            debug_list.append("debug_loop is %s" % (self.debug_loop,))
        if len(debug_list) > 0:
            self._plugin_instance.logger.info(" ".join(debug_list))

    @property
    def model(self):
        """What model device am I using"""

        return self.collector.station.model

    def get_cumulative_rain_field(self, data):
        """Determine the cumulative rain field used to derive field 'rain'.

        Ecowitt rain gauges/GW1000/GW1100 emit various rain totals but WeeWX
        needs a per period value for field rain. Try the 'big' (4 byte)
        counters starting at the longest period and working our way down. This
        should only need be done once.

        data: dic of parsed GW1000/GW1100 API data
        """

        # if raintotals is present used that as our first choice
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
        # otherwise do nothing, we can try again next packet
        else:
            self.rain_total_field = None
        # if we found a field log what we are using
        if self.rain_mapping_confirmed:
            self._plugin_instance.logger.info("Using '%s' for rain total" % self.rain_total_field)
        elif self.debug_rain:
            # if debug_rain is set log that we had nothing
            self._plugin_instance.logger.info("No suitable field found for rain total")

    def calculate_rain(self, data):
        """Calculate total rainfall for a period.

        'rain' is calculated as the change in a user designated cumulative rain
        field between successive periods. 'rain' is only calculated if the
        field to be used has been selected and the designated field exists.

        data: dict of parsed GW1000/GW1100 API data
        """

        # have we decided on a field to use and is the field present
        if self.rain_mapping_confirmed and self.rain_total_field in data:
            # yes on both counts, so get the new total
            new_total = data[self.rain_total_field]
            # now calculate field rain as the difference between the new and
            # old totals
            data['rain'] = self.delta_rain(new_total, self.last_rain)
            # if debug_rain is set log some pertinent values
            if self.debug_rain:
                self._plugin_instance.logger.info("calculate_rain: last_rain=%s new_total=%s calculated rain=%s" % (self.last_rain, new_total, data['rain']))
            # save the new total as the old total for next time
            self.last_rain = new_total

    def calculate_lightning_count(self, data):
        """Calculate total lightning strike count for a period.

        'lightning_strike_count' is calculated as the change in field
        'lightningcount' between successive periods. 'lightning_strike_count'
        is only calculated if 'lightningcount' exists.

        data: dict of parsed GW1000/GW1100 API data
        """

        # is the lightningcount field present
        if 'lightningcount' in data:
            # yes, so get the new total
            new_total = data['lightningcount']
            # now calculate field lightning_strike_count as the difference
            # between the new and old totals
            data['lightning_strike_count'] = self.delta_lightning(new_total,
                                                                  self.last_lightning)
            # save the new total as the old total for next time
            self.last_lightning = new_total

    @staticmethod
    def delta_rain(rain, last_rain):
        """Calculate rainfall from successive cumulative values.

        Rainfall is calculated as the difference between two cumulative values.
        If either value is None the value None is returned. If the previous
        value is greater than the latest value a counter wrap around is assumed
        and the latest value is returned.

        rain:      current cumulative rain value
        last_rain: last cumulative rain value
        """
        
        logger = logging.getLogger(__name__)

        # do we have a last rain value
        if last_rain is None:
            # no, log it and return None
            logger.info("skipping rain measurement of %s: no last rain" % rain)
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
            logger.info("rain counter wraparound detected: new=%s last=%s" % (rain, last_rain))
            return rain
        # otherwise return the difference between the counts
        return rain - last_rain

    @staticmethod
    def delta_lightning(count, last_count):
        """Calculate lightning strike count from successive cumulative values.

        Lightning strike count is calculated as the difference between two
        cumulative values. If either value is None the value None is returned.
        If the previous value is greater than the latest value a counter wrap
        around is assumed and the latest value is returned.

        count:      current cumulative lightning count
        last_count: last cumulative lightning count
        """

        # do we have a last count
        if last_count is None:
            # no, log it and return None
            logger.info("Skipping lightning count of %s: no last count" % count)
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
            logger.info("Lightning counter wraparound detected: new=%s last=%s" % (count, last_count))
            return count
        # otherwise return the difference between the counts
        return count - last_count

# ============================================================================
#                            GW1000 Driver class
# ============================================================================


class Gw1000Driver(Gw1000):
    """GW1000/GW1100 driver class.

    A driver to emit loop packets based on observational data obtained from the GW1000/GW1100 API. The Gw1000Driver should be used when there is no other data source.

    Data is obtained from the GW1000/GW1100 API. The data is parsed and mapped to WeeWX fields and emitted as a WeeWX loop packet.

    Class Gw1000Collector collects and parses data from the GW1000/GW1100 API. The Gw1000Collector runs in a separate thread so as to not block the main
    WeeWX processing loop. The Gw1000Collector is turn uses child classes Station and Parser to interact directly with the GW1000/GW1100 API and
    parse the API responses respectively."""

    def __init__(self, plugin_instance):
        """Initialise a GW1000/GW1100 driver object."""

        # now initialize my superclasses
        super(Gw1000Driver, self).__init__(plugin_instance)
        
        # init logger
        self._plugin_instance = plugin_instance
        self._plugin_instance.logger.debug("Starting Gw1000Driver")

        # log the relevant settings/parameters we are using
        if self.ip_address is None and self.port is None:
            self._plugin_instance.logger.info("%s IP address and port not specified, attempting to discover %s..." % (self.collector.station.model, self.collector.station.model))
        elif self.ip_address is None:
            self._plugin_instance.logger.info("%s IP address not specified, attempting to discover %s..." % (self.collector.station.model, self.collector.station.model))
        elif self.port is None:
            self._plugin_instance.logger.info("%s port not specified, attempting to discover %s..." % (self.collector.station.model, self.collector.station.model))
        self._plugin_instance.logger.info("%s address is %s:%d" % (self.collector.station.model, self.collector.station.ip_address.decode(), self.collector.station.port))
        self._plugin_instance.logger.info("poll interval is %d seconds" % self.poll_interval)
        self._plugin_instance.logger.debug('max tries is %d, retry wait time is %d seconds' % (self.max_tries, self.retry_wait))
        self._plugin_instance.logger.debug('broadcast address is %s:%d, broadcast timeout is %d seconds' % (self.broadcast_address, self.broadcast_port, self.broadcast_timeout))
        self._plugin_instance.logger.debug('socket timeout is %d seconds' % self.socket_timeout)
        # start the Gw1000Collector in its own thread
        self.collector.startup()

    def genLoopPackets(self):
        """Generator function that returns loop packets.

        Run a continuous loop checking the Gw1000Collector queue for data. When data arrives map the raw data to a WeeWX loop packet and yield the packet.
        """

        # generate loop packets forever
        while True:
            # wrap in a try to catch any instances where the queue is empty
            try:
                # get any data from the collector queue
                queue_data = self.collector.my_queue.get(True, 10)
            except queue.Empty:
                # self._plugin_instance.logger.debug("genLoopPackets: there was nothing in the queue so continue")
                # there was nothing in the queue so continue
                pass
            else:
                # We received something in the queue, it will be one of three things:
                # 1. a dict containing sensor data
                # 2. an exception
                # 3. the value None signalling a serious error that means the Collector needs to shut down

                # if the data has a 'keys' attribute it is a dict so must be data
                if hasattr(queue_data, 'keys'):
                    # we have a dict so assume it is data log the received data if necessary
                    if self.debug_loop:
                        if 'datetime' in queue_data:
                            self._plugin_instance.logger.info("Received %s data (debug_loop): %s %s" % (self.collector.station.model, timestamp_to_string(queue_data['datetime']), natural_sort_dict(queue_data)))
                        else:
                            self._plugin_instance.logger.info("Received %s data: %s" % (self.collector.station.model, natural_sort_dict(queue_data)))
                    # Now start to create a loop packet. A loop packet must have a timestamp, if we have one (key 'datetime') in the received data use it otherwise allocate one.
                    if 'datetime' in queue_data:
                        packet = {'dateTime': queue_data['datetime']}
                    else:
                        # we don't have a timestamp so create one
                        packet = {'dateTime': int(time.time() + 0.5)}
                    # if not already determined, determine which cumulative rain field will be used to determine the per period rain field
                    if not self.rain_mapping_confirmed:
                        self.get_cumulative_rain_field(queue_data)
                    # get the rainfall this period from total
                    self.calculate_rain(queue_data)
                    # get the lightning strike count this period from total
                    self.calculate_lightning_count(queue_data)
                    # add the qu queue_data to the empty packet
                    packet.update(queue_data)
                    # log the packet if necessary, there are several debug settings that may require this, start from the highest (most encompassing) and work to the lowest (least encompassing)
                    if self.debug_loop:
                        self._plugin_instance.logger.info('genLoopPackets: Packet %s: %s' % (timestamp_to_string(packet['dateTime']), natural_sort_dict(packet)))
                    # yield the loop packet
                    yield packet
                
                # if it's a tuple then it's a tuple with an exception and exception text
                elif isinstance(queue_data, BaseException):
                    # We have an exception. The collector did not deem it serious enough to want to shutdown or it would have sent None instead. If it is anything else we log it and then raise it.
                    
                    # first extract our exception
                    e = queue_data
                    # and process it if we have something
                    if e:
                        # is it a GW1000Error
                        self._plugin_instance.logger.error("Caught unexpected exception %s: %s" % (e.__class__.__name__, e))
                        # then raise it
                        raise e
                
                # if it's None then its a signal the Collector needs to shutdown
                elif queue_data is None:
                    # if debug_loop log what we received
                    if self.debug_loop:
                        self._plugin_instance.logger.info("Received 'None'")
                    # we received the signal to shutdown, so call closePort()
                    self.closePort()
                    # and raise an exception to cause the engine to shutdown
                    raise GW1000IOError("Gw1000Collector needs to shutdown")
                # if it's none of the above (which it should never be) we don't know what to do with it so pass and wait for the next item in the queue
                else:
                    pass

    @property
    def hardware_name(self):
        """Return the hardware name.

        Use the device model from our Collector's Station object, but if this
        is None use the driver name.
        """

        if self.collector.station.model is not None:
            return self.collector.station.model

    @property
    def mac_address(self):
        """Return the GW1000/GW1100 MAC address."""

        return self.collector.mac_address

    @property
    def firmware_version(self):
        """Return the GW1000/GW1100 firmware version string."""

        return self.collector.firmware_version

    @property
    def sensor_id_data(self):
        """Return the GW1000/GW1100 sensor identification data.

        The sensor ID data is available via the data property of the Collector objects' sensors property.
        """

        return self.collector.sensors.data

    def closePort(self):
        """Close down the driver port."""

        # in this case there is no port to close, just shutdown the collector
        self.collector.shutdown()

# ============================================================================
#                              class Collector
# ============================================================================


class Collector(object):
    """Base class for a client that polls an API."""

    # a queue object for passing data back to the driver
    my_queue = queue.Queue()

    def __init__(self):
        pass

    def startup(self):
        pass

    def shutdown(self):
        pass

# ============================================================================
#                              class Gw1000Collector
# ============================================================================


class Gw1000Collector(Collector):
    """Class to poll the GW1000/GW1100 API, decode and return data to the driver."""

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

    def __init__(self, ip_address=None, port=None, broadcast_address=None, broadcast_port=None, socket_timeout=None, broadcast_timeout=None,
                 poll_interval=0, max_tries=default_max_tries, retry_wait=default_retry_wait,
                 use_th32=False, show_battery=False, debug_rain=False, debug_wind=False, debug_sensors=False):
        """Initialise our class."""

        # initialize my base class:
        super(Gw1000Collector, self).__init__()
        
        # init logger
        self.logger = logging.getLogger(__name__)
        
        # interval between polls of the API, use a default
        self.poll_interval = poll_interval
        
        # how many times to poll the API before giving up, default is default_max_tries
        self.max_tries = max_tries
        
        # period in seconds to wait before polling again, default is default_retry_wait seconds
        self.retry_wait = retry_wait
        
        # are we using a th32 sensor
        self.use_th32 = use_th32
        
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
        self.sensors_obj = Gw1000Collector.Sensors(show_battery=show_battery, debug_sensors=debug_sensors)
        
        # create a thread property
        self.thread = None
        
        # we start off not collecting data, it will be turned on later when we are threaded
        self.collect_data = False

    def collect_sensor_data(self):
        """Collect sensor data by polling the API.

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
                self.my_queue.put(queue_data)
                # debug log when we will next poll the API
                self.logger.debug('Next update in %d seconds' % self.poll_interval)
                # reset the last poll ts
                last_poll = now
            # sleep for a second and then see if its time to poll again
            time.sleep(1)

    def get_live_sensor_data(self):
        """Get all current sensor data.

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
        self.logger.debug("Parsed data: %s" % parsed_data)
        # The parsed live data does not contain any sensor battery state or signal level data. The battery state and signal level data for each
        # sensor can be obtained from the GW1000/GW1100 API via our Sensors object.
        # first we need to update our Sensors object with current sensor ID data
        self.update_sensor_id_data()
        # now add any sensor battery state and signal level data to the parsed data
        parsed_data.update(self.sensors_obj.battery_and_signal_data)
        # log the processed parsed data but only if debug>=3
        self.logger.debug("Processed parsed data: %s" % parsed_data)
        return parsed_data

    def update_sensor_id_data(self):
        """Update the Sensors object with current sensor ID data."""

        # get the current sensor ID data
        sensor_id_data = self.station.get_sensor_id()
        # now use the sensor ID data to re-initialise our sensors object
        self.sensors_obj.set_sensor_id_data(sensor_id_data)

    @property
    def rain_data(self):
        """Obtain GW1000/GW1100 rain data."""

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
        """Obtain GW1000/GW1100 multi-channel temperature and humidity offset data."""

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
        """Obtain GW1000/GW1100 PM2.5 offset data."""

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
        """Obtain GW1000/GW1100 WH45 CO2, PM10 and PM2.5 offset data."""

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
        """Obtain GW1000/GW1100 calibration data."""

        # obtain the calibration data via the API
        response = self.station.get_calibration_coefficient()
        # determine the size of the calibration data
        raw_data_size = response[3]
        # extract the actual data
        data = response[4:4 + raw_data_size - 3]
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
        raw_data_size = response[3]
        # extract the actual data
        data = response[4:4 + raw_data_size - 3]
        # and decode/store the offset calibration data
        calibration_dict['intemp'] = struct.unpack(">h", data[0:2])[0]/10.0
        try:
            calibration_dict['inhum'] = struct.unpack("b", data[2])[0]
        except TypeError:
            calibration_dict['inhum'] = struct.unpack("b", int_to_bytes(data[2]))[0]
        calibration_dict['abs'] = struct.unpack(">l", data[3:7])[0]/10.0
        calibration_dict['rel'] = struct.unpack(">l", data[7:11])[0]/10.0
        calibration_dict['outtemp'] = struct.unpack(">h", data[11:13])[0]/10.0
        try:
            calibration_dict['outhum'] = struct.unpack("b", data[13])[0]
        except TypeError:
            calibration_dict['outhum'] = struct.unpack("b", int_to_bytes(data[13]))[0]
        calibration_dict['dir'] = struct.unpack(">h", data[14:16])[0]
        return calibration_dict

    @property
    def soil_calibration(self):
        """Obtain GW1000/GW1100 soil moisture sensor calibration data.

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
            calibration_dict[channel]['ad_select'] = ad_select
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
        """Obtain GW1000/GW1100 system parameters."""
        
        frequency = {0: '433 MHz',
                     1: '866 MHz',
                     2: '915 MHz',
                     3: '920 MHz'
                     }
        
        sensor_type = {1: 'WH24',
                       2: 'WH65'
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
        data_dict['sensor_type'] = sensor_type[data[1]]
        data_dict['utc'] = self.parser.decode_utc(data[2:6])
        data_dict['timezone_index'] = data[6]
        data_dict['dst'] = data[7] != 0
        return data_dict

    @property
    def ecowitt_net(self):
        """Obtain GW1000/GW1100 Ecowitt.net service parameters.

        Obtain the GW1000/GW1100 Ecowitt.net service settings.

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
        """Obtain GW1000/GW1100 Weather Underground service parameters.

        Obtain the GW1000/GW1100 Weather Underground service settings.

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
        data_dict = dict()
        # obtain the required data from the response decoding any bytestrings
        id_size = data[0]
        data_dict['id'] = data[1:1+id_size].decode()
        password_size = data[1+id_size]
        data_dict['password'] = data[2+id_size:2+id_size+password_size].decode()
        return data_dict

    @property
    def weathercloud(self):
        """Obtain GW1000/GW1100 Weathercloud service parameters.

        Obtain the GW1000/GW1100 Weathercloud service settings.

        Returns a dictionary of settings with string data in unicode format.
        """

        # obtain the system parameters data via the API
        response = self.station.get_weathercloud_params()
        # determine the size of the system parameters data
        raw_data_size = response[3]
        # extract the actual system parameters data
        data = response[4:4 + raw_data_size - 3]
        # initialise a dict to hold our final data
        data_dict = dict()
        # obtain the required data from the response decoding any bytestrings
        id_size = data[0]
        data_dict['id'] = data[1:1+id_size].decode()
        key_size = data[1+id_size]
        data_dict['key'] = data[2+id_size:2+id_size+key_size].decode()
        return data_dict

    @property
    def wow(self):
        """Obtain GW1000/GW1100 Weather Observations Website service parameters.

        Obtain the GW1000/GW1100 Weather Observations Website service settings.

        Returns a dictionary of settings with string data in unicode format.
        """

        # obtain the system parameters data via the API
        response = self.station.get_wow_params()
        # determine the size of the system parameters data
        raw_data_size = response[3]
        # extract the actual system parameters data
        data = response[4:4 + raw_data_size - 3]
        # initialise a dict to hold our final data
        data_dict = dict()
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
        """Obtain GW1000/GW1100 custom server parameters.

        Obtain the GW1000/GW1100 settings used for uploading data to a remote server.

        Returns a dictionary of settings with string data in unicode format.
        """

        # obtain the system parameters data via the API
        response = self.station.get_custom_params()
        # determine the size of the system parameters data
        raw_data_size = response[3]
        # extract the actual system parameters data
        data = response[4:4 + raw_data_size - 3]
        # initialise a dict to hold our final data
        data_dict = dict()
        # obtain the required data from the response decoding any bytestrings
        index = 0
        id_size = data[index]
        index += 1
        data_dict['id'] = data[index:index+id_size].decode()
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
        data_dict['type'] = data[index]
        index += 1
        data_dict['active'] = data[index]
        # the user path is obtained separately, get the user path and add it to our response
        data_dict.update(self.usr_path)
        return data_dict

    @property
    def usr_path(self):
        """Obtain the GW1000/GW1100 user defined custom paths.

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
        data_dict = dict()
        index = 0
        ecowitt_size = data[index]
        index += 1
        data_dict['ecowitt_path'] = data[index:index+ecowitt_size].decode()
        index += ecowitt_size
        wu_size = data[index]
        index += 1
        data_dict['wu_path'] = data[index:index+wu_size].decode()
        return data_dict

    @property
    def mac_address(self):
        """Obtain the MAC address of the GW1000/GW1100.

        Returns the GW1000/GW1100 MAC address as a string of colon separated hex bytes.
        """

        # obtain the GW1000/GW1100 MAC address bytes
        station_mac_b = self.station.get_mac_address()
        # return the formatted string
        return bytes_to_hex(station_mac_b[4:10], separator=":")

    @property
    def firmware_version(self):
        """Obtain the GW1000/GW1100 firmware version string.

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
        """Get the current Sensors object.

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

    def startup(self):
        """Start a thread that collects data from the GW1000/GW1100 API."""

        try:
            self.thread = Gw1000Collector.CollectorThread(self)
            self.collect_data = True
            self.thread.daemon = True
            self.thread.setName('Gw1000CollectorThread')
            self.thread.start()
        except threading.ThreadError:
            self.logger.error("Unable to launch Gw1000Collector thread")
            self.thread = None

    def shutdown(self):
        """Shut down the thread that collects data from the GW1000/GW1100 API.

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
                self.logger.error("Unable to shut down Gw1000Collector thread")
            else:
                self.logger.info("Gw1000Collector thread has been terminated")
        self.thread = None

    class CollectorThread(threading.Thread):
        """Class used to collect data via the GW1000/GW1100 API in a thread."""

        def __init__(self, client):
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
            except:
                pass

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

        def __init__(self, ip_address=None, port=None,
                     broadcast_address=None, broadcast_port=None,
                     socket_timeout=None, broadcast_timeout=None,
                     max_tries=default_max_tries,
                     retry_wait=default_retry_wait, mac=None):

            # init logger
            self.logger = logging.getLogger(__name__)

            # network broadcast address
            self.broadcast_address = broadcast_address if broadcast_address is not None else default_broadcast_address
            # network broadcast port
            self.broadcast_port = broadcast_port if broadcast_port is not None else default_broadcast_port
            self.socket_timeout = socket_timeout if socket_timeout is not None else default_socket_timeout
            self.broadcast_timeout = broadcast_timeout if broadcast_timeout is not None else default_broadcast_timeout

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
                        device_list = self.discover()
                    except socket.error as e:
                        _msg = "Unable to detect device IP address and port: %s (%s)" % (e, type(e))
                        self.logger.error(_msg)
                        # signal that we have a critical error
                        raise
                    else:
                        # did we find any GW1000/GW1100
                        if len(device_list) > 0:
                            # we have at least one, arbitrarily choose the first one
                            # found as the one to use
                            disc_ip = device_list[0]['ip_address']
                            disc_port = device_list[0]['port']
                            # log the fact as well as what we found
                            gw1000_str = ', '.join([':'.join(['%s:%d' % (d['ip_address'], d['port'])]) for d in device_list])
                            if len(device_list) == 1:
                                stem = "%s was" % device_list[0]['model']
                            else:
                                stem = "Multiple devices were"
                            self.logger.info("%s found at %s" % (stem, gw1000_str))
                            ip_address = disc_ip if ip_address is None else ip_address
                            port = disc_port if port is None else port
                            break
                        else:
                            # did not discover any GW1000/GW1100 so log it
                            self.logger.debug("Failed attempt %d to detect device IP address and/or port" % (attempt + 1,))
                            # do we try again or raise an exception
                            if attempt < max_tries - 1:
                                # we still have at least one more try left so sleep and try again
                                time.sleep(retry_wait)
                            else:
                                # we've used all our tries, log it and raise an exception
                                _msg = "Failed to detect device IP address and/or port after %d attempts" % (attempt + 1,)
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
            """Discover any GW1000/GW1100 devices on the local network.

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
                    # self.logger.debug(f"Received broadcast response in HEX '{bytes_to_hex(response)}' and in Bytes {response}")
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
                        # Some other error occurred in check_response(), perhaps the response was malformed. Log the stack trace but continue.
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

        def get_model(self, t):
            """Determine the device model from a string.

            To date GW1000 and GW1100 firmware versions have included the
            device model in the firmware version string or the device SSID.
            Both the firmware version string and device SSID are available via
            the device API so checking the firmware version string or SSID
            provides a de facto method of determining the device model.

            This method uses a simple check to see if a known model name is
            contained in the string concerned.

            Known model strings are contained in a tuple Station.known_models.

            If a known model is found in the string the model is returned as a
            string. None is returned if a known model is not found in the
            string.
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

            Sends the command to obtain live data from the GW1000/GW1100 to the
            API with retries. If the GW1000/GW1100 cannot be contacted
            re-discovery is attempted. If rediscovery is successful the command
            is tried again otherwise the lost contact timestamp is set and the
            exception raised. Any code that calls this method should be
            prepared to handle a GW1000IOError exception.
            """

            # send the API command to obtain live data from the GW1000/GW1100,
            # be prepared to catch the exception raised if the GW1000/GW1100
            # cannot be contacted
            try:
                # return the validated API response
                return self.send_cmd_with_retries('CMD_GW1000_LIVEDATA')
            except GW1000IOError:
                # there was a problem contacting the GW1000/GW1100, it could be
                # it has changed IP address so attempt to rediscover
                if not self.rediscover():
                    # we could not re-discover so raise the exception
                    raise
                else:
                    # we did rediscover successfully so try again, if it fails
                    # we get another GW1000IOError exception which will be raised
                    return self.send_cmd_with_retries('CMD_GW1000_LIVEDATA')

        def get_raindata(self):
            """Get GW1000/GW1100 rain data.

            Sends the command to obtain rain data from the GW10GW1000/GW110000
            to the API with retries. If the GW1000/GW1100 cannot be contacted a
            GW1000IOError will have been raised by send_cmd_with_retries()
            which will be passed through by get_raindata(). Any code calling
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

            Sends the command to obtain the GW1000/GW1100 Ecowitt.net
            parameters to the API with retries. If the GW1000/GW1100 cannot be
            contacted a GW1000IOError will have been raised by
            send_cmd_with_retries() which will be passed through by
            get_ecowitt_net_params(). Any code calling get_ecowitt_net_params()
            should be prepared to handle this exception.
            """

            return self.send_cmd_with_retries('CMD_READ_ECOWITT')

        def get_wunderground_params(self):
            """Get GW1000 Weather Underground parameters.

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
            """Get GW1000/GW1100 Weathercloud parameters.

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
            """Get GW1000/GW1100 Weather Observations Website parameters.

            Sends the command to obtain the GW1000/GW1100 Weather Observations
            Website parameters to the API with retries. If the GW1000/GW1100
            cannot be contacted a GW1000IOError will have been raised by
            send_cmd_with_retries() which will be passed through by
            get_wow_params(). Any code calling get_wow_params() should be
            prepared to handle this exception.
            """

            return self.send_cmd_with_retries('CMD_READ_WOW')

        def get_custom_params(self):
            """Get GW1000/GW1100 custom server parameters.

            Sends the command to obtain the GW1000/GW1100 custom server parameters to the API with retries. If the GW1000/GW1100 cannot be
            contacted a GW1000IOError will have been raised by send_cmd_with_retries() which will be passed through by
            get_custom_params(). Any code calling get_custom_params() should be prepared to handle this exception.
            """

            return self.send_cmd_with_retries('CMD_READ_CUSTOMIZED')
            
        def set_custom_params(self, custom_enabled=True, custom_host=None, custom_port=None, custom_interval=None):
            """Set GW1000/GW1100 custom server parameters.

            Sends the command to obtain the GW1000/GW1100 custom server parameters to the API with retries. If the GW1000/GW1100 cannot be
            contacted a GW1000IOError will have been raised by send_cmd_with_retries() which will be passed through by
            get_custom_params(). Any code calling set_custom_params() should be prepared to handle this exception.
            """
            
            _custom_server_id = ""
            _custom_password = ""
            _custom_ecowitt = True
            
            # first read current configuration to determine, whether writing new configuration is needed
            
            # obtain the system parameters data via the API
            response = self.get_custom_params()
            # determine the size of the system parameters data
            raw_data_size = response[3]
            # extract the actual system parameters data
            data = response[4:4 + raw_data_size - 3]
            # obtain the required data from the response decoding any bytestrings
            index = 0
            id_size = data[index]
            index += 1
            _server_id = data[index:index+id_size].decode()
            index += id_size
            password_size = data[index]
            index += 1
            _password = data[index:index+password_size].decode()
            index += password_size
            server_size = data[index]
            index += 1
            _server_ip = data[index:index+server_size].decode()
            index += server_size
            _port = struct.unpack(">h", data[index:index + 2])[0]
            index += 2
            _interval = struct.unpack(">h", data[index:index + 2])[0]
            index += 2
            _server_type = data[index]              # Ecowitt: 0 ; WU: 1
            index += 1
            _active = data[index]
            
            if not (_server_ip == custom_host and _port == custom_port and _interval == custom_interval and _active is True and bool(_server_type) is False):
                self.logger.debug(f"Need to set customized server: Server_IP current={_server_ip} vs. new={custom_host}; Port: current={_port} vs. new={custom_port}; Interval: current={_interval} vs. new={custom_interval}; Active: current={bool(_active)} vs. new=True; Protocol: current={bool(_server_type)} vs. new=False")
                # set command
                cmd = 'CMD_WRITE_CUSTOMIZED'
                # create payload
                payload = bytearray(chr(len(_custom_server_id)) + _custom_server_id + chr(len(_custom_password)) + _custom_password + chr(len(custom_host)) + custom_host + chr(int(int(custom_port)/256)) + chr(int(int(custom_port) % 256)) + chr(int(int(custom_interval)/256)) + chr(int(int(custom_interval) % 256)) + chr(not _custom_ecowitt) + chr(custom_enabled), 'latin-1')
                self.logger.debug(f"Customized Server: payload={payload}")
                return self.send_cmd_with_retries(cmd, payload)
            else:
                self.logger.debug(f"<INFO> Customized Server settings already correct; No need to do it again")
                return

        def get_usr_path(self):
            """Get GW1000/GW1100 user defined custom path.

            Sends the command to obtain the GW1000/GW1100 user defined custom path to the API with retries. If the GW1000/GW1100 cannot be
            contacted a GW1000IOError will have been raised by send_cmd_with_retries() which will be passed through by
            get_usr_path(). Any code calling get_usr_path() should be prepared to handle this exception.
            """

            return self.send_cmd_with_retries('CMD_READ_USR_PATH')
            
        def set_usr_path(self, custom_ecowitt_pathpath=None, custom_wu_path=None):
            """Get GW1000/GW1100 user defined custom path.

            Sends the command to set the GW1000/GW1100 user defined custom path to the API with retries. If the GW1000/GW1100 cannot be
            contacted a GW1000IOError will have been raised by send_cmd_with_retries() which will be passed through by
            get_usr_path(). Any code calling get_usr_path() should be prepared to handle this exception.
            """
            if custom_ecowitt_pathpath is None:
                custom_ecowitt_pathpath = "/data/report/"
            if custom_wu_path is None:
                custom_wu_path = "/weatherstation/updateweatherstation.php"
            
            # first read current configuration to determine, whether writing new configuration is needed
            response = self.station.get_usr_path()
            # determine the size of the user path data
            raw_data_size = response[3]
            # extract the actual system parameters data
            data = response[4:4 + raw_data_size - 3]
            # initialise a dict to hold our final data
            index = 0
            ecowitt_size = data[index]
            index += 1
            _ecowitt_path = data[index:index+ecowitt_size].decode()
            index += ecowitt_size
            wu_size = data[index]
            index += 1
            _wu_path = data[index:index+wu_size].decode()

            if not (_ecowitt_path == custom_ecowitt_pathpath and _wu_path == custom_wu_path):
                self.logger.debug(f"Need to set customized path: Ecowitt: current={_ecowitt_path} vs. new={custom_ecowitt_pathpath} and WU: current={_wu_path} vs. new={custom_wu_path}")
                # set command
                cmd = 'CMD_WRITE_USR_PATH'
                # create payload
                payload = bytearray
                payload.extend(int_to_bytes(len(custom_ecowitt_pathpath), 1))
                payload.extend(str.encode(custom_ecowitt_pathpath))
                payload.extend(int_to_bytes(len(custom_wu_path), 1))
                payload.extend(str.encode(custom_wu_path))
                self.logger.debug(f"Customized Path: payload={payload}")
                return self.send_cmd_with_retries(cmd, payload)
            else:
                self.logger.debug(f"<INFO> Customized Path settings already correct; No need to do it again")
                return

        def get_mac_address(self):
            """Get GW1000/GW1100 MAC address.

            Sends the command to obtain the GW1000/GW1100 MAC address to the
            API with retries. If the GW1000/GW1100 cannot be contacted a
            GW1000IOError will have been raised by send_cmd_with_retries()
            which will be passed through by get_mac_address(). Any code calling
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
            
        def set_firmware_upgrade(self, server_ip, server_port):
            """Set GW1000/GW1100 firmware upgrade.

            Sends the command to upgrade GW1000/GW1100 firmware version to the API with retries. If the GW1000/GW1100 cannot be contacted a
            GW1000IOError will have been raised by send_cmd_with_retries() which will be passed through by get_firmware_version(). Any code
            calling get_firmware_version() should be prepared to handle this exception.
            """
            # set command
            cmd = 'CMD_WRITE_UPDATE'
            # create payload
            payload = bytearray()
            payload.extend(socket.inet_aton(server_ip))
            payload.extend(int_to_bytes(server_port, 2))
            self.logger.debug(f"set_firmware_upgrade: payload={payload}")
            return self.send_cmd_with_retries('CMD_READ_FIRMWARE_VERSION')

        def get_sensor_id(self):
            """Get GW1000/GW1100 sensor ID data.

            Sends the command to obtain sensor ID data from the GW1000/GW1100
            to the API with retries. If the GW1000/GW1100 cannot be contacted
            re-discovery is attempted. If rediscovery is successful the command
            is tried again otherwise the lost contact timestamp is set and the
            exception raised. Any code that calls this method should be
            prepared to handle a GW1000IOError exception.
            """

            # send the API command to obtain sensor ID data from the
            # GW1000/GW1100, be prepared to catch the exception raised if the
            # GW1000/GW1100 cannot be contacted
            try:
                return self.send_cmd_with_retries('CMD_READ_SENSOR_ID_NEW')
            except GW1000IOError:
                # there was a problem contacting the GW1000/GW1100, it could be
                # it has changed IP address so attempt to rediscover
                if not self.rediscover():
                    # we could not re-discover so raise the exception
                    raise
                else:
                    # we did rediscover successfully so try again, if it fails
                    # we get another GW1000IOError exception which will be
                    # raised
                    return self.send_cmd_with_retries('CMD_READ_SENSOR_ID_NEW')

        def get_mulch_offset(self):
            """Get multi-channel temperature and humidity offset data.

            Sends the command to obtain the multi-channel temperature and
            humidity offset data to the API with retries. If the GW1000/GW1100
            cannot be contacted a GW1000IOError will have been raised by
            send_cmd_with_retries() which will be passed through by
            get_mulch_offset(). Any code calling get_mulch_offset() should be
            prepared to handle this exception.
            """

            return self.send_cmd_with_retries('CMD_GET_MulCH_OFFSET')

        def get_pm25_offset(self):
            """Get PM2.5 offset data.

            Sends the command to obtain the PM2.5 sensor offset data to the API
            with retries. If the GW1000/GW1100 cannot be contacted a
            GW1000IOError will have been raised by send_cmd_with_retries()
            which will be passed through by get_pm25_offset(). Any code
            calling get_pm25_offset() should be prepared to handle this
            exception.
            """

            return self.send_cmd_with_retries('CMD_GET_PM25_OFFSET')

        def get_calibration_coefficient(self):
            """Get calibration coefficient data.

            Sends the command to obtain the calibration coefficient data to the
            API with retries. If the GW1000/GW1100 cannot be contacted a
            GW1000IOError will have been raised by send_cmd_with_retries()
            which will be passed through by get_calibration_coefficient(). Any
            code calling get_calibration_coefficient() should be prepared to
            handle this exception.
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

            Sends the command to obtain the offset calibration data to the API
            with retries. If the GW1000/GW1100 cannot be contacted a
            GW1000IOError will have been raised by send_cmd_with_retries()
            which will be passed through by get_offset_calibration(). Any code
            calling get_offset_calibration() should be prepared to handle this
            exception.
            """

            return self.send_cmd_with_retries('CMD_READ_CALIBRATION')

        def get_co2_offset(self):
            """Get WH45 CO2, PM10 and PM2.5 offset data.

            Sends the command to obtain the WH45 CO2, PM10 and PM2.5 sensor
            offset data to the API with retries. If the GW1000/GW1100 cannot be
            contacted a GW1000IOError will have been raised by
            send_cmd_with_retries() which will be passed through by
            get_offset_calibration(). Any code calling get_offset_calibration()
            should be prepared to handle this exception.
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
                    if self.log_failures:
                        self.logger.debug("Failed to obtain response to attempt %d to send command '%s': %s" % (attempt + 1, cmd, e))
                except Exception as e:
                    # an exception was encountered, log it
                    if self.log_failures:
                        self.logger.debug("Failed attempt %d to send command '%s': %s" % (attempt + 1, cmd, e))
                else:
                    # check the response is valid
                    # self.logger.debug(f"send_cmd_with_retries: cmd={cmd}, self.commands[cmd]={self.commands[cmd]}, response={response}")
                    try:
                        self.check_response(response, self.commands[cmd])
                    except (InvalidChecksum, InvalidApiResponse) as e:
                        # the response was not valid, log it and attempt again if we haven't had too many attempts already
                        self.logger.debug("Invalid response to attempt %d to send command '%s': %s" % (attempt + 1, cmd, e))
                    except Exception as e:
                        # Some other error occurred in check_response(), perhaps the response was malformed. Log  but continue.
                        self.logger.error("Unexpected exception occurred while checking response to attempt %d to send command '%s': %s" % (attempt + 1, cmd, e))
                    else:
                        # our response is valid so return it
                        return response
                # sleep before our next attempt, but skip the sleep if we have just made our last attempt
                if attempt < self.max_tries - 1:
                    time.sleep(self.retry_wait)
            # if we made it here we failed after self.max_tries attempts first of all log it
            _msg = ("Failed to obtain response to command '%s' after %d attempts" % (cmd, attempt + 1))
            if response is not None or self.log_failures:
                self.logger.error(_msg)
            # finally raise a GW1000IOError exception
            raise GW1000IOError(_msg)

        def build_cmd_packet(self, cmd, payload=b''):
            """Construct an API command packet.

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
                raise UnknownCommand("Unknown API command '%s'" % (cmd,))
            # construct the portion of the message for which the checksum is calculated
            body = b''.join([self.commands[cmd], struct.pack('B', size), payload])
            # calculate the checksum
            checksum = self.calc_checksum(body)
            # return the constructed message packet
            return b''.join([self.header, body, struct.pack('B', checksum)])

        def send_cmd(self, packet):
            """Send a command to the GW1000/GW1100 API and return the response.

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
            """Check the validity of a GW1000/GW1100 API response.

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
            """Calculate the checksum for a GW1000/GW1100 API call or response.

            The checksum used on the GW1000/GW1100 responses is simply the LSB of the sum of the bytes.

            data: The data on which the checksum is to be calculated. Byte string.

            Returns the checksum as an integer.
            """

            checksum = sum(data)
            return checksum - int(checksum / 256) * 256

        def rediscover(self):
            """Attempt to rediscover a lost GW1000/GW1100.

            Use UDP broadcast to discover a GW1000/GW1100 that may have changed
            to a new IP. We should not be re-discovering a GW1000/GW1100 for
            which the user specified an IP, only for those for which we
            discovered the IP address on startup. If a GW1000/GW1100 is
            discovered then change my ip_address and port properties as
            necessary to use the device in future. If the rediscover was
            successful return True otherwise return False.
            """

            # we will only rediscover if we first discovered
            if self.ip_discovered:
                # log that we are attempting re-discovery
                if self.log_failures:
                    self.logger.info("Attempting to re-discover %s..." % self.model)
                # attempt to discover up to self.max_tries times
                for attempt in range(self.max_tries):
                    # sleep before our attempt, but not if its the first one
                    if attempt > 0:
                        time.sleep(self.retry_wait)
                    try:
                        # discover devices on the local network, the result is
                        # a list of dicts in IP address order with each dict
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
                            self.logger.info("%s found at %s" % (stem, gw1000_str))
                            # keep our current IP address and port in case we
                            # don't find a match as we will change our
                            # ip_address and port properties in order to get
                            # the MAC for that IP address and port
                            present_ip = self.ip_address
                            present_port = self.port
                            # iterate over each candidate checking their MAC
                            # address against my mac property. This way we know
                            # we are connecting to the GW1000/GW1100 we were
                            # previously using
                            for _ip, _port in device_list:
                                # do the MACs match, if so we have our old
                                # device and we can exit the loop
                                if self.mac == self.get_mac_address():
                                    self.ip_address = _ip.encode()
                                    self.port = _port
                                    break
                            else:
                                # exhausted the device_list without a match,
                                # revert to our old IP address and port
                                self.ip_address = present_ip
                                self.port = present_port
                                # and continue the outer loop if we have any
                                # attempts left
                                continue
                            # log the new IP address and port
                            self.logger.info("%s at address %s:%d will be used" % (self.model, self.ip_address.decode(), self.port))
                            # return True indicating the re-discovery was successful
                            return True
                        else:
                            # did not discover any GW1000/GW1100 so log it
                            if self.log_failures:
                                self.logger.debug("Failed attempt %d to detect any devices" % (attempt + 1,))
                else:
                    # we exhausted our attempts at re-discovery so log it
                    if self.log_failures:
                        self.logger.info("Failed to detect original %s after %d attempts" % (self.model, attempt + 1))
            else:
                # an IP address was specified so we cannot go searching, log it
                if self.log_failures:
                    self.logger.debug("IP address specified in 'weewx.conf', re-discovery was not attempted")
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
        rain_field_codes = (b'\x0D', b'\x0E', b'\x0F', b'\x10', b'\x11', b'\x12', b'\x13', b'\x14')
        # tuple of field codes for wind related fields in the GW1000/GW1100 live data so we can isolate these fields
        wind_field_codes = (b'\x0A', b'\x0B', b'\x0C', b'\x19')

        def __init__(self, is_wh24=False, debug_rain=False, debug_wind=False):

            # init logger
            self.logger = logging.getLogger(__name__)

            # Tell our battery state decoding whether we have a WH24 or a WH65
            # (they both share the same battery state bit). By default we are
            # coded to use a WH65. But is there a WH24 connected?
            if is_wh24:
                # We have a WH24. On startup we are set for a WH65 but if it is
                # a restart we will likely already be setup for a WH24. We need
                # to handle both cases.
                if 'wh24' not in self.multi_batt.keys():
                    # we don't have a 'wh24' entry so create one, it's the same
                    # as the 'wh65' entry
                    self.multi_batt['wh24'] = self.multi_batt['wh65']
                    # and pop off the no longer needed WH65 decode dict entry
                    self.multi_batt.pop('wh65')
            else:
                # We don't have a WH24 but a WH65. On startup we are set for a
                # WH65 but if it is a restart it is possible we have already
                # been setup for a WH24. We need to handle both cases.
                if 'wh65' not in self.multi_batt.keys():
                    # we don't have a 'wh65' entry so create one, it's the same
                    # as the 'wh24' entry
                    self.multi_batt['wh65'] = self.multi_batt['wh24']
                    # and pop off the no longer needed WH65 decode dict entry
                    self.multi_batt.pop('wh24')
            # get debug_rain and debug_wind
            self.debug_rain = debug_rain
            self.debug_wind = debug_wind

        def parse(self, raw_data, timestamp=None):
            """Parse raw sensor data.

            Parse the raw sensor data and create a dict of sensor
            observations/status data. Add a timestamp to the data if one does
            not already exist.

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
                        # We struck a field 'address' we do not know how to
                        # process. Ideally we would like to skip and move onto
                        # the next field (if there is one) but the problem is
                        # we do not know how long the data of this unknown
                        # field is. We could go on guessing the field data size
                        # by looking for the next field address but we won't
                        # know if we do find a valid field address is it a
                        # field address or data from this field? Of course this
                        # could also be corrupt data (unlikely though as it was
                        # decoded using a checksum). So all we can really do is
                        # accept the data we have so far, log the issue and
                        # ignore the remaining data.
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

        @staticmethod
        def decode_humid(data, field=None):
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

        @staticmethod
        def decode_press(data, field=None):
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

        @staticmethod
        def decode_dir(data, field=None):
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

        @staticmethod
        def decode_big_rain(data, field=None):
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

        @staticmethod
        def decode_batt(data, field=None):
            """Decode battery status data.

            GW1000/GW1100 firmware version 1.6.4 and earlier supported 16 bytes
            of battery state data at response field x4C for the following
            sensors:
                WH24, WH25, WH26(WH32), WH31 ch1-8, WH40, WH41/WH43 ch1-4,
                WH51 ch1-8, WH55 ch1-4, WH57, WH68 and WS80

            As of firmware version 1.6.5 the 16 bytes of battery state data is
            no longer returned at all. CMD_READ_SENSOR_ID_NEW or
            CMD_READ_SENSOR_ID must be used to obtain battery state information
            for connected sensors. The decode_batt() method has been retained
            to support devices using firmware version 1.6.4 and earlier.

            Since the GW1000/GW1100 driver now obtains battery state
            information via CMD_READ_SENSOR_ID_NEW or CMD_READ_SENSOR_ID only
            the decode_batt() method now returns None so that firmware versions
            before 1.6.5 continue to be supported.
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

        # Tuple of sensor ID values for sensors that are not registered with the GW1000/GW1100. 'fffffffe' means the sensor is disabled, 'ffffffff' means the sensor is registering.
        not_registered = ('fffffffe', 'ffffffff')

        def __init__(self, sensor_id_data=None, show_battery=False, debug_sensors=False):
            """Initialise myself"""

            # init logger
            self.logger = logging.getLogger(__name__)
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
            """Obtain a list of sensor addresses.

            This includes all sensor addresses reported by the GW1000/GW1100,
            this includes:
            - sensors that are actually connected to the GW1000/GW1100
            - sensors that are attempting to connect to the GW1000/GW1100
            - GW1000/GW1100 sensor addresses that are searching for a sensor
            - GW1000/GW1100 sensor addresses that are disabled
            """

            # this is simply the list of keys to our sensor data dict
            return self.sensor_data.keys()

        @property
        def connected_addresses(self):
            """Obtain a list of sensor addresses for connected sensors only.

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
            """Obtain a list of sensor types for connected sensors only.

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
            """Obtain a dict of sensor battery state and signal level data.

            Iterate over the list of connected sensors and obtain a dict of
            sensor battery state data for each connected sensor.
            """

            # initialise a dict to hold the battery state data
            data = {}
            # iterate over our connected sensors
            for sensor in self.connected_addresses:
                # get the sensor name
                sensor_name = Gw1000Collector.sensor_ids[sensor]['name']
                # create the sensor battery state field for this sensor
                data[''.join([sensor_name, '_batt'])] = self.battery_state(sensor)
                # create the sensor signal level field for this sensor
                data[''.join([sensor_name, '_sig'])] = self.signal_level(sensor)
            # return our data
            return data

        @staticmethod
        def battery_desc(address, value):
            """Determine the battery state description for a given sensor.

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
            """Decode a binary battery state.

            Battery state is stored in bit 0 as either 0 or 1. If 1 the battery
            is low, if 0 the battery is normal. We need to mask off bits 1 to 7 as
            they are not guaranteed to be set in any particular way.
            """

            return batt & 1

        @staticmethod
        def batt_int(batt):
            """Decode a integer battery state.

            According to the API documentation battery state is stored as an
            integer from 0 to 5 with <=1 being considered low. Experience with
            WH43 has shown that battery state 6 also exists when the device is
            run from DC. This does not appear to be documented in the API
            documentation.
            """

            return batt

        @staticmethod
        def batt_volt(batt):
            """Decode a voltage battery state in 2mV increments.

            Battery state is stored as integer values of battery voltage/0.02
            with <=1.2V considered low.
            """

            return round(0.02 * batt, 2)

        @staticmethod
        def batt_volt_tenth(batt):
            """Decode a voltage battery state in 100mV increments.

            Battery state is stored as integer values of battery voltage/0.1
            with <=1.2V considered low.
            """

            return round(0.1 * batt, 1)

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


def timestamp_to_string(ts, format_str="%Y-%m-%d %H:%M:%S %Z"):
    """Return a string formatted from the timestamp
    
    Example:
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


def to_sorted_string(rec):
    """Return a sorted string """

    import locale
    return ", ".join(["%s: %s" % (k, rec.get(k)) for k in sorted(rec, key=locale.strxfrm)])
