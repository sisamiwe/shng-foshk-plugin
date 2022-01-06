# !/usr/bin/env python
# vim: set encoding=utf-8 tabstop=4 softtabstop=4 shiftwidth=4 expandtab
# # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # #
# Copyright 2021 Michael Wenzel
# # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # #
#  Foshk-Plugin for SmartHomeNG.  https://github.com/smarthomeNG//
#
#  This plugin is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.
#
#  This plugin is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this plugin. If not, see <http://www.gnu.org/licenses/>.
# # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # #

# cmd_discover_alt   = "\xff\xff\x12\x00\x04\x16"
# cmd_discover       = "\xff\xff\x12\x03\x15"
# cmd_reboot         = "\xff\xff\x40\x03\x43"
# cmd_get_customC    = "\xff\xff\x51\x03\x54"        # ff ff 51 03 54 (last byte: CRC)
# cmd_get_customE    = "\xff\xff\x2a\x03\x2d"        # ff ff 2a 03 2d (last byte: CRC)
# cmd_set_customC    = "\xff\xff\x52"                # ff ff 52 Len [Laenge Path Ecowitt][Path Ecowitt][Laenge Path WU][Path WU][crc]
# cmd_set_customE    = "\xff\xff\x2b"                # ff ff 2b Len [Laenge ID][ID][Laenge Key][Key][Laenge IP][IP][Port][Intervall][ecowitt][enable][crc]
# cmd_get_FWver      = "\xff\xff\x50\x03\x53"        # ff ff 50 03 53 (last byte: CRC)
# ok_set_customE     = "\xff\xff\x2b\x04\x00\x2f"
# ok_set_customC     = "\xff\xff\x52\x04\x00\x56"
# ok_cmd_reboot      = "\xff\xff\x40\x04\x00\x44"
# cmd_get_live_data  = '\xFF\xFF\x27\x03\x2A'        # Packet Format: HEADER, CMD_GW1000_LIVE_DATA, SIZE, CHECKSUM

commandset = {
            'header': 0xff,
            # general commands
            'cmd_write_ssid':               0x11,    #  send ssid and password to wifi module
            'cmd_broadcast':                0x12,    #  udp cast for device echo，answer back data size is 2 bytes
            'cmd_read_ecowitt':             0x1e,    #  read aw.net setting
            'cmd_write_ecowitt':            0x1f,    #  write back awt.net setting
            'cmd_read_wunderground':        0x20,    #  read wunderground setting
            'cmd_write_wunderground':       0x21,    #  write back wunderground setting
            'cmd_read_wow':                 0x22,    #  read weatherobservationswebsite setting
            'cmd_write_wow':                0x23,    #  write back weatherobservationswebsite setting
            'cmd_read_weathercloud':        0x24,    #  read weathercloud setting
            'cmd_write_weathercloud':       0x25,    #  write back weathercloud setting
            'cmd_read_sation_mac':          0x26,    #  read mac address
            'cmd_read_customized':          0x2a,    #  read customized server setting
            'cmd_write_customized':         0x2b,    #  write back customized sever setting
            'cmd_write_update':             0x43,    #  firmware upgrade
            'cmd_read_firmware_version':    0x50,    #  read current firmware version number
            #  the following command is only valid for GW1000, WH2650 and wn1900
            'cmd_gw1000_livedata' :         0x27,    # read current data，reply data size is 2bytes.
            'cmd_get_soilhumiad' :          0x28,    # read soilmoisture sensor calibration parameters
            'cmd_set_soilhumiad' :          0x29,    # write back soilmoisture sensor calibration parameters
            'cmd_get_mulch_offset' :        0x2c,    # read multi channel sensor offset value
            'cmd_set_mulch_offset' :        0x2d,    # write back    multi channel sensor offset value
            'cmd_get_pm25_offset' :         0x2e,    # read pm2.5offset calibration data
            'cmd_set_pm25_offset' :         0x2f,    # writeback pm2.5offset calibration data
            'cmd_read_ssss' :               0x30,    # read system info
            'cmd_write_ssss' :              0x31,    # write back system info
            'cmd_read_raindata' :           0x34,    # read rain data
            'cmd_write_raindata' :          0x35,    # write back rain data
            'cmd_read_gain' :               0x36,    # read rain gain
            'cmd_write_gain' :              0x37,    # write back rain gain
            'cmd_read_calibration' :        0x38,    # read sensor set offset calibration value
            'cmd_write_calibration' :       0x39,    # write back    sensor set  offset value
            'cmd_read_sensor_id' :          0x3a,    # read sensors id
            'cmd_write_sensor_id' :         0x3b,    # write back sensors id
            'cmd_read_sensor_id_new' :      0x3c,    # this is reserved for newly added sensors
            'cmd_write_reboot' :            0x40,    # system restart
            'cmd_write_reset' :             0x41,    # reset to default
            'cmd_read_customized_path' :    0x51,
            'cmd_write_customized_path' :   0x52,
            'cmd_get_co2_offset' :          0x53,    # readco2 offset
            'cmd_set_co2_offset' :          0x54,    # write o2 offset
            'cmd_read_rstrain_time' :       0x55,    # read rain reset time
            'cmd_write_rstrain_time' :      0x56     # write back rain reset tim
            }
                
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
sensor_idt = {
        '0x01': {'item': 'ITEM_INTEMP' ,'name': 'Indoor Temperature' ,'unit': '°C', 'length': 2, 'signed': True, 'factor': 0.1},
        '0x02': {'item': 'ITEM_OUTTEMP' ,'name': 'Outdoor Temperature' ,'unit': '°C', 'length': 2, 'signed': True, 'factor': 0.1},
        '0x03': {'item': 'ITEM_DEWPOINT' ,'name': 'Dew point' ,'unit': '°C', 'length': 2, 'signed': True, 'factor': 0.1},
        '0x04': {'item': 'ITEM_WINDCHILL' ,'name': 'Wind chill' ,'unit': '°C', 'length': 2, 'signed': True, 'factor': 0.1},
        '0x05': {'item': 'ITEM_HEATINDEX' ,'name': 'Heat index' ,'unit': '°C', 'length': 2, 'signed': True, 'factor': 0.1},
        '0x06': {'item': 'ITEM_INHUMI' ,'name': 'Indoor Humidity' ,'unit': '%', 'length': 1},
        '0x07': {'item': 'ITEM_OUTHUMI' ,'name': 'Outdoor Humidity' ,'unit': '%', 'length': 1},
        '0x08': {'item': 'ITEM_ABSBARO' ,'name': 'Absolutely Barometric' ,'unit': 'hpa', 'length': 2, 'factor': 0.1},
        '0x09': {'item': 'ITEM_RELBARO' ,'name': 'Relative Barometric' ,'unit': 'hpa', 'length': 2, 'factor': 0.1},
        '0x0A': {'item': 'ITEM_WINDDIRECTION' ,'name': 'Wind Direction' ,'unit': '360°', 'length': 2},
        '0x0B': {'item': 'ITEM_WINDSPEED' ,'name': 'Wind Speed' ,'unit': 'm/s', 'length': 2},
        '0x0C': {'item': 'ITEM_GUSTSPEED' ,'name': 'Gust Speed' ,'unit': 'm/s', 'length': 2},
        '0x0D': {'item': 'ITEM_RAINEVENT' ,'name': 'Rain Event' ,'unit': 'mm', 'length': 2},
        '0x0E': {'item': 'ITEM_RAINRATE' ,'name': 'Rain Rate' ,'unit': 'mm/h', 'length': 2},
        '0x0F': {'item': 'ITEM_RAINHOUR' ,'name': 'Rainhour' ,'unit': 'mm', 'length': 2},
        '0x10': {'item': 'ITEM_RAINDAY' ,'name': 'RainDay' ,'unit': 'mm', 'length': 2},
        '0x11': {'item': 'ITEM_RAINWEEK' ,'name': 'RainWeek' ,'unit': 'mm', 'length': 2},
        '0x12': {'item': 'ITEM_RAINMONTH' ,'name': 'RainMonth' ,'unit': 'mm', 'length': 4},
        '0x13': {'item': 'ITEM_RAINYEAR' ,'name': 'RainYear' ,'unit': 'mm', 'length': 4},
        '0x14': {'item': 'ITEM_RAINTOTALS' ,'name': 'RainTotals' ,'unit': 'mm', 'length': 4},
        '0x15': {'item': 'ITEM_LIGHT' ,'name': 'Light' ,'unit': 'lux', 'length': 4, 'factor': 0.1},                   # 0.1 to convert to lux;
        '0x16': {'item': 'ITEM_UV' ,'name': 'UV' ,'unit': 'uW/m2', 'length': 2},
        '0x17': {'item': 'ITEM_UVI' ,'name': 'UVI' ,'unit': '0-15index', 'length': 1},
        '0x18': {'item': 'ITEM_TIME' ,'name': 'Time' ,'unit': 'None', 'length': 6},
        '0x19': {'item': 'ITEM_DAYLWINDMAX' ,'name': 'Daymaxwind' ,'unit': 'm/s', 'length': 2},
        '0x1A': {'item': 'ITEM_TEMP1' ,'name': 'Temperature1' ,'unit': '°C', 'length': 2, 'signed': True, 'factor': 0.1},
        '0x1B': {'item': 'ITEM_TEMP2' ,'name': 'Temperature2' ,'unit': '°C', 'length': 2, 'signed': True, 'factor': 0.1},
        '0x1C': {'item': 'ITEM_TEMP3' ,'name': 'Temperature3' ,'unit': '°C', 'length': 2, 'signed': True, 'factor': 0.1},
        '0x1D': {'item': 'ITEM_TEMP4' ,'name': 'Temperature4' ,'unit': '°C', 'length': 2, 'signed': True, 'factor': 0.1},
        '0x1E': {'item': 'ITEM_TEMP5' ,'name': 'Temperature5' ,'unit': '°C', 'length': 2, 'signed': True, 'factor': 0.1},
        '0x1F': {'item': 'ITEM_TEMP6' ,'name': 'Temperature6' ,'unit': '°C', 'length': 2, 'signed': True, 'factor': 0.1},
        '0x20': {'item': 'ITEM_TEMP7' ,'name': 'Temperature7' ,'unit': '°C', 'length': 2, 'signed': True, 'factor': 0.1},
        '0x21': {'item': 'ITEM_TEMP8' ,'name': 'Temperature8' ,'unit': '°C', 'length': 2, 'signed': True, 'factor': 0.1},
        '0x22': {'item': 'ITEM_HUMI1' ,'name': 'Humidity1' ,'unit': '%', 'length': 1},
        '0x23': {'item': 'ITEM_HUMI2' ,'name': 'Humidity2' ,'unit': '%', 'length': 2},
        '0x24': {'item': 'ITEM_HUMI3' ,'name': 'Humidity3' ,'unit': '%', 'length': 3},
        '0x25': {'item': 'ITEM_HUMI4' ,'name': 'Humidity4' ,'unit': '%', 'length': 4},
        '0x26': {'item': 'ITEM_HUMI5' ,'name': 'Humidity5' ,'unit': '%', 'length': 5},
        '0x27': {'item': 'ITEM_HUMI6' ,'name': 'Humidity6' ,'unit': '%', 'length': 6},
        '0x28': {'item': 'ITEM_HUMI7' ,'name': 'Humidity7' ,'unit': '%', 'length': 7},
        '0x29': {'item': 'ITEM_HUMI8' ,'name': 'Humidity8' ,'unit': '%', 'length': 8},
        '0x2A': {'item': 'ITEM_PM25_CH1' ,'name': 'PM2.5AirQualitySensor' ,'unit': 'μg/m3', 'length': 2},
        '0x2B': {'item': 'ITEM_SOILTEMP1' ,'name': 'SoilTemperature' ,'unit': '°C', 'length': 2, 'signed': True, 'factor': 0.1},
        '0x2C': {'item': 'ITEM_SOILMOISTURE1' ,'name': 'SoilMoisture' ,'unit': '%', 'length': 1},
        '0x2D': {'item': 'ITEM_SOILTEMP2' ,'name': 'SoilTemperature' ,'unit': '°C', 'length': 2, 'signed': True, 'factor': 0.1},
        '0x2E': {'item': 'ITEM_SOILMOISTURE2' ,'name': 'SoilMoisture' ,'unit': '%', 'length': 1},
        '0x2F': {'item': 'ITEM_SOILTEMP3' ,'name': 'SoilTemperature' ,'unit': '°C', 'length': 2, 'signed': True, 'factor': 0.1},
        '0x30': {'item': 'ITEM_SOILMOISTURE3' ,'name': 'SoilMoisture' ,'unit': '%', 'length': 1},
        '0x31': {'item': 'ITEM_SOILTEMP4' ,'name': 'SoilTemperature' ,'unit': '°C', 'length': 2, 'signed': True, 'factor': 0.1},
        '0x32': {'item': 'ITEM_SOILMOISTURE4' ,'name': 'SoilMoisture' ,'unit': '%', 'length': 1},
        '0x33': {'item': 'ITEM_SOILTEMP5' ,'name': 'SoilTemperature' ,'unit': '°C', 'length': 2, 'signed': True, 'factor': 0.1},
        '0x34': {'item': 'ITEM_SOILMOISTURE5' ,'name': 'SoilMoisture' ,'unit': '%', 'length': 1},
        '0x35': {'item': 'ITEM_SOILTEMP6' ,'name': 'SoilTemperature' ,'unit': '°C', 'length': 2, 'signed': True, 'factor': 0.1},
        '0x36': {'item': 'ITEM_SOILMOISTURE6' ,'name': 'SoilMoisture' ,'unit': '%', 'length': 1},
        '0x37': {'item': 'ITEM_SOILTEMP7' ,'name': 'SoilTemperature' ,'unit': '°C', 'length': 2, 'signed': True, 'factor': 0.1},
        '0x38': {'item': 'ITEM_SOILMOISTURE7' ,'name': 'SoilMoisture' ,'unit': '%', 'length': 1},
        '0x39': {'item': 'ITEM_SOILTEMP8' ,'name': 'SoilTemperature' ,'unit': '°C', 'length': 2, 'signed': True, 'factor': 0.1},
        '0x3A': {'item': 'ITEM_SOILMOISTURE8' ,'name': 'SoilMoisture' ,'unit': '%', 'length': 1},
        '0x3B': {'item': 'ITEM_SOILTEMP9' ,'name': 'SoilTemperature' ,'unit': '°C', 'length': 2, 'signed': True, 'factor': 0.1},
        '0x3C': {'item': 'ITEM_SOILMOISTURE9' ,'name': 'SoilMoisture' ,'unit': '%', 'length': 1},
        '0x3D': {'item': 'ITEM_SOILTEMP1' ,'name': 'SoilTemperature' ,'unit': '°C', 'length': 2, 'signed': True, 'factor': 0.1},
        '0x3E': {'item': 'ITEM_SOILMOISTURE1' ,'name': 'SoilMoisture' ,'unit': '%', 'length': 1},
        '0x3F': {'item': 'ITEM_SOILTEMP11' ,'name': 'SoilTemperature' ,'unit': '°C', 'length': 2, 'signed': True, 'factor': 0.1},
        '0x40': {'item': 'ITEM_SOILMOISTURE11' ,'name': 'SoilMoisture' ,'unit': '%', 'length': 1},
        '0x41': {'item': 'ITEM_SOILTEMP12' ,'name': 'SoilTemperature' ,'unit': '°C', 'length': 2, 'signed': True, 'factor': 0.1},
        '0x42': {'item': 'ITEM_SOILMOISTURE12' ,'name': 'SoilMoisture' ,'unit': '%', 'length': 1},
        '0x43': {'item': 'ITEM_SOILTEMP13' ,'name': 'SoilTemperature' ,'unit': '°C', 'length': 2, 'signed': True, 'factor': 0.1},
        '0x44': {'item': 'ITEM_SOILMOISTURE13' ,'name': 'SoilMoisture' ,'unit': '%', 'length': 1},
        '0x45': {'item': 'ITEM_SOILTEMP14' ,'name': 'SoilTemperature' ,'unit': '°C', 'length': 2, 'signed': True, 'factor': 0.1},
        '0x46': {'item': 'ITEM_SOILMOISTURE14' ,'name': 'SoilMoisture' ,'unit': '%', 'length': 1},
        '0x47': {'item': 'ITEM_SOILTEMP15' ,'name': 'SoilTemperature' ,'unit': '°C', 'length': 2, 'signed': True, 'factor': 0.1},
        '0x48': {'item': 'ITEM_SOILMOISTURE15' ,'name': 'SoilMoisture' ,'unit': '%', 'length': 1},
        '0x49': {'item': 'ITEM_SOILTEMP16' ,'name': 'SoilTemperature' ,'unit': '°C', 'length': 2, 'signed': True, 'factor': 0.1},
        '0x4A': {'item': 'ITEM_SOILMOISTURE16' ,'name': 'SoilMoisture' ,'unit': '%', 'length': 1},
        '0x4C': {'item': 'ITEM_LOWBATT' ,'name': 'LowBatt' ,'unit': 'None', 'length': 16},
        '0x4D': {'item': 'ITEM_PM25_24HAVG1' ,'name': 'PM25_24hAVG1' ,'unit': 'μg/m3', 'length': 2},
        '0x4E': {'item': 'ITEM_PM25_24HAVG2' ,'name': 'PM25_24hAVG2' ,'unit': 'μg/m3', 'length': 2},
        '0x4F': {'item': 'ITEM_PM25_24HAVG3' ,'name': 'PM25_24hAVG3' ,'unit': 'μg/m3', 'length': 2},
        '0x50': {'item': 'ITEM_PM25_24HAVG4' ,'name': 'PM25_24hAVG4' ,'unit': 'μg/m3', 'length': 2},
        '0x51': {'item': 'ITEM_PM25_CH2' ,'name': 'PM2.5AirQualitySensor' ,'unit': 'μg/m3', 'length': 2},
        '0x52': {'item': 'ITEM_PM25_CH3' ,'name': 'PM2.5AirQualitySensor' ,'unit': 'μg/m3', 'length': 2},
        '0x53': {'item': 'ITEM_PM25_CH4' ,'name': 'PM2.5AirQualitySensor' ,'unit': 'μg/m3', 'length': 2},
        '0x58': {'item': 'ITEM_LEAK_CH1' ,'name': 'Leak_1' ,'unit': 'None', 'length': 1},
        '0x59': {'item': 'ITEM_LEAK_CH2' ,'name': 'Leak_2' ,'unit': 'None', 'length': 1},
        '0x5A': {'item': 'ITEM_LEAK_CH3' ,'name': 'Leak_3' ,'unit': 'None', 'length': 1},
        '0x5B': {'item': 'ITEM_LEAK_CH4' ,'name': 'Leak_4' ,'unit': 'None', 'length': 1},
        '0x60': {'item': 'ITEM_LIGHTNING' ,'name': 'Lightning Distance' ,'unit': 'km', 'length': 1},
        '0x61': {'item': 'ITEM_LIGHTNING_TIME' ,'name': 'lightninghappenedtime' ,'unit': 'UTC', 'length': 4},
        '0x62': {'item': 'ITEM_LIGHTNING_POWER' ,'name': 'LigthningCounterDay' ,'unit': 'None', 'length': 4},
        '0x63': {'item': 'ITEM_TF_USR1' ,'name': 'Temperature' ,'unit': '°C', 'length': 3},
        '0x64': {'item': 'ITEM_TF_USR2' ,'name': 'Temperature' ,'unit': '°C', 'length': 3},
        '0x65': {'item': 'ITEM_TF_USR3' ,'name': 'Temperature' ,'unit': '°C', 'length': 3},
        '0x66': {'item': 'ITEM_TF_USR4' ,'name': 'Temperature' ,'unit': '°C', 'length': 3},
        '0x67': {'item': 'ITEM_TF_USR5' ,'name': 'Temperature' ,'unit': '°C', 'length': 3},
        '0x68': {'item': 'ITEM_TF_USR6' ,'name': 'Temperature' ,'unit': '°C', 'length': 3},
        '0x69': {'item': 'ITEM_TF_USR7' ,'name': 'Temperature' ,'unit': '°C', 'length': 3},
        '0x6A': {'item': 'ITEM_TF_USR8' ,'name': 'Temperature' ,'unit': '°C', 'length': 3},
        '0x70': {'item': 'ITEM_SENSOR_CO2' ,'name': 'CO2' ,'unit': 'None', 'length': 16},
        '0x72': {'item': 'ITEM_LEAF_WETNESS_CH1' ,'name': 'LeafWetness1' ,'unit': 'None', 'length': 1},
        '0x73': {'item': 'ITEM_LEAF_WETNESS_CH2' ,'name': 'LeafWetness2' ,'unit': 'None', 'length': 1},
        '0x74': {'item': 'ITEM_LEAF_WETNESS_CH3' ,'name': 'LeafWetness3' ,'unit': 'None', 'length': 1},
        '0x75': {'item': 'ITEM_LEAF_WETNESS_CH4' ,'name': 'LeafWetness4' ,'unit': 'None', 'length': 1},
        '0x76': {'item': 'ITEM_LEAF_WETNESS_CH5' ,'name': 'LeafWetness5' ,'unit': 'None', 'length': 1},
        '0x77': {'item': 'ITEM_LEAF_WETNESS_CH6' ,'name': 'LeafWetness6' ,'unit': 'None', 'length': 1},
        '0x78': {'item': 'ITEM_LEAF_WETNESS_CH7' ,'name': 'LeafWetness7' ,'unit': 'None', 'length': 1},
        '0x79': {'item': 'ITEM_LEAF_WETNESS_CH8' ,'name': 'LeafWetness8' ,'unit': 'None', 'length': 1}
            }
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
frequencies = ['433MHz', '868MHz', '915MHz', '920MHz']
multi_batt = {
        'wh40': {'mask': 1 << 4},
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
        # WH34 battery data is not obtained from live data rather it is obtained from sensor ID data
        b'\x63': ('decode_wh34', 3, 'temp9'),
        b'\x64': ('decode_wh34', 3, 'temp10'),
        b'\x65': ('decode_wh34', 3, 'temp11'),
        b'\x66': ('decode_wh34', 3, 'temp12'),
        b'\x67': ('decode_wh34', 3, 'temp13'),
        b'\x68': ('decode_wh34', 3, 'temp14'),
        b'\x69': ('decode_wh34', 3, 'temp15'),
        b'\x6A': ('decode_wh34', 3, 'temp16'),
        # WH45 battery data is not obtained from live data rather it is obtained from sensor ID data
        b'\x70': ('decode_wh45', 16, ('temp17', 'humid17', 'pm10', 'pm10_24h_avg', 'pm255', 'pm255_24h_avg', 'co2', 'co2_24h_avg')),
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

# header used in each API command and response packet
header = b'\xff\xff'

# known device models



# tuple of field codes for rain related fields in the GW1000/GW1100 live data so we can isolate these fields
rain_field_codes = (b'\x0D', b'\x0E', b'\x0F', b'\x10', b'\x11', b'\x12', b'\x13', b'\x14')
                    
# tuple of field codes for wind related fields in the GW1000/GW1100 live data so we can isolate these fields
wind_field_codes = (b'\x0A', b'\x0B', b'\x0C', b'\x19')


"""Data exchange format"""
# Fixed header, CMD, SIZE, DATA1, DATA2, ... , DATAn, CHECKSUM

# Fixed header: 2 bytes, header is fixed as 0xffff
# CMD: 1 byte, Command
# SIZE: 1 byte, packet size，counted from CMD till CHECKSUM
# DATA: n bytes, payloads，variable length
# CHECKSUM: 1 byte, CHECKSUM=CMD+SIZE+DATA1+DATA2+...+DATAn

