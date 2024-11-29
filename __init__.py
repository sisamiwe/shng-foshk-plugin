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

import os
import queue
import pickle

from lib.model.smartplugin import SmartPlugin
from lib.utils import Utils
from lib.shtime import Shtime
from .webif import WebInterface

from .gateway_driver import *
from .utility import *


class Foshk(SmartPlugin):
    """Main class of the Plugin. Does all plugin specific stuff and provides the update functions for the items."""

    PLUGIN_VERSION = '1.3.2'

    def __init__(self, sh):
        """Initializes the plugin"""

        # call init code of parent class (SmartPlugin)
        super().__init__()

        # define variables and attributes
        self.data_queue = queue.Queue()                                    # Queue containing all polled data
        self.data_dict = dict()                                            # dict to hold all live data gotten from weather station gateway via post, api and http
        self.gateway = None                                                # driver object
        self.alive = False                                                 # plugin alive
        self.pickle_filepath = f"{os.getcwd()}/var/plugin_data/{self.get_shortname()}"
        self.shtime = Shtime.get_instance()

        # get pause item path
        self._pause_item_path = self.get_parameter_value('pause_item')

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
        # ToDo: read crontab form default plugin parameters
        # self.logger.warning(f"{api_update_crontab=}")
        if not api_update_crontab:
            api_update_crontab = None
        if not (api_update_cycle or api_update_crontab):
            self.logger.warning(f"{self.get_fullname()}: no update cycle or crontab set. The data will not be polled automatically")

        fw_check_crontab = self.get_parameter_value('FW_Update_Check_Crontab')
        # ToDo: read crontab form default plugin parameters
        # self.logger.warning(f"{fw_check_crontab=}")
        if not fw_check_crontab:
            fw_check_crontab = None

        _ecowitt_data_cycle = self.get_parameter_value('Ecowitt_Data_Cycle')

        gateway_config = {'ip_address': gateway_address,
                          'port': gateway_port,
                          'api_data_cycle': api_update_cycle,
                          'api_data_crontab': api_update_crontab,
                          'fw_check_crontab': fw_check_crontab,
                          'use_wh32': self.get_parameter_value('Use_of_WH32'),
                          'ignore_wh40_batt': self.get_parameter_value('Ignore_WH40_Battery'),
                          'discovery_method': self.get_parameter_value('Discovery_Method'),
                          'lat': self.get_sh()._lat,
                          'lon': self.get_sh()._lon,
                          'alt': self.get_sh()._elev,
                          'lang': self.get_sh().get_defaultlanguage(),
                          'post_server_cycle': max(_ecowitt_data_cycle, 16),
                          }

        # init Config Classes
        self.gw_config = GatewayConfig(**gateway_config)

        # get a GatewayDriver object
        try:
            self.logger.debug(f"Start interrogating.....")
            self.gateway = GatewayDriver(plugin_instance=self)
            self.logger.debug(f"Interrogating {self.gateway.gateway_model} at {self.gateway.ip_address}:{self.gateway.port}")
        except GatewayIOError:
            self.logger.error(f"Unable to connect to device: {self.gw_config.ip_address}")
            self.gateway = None
            self._init_complete = False

        # get webinterface
        if not self.init_webinterface(WebInterface):
            self.logger.warning("Webinterface not initialized")

    def run(self):
        """Run method for the plugin"""

        self.logger.debug("Run method called")

        # add scheduler
        self.scheduler_add('poll_api', self.gateway.get_current_api_data, cycle=self.gw_config.api_data_cycle, cron=self.gw_config.api_data_crontab)
        if self.gw_config.fw_check_crontab is not None:
            self.scheduler_add('check_fw_update', self.is_firmware_update_available, cron=self.gw_config.fw_check_crontab)

        self.gateway.run()
        self._update_gateway_meta_data()

        # let the plugin change the state of pause_item
        if self._pause_item:
            self._pause_item(False, self.get_fullname())

        self.alive = True

        self.logger.debug('Start consuming queue')
        self._work_data_queue()

    def stop(self):
        """Stop method for the plugin"""

        self.alive = False
        self.gateway.stop()
        self.scheduler_remove_all()
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

        # check for pause item
        if item.property.path == self._pause_item_path:
            self.logger.debug(f'pause item {item.property.path} registered')
            self._pause_item = item
            self.add_item(item, updating=True)
            return self.update_item

        if self.has_iattr(item.conf, 'foshk_attribute'):
            foshk_attribute = (self.get_iattr_value(item.conf, 'foshk_attribute')).lower()

            # ignore item for showing fw_update_available, if FW-Update Check is not enabled.
            if foshk_attribute == DataPoints.FIRMWARE_UPDATE_AVAILABLE[0] and not self.gw_config.fw_check_crontab:
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

        # check for pause item
        if item is self._pause_item and caller != self.get_shortname():
            self.logger.debug(f'pause item changed to {item()}')
            if item() and self.alive:
                self.stop()
            elif not item() and not self.alive:
                self.run()
            return

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

        self.logger.debug(f"Called with source='{source}'")

        for entry in data:
            if entry not in self.data_dict:
                self.data_dict[entry] = {}

            self.data_dict[entry].update({source: data[entry]})

    #############################################################
    #  Config Methods
    #############################################################

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
