#!/usr/bin/env python3
# vim: set encoding=utf-8 tabstop=4 softtabstop=4 shiftwidth=4 expandtab
#########################################################################
#  Copyright 2023-      Michael Wenzel              wenzel_michael@web.de
#########################################################################
#  This file is part of SmartHomeNG.
#  https://www.smarthomeNG.de
#  https://knx-user-forum.de/forum/supportforen/smarthome-py
#
#  Keys and datapoint for Foshk Plugin
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

from dataclasses import dataclass, fields


@dataclass
class MasterKeys:
    # MASTER KEYS
    ABSBARO = 'absbarometer'
    ABSHUM = 'abshum'
    BATTERY_EXTENTION = '_batt'
    CHANNEL = 'ch'
    CO2 = 'co2'
    DAYLWINDMAX = 'winddaymax'
    DEWPT = 'dewpt'
    FROSTPT = 'frostpt'
    GUSTSPEED = 'gustspeed'
    HEATINDEX = 'heatindex'
    HUMID = 'humid'
    LEAF_WETNESS = 'leafwet'
    LEAK = 'leak'
    LIGHT = 'light'
    LIGHTNING_COUNT = 'lightningcount'
    LIGHTNING_DIST = 'lightningdist'
    LIGHTNING_TIME = 'lightningdettime'
    LOWBATT = 'lowbatt'
    PIEZO = 'p_'
    PM10 = 'pm10'
    PM25 = 'pm25'
    PM25_AVG = f'{PM25}_24h_avg'
    RAD_COMP = 'rad_comp'
    RAIN = 'rain'
    RAIN_DAY = f'{RAIN}_day'
    RAIN_EVENT = f'{RAIN}_event'
    RAIN_HOUR = f'{RAIN}_hour'
    RAIN_MONTH = f'{RAIN}_month'
    RAIN_RATE = f'{RAIN}_rate'
    RAIN_TOTALS = f'{RAIN}_totals'
    RAIN_WEEK = f'{RAIN}_week'
    RAIN_YEAR = f'{RAIN}_year'
    RAIN_GAIN = f'{RAIN}_gain'
    RAIN_PRIO = f'{RAIN}_priority'
    RAIN_RESET_YEAR = f'{RAIN}_reset_year'
    RAIN_RESET_DAY = f'{RAIN}_reset_day'
    RAIN_RESET_WEEK = f'{RAIN}_reset_week'
    RELBARO = 'relbarometer'
    SEPARATOR = '_'
    SIGNAL_EXTENTION = '_sig'
    SOILMOISTURE = 'soilmoist'
    SOILTEMP = 'soiltemp'
    SOLAR = 'solarradiation'
    TEMP = 'temp'
    TIME = 'datetime'
    TIMESTAMP = 'ts'
    UV = 'solarradiation'
    UVI = 'uvi'
    WH24 = 'wh24'
    WH25 = 'wh25'
    WH31 = 'wh31'
    WH32 = 'wh32'
    WH40 = 'wh40'
    WH41 = 'wh41'
    WH45 = 'wh45'
    WH51 = 'wh51'
    WH55 = 'wh55'
    WH57 = 'wh57'
    WH65 = 'wh65'
    WIND = 'wind'
    WINDCHILL = f'{WIND}chill'
    WINDDIRECTION = f'{WIND}dir'
    WINDSPEED = f'{WIND}speed'
    WN26 = 'wn26'
    WN30 = 'wn30'
    WN34 = 'wn34'
    WN35 = 'wn35'
    WS68 = 'wh68'
    WS80 = 'ws80'
    WS90 = 'ws90'


@dataclass
class DataPoints:
    # Sub DataPoints used in DataPoints
    SENSOR_CO2_TEMP: tuple = (f'{MasterKeys.TEMP}17', 'Temperatur am CO2 Sensor', '°C')
    SENSOR_CO2_HUM: tuple = (f'{MasterKeys.HUMID}17', 'Luftfeuchtigkeit am CO2 Sensor', '%')
    SENSOR_CO2_PM10: tuple = (MasterKeys.PM10, 'PM10 Wert des CO2 Sensors', '')
    SENSOR_CO2_PM10_24: tuple = (f'{MasterKeys.PM10}_24h_avg', 'durchschnittlicher PM10 Wert der letzten 24h des CO2 Sensors', '')
    SENSOR_CO2_PM255: tuple = (f'{MasterKeys.PM25}5', '', '')
    SENSOR_CO2_PM255_24: tuple = (f'{MasterKeys.PM25}5_24h_avg', '', '')
    SENSOR_CO2_CO2: tuple = (MasterKeys.CO2, '', '')
    SENSOR_CO2_CO2_24: tuple = (f'{MasterKeys.CO2}_24h_avg', '', '')
    PIEZO_RAIN:   tuple = (f'{MasterKeys.PIEZO}{MasterKeys.RAIN_GAIN}', None, None)
    PIEZO_RAIN_0: tuple = (f'{PIEZO_RAIN[0]}0', 'Kalibrierfaktor 0 für Piezo Regensensor', '')
    PIEZO_RAIN_1: tuple = (f'{PIEZO_RAIN[0]}1', 'Kalibrierfaktor 1 für Piezo Regensensor', '')
    PIEZO_RAIN_2: tuple = (f'{PIEZO_RAIN[0]}2', 'Kalibrierfaktor 2 für Piezo Regensensor', '')
    PIEZO_RAIN_3: tuple = (f'{PIEZO_RAIN[0]}3', 'Kalibrierfaktor 3 für Piezo Regensensor', '')
    PIEZO_RAIN_4: tuple = (f'{PIEZO_RAIN[0]}4', 'Kalibrierfaktor 4 für Piezo Regensensor', '')
    PIEZO_RAIN_5: tuple = (f'{PIEZO_RAIN[0]}5', 'Kalibrierfaktor 5 für Piezo Regensensor (reserviert)', '')
    PIEZO_RAIN_6: tuple = (f'{PIEZO_RAIN[0]}6', 'Kalibrierfaktor 6 für Piezo Regensensor (reserviert)', '')
    PIEZO_RAIN_7: tuple = (f'{PIEZO_RAIN[0]}7', 'Kalibrierfaktor 7 für Piezo Regensensor (reserviert)', '')
    PIEZO_RAIN_8: tuple = (f'{PIEZO_RAIN[0]}8', 'Kalibrierfaktor 8 für Piezo Regensensor (reserviert)', '')
    PIEZO_RAIN_9: tuple = (f'{PIEZO_RAIN[0]}9', 'Kalibrierfaktor 9 für Piezo Regensensor (reserviert)', '')
    RAIN_RST_DAY: tuple = (MasterKeys.RAIN_RESET_DAY, 'Uhrzeit des Reset für Rain Day', '')
    RAIN_RST_WEEK: tuple = (MasterKeys.RAIN_RESET_WEEK, 'Tag des Reset für Rain Week', '')
    RAIN_RST_YEAR: tuple = (MasterKeys.RAIN_RESET_YEAR, 'Monat des Reset für Rain Year', '')

    # Data Points
    INTEMP: tuple = (f'in{MasterKeys.TEMP}', 'Indoor Temperature', '°C')
    OUTTEMP: tuple = (f'out{MasterKeys.TEMP}', 'Outdoor Temperature', '°C')                                         # 0x02 // 2 //
    DEWPOINT: tuple = (MasterKeys.DEWPT, 'Dew Point', '°C')                                                         # 0x03 // 2 //
    WINDCHILL: tuple = (MasterKeys.WINDCHILL, 'Wind Chill', '°C')                                                   # 0x04 // 2 //
    HEATINDEX: tuple = (MasterKeys.HEATINDEX, 'Heat Index', '')                                                     # 0x05 // 2 //
    INHUMI: tuple = (f'in{MasterKeys.HUMID}', 'Indoor Humidity', '%')                                               # 0x06 // 1 //
    OUTHUMI: tuple = (f'out{MasterKeys.HUMID}', 'Outdoor Humidity', '%')                                            # 0x07 // 1 //
    ABSBARO: tuple = (MasterKeys.ABSBARO, 'Absolutely Barometric', 'hpa')                                           # 0x08 // 2 //
    RELBARO: tuple = (MasterKeys.RELBARO, 'Relative Barometric', 'hpa')                                             # 0x09 // 2 //
    WINDDIRECTION: tuple = (MasterKeys.WINDDIRECTION, 'Wind Direction', '360°')                                     # 0x0A // 2 //
    WINDSPEED: tuple = (MasterKeys.WINDSPEED, 'Wind Speed', 'm/s')                                                  # 0x0B // 2 //
    GUSTSPEED: tuple = (MasterKeys.GUSTSPEED, 'Gust Speed', 'm/s')                                                  # 0x0C // 2 //
    RAINEVENT: tuple = (MasterKeys.RAIN_EVENT, 'Rain Event', 'mm')                                                  # 0x0D // 2 //
    RAINRATE: tuple = (MasterKeys.RAIN_RATE, 'Rain Rate', 'mm')                                                     # 0x0E // 2 //
    RAINHOUR: tuple = (MasterKeys.RAIN_HOUR, 'Rain hour', 'mm')                                                     # 0x0F // 2 //
    RAINDAY: tuple = (MasterKeys.RAIN_DAY, 'Rain Day', 'mm')                                                        # 0x10 // 2 //
    RAINWEEK: tuple = (MasterKeys.RAIN_WEEK, 'Rain Week', 'mm')                                                     # 0x11 // 2 //
    RAINMONTH: tuple = (MasterKeys.RAIN_MONTH, 'Rain Month', 'mm')                                                  # 0x12 // 4 //
    RAINYEAR: tuple = (MasterKeys.RAIN_YEAR, 'Rain Year', 'mm')                                                     # 0x13 // 4 //
    RAINTOTALS: tuple = (MasterKeys.RAIN_TOTALS, 'Rain Totals', 'mm')                                               # 0x14 // 4 //
    LIGHT: tuple = (MasterKeys.LIGHT, 'Light', 'lux')                                                               # 0x15 // 4 //
    UV: tuple = (MasterKeys.UV, 'UV', 'uW/m2')                                                                      # 0x16 // 2 //
    UVI: tuple = (MasterKeys.UVI, 'UVI', '0-15')                                                                    # 0x17 // 1 //
    TIME: tuple = (MasterKeys.TIME, 'Datetime', None)                                                               # 0x18 // 6 //
    DAYLWINDMAX: tuple = (MasterKeys.DAYLWINDMAX, '', '')                                                           # 0X19 // 2 //
    TEMP1: tuple = (f'{MasterKeys.TEMP}01', 'Temperature', '°C')                                                    # 0x1A // 2 //
    TEMP2: tuple = (f'{MasterKeys.TEMP}02', 'Temperature', '°C')                                                    # 0x1B // 2 //
    TEMP3: tuple = (f'{MasterKeys.TEMP}03', 'Temperature', '°C')                                                    # 0x1C // 2 //
    TEMP4: tuple = (f'{MasterKeys.TEMP}04', 'Temperature', '°C')                                                    # 0x1D // 2 //
    TEMP5: tuple = (f'{MasterKeys.TEMP}05', 'Temperature', '°C')                                                    # 0x1E // 2 //
    TEMP6: tuple = (f'{MasterKeys.TEMP}06', 'Temperature', '°C')                                                    # 0x1F // 2 //
    TEMP7: tuple = (f'{MasterKeys.TEMP}07', 'Temperature', '°C')                                                    # 0x20 // 2 //
    TEMP8: tuple = (f'{MasterKeys.TEMP}08', 'Temperature', '°C')                                                    # 0x21 // 2 //
    TF_USR1: tuple = (f'{MasterKeys.TEMP}09', 'Temperature', '°C')                                                  # 0x63 // 3 //
    TF_USR2: tuple = (f'{MasterKeys.TEMP}10', 'Temperature', '°C')                                                  # 0x64 // 3 //
    TF_USR3: tuple = (f'{MasterKeys.TEMP}11', 'Temperature', '°C')                                                  # 0x65 // 3 //
    TF_USR4: tuple = (f'{MasterKeys.TEMP}12', 'Temperature', '°C')                                                  # 0x66 // 3 //
    TF_USR5: tuple = (f'{MasterKeys.TEMP}13', 'Temperature', '°C')                                                  # 0x67 // 3 //
    TF_USR6: tuple = (f'{MasterKeys.TEMP}14', 'Temperature', '°C')                                                  # 0x68 // 3 //
    TF_USR7: tuple = (f'{MasterKeys.TEMP}15', 'Temperature', '°C')                                                  # 0x69 // 3 //
    TF_USR8: tuple = (f'{MasterKeys.TEMP}16', 'Temperature', '°C')                                                  # 0x6A // 3 //
    HUMI1: tuple = (f'{MasterKeys.HUMID}1', 'Humidity', '%')                                                        # 0x22 // 1 //
    HUMI2: tuple = (f'{MasterKeys.HUMID}2', 'Humidity', '%')                                                        # 0x23 // 1 //
    HUMI3: tuple = (f'{MasterKeys.HUMID}3', 'Humidity', '%')                                                        # 0x24 // 1 //
    HUMI4: tuple = (f'{MasterKeys.HUMID}4', 'Humidity', '%')                                                        # 0x25 // 1 //
    HUMI5: tuple = (f'{MasterKeys.HUMID}5', 'Humidity', '%')                                                        # 0x26 // 1 //
    HUMI6: tuple = (f'{MasterKeys.HUMID}6', 'Humidity', '%')                                                        # 0x27 // 1 //
    HUMI7: tuple = (f'{MasterKeys.HUMID}7', 'Humidity', '%')                                                        # 0x28 // 1 //
    HUMI8: tuple = (f'{MasterKeys.HUMID}8', 'Humidity', '%')                                                        # 0x29 // 1 //
    SOILTEMP1: tuple = (f'{MasterKeys.SOILTEMP}01', 'Soil Temperature', '°C')                                       # 0x2B // 2 //
    SOILTEMP2: tuple = (f'{MasterKeys.SOILTEMP}02', 'Soil Temperature', '°C')                                       # 0x2D // 2 //
    SOILTEMP3: tuple = (f'{MasterKeys.SOILTEMP}03', 'Soil Temperature', '°C')                                       # 0x2F // 2 //
    SOILTEMP4: tuple = (f'{MasterKeys.SOILTEMP}04', 'Soil Temperature', '°C')                                       # 0x31 // 2 //
    SOILTEMP5: tuple = (f'{MasterKeys.SOILTEMP}05', 'Soil Temperature', '°C')                                       # 0x33 // 2 //
    SOILTEMP6: tuple = (f'{MasterKeys.SOILTEMP}06', 'Soil Temperature', '°C')                                       # 0x35 // 2 //
    SOILTEMP7: tuple = (f'{MasterKeys.SOILTEMP}07', 'Soil Temperature', '°C')                                       # 0x37 // 2 //
    SOILTEMP8: tuple = (f'{MasterKeys.SOILTEMP}08', 'Soil Temperature', '°C')                                       # 0x39 // 2 //
    SOILTEMP9: tuple = (f'{MasterKeys.SOILTEMP}09', 'Soil Temperature', '°C')                                       # 0x3B // 2 //
    SOILTEMP10: tuple = (f'{MasterKeys.SOILTEMP}10', 'Soil Temperature', '°C')                                      # 0x3D // 2 //
    SOILTEMP11: tuple = (f'{MasterKeys.SOILTEMP}11', 'Soil Temperature', '°C')                                      # 0x3F // 2 //
    SOILTEMP12: tuple = (f'{MasterKeys.SOILTEMP}12', 'Soil Temperature', '°C')                                      # 0x41 // 2 //
    SOILTEMP13: tuple = (f'{MasterKeys.SOILTEMP}13', 'Soil Temperature', '°C')                                      # 0x43 // 2 //
    SOILTEMP14: tuple = (f'{MasterKeys.SOILTEMP}14', 'Soil Temperature', '°C')                                      # 0x45 // 2 //
    SOILTEMP15: tuple = (f'{MasterKeys.SOILTEMP}15', 'Soil Temperature', '°C')                                      # 0x47 // 2 //
    SOILTEMP16: tuple = (f'{MasterKeys.SOILTEMP}16', 'Soil Temperature', '°C')                                      # 0x49 // 2 //
    SOILMOISTURE1: tuple = (f'{MasterKeys.SOILMOISTURE}01', 'Soil Moisture', '%')                                   # 0x2C // 1 //
    SOILMOISTURE2: tuple = (f'{MasterKeys.SOILMOISTURE}02', 'Soil Moisture', '%')                                   # 0x2E // 1 //
    SOILMOISTURE3: tuple = (f'{MasterKeys.SOILMOISTURE}03', 'Soil Moisture', '%')                                   # 0x30 // 1 //
    SOILMOISTURE4: tuple = (f'{MasterKeys.SOILMOISTURE}04', 'Soil Moisture', '%')                                   # 0x32 // 1 //
    SOILMOISTURE5: tuple = (f'{MasterKeys.SOILMOISTURE}05', 'Soil Moisture', '%')                                   # 0x34 // 1 //
    SOILMOISTURE6: tuple = (f'{MasterKeys.SOILMOISTURE}06', 'Soil Moisture', '%')                                   # 0x36 // 1 //
    SOILMOISTURE7: tuple = (f'{MasterKeys.SOILMOISTURE}07', 'Soil Moisture', '%')                                   # 0x38 // 1 //
    SOILMOISTURE8: tuple = (f'{MasterKeys.SOILMOISTURE}08', 'Soil Moisture', '%')                                   # 0x3A // 1 //
    SOILMOISTURE9: tuple = (f'{MasterKeys.SOILMOISTURE}09', 'Soil Moisture', '%')                                   # 0x3C // 1 //
    SOILMOISTURE10: tuple = (f'{MasterKeys.SOILMOISTURE}10', 'Soil Moisture', '%')                                  # 0x3E // 1 //
    SOILMOISTURE11: tuple = (f'{MasterKeys.SOILMOISTURE}11', 'Soil Moisture', '%')                                  # 0x40 // 1 //
    SOILMOISTURE12: tuple = (f'{MasterKeys.SOILMOISTURE}12', 'Soil Moisture', '%')                                  # 0x42 // 1 //
    SOILMOISTURE13: tuple = (f'{MasterKeys.SOILMOISTURE}13', 'Soil Moisture', '%')                                  # 0x44 // 1 //
    SOILMOISTURE14: tuple = (f'{MasterKeys.SOILMOISTURE}14', 'Soil Moisture', '%')                                  # 0x46 // 1 //
    SOILMOISTURE15: tuple = (f'{MasterKeys.SOILMOISTURE}15', 'Soil Moisture', '%')                                  # 0x48 // 1 //
    SOILMOISTURE16: tuple = (f'{MasterKeys.SOILMOISTURE}16', 'Soil Moisture', '%')                                  # 0x4A // 1 //
    LOWBATT: tuple = (MasterKeys.LOWBATT, 'All sensor lowbatt', '16 char')                                          # 0x4C // 16 //
    PM251: tuple = (f'{MasterKeys.PM25}1', 'PM2.5 Air Quality', 'μg/m3')                                            # 0x2A // 2 //
    PM252: tuple = (f'{MasterKeys.PM25}2', 'PM2.5 Air Quality', 'μg/m3')                                            # 0x51 // 2 //
    PM253: tuple = (f'{MasterKeys.PM25}3', 'PM2.5 Air Quality', 'μg/m3')                                            # 0x52 // 2 //
    PM254: tuple = (f'{MasterKeys.PM25}4', 'PM2.5 Air Quality', 'μg/m3')                                            # 0x53 // 2 //
    PM25_24H_AVG1: tuple = (f'{MasterKeys.PM25_AVG}1', 'PM2.5 Air Quality 24h average', 'μg/m3')                    # 0x4D // 2 //
    PM25_24H_AVG2: tuple = (f'{MasterKeys.PM25_AVG}2', 'PM2.5 Air Quality 24h average', 'μg/m3')                    # 0x4E // 2 //
    PM25_24H_AVG3: tuple = (f'{MasterKeys.PM25_AVG}3', 'PM2.5 Air Quality 24h average', 'μg/m3')                    # 0x4F // 2 //
    PM25_24H_AVG4: tuple = (f'{MasterKeys.PM25_AVG}4', 'PM2.5 Air Quality 24h average', 'μg/m3')                    # 0x50 // 2 //
    LEAK1: tuple = (f'{MasterKeys.LEAK}1', 'Leakage', 'True/False')                                                 # 0x58 // 1 //
    LEAK2: tuple = (f'{MasterKeys.LEAK}2', 'Leakage', 'True/False')                                                 # 0x59 // 1 //
    LEAK3: tuple = (f'{MasterKeys.LEAK}3', 'Leakage', 'True/False')                                                 # 0x5A // 1 //
    LEAK4: tuple = (f'{MasterKeys.LEAK}4', 'Leakage', 'True/False')                                                 # 0x5B // 1 //
    LIGHTNING_DIST: tuple = (MasterKeys.LIGHTNING_DIST, 'lightning distance', '1~40KM')                             # 0x60 // 1 //
    LIGHTNING_TIME: tuple = (MasterKeys.LIGHTNING_TIME, 'lightning happened time', None)                            # 0x61 // 4 //
    LIGHTNING_COUNT: tuple = (MasterKeys.LIGHTNING_COUNT, 'lightning counter for the day', None)                    # 0x62 // 4 //
    SENSOR_CO2: tuple = ((SENSOR_CO2_TEMP[0],                                                                       # see first entries of dataclass
                          SENSOR_CO2_HUM[0],                                                                        # see first entries of dataclass
                          SENSOR_CO2_PM10[0],                                                                       # see first entries of dataclass
                          SENSOR_CO2_PM10_24[0],                                                                    # see first entries of dataclass
                          SENSOR_CO2_PM255[0],                                                                      # see first entries of dataclass
                          SENSOR_CO2_PM255_24[0],                                                                   # see first entries of dataclass
                          SENSOR_CO2_CO2[0],                                                                        # see first entries of dataclass
                          SENSOR_CO2_CO2_24[0]), None, None)                                                        # 0x70 // 16 // CO2
    PM25_AQI: tuple = (None, None, None)                                                                            # 0x71 //   // only for amb
    LEAF_WETNESS1: tuple = (f'{MasterKeys.LEAF_WETNESS}1', 'Leaf Wetness', '%')                                     # 0x72 // 1 //
    LEAF_WETNESS2: tuple = (f'{MasterKeys.LEAF_WETNESS}2', 'Leaf Wetness', '%')                                     # 0x73 // 1 //
    LEAF_WETNESS3: tuple = (f'{MasterKeys.LEAF_WETNESS}3', 'Leaf Wetness', '%')                                     # 0x74 // 1 //
    LEAF_WETNESS4: tuple = (f'{MasterKeys.LEAF_WETNESS}4', 'Leaf Wetness', '%')                                     # 0x75 // 1 //
    LEAF_WETNESS5: tuple = (f'{MasterKeys.LEAF_WETNESS}5', 'Leaf Wetness', '%')                                     # 0x76 // 1 //
    LEAF_WETNESS6: tuple = (f'{MasterKeys.LEAF_WETNESS}6', 'Leaf Wetness', '%')                                     # 0x77 // 1 //
    LEAF_WETNESS7: tuple = (f'{MasterKeys.LEAF_WETNESS}7', 'Leaf Wetness', '%')                                     # 0x78 // 1 //
    LEAF_WETNESS8: tuple = (f'{MasterKeys.LEAF_WETNESS}8', 'Leaf Wetness', '%')                                     # 0x79 // 1 //
    RAIN_PRIO: tuple = (MasterKeys.RAIN_PRIO, 'rain priority (classical or piezo)', '1: classical, 2: piezo')       # 0x7A // 1 //
    RAD_COMP: tuple = (MasterKeys.RAD_COMP, 'radiation compensation', 'on/off')                                     # 0x7B // 1 //
    PIEZO_RAINRATE: tuple = (f'{MasterKeys.PIEZO}{MasterKeys.RAIN_RATE}', 'Rain Rate', 'mm')                        # 0x80 // 2 //
    PIEZO_RAINEVENT: tuple = (f'{MasterKeys.PIEZO}{MasterKeys.RAIN_EVENT}', 'Rain Event', 'mm')                     # 0x81 // 2 //
    PIEZO_RAINHOUR: tuple = (f'{MasterKeys.PIEZO}{MasterKeys.RAIN_HOUR}', 'Rain Hour', 'mm')                        # 0x82 // 2 //
    PIEZO_RAINDAY: tuple = (f'{MasterKeys.PIEZO}{MasterKeys.RAIN_DAY}', 'Rain Day', 'mm')                           # 0x83 // 4 //
    PIEZO_RAINWEEK: tuple = (f'{MasterKeys.PIEZO}{MasterKeys.RAIN_WEEK}', 'Rain Week', 'mm')                        # 0x84 // 4 //
    PIEZO_RAINMONTH: tuple = (f'{MasterKeys.PIEZO}{MasterKeys.RAIN_MONTH}', 'Rain Month', 'mm')                     # 0x85 // 4 //
    PIEZO_RAINYEAR: tuple = (f'{MasterKeys.PIEZO}{MasterKeys.RAIN_YEAR}', 'Rain Year', 'mm')                        # 0x86 // 4 //
    PIEZO_RAINGAIN: tuple = ((PIEZO_RAIN_0[0],                                                                      # see first entries of dataclass
                              PIEZO_RAIN_1[0],                                                                      # see first entries of dataclass
                              PIEZO_RAIN_2[0],                                                                      # see first entries of dataclass
                              PIEZO_RAIN_3[0],                                                                      # see first entries of dataclass
                              PIEZO_RAIN_4[0],                                                                      # see first entries of dataclass
                              PIEZO_RAIN_5[0],                                                                      # see first entries of dataclass
                              PIEZO_RAIN_6[0],                                                                      # see first entries of dataclass
                              PIEZO_RAIN_7[0],                                                                      # see first entries of dataclass                    
                              PIEZO_RAIN_8[0],                                                                      # see first entries of dataclass
                              PIEZO_RAIN_9[0]), None, None)                                                         # 0x87 // 2*10 //
    RAIN_RST_TIME: tuple = ((RAIN_RST_DAY[0],                                                                       # see first entries of dataclass
                             RAIN_RST_WEEK[0],                                                                      # see first entries of dataclass
                             RAIN_RST_YEAR[0]), None, None)                                                         # 0x88 // 3 //
    CLIENT_IP: tuple = ('client_ip', 'Client IP', None)
    PASSKEY: tuple = (None, 'Passkey', None)
    FIRMWARE: tuple = ('firmware', 'Firmware Version', None)
    FREQ: tuple = ('frequency', 'Frequency of Transmitter', None)
    MODEL: tuple = ('model', 'Gateway Model', None)
    RUNTIME: tuple = ('runtime', 'Runtime', 's')
    INTERVAL: tuple = ('interval', 'Data Inteval', 's')
    INDEWPPOINT: tuple = (f'in{MasterKeys.DEWPT}', 'Dew Point Indoor', '°C')
    INABSHUM: tuple = (f'in{MasterKeys.ABSHUM}', 'Absolute Humidity Indoor', '')
    OUTDEWPT: tuple = (f'out{MasterKeys.DEWPT}', 'Dew Point Outdoor', '°C')
    OUTFROSTPT: tuple = (f'out{MasterKeys.FROSTPT}', 'Frost Point Outdoor', '°C')
    OUTABSHUM: tuple = (f'out{MasterKeys.ABSHUM}', 'Absolute Humidity Outdoor', '')
    RESET: tuple = ('reset', 'Reset', None)
    REBOOT: tuple = ('reboot', 'Reboot', None)
    FEELS_LIKE: tuple = ('feelslike', 'Feels Like Temperature', '°C')
    SENSOR_WARNING: tuple = ('sensor_warning', 'Warning of any Sensor', 'True/False')
    BATTERY_WARNING: tuple = ('battery_warning', 'Warning of any Battery', 'True/False')
    STORM_WARNING: tuple = ('storm_warning', 'Storm Warning', 'True/False')
    THUNDERSTORM_WARNING: tuple = ('thunderstorm_warning', 'Thunderstorm Warning', 'True/False')
    WEATHERSTATION_WARNING: tuple = ('weatherstation_warning', 'Weatherstation Warning', 'True/False')
    FIRMWARE_UPDATE_AVAILABLE: tuple = ('firmware_update_available', 'Firmware Update available', 'True/False')
    FIRMWARE_UPDATE_TEXT: tuple = ('firmware_update_text', 'Firmware Update Description', None)
    CLOUD_CEILING: tuple = ('cloud_ceiling', 'Cloud Ceiling', 'm')
    WINDDIR_TEXT: tuple = ('winddir_txt', 'Wind Direction Desctiption', None)
    WINDSPEED_BFT: tuple = ('windspeed_bft', 'Wind Speed in Beautford', None)
    WINDSPEED_BFT_TEXT: tuple = ('windspeed_bft_txt', 'Wind Speed in Beautford Text', None)
    WEATHER_TEXT: tuple = ('weather_txt', 'Weather Description', None)
    WINDSPEED_AVG10M: tuple = ('windspeed_avg10m', 'Average Windspeed 10min', 'm/s')
    WINDDIR_AVG10M: tuple = ('winddir_avg10m', 'Average Wind Direction 10min', '360°')
    GUSTSPEED_AVG10M: tuple = ('gustspeed_avg10m', 'Average Gust Speed 10min', 'm/s')
    PIEZO_RAIN: tuple = (f'{MasterKeys.PIEZO}{MasterKeys.RAIN}', 'Rain', 'mm')
    RAIN: tuple = (MasterKeys.RAIN, 'Rain', 'mm')


@dataclass
class SensorKeys:
    WH65: tuple = (MasterKeys.WH65, MasterKeys.WH65.upper(), 'Außensensor WH65')
    WS68: tuple = (MasterKeys.WS68, MasterKeys.WS68.upper(), 'Wetterstation WS68')
    WS80: tuple = (MasterKeys.WS80, MasterKeys.WS80.upper(), 'Wetterstation WS80')
    WH40: tuple = (MasterKeys.WH40, MasterKeys.WH40.upper(), 'Regensensor')
    WH25: tuple = (MasterKeys.WH25, MasterKeys.WH25.upper(), 'Temperatur-, Feuchtigkeits- und Drucksensor')
    WN26: tuple = (MasterKeys.WN26, MasterKeys.WN26.upper(), 'Pool Thermometer')
    WH32: tuple = (MasterKeys.WH32, MasterKeys.WH32.upper(), 'Temperatur- und Feuchtigkeitssensor WH32')
    WH24: tuple = (MasterKeys.WH24, MasterKeys.WH24.upper(), 'Temperatur- und Feuchtigkeitssensor Außen WH24')
    WH57: tuple = (MasterKeys.WH57, MasterKeys.WH57.upper(), 'Blitzsensor WH57')
    WH45: tuple = (MasterKeys.WH45, MasterKeys.WH45.upper(), 'Partikel- und CO2 Sensor WH45')
    WS90: tuple = (MasterKeys.WS90, MasterKeys.WS90.upper(), 'Wetterstation 7in1 WS90')
    WH31: tuple = (f'{MasterKeys.WH31}{MasterKeys.SEPARATOR}{MasterKeys.CHANNEL}', f'{MasterKeys.WH31.upper()} {MasterKeys.CHANNEL}', None)
    WH31_1: tuple = (f'{WH31[0]}1', f'{WH31[1]}1', 'Thermo-Hygrometer Kanal 1')
    WH31_2: tuple = (f'{WH31[0]}2', f'{WH31[1]}2', 'Thermo-Hygrometer Kanal 2')
    WH31_3: tuple = (f'{WH31[0]}3', f'{WH31[1]}3', 'Thermo-Hygrometer Kanal 3')
    WH31_4: tuple = (f'{WH31[0]}4', f'{WH31[1]}4', 'Thermo-Hygrometer Kanal 4')
    WH31_5: tuple = (f'{WH31[0]}5', f'{WH31[1]}5', 'Thermo-Hygrometer Kanal 5')
    WH31_6: tuple = (f'{WH31[0]}6', f'{WH31[1]}6', 'Thermo-Hygrometer Kanal 6')
    WH31_7: tuple = (f'{WH31[0]}7', f'{WH31[1]}7', 'Thermo-Hygrometer Kanal 7')
    WH31_8: tuple = (f'{WH31[0]}8', f'{WH31[1]}8', 'Thermo-Hygrometer Kanal 8')
    WH51: tuple = (f'{MasterKeys.WH51}{MasterKeys.SEPARATOR}{MasterKeys.CHANNEL}', f'{MasterKeys.WH51.upper()} {MasterKeys.CHANNEL}', None)
    WH51_1: tuple = (f'{WH51[0]}1', f'{WH51[1]}1', 'Bodenfeuchtesensor Kanal 1')
    WH51_2: tuple = (f'{WH51[0]}2', f'{WH51[1]}2', 'Bodenfeuchtesensor Kanal 2')
    WH51_3: tuple = (f'{WH51[0]}3', f'{WH51[1]}3', 'Bodenfeuchtesensor Kanal 3')
    WH51_4: tuple = (f'{WH51[0]}4', f'{WH51[1]}4', 'Bodenfeuchtesensor Kanal 4')
    WH51_5: tuple = (f'{WH51[0]}5', f'{WH51[1]}5', 'Bodenfeuchtesensor Kanal 5')
    WH51_6: tuple = (f'{WH51[0]}6', f'{WH51[1]}6', 'Bodenfeuchtesensor Kanal 6')
    WH51_7: tuple = (f'{WH51[0]}7', f'{WH51[1]}7', 'Bodenfeuchtesensor Kanal 7')
    WH51_8: tuple = (f'{WH51[0]}8', f'{WH51[1]}8', 'Bodenfeuchtesensor Kanal 8')
    WH41: tuple = (f'{MasterKeys.WH41}{MasterKeys.SEPARATOR}{MasterKeys.CHANNEL}', f'{MasterKeys.WH41.upper()} {MasterKeys.CHANNEL}', None)
    WH41_1: tuple = (f'{WH41[0]}1', f'{WH41[1]}1', 'Partikelsensor PM2.5 WH41 Kanal 1')
    WH41_2: tuple = (f'{WH41[0]}2', f'{WH41[1]}2', 'Partikelsensor PM2.5 WH41 Kanal 2')
    WH41_3: tuple = (f'{WH41[0]}3', f'{WH41[1]}3', 'Partikelsensor PM2.5 WH41 Kanal 3')
    WH41_4: tuple = (f'{WH41[0]}4', f'{WH41[1]}4', 'Partikelsensor PM2.5 WH41 Kanal 4')
    WH55: tuple = (f'{MasterKeys.WH55}{MasterKeys.SEPARATOR}{MasterKeys.CHANNEL}', f'{MasterKeys.WH55.upper()} {MasterKeys.CHANNEL}', None)
    WH55_1: tuple = (f'{WH55[0]}1', f'{WH55[1]}1', 'Leckagesensor Kanal 1')
    WH55_2: tuple = (f'{WH55[0]}2', f'{WH55[1]}2', 'Leckagesensor Kanal 2')
    WH55_3: tuple = (f'{WH55[0]}3', f'{WH55[1]}3', 'Leckagesensor Kanal 3')
    WH55_4: tuple = (f'{WH55[0]}4', f'{WH55[1]}4', 'Leckagesensor Kanal 4')
    WN34: tuple = (f'{MasterKeys.WN34}{MasterKeys.SEPARATOR}{MasterKeys.CHANNEL}', f'{MasterKeys.WN34.upper()} {MasterKeys.CHANNEL}', None)
    WN34_1: tuple = (f'{WN34[0]}1', f'{WN34[1]}1', 'Thermometer mit wasserdichtem Sensor WN34 Kanal 1')
    WN34_2: tuple = (f'{WN34[0]}2', f'{WN34[1]}2', 'Thermometer mit wasserdichtem Sensor WN34 Kanal 2')
    WN34_3: tuple = (f'{WN34[0]}3', f'{WN34[1]}3', 'Thermometer mit wasserdichtem Sensor WN34 Kanal 3')
    WN34_4: tuple = (f'{WN34[0]}4', f'{WN34[1]}4', 'Thermometer mit wasserdichtem Sensor WN34 Kanal 4')
    WN34_5: tuple = (f'{WN34[0]}5', f'{WN34[1]}5', 'Thermometer mit wasserdichtem Sensor WN34 Kanal 5')
    WN34_6: tuple = (f'{WN34[0]}6', f'{WN34[1]}6', 'Thermometer mit wasserdichtem Sensor WN34 Kanal 6')
    WN34_7: tuple = (f'{WN34[0]}7', f'{WN34[1]}7', 'Thermometer mit wasserdichtem Sensor WN34 Kanal 7')
    WN34_8: tuple = (f'{WN34[0]}8', f'{WN34[1]}8', 'Thermometer mit wasserdichtem Sensor WN34 Kanal 8')
    WN35: tuple = (f'{MasterKeys.WN35}{MasterKeys.SEPARATOR}{MasterKeys.CHANNEL}', f'{MasterKeys.WN35.upper()} {MasterKeys.CHANNEL}', None)
    WN35_1: tuple = (f'{WN35[0]}1', f'{WN35[1]}1', 'Feuchtigkeitssensor für Pflanzen/Blätter WN35 Kanal 1')
    WN35_2: tuple = (f'{WN35[0]}2', f'{WN35[1]}2', 'Feuchtigkeitssensor für Pflanzen/Blätter WN35 Kanal 2')
    WN35_3: tuple = (f'{WN35[0]}3', f'{WN35[1]}3', 'Feuchtigkeitssensor für Pflanzen/Blätter WN35 Kanal 3')
    WN35_4: tuple = (f'{WN35[0]}4', f'{WN35[1]}4', 'Feuchtigkeitssensor für Pflanzen/Blätter WN35 Kanal 4')
    WN35_5: tuple = (f'{WN35[0]}5', f'{WN35[1]}5', 'Feuchtigkeitssensor für Pflanzen/Blätter WN35 Kanal 5')
    WN35_6: tuple = (f'{WN35[0]}6', f'{WN35[1]}6', 'Feuchtigkeitssensor für Pflanzen/Blätter WN35 Kanal 6')
    WN35_7: tuple = (f'{WN35[0]}7', f'{WN35[1]}7', 'Feuchtigkeitssensor für Pflanzen/Blätter WN35 Kanal 7')
    WN35_8: tuple = (f'{WN35[0]}8', f'{WN35[1]}8', 'Feuchtigkeitssensor für Pflanzen/Blätter WN35 Kanal 8')
    WN30: tuple = (f'{MasterKeys.WN30}{MasterKeys.SEPARATOR}{MasterKeys.CHANNEL}', f'{MasterKeys.WN30.upper()} {MasterKeys.CHANNEL}', None)
    WN30_1: tuple = (f'{WN30[0]}1', f'{WN30[1]}1', 'Thermometer mit wasserdichtem Sensor WN30 Kanal 1')
    WN30_2: tuple = (f'{WN30[0]}2', f'{WN30[1]}2', 'Thermometer mit wasserdichtem Sensor WN30 Kanal 2')
    WN30_3: tuple = (f'{WN30[0]}3', f'{WN30[1]}3', 'Thermometer mit wasserdichtem Sensor WN30 Kanal 3')
    WN30_4: tuple = (f'{WN30[0]}4', f'{WN30[1]}4', 'Thermometer mit wasserdichtem Sensor WN30 Kanal 4')
    WN30_5: tuple = (f'{WN30[0]}5', f'{WN30[1]}5', 'Thermometer mit wasserdichtem Sensor WN30 Kanal 5')
    WN30_6: tuple = (f'{WN30[0]}6', f'{WN30[1]}6', 'Thermometer mit wasserdichtem Sensor WN30 Kanal 6')
    WN30_7: tuple = (f'{WN30[0]}7', f'{WN30[1]}7', 'Thermometer mit wasserdichtem Sensor WN30 Kanal 7')
    WN30_8: tuple = (f'{WN30[0]}8', f'{WN30[1]}8', 'Thermometer mit wasserdichtem Sensor WN30 Kanal 8')


META_ATTRIBUTES = [DataPoints.MODEL,
                   DataPoints.FREQ,
                   DataPoints.SENSOR_WARNING,
                   DataPoints.BATTERY_WARNING,
                   DataPoints.STORM_WARNING,
                   DataPoints.THUNDERSTORM_WARNING,
                   DataPoints.WEATHERSTATION_WARNING,
                   DataPoints.FIRMWARE,
                   DataPoints.FIRMWARE_UPDATE_AVAILABLE,
                   DataPoints.FIRMWARE_UPDATE_TEXT,
                   ]


POST_ATTRIBUTES = [DataPoints.RUNTIME]


FW_UPDATE_URL = 'http://download.ecowitt.net/down/filewave?v=FirwaveReadme.txt'.replace("\"", "")


if __name__ == '__main__':

    import ruamel.yaml

    FILENAME_PLUGIN = 'plugin.yaml'
    attribute = 'foshk_attribute'
    data_points = DataPoints()
    sensor_keys = SensorKeys()
    attributs_dict = dict()

    # Iterate over the attributes of the dataclass DataPoints and create dict
    for field in fields(data_points):
        field_name = field.name
        field_value = getattr(data_points, field_name)
        fosk_attr = field_value[0]
        fosk_attr_desc = field_value[1]
        fosk_attr_unit = field_value[2]

        # Wenn Beschreibung, dann zum Dict hinzu
        if fosk_attr is not None and fosk_attr_desc is not None:
            attributs_dict.update({fosk_attr: (fosk_attr_desc, fosk_attr_unit)})

    # Iterate over the attributes of the dataclass SensorKeys and update dict
    for field in fields(sensor_keys):
        field_name = field.name
        field_value = getattr(sensor_keys, field_name)
        sensor_short = field_value[0]
        sensor_desc = field_value[2]

        # Wenn Beschreibung, dann zum Dict hinzu
        if sensor_short is not None and sensor_desc is not None:
            attributs_dict.update({f"{sensor_short}{MasterKeys.BATTERY_EXTENTION}": (f"Batteriestatus für {sensor_desc}",)})
            attributs_dict.update({f"{sensor_short}{MasterKeys.SIGNAL_EXTENTION}": (f"Signalstärke für {sensor_desc}",)})

    # sort dict by key
    attributs_dict_sorted = dict(sorted(attributs_dict.items()))

    # interate over dict and create strings
    valid_list_str =         """        # NOTE: valid_list is automatically created by using datapoints.py"""
    valid_list_desc_str =    """        # NOTE: valid_list_description is automatically created by using datapoints.py"""

    for key in attributs_dict_sorted:
        valid_list_str = f"""{valid_list_str}\n\
              - {key!r:<40}"""

        valid_list_desc_str = f"""{valid_list_desc_str}\n\
              - {attributs_dict_sorted[key][0]:<}"""

    valid_list_desc_str = f"""{valid_list_desc_str}\n\r"""

    # open plugin.yaml and update
    yaml = ruamel.yaml.YAML()
    yaml.indent(mapping=4, sequence=4, offset=4)
    yaml.width = 200
    yaml.allow_unicode = True
    yaml.preserve_quotes = False

    with open(FILENAME_PLUGIN, 'r', encoding="utf-8") as f:
        data = yaml.load(f)

    if data.get('item_attributes', {}).get(attribute):
        data['item_attributes'][attribute]['valid_list'] = yaml.load(valid_list_str)
        data['item_attributes'][attribute]['valid_list_description'] = yaml.load(valid_list_desc_str)

        with open(FILENAME_PLUGIN, 'w', encoding="utf-8") as f:
            yaml.dump(data, f)
        print(f"Successfully updated Attribute '{attribute}' in {FILENAME_PLUGIN}!")
    else:
        print(f"Attribute '{attribute}' not defined in {FILENAME_PLUGIN}!")
