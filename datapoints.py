#!/usr/bin/env python3
# vim: set encoding=utf-8 tabstop=4 softtabstop=4 shiftwidth=4 expandtab
#########################################################################
#  Copyright 2022-      Michael Wenzel              wenzel_michael@web.de
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

# MASTER KEYS
KEY_TEMP = 'temp'
KEY_HUMID = 'humid'
KEY_DEWPT = 'dewpt'
KEY_FROSTPT = 'frostpt'
KEY_SOILTEMP = 'soiltemp'
KEY_SOILMOISTURE = 'soilmoist'
KEY_ABSHUM = 'abshum'
KEY_PM25 = 'pm25'
KEY_PM25_AVG = f'{KEY_PM25}_24h_avg'
KEY_LEAK = 'leak'
KEY_LEAF_WETNESS = 'leafwet'
KEY_CO2 = 'co2'
KEY_PM10 = 'pm10'
KEY_SEPARATOR = ''

# SUB KEYS
KEY_SENSOR_CO2_TEMP = f'{KEY_TEMP}17'
KEY_SENSOR_CO2_HUM = f'{KEY_HUMID}17'
KEY_SENSOR_CO2_PM10 = KEY_PM10
KEY_SENSOR_CO2_PM10_24 = f'{KEY_PM10}_24h_avg'
KEY_SENSOR_CO2_PM255 = f'{KEY_PM25}5'
KEY_SENSOR_CO2_PM255_24 = f'{KEY_PM25}5_24h_avg'
KEY_SENSOR_CO2_CO2 = KEY_CO2
KEY_SENSOR_CO2_CO2_24 = f'{KEY_CO2}_24h_avg'

# API KEYS
KEY_INTEMP = f'in{KEY_TEMP}'                            # 0x01 // 2 // Indoor Temperature (°C)
KEY_OUTTEMP = f'out{KEY_TEMP}'                          # 0x02 // 2 // Outdoor Temperature (°C)
KEY_DEWPOINT = KEY_DEWPT                                # 0x03 // 2 // Dew point (°C)
KEY_WINDCHILL = 'windchill'                             # 0x04 // 2 // Wind chill (°C)
KEY_HEATINDEX = 'heatindex'                             # 0x05 // 2 // Heat index (°C)
KEY_INHUMI = f'in{KEY_HUMID}'                           # 0x06 // 1 // Indoor Humidity (%)
KEY_OUTHUMI = f'out{KEY_HUMID}'                         # 0x07 // 1 // Outdoor Humidity (%)
KEY_ABSBARO = 'absbarometer'                            # 0x08 // 2 // Absolutely Barometric (hpa)
KEY_RELBARO = 'relbarometer'                            # 0x09 // 2 // Relative Barometric (hpa)
KEY_WINDDIRECTION = 'winddir'                           # 0x0A // 2 // Wind Direction (360°)
KEY_WINDSPEED = 'windspeed'                             # 0x0B // 2 // Wind Speed (m/s)
KEY_GUSTSPEED = 'gustspeed'                             # 0x0C // 2 // Gust Speed (m/s)
KEY_RAINEVENT = 'rainevent'                             # 0x0D // 2 // Rain Event (mm)
KEY_RAINRATE = 'rainrate'                               # 0x0E // 2 // Rain Rate (mm/h)
KEY_RAINHOUR = 'raingain'                               # 0x0F // 2 // Rain hour (mm)
KEY_RAINDAY = 'rainday'                                 # 0x10 // 2 // Rain Day (mm)
KEY_RAINWEEK = 'rainweek'                               # 0x11 // 2 // Rain Week (mm)
KEY_RAINMONTH = 'rainmonth'                             # 0x12 // 4 // Rain Month (mm)
KEY_RAINYEAR = 'rainyear'                               # 0x13 // 4 // Rain Year (mm)
KEY_RAINTOTALS = 'raintotals'                           # 0x14 // 4 // Rain Totals (mm)
KEY_LIGHT = 'light'                                     # 0x15 // 4 // Light (lux)
KEY_UV = 'solarradiation'                               # 0x16 // 2 // UV (uW/m2)
KEY_UVI = 'uvi'                                         # 0x17 // 1 // UVI (0-15 index)
KEY_TIME = 'datetime'                                   # 0x18 // 6 // Date and time
KEY_DAYLWINDMAX = 'winddaymax'                          # 0X19 // 2 // Day max wind(m/s)
KEY_TEMP1 = f'{KEY_TEMP}1'                              # 0x1A // 2 // Temperature 1(°C)
KEY_TEMP2 = f'{KEY_TEMP}2'                              # 0x1B // 2 // Temperature 2(°C)
KEY_TEMP3 = f'{KEY_TEMP}3'                              # 0x1C // 2 // Temperature 3(°C)
KEY_TEMP4 = f'{KEY_TEMP}4'                              # 0x1D // 2 // Temperature 4(°C)
KEY_TEMP5 = f'{KEY_TEMP}5'                              # 0x1E // 2 // Temperature 5(°C)
KEY_TEMP6 = f'{KEY_TEMP}6'                              # 0x1F // 2 // Temperature 6(°C)
KEY_TEMP7 = f'{KEY_TEMP}7'                              # 0x20 // 2 // Temperature 7(°C)
KEY_TEMP8 = f'{KEY_TEMP}8'                              # 0x21 // 2 // Temperature 8(°C)
KEY_TF_USR1 = f'{KEY_TEMP}9'                            # 0x63 // 3 // Temperature(°C)
KEY_TF_USR2 = f'{KEY_TEMP}10'                           # 0x64 // 3 // Temperature(°C)
KEY_TF_USR3 = f'{KEY_TEMP}11'                           # 0x65 // 3 // Temperature(°C)
KEY_TF_USR4 = f'{KEY_TEMP}12'                           # 0x66 // 3 // Temperature(°C)
KEY_TF_USR5 = f'{KEY_TEMP}13'                           # 0x67 // 3 // Temperature(°C)
KEY_TF_USR6 = f'{KEY_TEMP}14'                           # 0x68 // 3 // Temperature(°C)
KEY_TF_USR7 = f'{KEY_TEMP}15'                           # 0x69 // 3 // Temperature(°C)
KEY_TF_USR8 = f'{KEY_TEMP}16'                           # 0x6A // 3 // Temperature(°C)
KEY_HUMI1 = f'{KEY_HUMID}1'                             # 0x22 // 1 // Humidity 1, 0-100%
KEY_HUMI2 = f'{KEY_HUMID}2'                             # 0x23 // 1 // Humidity 2, 0-100%
KEY_HUMI3 = f'{KEY_HUMID}3'                             # 0x24 // 1 // Humidity 3, 0-100%
KEY_HUMI4 = f'{KEY_HUMID}4'                             # 0x25 // 1 // Humidity 4, 0-100%
KEY_HUMI5 = f'{KEY_HUMID}5'                             # 0x26 // 1 // Humidity 5, 0-100%
KEY_HUMI6 = f'{KEY_HUMID}6'                             # 0x27 // 1 // Humidity 6, 0-100%
KEY_HUMI7 = f'{KEY_HUMID}7'                             # 0x28 // 1 // Humidity 7, 0-100%
KEY_HUMI8 = f'{KEY_HUMID}8'                             # 0x29 // 1 // Humidity 8, 0-100%
KEY_SOILTEMP1 = f'{KEY_SOILTEMP}1'                      # 0x2B // 2 // Soil Temperature(°C)
KEY_SOILTEMP2 = f'{KEY_SOILTEMP}2'                      # 0x2D // 2 // Soil Temperature(°C)
KEY_SOILTEMP3 = f'{KEY_SOILTEMP}3'                      # 0x2F // 2 // Soil Temperature(°C)
KEY_SOILTEMP4 = f'{KEY_SOILTEMP}4'                      # 0x31 // 2 // Soil Temperature(°C)
KEY_SOILTEMP5 = f'{KEY_SOILTEMP}5'                      # 0x33 // 2 // Soil Temperature(°C)
KEY_SOILTEMP6 = f'{KEY_SOILTEMP}6'                      # 0x35 // 2 // Soil Temperature(°C)
KEY_SOILTEMP7 = f'{KEY_SOILTEMP}7'                      # 0x37 // 2 // Soil Temperature(°C)
KEY_SOILTEMP8 = f'{KEY_SOILTEMP}8'                      # 0x39 // 2 // Soil Temperature(°C)
KEY_SOILTEMP9 = f'{KEY_SOILTEMP}9'                      # 0x3B // 2 // Soil Temperature(°C)
KEY_SOILTEMP10 = f'{KEY_SOILTEMP}10'                    # 0x3D // 2 // Soil Temperature(°C)
KEY_SOILTEMP11 = f'{KEY_SOILTEMP}11'                    # 0x3F // 2 // Soil Temperature(°C)
KEY_SOILTEMP12 = f'{KEY_SOILTEMP}12'                    # 0x41 // 2 // Soil Temperature(°C)
KEY_SOILTEMP13 = f'{KEY_SOILTEMP}13'                    # 0x43 // 2 // Soil Temperature(°C)
KEY_SOILTEMP14 = f'{KEY_SOILTEMP}14'                    # 0x45 // 2 // Soil Temperature(°C)
KEY_SOILTEMP15 = f'{KEY_SOILTEMP}15'                    # 0x47 // 2 // Soil Temperature(°C)
KEY_SOILTEMP16 = f'{KEY_SOILTEMP}16'                    # 0x49 // 2 // Soil Temperature(°C)
KEY_SOILMOISTURE1 = f'{KEY_SOILMOISTURE}1'              # 0x2C // 1 // Soil Moisture(%)
KEY_SOILMOISTURE2 = f'{KEY_SOILMOISTURE}2'              # 0x2E // 1 // Soil Moisture(%)
KEY_SOILMOISTURE3 = f'{KEY_SOILMOISTURE}3'              # 0x30 // 1 // Soil Moisture(%)
KEY_SOILMOISTURE4 = f'{KEY_SOILMOISTURE}4'              # 0x32 // 1 // Soil Moisture(%)
KEY_SOILMOISTURE5 = f'{KEY_SOILMOISTURE}5'              # 0x34 // 1 // Soil Moisture(%)
KEY_SOILMOISTURE6 = f'{KEY_SOILMOISTURE}6'              # 0x36 // 1 // Soil Moisture(%)
KEY_SOILMOISTURE7 = f'{KEY_SOILMOISTURE}7'              # 0x38 // 1 // Soil Moisture(%)
KEY_SOILMOISTURE8 = f'{KEY_SOILMOISTURE}8'              # 0x3A // 1 // Soil Moisture(%)
KEY_SOILMOISTURE9 = f'{KEY_SOILMOISTURE}9'              # 0x3C // 1 // Soil Moisture(%)
KEY_SOILMOISTURE10 = f'{KEY_SOILMOISTURE}10'            # 0x3E // 1 // Soil Moisture(%)
KEY_SOILMOISTURE11 = f'{KEY_SOILMOISTURE}11'            # 0x40 // 1 // Soil Moisture(%)
KEY_SOILMOISTURE12 = f'{KEY_SOILMOISTURE}12'            # 0x42 // 1 // Soil Moisture(%)
KEY_SOILMOISTURE13 = f'{KEY_SOILMOISTURE}13'            # 0x44 // 1 // Soil Moisture(%)
KEY_SOILMOISTURE14 = f'{KEY_SOILMOISTURE}14'            # 0x46 // 1 // Soil Moisture(%)
KEY_SOILMOISTURE15 = f'{KEY_SOILMOISTURE}15'            # 0x48 // 1 // Soil Moisture(%)
KEY_SOILMOISTURE16 = f'{KEY_SOILMOISTURE}16'            # 0x4A // 1 // Soil Moisture(%)
KEY_LOWBATT = 'lowbatt'                                 # 0x4C // 16 // All sensor lowbatt 16 char
KEY_PM25_CH1 = f'{KEY_PM25}1'                           # 0x2A // 2 // PM2.5 Air Quality Sensor(μg/m3)
KEY_PM25_CH2 = f'{KEY_PM25}2'                           # 0x51 // 2 // PM2.5 Air Quality Sensor(μg/m3)
KEY_PM25_CH3 = f'{KEY_PM25}3'                           # 0x52 // 2 // PM2.5 Air Quality Sensor(μg/m3)
KEY_PM25_CH4 = f'{KEY_PM25}4'                           # 0x53 // 2 // PM2.5 Air Quality Sensor(μg/m3)
KEY_PM25_24HAVG1 = f'{KEY_PM25_AVG}1'               # 0x4D // 2 // for pm25_ch1
KEY_PM25_24HAVG2 = f'{KEY_PM25_AVG}2'               # 0x4E // 2 // for pm25_ch2
KEY_PM25_24HAVG3 = f'{KEY_PM25_AVG}3'               # 0x4F // 2 // for pm25_ch3
KEY_PM25_24HAVG4 = f'{KEY_PM25_AVG}4'               # 0x50 // 2 // for pm25_ch4
KEY_LEAK_CH1 = f'{KEY_LEAK}1'                           # 0x58 // 1 // for Leak_ch1
KEY_LEAK_CH2 = f'{KEY_LEAK}2'                           # 0x59 // 1 // for Leak_ch2
KEY_LEAK_CH3 = f'{KEY_LEAK}3'                           # 0x5A // 1 // for Leak_ch3
KEY_LEAK_CH4 = f'{KEY_LEAK}4'                           # 0x5B // 1 // for Leak_ch4
KEY_LIGHTNING_DIST = 'lightningdist'                         # 0x60 // 1 // lightning distance （1~40KM)
KEY_LIGHTNING_TIME = 'lightningdettime'                 # 0x61 // 4 // lightning happened time(UTC)
KEY_LIGHTNING_COUNT = 'lightningcount'                  # 0x62 // 4 // lightning counter for the day
KEY_SENSOR_CO2 = (KEY_SENSOR_CO2_TEMP,
                   KEY_SENSOR_CO2_HUM,
                   KEY_SENSOR_CO2_PM10,
                   KEY_SENSOR_CO2_PM10_24,
                   KEY_SENSOR_CO2_PM255,
                   KEY_SENSOR_CO2_PM255_24,
                   KEY_SENSOR_CO2_CO2,
                   KEY_SENSOR_CO2_CO2_24)               # 0x70 // 16 // CO2
KEY_PM25_AQI = None                                     # 0x71 //   // only for amb
KEY_LEAF_WETNESS_CH1 = f'{KEY_LEAF_WETNESS}1'           # 0x72 // 1 //
KEY_LEAF_WETNESS_CH2 = f'{KEY_LEAF_WETNESS}2'           # 0x73 // 1 //
KEY_LEAF_WETNESS_CH3 = f'{KEY_LEAF_WETNESS}3'           # 0x74 // 1 //
KEY_LEAF_WETNESS_CH4 = f'{KEY_LEAF_WETNESS}4'           # 0x75 // 1 //
KEY_LEAF_WETNESS_CH5 = f'{KEY_LEAF_WETNESS}5'           # 0x76 // 1 //
KEY_LEAF_WETNESS_CH6 = f'{KEY_LEAF_WETNESS}6'           # 0x77 // 1 //
KEY_LEAF_WETNESS_CH7 = f'{KEY_LEAF_WETNESS}7'           # 0x78 // 1 //
KEY_LEAF_WETNESS_CH8 = f'{KEY_LEAF_WETNESS}8'           # 0x79 // 1 //
KEY_RAIN_PRIO = 'rain_priority'                         # 0x7A // 1 // rain priority (classical or piezo) - 1 = classical, 2 = piezo
KEY_RAD_COMP = 'rad_comp'                               # 0x7B // 1 // radiation compensation - on/off
KEY_PIEZO_RAIN_RATE = 'p_rainrate'                      # 0x80 // 2 //
KEY_PIEZO_EVENT_RAIN = 'p_rainevent'                    # 0x81 // 2 //
KEY_PIEZO_HOURLY_RAIN = 'p_rainhour'                    # 0x82 // 2 //
KEY_PIEZO_DAILY_RAIN = 'p_rainday'                      # 0x83 // 4 //
KEY_PIEZO_WEEKLY_RAIN = 'p_rainweek'                    # 0x84 // 4 //
KEY_PIEZO_MONTHLY_RAIN = 'p_rainmonth'                  # 0x85 // 4 //
KEY_PIEZO_YEARLY_RAIN = 'p_rainyear'                    # 0x86 // 4 //
KEY_PIEZO_GAIN10 = None                                 # 0x87 // 2*10 //
KEY_RST_RAINTIME = None                                 # 0x88 // 3 //
KEY_RAIN_RESET_DAY = 'day_reset'
KEY_RAIN_RESET_WEEK = 'week_reset'
KEY_RAIN_RESET_ANNUAL = 'annual_reset'

# ADDITIONAL TCP DATA_POINTS
KEY_CLIENT_IP = 'client_ip'
KEY_PASSKEY = None
KEY_FIRMWARE = 'firmware'
KEY_FREQ = 'frequency'
KEY_MODEL = 'model'
KEY_RUNTIME = 'runtime'
KEY_INTERVAL = 'interval'

# PLUGIN DATA_POINTS
KEY_INDEWPPOINT = f'in{KEY_DEWPT}'
KEY_INABSHUM = f'in{KEY_ABSHUM}'
KEY_OUTDEWPT = f'out{KEY_DEWPT}'
KEY_OUTFROSTPT = f'out{KEY_FROSTPT}'
KEY_OUTABSHUM = f'out{KEY_ABSHUM}'
KEY_RESET = 'reset'
KEY_REBOOT = 'reboot'
KEY_FEELS_LIKE = 'feelslike'
KEY_SENSOR_WARNING = 'sensor_warning'
KEY_BATTERY_WARNING = 'battery_warning'
KEY_STORM_WARNING = 'storm_warning'
KEY_THUNDERSTORM_WARNING = 'thunderstorm_warning'
KEY_WEATHERSTATION_WARNING = 'weatherstation_warning'
KEY_FIRMWARE_UPDATE_AVAILABLE = 'firmware_update_available'
KEY_FIRMWARE_UPDATE_TEXT = 'firmware_update_text'
KEY_CLOUD_CEILING = 'cloud_ceiling'
KEY_WINDDIR_TEXT = 'winddir_txt'
KEY_WINDSPEED_BFT = 'windspeed_bft'
KEY_WINDSPEED_BFT_TEXT= 'windspeed_bft_txt'
KEY_WEATHER_TEXT = 'weather_txt'
KEY_WINDSPEED_AVG10M = 'windspeed_avg10m'
KEY_WINDDIR_AVG10M = 'winddir_avg10m'
KEY_GUSTSPEED_AVG10M = 'gustspeed_avg10m'

# OTHERS
BATTERY_EXTENTION = '_batt'
SIGNAL_EXTENTION = '_sig'

# ATTRIBUTE_GROUPS
META_ATTRIBUTES = [KEY_MODEL,
                   KEY_FREQ,
                   KEY_SENSOR_WARNING,
                   KEY_BATTERY_WARNING,
                   KEY_STORM_WARNING,
                   KEY_THUNDERSTORM_WARNING,
                   KEY_WEATHERSTATION_WARNING,
                   KEY_FIRMWARE,
                   KEY_FIRMWARE_UPDATE_AVAILABLE,
                   KEY_FIRMWARE_UPDATE_TEXT,
                   ]

TCP_ATTRIBUTES = [KEY_RUNTIME]

FW_UPDATE_URL = 'http://download.ecowitt.net/down/filewave?v=FirwaveReadme.txt'.replace("\"", "")