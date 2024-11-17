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


from .sensors import *
from .utility import *
from .config import *
from .exceptions import *


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
        self.gw_config = self._plugin_instance.gw_config

        # get a parser object to parse any API data
        self.parser = ApiParser(plugin_instance)

        # initialise flags to indicate if IP address were discovered
        self.ip_discovered = self.gw_config.ip_address is None

        # if IP address or port was not specified (None) then attempt to discover the device with a UDP broadcast
        if self.gw_config.ip_address is None or self.gw_config.port is None:
            for attempt in range(self.gw_config.max_tries):
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
                        self.gw_config.ip_address = disc_ip
                        self.gw_config.port = disc_port
                        break
                    else:
                        # did not discover any device so log it
                        if DebugLogConfig.api:
                            self.logger.debug(f"Failed to detect device IP address and/or port after {attempt + 1,} attempts")
                        # do we try again or raise an exception
                        if attempt < self.gw_config.max_tries - 1:
                            # we still have at least one more try left so sleep and try again
                            time.sleep(self.gw_config.retry_wait)
                        else:
                            # we've used all our tries, log it and raise an exception
                            _msg = f"Failed to detect device IP address and/or port after {attempt + 1,} attempts"
                            self.logger.error(_msg)
                            raise GatewayIOError(_msg)

        # Get my MAC address to use later if we have to rediscover. Within class GatewayApi the MAC address is stored as a bytestring.
        self.gw_config.mac = self.get_mac_address()

        # get my device model
        self.gw_config.model = self.get_model_from_firmware(self.get_firmware_version())

        # Do we have a WH24 attached? First obtain our system parameters.
        _sys_params = self.get_system_params()
        self.gw_config.is_wh24 = _sys_params.get('sensor_type', 0) == 'WH24'

        # get a Sensors object to parse any API sensor state data
        self.sensors = Sensors(plugin_instance=plugin_instance)

        """
        # do we have a legacy WH40 and how are we handling its battery state data
        if b'\x03' in self.sensors.get_connected_addresses() and self.sensors.legacy_wh40:
            # we have a connected legacy WH40
            if self.gw_config.ignore_wh40_batt:
                _msg = 'Legacy WH40 detected, WH40 battery state data will be ignored'
            else:
                _msg = 'Legacy WH40 detected, WH40 battery state data will be reported'
            self.logger.info(_msg)
        """

        # update the sensors object
        self.update_sensor_id_data()

    def discover(self):
        """Discover gateway devices on the local network segment.

        There are two methods of discovering gateway devices on the local network segment. The first utilises the CMD_BROADCAST gateway API
        command which utilises port 46000 to issue a request for gateway devices to respond with relevant device details. The second approach
        relies on the regular, routine broadcast made by active gateway devices on port 59387. By monitoring port 59387 over a period of time details
        of the gateway devices active on the local network segment may be obtained.

        In practise the use of the CMD_BROADCAST API command has shown itself to be unreliable with only devices responding. In some cases certain
        devices have been found to effectively ignore receipt of the CMD_BROADCAST API command. On the other hand the monitoring of
        port 59387 has proven to be effective and for this reason it is the default and preferred approach to be used when discovering gateway
        devices.
        """

        # we have been asked to discover gateway devices, but which method are we to use
        if self.gw_config.discovery_method == 'api':
            # use the CMD_BROADCAST API command approach
            return self.api_discover()
        else:
            # use the default approach of monitoring port 59387
            return self.broadcast_discover()

    def broadcast_discover(self):
        """Discover devices on the local network by monitoring port 59387.

        To discover Ecowitt gateway devices monitor UDP port 59387 for a set period of time and capture all port 59387 UDP broadcasts received.
        Decode each reply to obtain details of any devices on the local network. Create a dict of details for each device including a derived
        model name. Construct a list of dicts with details of each unique (ie each unique MAC address) device that responded. When complete
        return the list of devices found.
        """

        # create a socket object so we can receive IPv4 UDP
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        # set timeout
        s.settimeout(self.gw_config.broadcast_timeout)
        # bind our socket to the port we are using
        s.bind(("", self.gw_config.discovery_port))
        # initialise a list for the results as multiple devices may respond
        result_list = []
        # get the current time
        start_ts = time.time()
        # start receiving continuously, we will stop once our discovery period
        # has elapsed
        while True:
            # wrap in try .. except to capture any errors
            try:
                # receive a response
                response = s.recv(1024)
                # log the response if debug is high enough
            except socket.timeout:
                # if we time out then we are done with this attempt
                break
            except socket.error:
                # raise any other socket error
                raise
            # check the response is valid, as it happens the format is the same
            # as used when responding to CMD_BROADCAST API commands
            try:
                self._check_response(response, self.API_COMMANDS['CMD_BROADCAST'])
            except InvalidChecksum as e:
                # the response was not valid, log it and attempt again if we haven't had too many attempts already
                self.logger.debug(f"Invalid discovery response received: {e}")
            except UnknownApiCommand:
                # most likely we have encountered a device that does not understand the command, possibly due to an old or
                # outdated firmware version, raise the exception for our caller to deal with
                raise
            except Exception as e:
                # Some other error occurred in check_response(), perhaps the response was malformed. Log the stack trace but continue.
                self.logger.error(f"Unexpected exception occurred while checking discovery response: {e}")

            else:
                # we have a valid response so decode the response
                # and obtain a dict of device data
                device = self.decode_broadcast_response(response)
                # if we haven't seen this MAC before attempt to obtain
                # and save the device model then add the device to our
                # results list
                if not any((d['mac'] == device['mac']) for d in result_list):
                    # determine the device model based on the device
                    # SSID and add the model to the device dict
                    device['model'] = self.get_model_from_ssid(device.get('ssid'))
                    # append the device to our list
                    result_list.append(device)
            # has our discovery period elapsed, if it has break out of the
            # loop
            if time.time() - start_ts > self.gw_config.discovery_period:
                break
        # we are done, close our socket
        s.close()
        # now return our results
        return result_list

    def api_discover(self):
        """Discover any devices on the local network.

        Send a UDP broadcast and check for replies. Decode each reply to obtain details of any devices on the local network. Create a dict
        of details for each device including a derived model name.
        Construct a list of dicts with details of unique (MAC address) devices that responded. When complete return the list of devices found.
        """

        # create a socket object to broadcast to the network via IPv4 UDP
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        s.settimeout(self.gw_config.broadcast_timeout)
        # set TTL to 1 to so messages do not go past the local network segment
        ttl = struct.pack('b', 1)
        s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, ttl)
        packet = self._build_cmd_packet('CMD_BROADCAST')
        if DebugLogConfig.api:
            self.logger.debug(f"Sending broadcast packet <{packet}> in Hex: '{bytes_to_hex(packet)}' to '{self.gw_config.broadcast_address}:{self.gw_config.broadcast_port}'")
        
        # initialise a list for the results as multiple devices may respond
        result_list = []
        s.sendto(packet, (self.gw_config.broadcast_address, self.gw_config.broadcast_port))
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
                    device = self.decode_broadcast_response(response)
                    if not any((d['mac'] == device['mac']) for d in result_list):
                        device['model'] = self.get_model_from_ssid(device.get('ssid'))
                        result_list.append(device)
        s.close()
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
            self.logger.info(f"Attempting to re-discover {self.gw_config.model}...")
            # attempt to discover up to self.max_tries times
            for attempt in range(self.gw_config.max_tries):
                # sleep before our attempt, but not if it's the first one
                if attempt > 0:
                    time.sleep(self.gw_config.retry_wait)
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
                            if self.gw_config.mac == device['mac']:
                                self.gw_config.ip_address = device['ip_address'].encode()
                                self.gw_config.port = device['port']
                                break
                        else:
                            # we have exhausted the device list without a match so continue the outer loop if we have any attempts left
                            continue
                        # log the new IP address and port
                        self.logger.info(f"{self.gw_config.model} at address {self.gw_config.ip_address}:{self.gw_config.port} will be used")
                        # return True indicating the re-discovery was successful
                        return True
                    else:
                        if DebugLogConfig.api:
                            self.logger.debug(f"Failed attempt {attempt + 1} to detect any devices")
            else:
                # we exhausted our attempts at re-discovery so log it
                self.logger.info(f"Failed to detect original {self.gw_config.model} after {self.gw_config.max_tries} attempts")
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
            for model in self.gw_config.known_models:
                if model in t.upper():
                    return model
            # we don't have a known model so return None
            return 'unknown model'
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
        self.logger.debug(f"get_system_params: response={response}")
        self.logger.debug(f"get_system_params: parsed response={self.parser.parse_read_ssss(response)}")
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
            self.logger.debug(f"Firmware update called for {self.gw_config.ip_address}:{self.gw_config.port}")
        payload = bytearray()
        payload.extend(socket.inet_aton(self.gw_config.ip_address))
        payload.extend(int_to_bytes(self.gw_config.port, 2))
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
            self.logger.debug(f"set_reboot: Reboot called for {self.gw_config.ip_address}:{self.gw_config.port}")
        return self._send_cmd_with_retries('CMD_WRITE_REBOOT')

    def set_reset(self):
        """
        Reset Gateway .

        Sends the command to reboot Gateway to the API with retries. If the Gateway cannot be contacted a
        GatewayIOError will have been raised by _send_cmd_with_retries() which will be passed through by set_reboot(). Any code
        calling set_reboot() should be prepared to handle this exception.
        """
        if DebugLogConfig.api:
            self.logger.debug(f"set_reboot: Reset called for {self.gw_config.ip_address}:{self.gw_config.port}")
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
        for attempt in range(self.gw_config.max_tries):
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
            if attempt < self.gw_config.max_tries - 1:
                time.sleep(self.gw_config.retry_wait)

        # if we made it here we failed after self.max_tries attempts first log it
        _msg = f"Failed to obtain response to command '{cmd}' after {self.gw_config.max_tries} attempts"
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
            s.settimeout(self.gw_config.socket_timeout)
            try:
                s.connect((self.gw_config.ip_address, self.gw_config.port))
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

    # Dictionary of 'address' based data. Dictionary is keyed by device data field 'address' containing various parameters for each 'address'.
    # Dictionary tuple format is: (decode fn, size, field name) where:
    #   decode fn:  the decode function name to be used for the field
    #   size:       the size of field data in bytes
    #   field name: the name of the device field to be used for the decoded data

    api_data_struct = {
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
        b'\x6B': ('decode_wh46', 24, DataPoints.SENSOR_WH45[0]),             # WH46 battery data is not obtained from live data rather it is obtained from sensor ID data
        b'\x6C': ('decode_memory', 4, DataPoints.HEAP[0]),
        b'\x70': ('decode_wh45', 16, DataPoints.SENSOR_WH45[0]),             # WH45 battery data is not obtained from live data rather it is obtained from sensor ID data
        b'\x71': (None, None, None),                                         # placeholder for unknown field 0x71
        b'\x72': ('decode_wet', 1, DataPoints.LEAF_WETNESS1[0]),
        b'\x73': ('decode_wet', 1, DataPoints.LEAF_WETNESS2[0]),
        b'\x74': ('decode_wet', 1, DataPoints.LEAF_WETNESS3[0]),
        b'\x75': ('decode_wet', 1, DataPoints.LEAF_WETNESS4[0]),
        b'\x76': ('decode_wet', 1, DataPoints.LEAF_WETNESS5[0]),
        b'\x77': ('decode_wet', 1, DataPoints.LEAF_WETNESS6[0]),
        b'\x78': ('decode_wet', 1, DataPoints.LEAF_WETNESS7[0]),
        b'\x79': ('decode_wet', 1, DataPoints.LEAF_WETNESS8[0])
    }

    api_rain_data_struct = {
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
        self.logger.debug(f"ApiParser object created")
        # get interface config
        self.gw_config = self._plugin_instance.gw_config

        # do we log unknown fields at info or leave at debug
        self.log_unknown_fields = self.gw_config.log_unknown_fields

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
                    _decode_fn_str, _field_size, _field = structure[payload[index:index + 1]]
                    if DebugLogConfig.api:
                        self.logger.debug(f"Decode id={payload[index:index + 1]} with {_field=} and {_field_size=}")
                except KeyError:
                    _msg = f"Unknown field address '{bytes_to_hex(payload[index:index + 1])}' detected. Remaining data '{bytes_to_hex(payload[index + 1:])}' ignored."
                    if self.log_unknown_fields:
                        self.logger.info(_msg)
                    else:
                        if DebugLogConfig.api:
                            self.logger.debug(_msg)
                    break
                else:
                    _field_data = getattr(self, _decode_fn_str)(payload[index + 1:index + 1 + _field_size], _field, _field_size)
                    if _field_data is not None:
                        data.update(_field_data)
                    else:
                        # we received None from the decode function, this usually indicates a field marked as 'reserved' in the API documentation
                        pass
                    index += _field_size + 1
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
        return self.parse_addressed_data(payload,  self.api_data_struct)

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
        return self.parse_addressed_data(payload, self.api_rain_data_struct)

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
        gain_dict[MasterKeys.SOLARRADIATION] = struct.unpack(">H", data[4:6])[0] / 100.0
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
            # get 'Customize' setting 1 = enable, 0 = customized
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

        self.logger.debug(f"parse_read_ssss {data=}")
        # initialise a dict to hold our final data
        data_dict = dict()
        data_dict['frequency'] = FREQUENCIES[data[0]]
        data_dict['sensor_type'] = SENSOR_TYPES[data[1]]
        utc_dt = datetime.fromtimestamp(self.decode_utc(data[2:6], field_size=4)).replace(tzinfo=timezone.utc)
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
    def decode_temp(data, field=None, field_size: int = 2):
        """Decode temperature data.

        Data is contained in a two byte big endian signed integer and represents tenths of a degree. If field is not None return the
        result as a dict in the format {field: decoded value} otherwise return just the decoded value.
        """

        if len(data) == field_size:
            value = struct.unpack(">h", data)[0] / 10.0
        else:
            value = None
        if field is not None:
            return {field: value}
        else:
            return value

    @staticmethod
    def decode_humid(data, field=None, field_size: int = 1):
        """Decode humidity data.

        Data is contained in a single unsigned byte and represents whole units. If field is not None return the result as a dict in the
        format {field: decoded value} otherwise return just the decoded value.
        """

        if len(data) == field_size:
            value = struct.unpack("B", data)[0]
        else:
            value = None
        if field is not None:
            return {field: value}
        else:
            return value

    def decode_uv(self, data, field=None, field_size: int = 2):

        if len(data) == field_size:
            value = struct.unpack(">H", data)[0]
            self.logger.debug(f"decode_uv: {data=}, {value=}")
        else:
            value = None
        if field is not None:
            return {field: value}
        else:
            return value

    def decode_solarradiation(self, data, field=None, field_size: int = 4):

        if len(data) == field_size:
            value = struct.unpack(">H", data)[0]
            self.logger.debug(f"decode_solarradiation: {data=}, {value=}")
        else:
            value = None
        if field is not None:
            return {field: value}
        else:
            return value

    @staticmethod
    def decode_press(data, field=None, field_size: int = 2):
        """Decode pressure data.

        Data is contained in a two byte big endian integer and represents tenths of a unit. If data contains more than two bytes take the
        last two bytes. If field is not None return the result as a dict in the format {field: decoded value} otherwise return just the decoded
        value.

        Also used to decode other two byte big endian integer fields.
        """

        if len(data) == field_size:
            value = struct.unpack(">H", data)[0] / 10.0
        elif len(data) > field_size:
            value = struct.unpack(">H", data[-2:])[0] / 10.0
        else:
            value = None
        if field is not None:
            return {field: value}
        else:
            return value

    @staticmethod
    def decode_dir(data, field=None, field_size: int = 2):
        """Decode direction data.

        Data is contained in a two byte big endian integer and represents whole degrees. If field is not None return the result as a dict in
        the format {field: decoded value} otherwise return just the decoded value.
        """

        if len(data) == field_size:
            value = struct.unpack(">H", data)[0]
        else:
            value = None
        if field is not None:
            return {field: value}
        else:
            return value

    @staticmethod
    def decode_big_rain(data, field=None, field_size: int = 4):
        """Decode 4 byte rain data.

        Data is contained in a four byte big endian integer and represents tenths of a unit. If field is not None return the result as a dict
        in the format {field: decoded value} otherwise return just the decoded value.
        """

        if len(data) == field_size:
            value = struct.unpack(">L", data)[0] / 10.0
        else:
            value = None
        if field is not None:
            return {field: value}
        else:
            return value

    @staticmethod
    def decode_datetime(data, field=None, field_size: int = None):
        """Decode date-time data.

        Unknown format but length is six bytes. If field is not None return the result as a dict in the format {field: decoded value} otherwise
        return just the decoded value.
        """

        if len(data) == field_size:
            value = struct.unpack("BBBBBB", data)[0]
        else:
            value = None

        if value and value.isdigit():
            value = int(value)

        if field is not None:
            return {field: value}
        else:
            return value

    def decode_datetime_as_dt(self, data, field=None, field_size: int = 6):
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
    def decode_distance(data, field=None, field_size: int = 1):
        """Decode lightning distance.

        Data is contained in a single byte integer and represents a value from 0 to 40km. If field is not None return the result as a dict in
        the format {field: decoded value} otherwise return just the decoded value.
        """

        if len(data) == field_size:
            value = struct.unpack("B", data)[0]
            value = value if value <= 40 else None
        else:
            value = None
        if field is not None:
            return {field: value}
        else:
            return value

    @staticmethod
    def decode_utc(data, field=None, field_size: int = 4):
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

        if len(data) == field_size:
            value = struct.unpack(">L", data)[0]
            # when processing the last lightning strike time if the value is 0xFFFFFFFF it means we have never seen a strike so return None
            value = value if value != 0xFFFFFFFF else None
        else:
            value = None

        if field is not None:
            return {field: value}

        return value

    @staticmethod
    def decode_count(data, field=None, field_size: int = 4):
        """Decode lightning count.

        Count is an integer stored in a four byte big endian integer. If field is not None return the result as a dict in the format
        {field: decoded value} otherwise return just the decoded value.
        """

        if len(data) == field_size:
            value = struct.unpack(">L", data)[0]
        else:
            value = None
        if field is not None:
            return {field: value}
        else:
            return value

    @staticmethod
    def decode_gain_100(data, field=None, field_size: int = 2):
        """Decode a sensor gain expressed in hundredths.

        Gain is stored in a four byte big endian integer and represents hundredths of a unit.
        """

        if len(data) == field_size:
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

    def decode_wn34(self, data, fields=None, field_size: int = 3):
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

        if len(data) != field_size or fields is None:
            return {}

        results = dict()
        results[fields] = self.decode_temp(data[0:2])
        # we could decode the battery voltage but we will be obtaining battery voltage data from the sensor IDs in a later step so we can skip it here
        return results

    def decode_wh45(self, data, fields=None, field_size: int = 16):
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

        if len(data) != field_size or fields is None:
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

    def decode_wh46(self, data, fields=None, field_size: int = 24):
        """Decode WH46 sensor data.

        WH46 sensor data includes TH sensor values, CO2/PM1/PM4/PM2.5/PM10
        sensor values and 24 hour aggregates and battery state data in
        24 bytes.

        The 24 bytes of WH46 sensor data is allocated as follows:
        Byte(s) #      Data               Format          Comments
        bytes   1-2    temperature        short           C x10
                3      humidity           unsigned byte   percent
                4-5    PM10               unsigned short  ug/m3 x10
                6-7    PM10 24-hour avg   unsigned short  ug/m3 x10
                8-9    PM2.5              unsigned short  ug/m3 x10
                10-11  PM2.5 24-hour avg  unsigned short  ug/m3 x10
                12-13  CO2                unsigned short  ppm
                14-15  CO2 24-hour avg    unsigned short  ppm
                16-17  PM1                unsigned short  ug/m3 x10
                18-19  PM1 24-hour avg    unsigned short  ug/m3 x10
                20-21  PM4                unsigned short  ug/m3 x10
                22-23  PM4 24-hour avg    unsigned short  ug/m3 x10
                24     battery state      unsigned byte   0-5 <=1 is low

        WH46 battery state data is included in the WH46 sensor data (along
        with temperature) as well as in the complete sensor ID data. In
        keeping with other sensors we do not use the sensor data battery
        state, rather we obtain it from the sensor ID data.
        """

        if len(data) != field_size or fields is None:
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
        results[fields[8]] = self.decode_pm1(data[15:17])
        results[fields[9]] = self.decode_pm1(data[17:19])
        results[fields[10]] = self.decode_pm4(data[19:21])
        results[fields[11]] = self.decode_pm4(data[21:23])
        # we could decode the battery state, but we will be obtaining
        # battery state data from the sensor IDs in a later step so
        # we can skip it here
        return results

    def decode_rain_gain(self, data, fields=None, field_size: int = 20):
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

        if len(data) != field_size:
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
    def decode_rain_reset(data, fields=None, field_size: int = 3):
        """Decode rain reset data.

        Rain reset data is three bytes of data comprising three unsigned
        byte fields with each field representing an integer.

        The three bytes of rain reset data is allocated as follows:
        Byte  #  Data               Format         Comments
        byte  1  day reset time     unsigned byte  hour of the day to reset day rain, eg 7 = 07:00
              2  week reset time    unsigned byte  day of week to reset week rain, allowed values are 0 or 1. 0=Sunday, 1=Monday
              3  annual reset time  unsigned byte  month of year to reset annual rain, allowed values are 0-11, eg 2 = March
        """

        if len(data) != field_size:
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
    def decode_batt(data, field=None, field_size: int = None):
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
    decode_memory = decode_count
    decode_pm1 = decode_press
    decode_pm4 = decode_press
