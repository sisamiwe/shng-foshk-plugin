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


import struct

from .datapoints import *
from .utility import *


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
        b'\x30': {'name': SensorKeys.WS90,   'batt_fn': 'batt_volt', 'low_batt': 3},
        b'\x31': {'name': SensorKeys.WS85,   'batt_fn': 'batt_volt'}
    }
    # sensors for which there is no low battery state
    no_low = ['ws80', 'ws85', 'ws90']

    # Tuple of sensor ID values for sensors that are not registered with the device.
    # 'fffffffe' means the sensor is disabled, 'ffffffff' means the sensor is registering.
    not_registered = ('fffffffe', 'ffffffff')

    def __init__(self, plugin_instance, sensor_id_data=None):

        # get instance
        self._plugin_instance = plugin_instance
        self.logger = self._plugin_instance.logger

        # get interface config
        self.gw_config = self._plugin_instance.gw_config

        # If WH32 sensor is used, decode that, otherwise it will decode to WH26 by default
        if self.gw_config.use_wh32:
            # set the WH24 sensor id decode dict entry
            self.sensor_ids[b'\x05']['name'] = SensorKeys.WH32

        # Tell our sensor id decoding whether we have a WH24 or a WH65. By default, we are coded to use a WH65.
        if self.gw_config.is_wh24:
            # set the WH24 sensor id decode dict entry
            self.sensor_ids[b'\x00']['name'] = SensorKeys.WH24

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
                    if not self.gw_config.show_battery and data[index + 6] == 0:
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
            self.gw_config.legacy_wh40 = True
            # then do we ignore the result or pass it on
            if self.gw_config.ignore_wh40_batt:
                # we are ignoring the result so return None
                return None
            else:
                # we are not ignoring the result so return the result
                return round(0.1 * batt, 1)
        else:
            # assume we have a battery state reporting WH40 first reset the legacy_wh40 flag
            self.gw_config.legacy_wh40 = False
            return round(0.01 * batt, 2)

    @staticmethod
    def batt_volt_tenth(batt) -> float:
        """Decode a voltage battery state in 100mV increments.

        Battery state is stored as integer values of battery voltage/0.1 with <=1.2V considered low.
        """

        return round(0.1 * batt, 1)
