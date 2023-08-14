foshk
=====

Anforderungen
-------------
Benötigt wird eine Wetterstation von `Fine Offset Electronics <https://www.foshk.com >`_ mit entsprechender API
oder ein passendes Gateway das die Daten der Wetterstation lokal zur Verfügung stellt.
Die Datenbasis muss *Ecowitt kompatibel* erfolgen.

Getestet wurden GW1000 und WH2650 sowie Froggit DP2000 mit DP1100 7-in-1 Sensor (entspricht GW2000 mit WS90)

Die API ist hier beschrieben: `Data Exchange TCP Protocol for GW1000,1100,1900,2000,2680,2650 <https://osswww.ecowitt.net/uploads/20220407/WN1900%20GW1000,1100%20WH2680,2650%20telenet%20v1.6.4.pdf>`_

Das Plugin bietet die Möglichkeit, die Wetterdaten direkt über die API zu lesen oder die Daten aus dem ECOWITT Protokoll der "Customized Settings" zu beziehen.
Die Einrichtung erfolgt automatisch gemäß den Einstellungen im Plugin.

Konfiguration
-------------

Informationen über Plugin Parameter sind unter :doc:`/plugins_doc/config/foshk` beschrieben.


Foshk Item-Attribute
--------------------

Dieses Kapitel wurde automatisch durch Ausführen des Skripts in der Datei 'datapoints.py' erstellt.

Nachfolgend eine Auflistung der möglichen Attribute für das Plugin im Format: Attribute: Beschreibung [Einheit]

- air_pressure_abs: Absoluter Luftdruck [hpa]

- air_pressure_rel: Relativer Luftdruck [hpa]

- air_pressure_rel_diff_1h: Unterschied im Luftdruck innerhalb der letzten Stunde *Berechnung im Plugin [hPa]

- air_pressure_rel_diff_3h: Unterschied im Luftdruck innerhalb der letzten 3 Stunden *Berechnung im Plugin [hPa]

- air_pressure_rel_trend_1h: Trend des Luftdrucks innerhalb der letzten Stunde *Berechnung im Plugin [-]

- air_pressure_rel_trend_3h: Trend des Luftdrucks innerhalb der letzten 3 Stunden *Berechnung im Plugin [-]

- battery_warning: Batteriewarnung [True/False]

- cloud_ceiling: Wolkenhöhe *Berechnung im Plugin [m]

- co2: Aktueller CO2 Meßwert des CO2 Sensors [Vol%]

- co2_24h_avg: Mittlerer CO2 Messwert der letzten 24h des CO2 Sensors [Vol%]

- datetime: Datetime [None]

- dewpt: Taupunkt [°C]

- feelslike: Gefühlte Temperatur [°C]

- firmware: Firmware Version [None]

- firmware_update_available: Firmwareupdate verfügbar [True/False]

- frequency: Frequenz des Transmitter [None]

- gustspeed: Böengeschwindigkeit [m/s]

- gustspeed_avg10m: Durchschnittliche Windböen der letzten 10min *Berechnung im Plugin [m/s]

- heatindex: Heat Index [-]

- humid1: Luftfeuchtigkeit [%RH]

- humid17: Luftfeuchtigkeit am CO2 Sensor [%]

- humid2: Luftfeuchtigkeit [%RH]

- humid3: Luftfeuchtigkeit [%RH]

- humid4: Luftfeuchtigkeit [%RH]

- humid5: Luftfeuchtigkeit [%RH]

- humid6: Luftfeuchtigkeit [%RH]

- humid7: Luftfeuchtigkeit [%RH]

- humid8: Luftfeuchtigkeit [%RH]

- inabshum: Absolute Luftfeuchtigkeit Innen []

- indewpt: Taupunkt Innen [°C]

- inhumid: Innenluftfeuchtigkeit [%RH]

- intemp: Innentemperatur [°C]

- interval: Interval des Datenflusses [s]

- leafwet1: Blätter-/Pflanzenfeuchtigkeit Kanal 1 [%]

- leafwet2: Blätter-/Pflanzenfeuchtigkeit Kanal 2 [%]

- leafwet3: Blätter-/Pflanzenfeuchtigkeit Kanal 3 [%]

- leafwet4: Blätter-/Pflanzenfeuchtigkeit Kanal 4 [%]

- leafwet5: Blätter-/Pflanzenfeuchtigkeit Kanal 5 [%]

- leafwet6: Blätter-/Pflanzenfeuchtigkeit Kanal 6 [%]

- leafwet7: Blätter-/Pflanzenfeuchtigkeit Kanal 7 [%]

- leafwet8: Blätter-/Pflanzenfeuchtigkeit Kanal 8 [%]

- leak1: Leckage [True/False]

- leak2: Leckage [True/False]

- leak3: Leckage [True/False]

- leak4: Leckage [True/False]

- leakage_warning: Leckagewarnung [True/False]

- light: Helligkeit [lux]

- lightningcount: kumulierte Anzahl der Blitze des Tages [-]

- lightningdettime: Zeitpunkt des Blitzes [-]

- lightningdist: Blitzentfernung [1~40KM]

- lowbatt: All sensor lowbatt [-]

- model: Gateway Modell [None]

- outabshum: Absolute Luftfeuchtigkeit Außen []

- outdewpt: Taupunkt Außen [°C]

- outfrostpt: Frostpunkt Außen [°C]

- outhumid: Außenluftfeuchtigkeit [%RH]

- outtemp: Außentemperatur [°C]

- p_rain: Regenmenge [mm]

- p_rain_day: kumulierte Regenmenge des aktuellen Tages [mm]

- p_rain_event: kumulierte Regenmenge des aktuellen Regenevents [mm]

- p_rain_gain0: Kalibrierfaktor 0 für Piezo Regensensor [-]

- p_rain_gain1: Kalibrierfaktor 1 für Piezo Regensensor [-]

- p_rain_gain2: Kalibrierfaktor 2 für Piezo Regensensor [-]

- p_rain_gain3: Kalibrierfaktor 3 für Piezo Regensensor [-]

- p_rain_gain4: Kalibrierfaktor 4 für Piezo Regensensor [-]

- p_rain_gain5: Kalibrierfaktor 5 für Piezo Regensensor (reserviert) [-]

- p_rain_gain6: Kalibrierfaktor 6 für Piezo Regensensor (reserviert) [-]

- p_rain_gain7: Kalibrierfaktor 7 für Piezo Regensensor (reserviert) [-]

- p_rain_gain8: Kalibrierfaktor 8 für Piezo Regensensor (reserviert) [-]

- p_rain_gain9: Kalibrierfaktor 9 für Piezo Regensensor (reserviert) [-]

- p_rain_hour: kumulierte Regenmenge der aktuellen Stunde [mm]

- p_rain_month: kumulierte Regenmenge des aktuellen Monats [mm]

- p_rain_rate: Regenmenge pro Zeit des aktuellen Regenevents [mm]

- p_rain_week: kumulierte Regenmenge der aktuellen Woche [mm]

- p_rain_year: kumulierte Regenmenge des aktuellen Jahres [mm]

- pm10: PM10 Wert des CO2 Sensors []

- pm10_24h_avg: durchschnittlicher PM10 Wert der letzten 24h des CO2 Sensors []

- pm251: PM2.5 Partikelmenge Kanal 1 [μg/m3]

- pm252: PM2.5 Partikelmenge Kanal 2 [μg/m3]

- pm253: PM2.5 Partikelmenge Kanal 3 [μg/m3]

- pm254: PM2.5 Partikelmenge Kanal 4 [μg/m3]

- pm255: PM2.5 Wert des CO2 Sensors []

- pm255_24h_avg: durchschnittlicher PM2.5 Wert der letzten 24h des CO2 Sensors []

- pm25_24h_avg1: PM2.5 Partikelmenge 24h Mittel Kanal 1 [μg/m3]

- pm25_24h_avg2: PM2.5 Partikelmenge 24h Mittel Kanal 2 [μg/m3]

- pm25_24h_avg3: PM2.5 Partikelmenge 24h Mittel Kanal 3 [μg/m3]

- pm25_24h_avg4: PM2.5 Partikelmenge 24h Mittel Kanal 4 [μg/m3]

- rad_comp: Anwendung der Strahlungskompensation [on/off]

- rain: Regenmenge [mm]

- rain_day: kumulierte Regenmenge des aktuellen Tages [mm]

- rain_event: kumulierte Regenmenge des aktuellen Regenevents [mm]

- rain_hour: kumulierte Regenmenge der aktuellen Stunde [mm]

- rain_month: kumulierte Regenmenge des aktuellen Monats [mm]

- rain_priority: Verwendung des Regensensors [1: classical, 2: piezo]

- rain_rate: Regenmenge pro Zeit des aktuellen Regenevents [mm/h]

- rain_reset_day: Uhrzeit des Reset für Rain Day []

- rain_reset_week: Tag des Reset für Rain Week []

- rain_reset_year: Monat des Reset für Rain Year []

- rain_totals: kumulierte Regenmenge seit Inbetriebnahme bzw. Reset [mm]

- rain_week: kumulierte Regenmenge der aktuellen Woche [mm]

- rain_year: kumulierte Regenmenge des aktuellen Jahres [mm]

- reboot: Reboot [None]

- reset: Reset [None]

- sensor_warning: Sensorwarnung [True/False]

- soilmoist01: Bodenfeuchtigkeit [%]

- soilmoist02: Bodenfeuchtigkeit [%]

- soilmoist03: Bodenfeuchtigkeit [%]

- soilmoist04: Bodenfeuchtigkeit [%]

- soilmoist05: Bodenfeuchtigkeit [%]

- soilmoist06: Bodenfeuchtigkeit [%]

- soilmoist07: Bodenfeuchtigkeit [%]

- soilmoist08: Bodenfeuchtigkeit [%]

- soilmoist09: Bodenfeuchtigkeit [%]

- soilmoist10: Bodenfeuchtigkeit [%]

- soilmoist11: Bodenfeuchtigkeit [%]

- soilmoist12: Bodenfeuchtigkeit [%]

- soilmoist13: Bodenfeuchtigkeit [%]

- soilmoist14: Bodenfeuchtigkeit [%]

- soilmoist15: Bodenfeuchtigkeit [%]

- soilmoist16: Bodenfeuchtigkeit [%]

- soiltemp01: Bodentemperatur [°C]

- soiltemp02: Bodentemperatur [°C]

- soiltemp03: Bodentemperatur [°C]

- soiltemp04: Bodentemperatur [°C]

- soiltemp05: Bodentemperatur [°C]

- soiltemp06: Bodentemperatur [°C]

- soiltemp07: Bodentemperatur [°C]

- soiltemp08: Bodentemperatur [°C]

- soiltemp09: Bodentemperatur [°C]

- soiltemp10: Bodentemperatur [°C]

- soiltemp11: Bodentemperatur [°C]

- soiltemp12: Bodentemperatur [°C]

- soiltemp13: Bodentemperatur [°C]

- soiltemp14: Bodentemperatur [°C]

- soiltemp15: Bodentemperatur [°C]

- soiltemp16: Bodentemperatur [°C]

- solarradiation: UV Strahlung [uW/m2]

- storm_warning: Sturmwarnung [True/False]

- sun_duration_day: Sonnenstunden am aktuellen Tag *Berechnung im Plugin [h]

- sun_duration_hour: Sonnenminuten in der aktuellen Stunde *Berechnung im Plugin [min]

- sun_duration_month: Sonnenstunden im aktuellen Monat *Berechnung im Plugin [h]

- sun_duration_week: Sonnenstunden in der aktuellen Woche *Berechnung im Plugin [h]

- sun_duration_year: Sonnenstunden im aktuellen Jahr *Berechnung im Plugin [h]

- temp01: Temperatur [°C]

- temp02: Temperatur [°C]

- temp03: Temperatur [°C]

- temp04: Temperatur [°C]

- temp05: Temperatur [°C]

- temp06: Temperatur [°C]

- temp07: Temperatur [°C]

- temp08: Temperatur [°C]

- temp09: Temperatur [°C]

- temp10: Temperatur [°C]

- temp11: Temperatur [°C]

- temp12: Temperatur [°C]

- temp13: Temperatur [°C]

- temp14: Temperatur [°C]

- temp15: Temperatur [°C]

- temp16: Temperatur [°C]

- temp17: Temperatur am CO2 Sensor [°C]

- thunderstorm_warning: Gewitterwarnung [True/False]

- uvi: UV-Index [0-15]

- weather_forecast_txt: Beschreibung des Wetterausblicks als Text *Berechnung im Plugin [-]

- weather_txt: Beschreibung des aktuellen Wetters als Text *Berechnung im Plugin [-]

- weatherstation_warning: Warnung der Wetterstation [True/False]

- wh24_batt: Batteriestatus für Temperatur- und Feuchtigkeitssensor Außen WH24 [-]

- wh24_sig: Signalstärke für Temperatur- und Feuchtigkeitssensor Außen WH24 [1-6]

- wh25_batt: Batteriestatus für Temperatur-, Feuchtigkeits- und Drucksensor [-]

- wh25_sig: Signalstärke für Temperatur-, Feuchtigkeits- und Drucksensor [1-6]

- wh31_ch1_batt: Batteriestatus für Thermo-Hygrometer Kanal 1 [-]

- wh31_ch1_sig: Signalstärke für Thermo-Hygrometer Kanal 1 [1-6]

- wh31_ch2_batt: Batteriestatus für Thermo-Hygrometer Kanal 2 [-]

- wh31_ch2_sig: Signalstärke für Thermo-Hygrometer Kanal 2 [1-6]

- wh31_ch3_batt: Batteriestatus für Thermo-Hygrometer Kanal 3 [-]

- wh31_ch3_sig: Signalstärke für Thermo-Hygrometer Kanal 3 [1-6]

- wh31_ch4_batt: Batteriestatus für Thermo-Hygrometer Kanal 4 [-]

- wh31_ch4_sig: Signalstärke für Thermo-Hygrometer Kanal 4 [1-6]

- wh31_ch5_batt: Batteriestatus für Thermo-Hygrometer Kanal 5 [-]

- wh31_ch5_sig: Signalstärke für Thermo-Hygrometer Kanal 5 [1-6]

- wh31_ch6_batt: Batteriestatus für Thermo-Hygrometer Kanal 6 [-]

- wh31_ch6_sig: Signalstärke für Thermo-Hygrometer Kanal 6 [1-6]

- wh31_ch7_batt: Batteriestatus für Thermo-Hygrometer Kanal 7 [-]

- wh31_ch7_sig: Signalstärke für Thermo-Hygrometer Kanal 7 [1-6]

- wh31_ch8_batt: Batteriestatus für Thermo-Hygrometer Kanal 8 [-]

- wh31_ch8_sig: Signalstärke für Thermo-Hygrometer Kanal 8 [1-6]

- wh32_batt: Batteriestatus für Temperatur- und Feuchtigkeitssensor WH32 [-]

- wh32_sig: Signalstärke für Temperatur- und Feuchtigkeitssensor WH32 [1-6]

- wh40_batt: Batteriestatus für Regensensor [-]

- wh40_sig: Signalstärke für Regensensor [1-6]

- wh41_ch1_batt: Batteriestatus für Partikelsensor PM2.5 WH41 Kanal 1 [-]

- wh41_ch1_sig: Signalstärke für Partikelsensor PM2.5 WH41 Kanal 1 [1-6]

- wh41_ch2_batt: Batteriestatus für Partikelsensor PM2.5 WH41 Kanal 2 [-]

- wh41_ch2_sig: Signalstärke für Partikelsensor PM2.5 WH41 Kanal 2 [1-6]

- wh41_ch3_batt: Batteriestatus für Partikelsensor PM2.5 WH41 Kanal 3 [-]

- wh41_ch3_sig: Signalstärke für Partikelsensor PM2.5 WH41 Kanal 3 [1-6]

- wh41_ch4_batt: Batteriestatus für Partikelsensor PM2.5 WH41 Kanal 4 [-]

- wh41_ch4_sig: Signalstärke für Partikelsensor PM2.5 WH41 Kanal 4 [1-6]

- wh45_batt: Batteriestatus für Partikel- und CO2 Sensor WH45 [-]

- wh45_sig: Signalstärke für Partikel- und CO2 Sensor WH45 [1-6]

- wh51_ch1_batt: Batteriestatus für Bodenfeuchtesensor Kanal 1 [-]

- wh51_ch1_sig: Signalstärke für Bodenfeuchtesensor Kanal 1 [1-6]

- wh51_ch2_batt: Batteriestatus für Bodenfeuchtesensor Kanal 2 [-]

- wh51_ch2_sig: Signalstärke für Bodenfeuchtesensor Kanal 2 [1-6]

- wh51_ch3_batt: Batteriestatus für Bodenfeuchtesensor Kanal 3 [-]

- wh51_ch3_sig: Signalstärke für Bodenfeuchtesensor Kanal 3 [1-6]

- wh51_ch4_batt: Batteriestatus für Bodenfeuchtesensor Kanal 4 [-]

- wh51_ch4_sig: Signalstärke für Bodenfeuchtesensor Kanal 4 [1-6]

- wh51_ch5_batt: Batteriestatus für Bodenfeuchtesensor Kanal 5 [-]

- wh51_ch5_sig: Signalstärke für Bodenfeuchtesensor Kanal 5 [1-6]

- wh51_ch6_batt: Batteriestatus für Bodenfeuchtesensor Kanal 6 [-]

- wh51_ch6_sig: Signalstärke für Bodenfeuchtesensor Kanal 6 [1-6]

- wh51_ch7_batt: Batteriestatus für Bodenfeuchtesensor Kanal 7 [-]

- wh51_ch7_sig: Signalstärke für Bodenfeuchtesensor Kanal 7 [1-6]

- wh51_ch8_batt: Batteriestatus für Bodenfeuchtesensor Kanal 8 [-]

- wh51_ch8_sig: Signalstärke für Bodenfeuchtesensor Kanal 8 [1-6]

- wh55_ch1_batt: Batteriestatus für Leckagesensor Kanal 1 [-]

- wh55_ch1_sig: Signalstärke für Leckagesensor Kanal 1 [1-6]

- wh55_ch2_batt: Batteriestatus für Leckagesensor Kanal 2 [-]

- wh55_ch2_sig: Signalstärke für Leckagesensor Kanal 2 [1-6]

- wh55_ch3_batt: Batteriestatus für Leckagesensor Kanal 3 [-]

- wh55_ch3_sig: Signalstärke für Leckagesensor Kanal 3 [1-6]

- wh55_ch4_batt: Batteriestatus für Leckagesensor Kanal 4 [-]

- wh55_ch4_sig: Signalstärke für Leckagesensor Kanal 4 [1-6]

- wh57_batt: Batteriestatus für Blitzsensor WH57 [-]

- wh57_sig: Signalstärke für Blitzsensor WH57 [1-6]

- wh65_batt: Batteriestatus für Außensensor WH65 [-]

- wh65_sig: Signalstärke für Außensensor WH65 [1-6]

- wh68_batt: Batteriestatus für Wetterstation WS68 [-]

- wh68_sig: Signalstärke für Wetterstation WS68 [1-6]

- windchill: Wind Chill [°C]

- winddaymax: max. Windböengeschwindigkeit des Tages [m/s]

- winddir: Windrichtung [360°]

- winddir_avg10m: Durchschnittliche Windrichtung der letzten 10min *Berechnung im Plugin [360°]

- winddir_txt: Windrichtung als Richtungstext *Berechnung im Plugin [-]

- windspeed: Windgeschwindigkeit [m/s]

- windspeed_avg10m: Durchschnittliche Windgeschwindigkeit der letzten 10min *Berechnung im Plugin [m/s]

- windspeed_bft: Windgeschwindigkeit auf der Beaufort Skala *Berechnung im Plugin [-]

- windspeed_bft_txt: Windgeschwindigkeit auf der Beaufort Skala als Text *Berechnung im Plugin [-]

- wn26_batt: Batteriestatus für Pool Thermometer [-]

- wn26_sig: Signalstärke für Pool Thermometer [1-6]

- wn30_ch1_batt: Batteriestatus für Thermometer mit wasserdichtem Sensor WN30 Kanal 1 [-]

- wn30_ch1_sig: Signalstärke für Thermometer mit wasserdichtem Sensor WN30 Kanal 1 [1-6]

- wn30_ch2_batt: Batteriestatus für Thermometer mit wasserdichtem Sensor WN30 Kanal 2 [-]

- wn30_ch2_sig: Signalstärke für Thermometer mit wasserdichtem Sensor WN30 Kanal 2 [1-6]

- wn30_ch3_batt: Batteriestatus für Thermometer mit wasserdichtem Sensor WN30 Kanal 3 [-]

- wn30_ch3_sig: Signalstärke für Thermometer mit wasserdichtem Sensor WN30 Kanal 3 [1-6]

- wn30_ch4_batt: Batteriestatus für Thermometer mit wasserdichtem Sensor WN30 Kanal 4 [-]

- wn30_ch4_sig: Signalstärke für Thermometer mit wasserdichtem Sensor WN30 Kanal 4 [1-6]

- wn30_ch5_batt: Batteriestatus für Thermometer mit wasserdichtem Sensor WN30 Kanal 5 [-]

- wn30_ch5_sig: Signalstärke für Thermometer mit wasserdichtem Sensor WN30 Kanal 5 [1-6]

- wn30_ch6_batt: Batteriestatus für Thermometer mit wasserdichtem Sensor WN30 Kanal 6 [-]

- wn30_ch6_sig: Signalstärke für Thermometer mit wasserdichtem Sensor WN30 Kanal 6 [1-6]

- wn30_ch7_batt: Batteriestatus für Thermometer mit wasserdichtem Sensor WN30 Kanal 7 [-]

- wn30_ch7_sig: Signalstärke für Thermometer mit wasserdichtem Sensor WN30 Kanal 7 [1-6]

- wn30_ch8_batt: Batteriestatus für Thermometer mit wasserdichtem Sensor WN30 Kanal 8 [-]

- wn30_ch8_sig: Signalstärke für Thermometer mit wasserdichtem Sensor WN30 Kanal 8 [1-6]

- wn34_ch1_batt: Batteriestatus für Thermometer mit wasserdichtem Sensor WN34 Kanal 1 [-]

- wn34_ch1_sig: Signalstärke für Thermometer mit wasserdichtem Sensor WN34 Kanal 1 [1-6]

- wn34_ch2_batt: Batteriestatus für Thermometer mit wasserdichtem Sensor WN34 Kanal 2 [-]

- wn34_ch2_sig: Signalstärke für Thermometer mit wasserdichtem Sensor WN34 Kanal 2 [1-6]

- wn34_ch3_batt: Batteriestatus für Thermometer mit wasserdichtem Sensor WN34 Kanal 3 [-]

- wn34_ch3_sig: Signalstärke für Thermometer mit wasserdichtem Sensor WN34 Kanal 3 [1-6]

- wn34_ch4_batt: Batteriestatus für Thermometer mit wasserdichtem Sensor WN34 Kanal 4 [-]

- wn34_ch4_sig: Signalstärke für Thermometer mit wasserdichtem Sensor WN34 Kanal 4 [1-6]

- wn34_ch5_batt: Batteriestatus für Thermometer mit wasserdichtem Sensor WN34 Kanal 5 [-]

- wn34_ch5_sig: Signalstärke für Thermometer mit wasserdichtem Sensor WN34 Kanal 5 [1-6]

- wn34_ch6_batt: Batteriestatus für Thermometer mit wasserdichtem Sensor WN34 Kanal 6 [-]

- wn34_ch6_sig: Signalstärke für Thermometer mit wasserdichtem Sensor WN34 Kanal 6 [1-6]

- wn34_ch7_batt: Batteriestatus für Thermometer mit wasserdichtem Sensor WN34 Kanal 7 [-]

- wn34_ch7_sig: Signalstärke für Thermometer mit wasserdichtem Sensor WN34 Kanal 7 [1-6]

- wn34_ch8_batt: Batteriestatus für Thermometer mit wasserdichtem Sensor WN34 Kanal 8 [-]

- wn34_ch8_sig: Signalstärke für Thermometer mit wasserdichtem Sensor WN34 Kanal 8 [1-6]

- wn35_ch1_batt: Batteriestatus für Feuchtigkeitssensor für Pflanzen/Blätter WN35 Kanal 1 [-]

- wn35_ch1_sig: Signalstärke für Feuchtigkeitssensor für Pflanzen/Blätter WN35 Kanal 1 [1-6]

- wn35_ch2_batt: Batteriestatus für Feuchtigkeitssensor für Pflanzen/Blätter WN35 Kanal 2 [-]

- wn35_ch2_sig: Signalstärke für Feuchtigkeitssensor für Pflanzen/Blätter WN35 Kanal 2 [1-6]

- wn35_ch3_batt: Batteriestatus für Feuchtigkeitssensor für Pflanzen/Blätter WN35 Kanal 3 [-]

- wn35_ch3_sig: Signalstärke für Feuchtigkeitssensor für Pflanzen/Blätter WN35 Kanal 3 [1-6]

- wn35_ch4_batt: Batteriestatus für Feuchtigkeitssensor für Pflanzen/Blätter WN35 Kanal 4 [-]

- wn35_ch4_sig: Signalstärke für Feuchtigkeitssensor für Pflanzen/Blätter WN35 Kanal 4 [1-6]

- wn35_ch5_batt: Batteriestatus für Feuchtigkeitssensor für Pflanzen/Blätter WN35 Kanal 5 [-]

- wn35_ch5_sig: Signalstärke für Feuchtigkeitssensor für Pflanzen/Blätter WN35 Kanal 5 [1-6]

- wn35_ch6_batt: Batteriestatus für Feuchtigkeitssensor für Pflanzen/Blätter WN35 Kanal 6 [-]

- wn35_ch6_sig: Signalstärke für Feuchtigkeitssensor für Pflanzen/Blätter WN35 Kanal 6 [1-6]

- wn35_ch7_batt: Batteriestatus für Feuchtigkeitssensor für Pflanzen/Blätter WN35 Kanal 7 [-]

- wn35_ch7_sig: Signalstärke für Feuchtigkeitssensor für Pflanzen/Blätter WN35 Kanal 7 [1-6]

- wn35_ch8_batt: Batteriestatus für Feuchtigkeitssensor für Pflanzen/Blätter WN35 Kanal 8 [-]

- wn35_ch8_sig: Signalstärke für Feuchtigkeitssensor für Pflanzen/Blätter WN35 Kanal 8 [1-6]

- ws80_batt: Batteriestatus für Wetterstation WS80 [-]

- ws80_sig: Signalstärke für Wetterstation WS80 [1-6]

- ws90_batt: Batteriestatus für Wetterstation 7in1 WS90 [-]

- ws90_sig: Signalstärke für Wetterstation 7in1 WS90 [1-6]


Beispiele
---------

Hier können ausführlichere Beispiele und Anwendungsfälle beschrieben werden.


Web Interface
-------------

FOSHK Items
^^^^^^^^^^^

Das Webinterface zeigt die Items an, für die ein Foshk-Attribut konfiguriert ist.


FOSHK data
^^^^^^^^^^

Das Webinterface zeigt die verfügbaren Daten (Dict Key und Dict Value) an, die ausgelesen wurden.


FOSHK Settings
^^^^^^^^^^^^^^

Das Webinterface die Einstellung der Wetterstation an.


FOSHK Maintenance
^^^^^^^^^^^^^^^^^

Das Webinterface zeigt detaillierte Informationen über die im Plugin verfügbaren Daten an.
Dies dient der Maintenance bzw. Fehlersuche.
