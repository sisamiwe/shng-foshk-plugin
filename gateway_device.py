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


from collections import deque
from math import sin, cos, pi, radians, degrees, atan2

import lib.env as env

from .config import *
from .datapoints import *
from .utility import *
from .meteocalcs import *


class GatewayDevice(object):
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
        self.gw_config = self._plugin_instance.gw_config

        # define data structures
        self.pickle_data_validity_time = 600                                                         # seconds after which the data saved in pickle are not valid anymore
        self.wind_avg10m = deque(maxlen=(int(10 * 60 / self.gw_config.api_data_cycle)))              # deque to hold 10 minutes of wind speed, wind direction and windgust
        self.pressure_3h = self._init_pressure_3h()                                                  # deque to hold air pressure date
        self.pressure_last = self._init_pressure_last()                                              # dict to hold last air_pressure_values
        self.sun_time = self._init_sun_time_dict()                                                   # dict to hold sun time data

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
        return deque(maxlen=(int(3 * 3600 / self.gw_config.api_data_cycle + 5)))

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

    def add_temp_data(self, data: dict) -> None:
        """
        Add calculated data to dict

        :param data: dict of parsed Ecowitt Gateway data
        """

        if DataPoints.OUTTEMP[0] in data:

            if DataPoints.WINDSPEED[0] in data:
                data[DataPoints.FEELS_LIKE[0]] = get_windchill_index(data[DataPoints.OUTTEMP[0]], data[DataPoints.WINDSPEED[0]], units='metric')
                data[DataPoints.HEATINDEX[0]] = get_heat_index(data[DataPoints.OUTTEMP[0]], data[DataPoints.WINDSPEED[0]], units='metric')

                if data.keys() >= {DataPoints.OUTHUMI[0]}:
                    data[DataPoints.FEELS_LIKE[0]] = get_feels_like_temperature(temperature=data[DataPoints.OUTTEMP[0]], humidity_rel=DataPoints.OUTHUMI[0], wind_speed=data[DataPoints.WINDSPEED[0]], units='metric')
            if DataPoints.OUTHUMI[0] in data:
                dewpt_c = get_dew_point(temperature=data[DataPoints.OUTTEMP[0]], humidity_rel=data[DataPoints.OUTHUMI[0]], units='metric')
                data[DataPoints.OUTDEWPT[0]] = dewpt_c
                data[DataPoints.OUTFROSTPT[0]] = get_frost_point(temperature=data[DataPoints.OUTTEMP[0]], dew_point=dewpt_c, units='metric')
                data[DataPoints.CLOUD_CEILING[0]] = get_cloud_ceiling(temperature=data[DataPoints.OUTTEMP[0]], dew_point=dewpt_c, units='metric')
                data[DataPoints.OUTABSHUM[0]] = get_abs_hum(temperature=data[DataPoints.OUTTEMP[0]], humidity_rel=data[DataPoints.OUTHUMI[0]], units='metric')

        if DataPoints.INTEMP[0] in data and DataPoints.INHUMI[0] in data:
            data[DataPoints.INDEWPPOINT[0]] = get_dew_point(temperature=data[DataPoints.INTEMP[0]], humidity_rel=data[DataPoints.INHUMI[0]], units='metric')
            data[DataPoints.INABSHUM[0]] = get_abs_hum(temperature=data[DataPoints.INTEMP[0]], humidity_rel=data[DataPoints.INHUMI[0]], units='metric')

        for i in range(1, 9):
            if f'{MasterKeys.TEMP}{i}' in data and f'{MasterKeys.HUMID}{i}' in data:
                data[f'{MasterKeys.DEWPT}{i}'] = get_dew_point(data[f'{MasterKeys.TEMP}{i}'], data[f'{MasterKeys.HUMID}{i}'], units='metric')
                data[f'{MasterKeys.ABSHUM}{i}'] = get_abs_hum(data[f'{MasterKeys.TEMP}{i}'], data[f'{MasterKeys.HUMID}{i}'], units='metric')

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
            data[DataPoints.WINDSPEED_BFT_TEXT[0]] = env.bft_to_text(windspeed_bft, self.gw_config.lang)

        if DataPoints.ABSBARO[0] in data:
            data[DataPoints.WEATHER_TEXT[0]] = get_weather_now(data[DataPoints.ABSBARO[0]], self.gw_config.lang)
                
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
        if air_pressure_rel:
            self.pressure_3h.append([int(time.time()), air_pressure_rel])

        # get index of current position of deque
        pos_current = len(self.pressure_3h)

        # calculate values für 1h and 3h ago
        for x in [1, 3]:
            # get position of data x hour before
            pos_xh_ago = pos_current - int(x * 3600 / self.gw_config.api_data_cycle)

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
                    data[DataPoints.WEATHER_FORECAST_TEXT[0]] = get_weather_forecast(air_pressure_rel_diff_xh_ago, self.gw_config.lang)

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
        # Maybe ToDo: In GW2000 gateway with WS90 (Wittboy) there is UV Index present (0x17) and Solarradiation (0x15)
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
                sinSum += sin(radians(d[i][w]))
                cosSum += cos(radians(d[i][w]))

            # for windspeed and windgust
            else:
                s = s + d[i][w]

        return round((degrees(atan2(sinSum, cosSum)) + 360) % 360, 1) if w == 2 else round(s / len(d), 1)

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
        is3h = True if (end_pos - start_pos) * self.gw_config.api_data_cycle > 3600 else False

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

        if abs(air_pressure_rel_diff_1h_ago) > WarningLevels.STORM_WARNDIFF_1H:
            storm_warning_1h = True
        if abs(air_pressure_rel_diff_3h_ago) > WarningLevels.STORM_WARNDIFF_3H:
            storm_warning_3h = True

        if storm_warning_3h or storm_warning_1h:
            if self.storm_warning_start_time == 0:
                self.storm_warning_start_time = now
            self.logger.info(f"storm warning active since air pressure difference is above warning limit.")
            self.logger.debug(f"{storm_warning_1h=}, {storm_warning_3h=}")
            self.logger.debug(f"Air pressure has {what(air_pressure_rel_diff_1h_ago)} by {air_pressure_rel_diff_1h_ago} within last hour and {what(air_pressure_rel_diff_3h_ago)} by {air_pressure_rel_diff_3h_ago} within last 3 hours.")

        elif self.storm_warning_start_time and now >= self.storm_warning_start_time + WarningLevels.STORM_EXPIRE * 60:
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
        # Maybe ToDo: In GW2000 with WS90 (Wittboy) there ist solarradiation (0x15) and UV index present but not UV
        solar_radiation = data.get(DataPoints.UV[0])
        if not solar_radiation:
            solar_radiation = data.get(DataPoints.SOLARRADIATION[0])

        if not solar_radiation:
            return

        # get basic values
        day_of_year = self._plugin_instance.shtime.day_of_year()
        azimut_radians, elevation_radians = self._plugin_instance.get_sh().sun.pos()
        elevation_degrees = degrees(elevation_radians)
        timestamp = int(time.time())
        last_timestamp, last_sun_sec_last = self.sun_time['last']

        # evaluate sun shine and calc sun sec since last call
        if elevation_degrees <= 3 or solar_radiation < WarningLevels.SUN_MIN:
            sun_sec = 0
        else:
            solar_threshold = int(
                    (0.73 + 0.06 * cos((pi / 180) * 360 * day_of_year / 365))
                    * 1080
                    * pow((sin(pi / 180 * elevation_degrees)), 1.25)
                    * WarningLevels.SUN_COEF
                    )

            if solar_radiation > solar_threshold:
                sun_sec = timestamp - last_timestamp
                self.logger.debug(f"Sonnenschein mit solar_radiation: {solar_radiation} solar_threshold: {solar_threshold} SUN_COEF: {WarningLevels.SUN_COEF}, sun seconds: {sun_sec}")
            else:
                sun_sec = 0
                self.logger.debug(f"kein Sonnenschein mit solar_radiation: {solar_radiation} solar_threshold: {solar_threshold} SUN_COEF: {WarningLevels.SUN_COEF}, sun seconds: {sun_sec}")

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
