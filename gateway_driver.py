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

from configparser import ConfigParser

from .gateway_device import *
from .gateway_api import *
from .gateway_http import *
from .gateway_tcp import *


class GatewayDriver(GatewayDevice):

    def __init__(self, plugin_instance):

        # get instance
        self._plugin_instance = plugin_instance
        self.logger = self._plugin_instance.logger

        # get interface config
        self.gw_config = self._plugin_instance.gw_config

        # now initialize my superclasses
        super().__init__(plugin_instance)

        # get a GatewayApi object to handle the interaction with the API
        try:
            self.logger.info('Init connection to Ecowitt Gateway via API')
            self.api = GatewayApi(plugin_instance)
        except Exception as e:
            self.api = None
            raise GatewayConnectError(e)

        # get a GatewayHttp object to handle any HTTP requests
        if self.gateway_model in self.gw_config.known_models_with_get_request:
            try:
                self.logger.info('Init connection to Ecowitt Gateway via HTTP requests')
                self.http = GatewayHttp(plugin_instance)
            except Exception as e:
                self.http = None
                raise GatewayConnectError(e)
        else:
            if DebugLogConfig.gateway:
                self.logger.debug('Ecowitt Gateway does not support interface via HTTP requests')
            self.http = None

        # get a GatewayTCP object to handle data from server upload
        if self.gw_config.post_server_ip and self.gw_config.post_server_port:
            try:
                self.logger.info('Init connection to Ecowitt Gateway via HTTP Post')
                self.tcp = GatewayTcp(plugin_instance, self.get_current_tcp_data)
            except Exception as e:
                self.tcp = None
                raise GatewayConnectError(e)
        else:
            if DebugLogConfig.gateway:
                self.logger.debug('Interface via HTTP Post not activated')
            self.tcp = None

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

        if self.gw_config.show_sensor_warning:
            # add sensor warning data field
            self.check_sensors(data, self.api.sensors.get_connected_addresses())

        if self.gw_config.show_battery_warning:
            # add battery warning data field
            self.check_battery(data, self.api.sensors.get_battery_description_data())

        if self.gw_config.show_storm_warning:
            # add storm warning data field
            data[DataPoints.STORM_WARNING[0]] = self.get_storm_warning()

        if self.gw_config.show_leakage_warning:
            # add leakage warning data field
            data[DataPoints.LEAKAGE_WARNING[0]] = self.get_leakage_warning(data)

        if self.gw_config.show_fw_update_available:
            # add show_fw_update_available field
            data[DataPoints.FIRMWARE_UPDATE_AVAILABLE[0]] = self.gw_config.fw_update_available

        # check data
        self.check_ws_warning(data, self.gw_config.show_weatherstation_warning)

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

        return self.gw_config.ip_address

    @property
    def port(self):
        """The gateway device port number."""

        return self.gw_config.port

    @property
    def gateway_model(self):
        """Gateway device model."""

        return self.gw_config.model

    @property
    def mac_address(self):
        """Gateway device MAC address."""

        return self.gw_config.mac

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

    @property
    def discovered_devices(self):
        """List of discovered gateway devices.

        Each list element is a dict keyed by 'ip_address', 'port', 'model',
        'mac' and 'ssid'."""

        return self.api.discover()

    @property
    def firmware_update_available(self):
        """Whether a device firmware update is available or not.

        Return True if a device firmware update is available, False if there is
        no available firmware update or None if firmware update availability
        cannot be determined.
        """

        # get firmware version info
        version = self.http.get_version()
        # do we have current firmware version info and availability of a new
        # firmware version ?
        if version is not None and 'newVersion' in version:
            # we can now determine with certainty whether there is a new
            # firmware update or not
            return True if version['newVersion'] == '1' else False
        # We cannot determine the availability of a firmware update so return
        # None
        return None

    @property
    def firmware_update_message(self):
        """The device firmware update message.

        Returns the 'curr_msg' field in the 'get_device_info' response in the
        device HTTP API. This field is usually used for firmware update release
        notes.

        Returns a string containing the 'curr_msg' field contents of the
        'get_device_info' response. Return None if the 'get_device_info'
        response could not be obtained or the 'curr_msg' field was not included
        in the 'get_device_info' response.
        """

        # get device info
        device_info = self.http.get_device_info()
        # return the 'curr_msg' field contents or None
        return device_info.get('curr_msg') if device_info is not None else None

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
    def sensor_firmware_versions(self):
        """Firmware versions for attached sensors with user updatable firmware.

        Some sensors have user updatable firmware, at time of release the only sensors/sensor platforms that have user updatable firmware are:

        The sensor firmware version can be obtained via the HTTP API. Obtain the sensor information via the HTTP API and extract the firmware
        version info for known user updatable sensors.

        Returns a dict keyed by sensor/sensor platform model containing the applicable firmware versions. If no sensors/sensor platforms were found
        with user updatable firmware return and empty dict.
        """

        # obtain the sensor info via the HTTP API
        sensors = self.http.get_sensors_info()
        # initialise a dict to hold our results
        fware_dict = dict()
        # do we have any sensor information
        if sensors is not None:
            # we have sensor information so iterate over each sensor
            for sensor in sensors:
                # if we have a sensor with user updatable firmware obtain the firmware version and save it to our result dict, but only if the device exists, ie 'batt' != '9'
                if sensor.get('img') in self.gw_config.sensors_with_firmware and sensor.get('batt') != '9':
                    fware_dict[self.gw_config.sensors_with_firmware[sensor.get('img')]] = sensor.get('version', 'not available')
        # return the result dict
        return fware_dict

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

        current_usr_path = self.gw_config.usr_path
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

        current_custom_params = self.gw_config.custom_params
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

        fw_info = requests.get(self.gw_config.FW_UPDATE_URL)
        if DebugLogConfig.gateway:
            self.logger.debug(f"check_firmware_update: getting firmware update info from {self.gw_config.FW_UPDATE_URL} results in status={fw_info.status_code}")

        if fw_info.status_code == 200:

            # establish configparser, read response text and extract information for given model
            fw_update_info = ConfigParser(allow_no_value=True, strict=False)
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
        self.gw_config.fw_update_available = result
        return result
