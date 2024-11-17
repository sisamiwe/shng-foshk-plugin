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


# ============================================================================
#                           Config classes
# ============================================================================

from dataclasses import dataclass, field


@dataclass
class GatewayConfig:
    """Class to simplify use and handling of gateway config."""

    # known device models
    known_models: set = ('GW1000', 'GW1100', 'GW2000', 'WH2650', 'WH2680', 'WN1900', 'GW1200', 'WS3800', 'WS3900', 'WS3910')
    
    # models supporting get-request
    known_models_with_get_request: set = ('GW1100', 'GW2000')

    # sensor with separate firmware
    sensors_with_firmware: dict = field(default_factory=lambda: {'wh80': 'WS80', 'wh85': 'WS85', 'wh90': 'WS90'})

    # Gateway IP for api communication
    ip_address: str = None

    # Gateway port for api communication
    port: int = 45000

    # Gateway mac address
    mac: str = None

    # Gateway model
    model: str = None

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

    # default discovery method, may be 'api' or 'broadcast'
    discovery_method: str = 'broadcast'

    # default port to use for discovery of devices by broadcast monitoring
    discovery_port = 59387

    # default period in seconds to use for discovery of devices by broadcast monitoring
    discovery_period = 5

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

    # is a legacy wh40 sensor connected
    legacy_wh40: bool = False

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

    # Firmware Update URL String
    FW_UPDATE_URL: str = 'http://download.ecowitt.net/down/filewave?v=FirwaveReadme.txt'.replace("\"", "")

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
class WarningLevels:
    # Druckunterschied in 1h zur Auslösung der Sturmwarnung: 1.75hPa
    STORM_WARNDIFF_1H: float = 1.75

    # Druckunterschied in 3h zur Auslösung der Sturmwarnung: 3.75hPa
    STORM_WARNDIFF_3H: float = 3.75

    # Auflauf der Sturmwarnung: 60 Minuten
    STORM_EXPIRE: int = 60

    # Auslösen der Gewitterwarnung nach: 1 Blitz
    TSTORM_WARNCOUNT: int = 1

    # Auslösen der Gewitterwarnung bei Gewitterabstand: 30km
    TSTORM_WARNDIST: int = 30

    # Auflauf der Gewitterwarnung: 15 Minuten
    TSTORM_EXPIRE: int = 15

    # Auslösen der CO2 Warnung: ab 1200
    CO2_WARNLEVEL: int = 1200

    # Minimal Sonne
    SUN_MIN: float = 0

    # Sonnenkoeffizient
    SUN_COEF: float = 0.8
