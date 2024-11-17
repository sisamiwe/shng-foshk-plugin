import math
from typing import Union
import lib.env as env


MAGNUS_COEFFICIENTS = dict(
    positive=dict(a=6.11213, b=17.5043, c=241.2),
    negative=dict(a=6.11153, b=22.4433, c=272.186),
    )
ZERO_CELSIUS_IN_KELVIN = 273.15                 # 0K = -273.15°C
M_WASSERDAMPF = 18.016                          # Molekulargewicht des Wasserdampfes in kg/kmol
S2B = 126.7                                     # 1W/m² = 126.7 lux
NA = 6.02214129e23                              # Avogadro-Konstante
KB = 1.3806488e-23                              # Boltzmann-Konstante
R = NA * KB * 1000                              # allgemeine Gaskonstante in J/(kmol*K) https://de.wikipedia.org/wiki/Gaskonstante
R_WATER_VAPOUR = 461.4                          # https://de.wikipedia.org/wiki/Gaskonstante
R_DRY_AIR = 287.058                             # specific gas constant of dry air
R_CO2 = 188.9                                   # specific gas constant of carbon dioxide
STEFAN_BOLTZMANN_CONSTANT = 5.670367e-8         # Stefan-Boltzmann constant for blackbody-radiation https://de.wikipedia.org/wiki/Stefan-Boltzmann-Gesetz
SOLAR_CONSTANT_TOA = 1367                       # solar constant at top of atmosphere https://de.wikipedia.org/wiki/Solarkonstante
DENSITY_WATER_0C = 999.87                       # density of water at 0°C and standard sea-level atmospheric https://water.usgs.gov/edu/density.html
SPECIFIC_HEAT_CAPACITY_DRY_AIR = 1005           # specific heat capacity of dry air at constant pressure https://de.wikipedia.org/wiki/Spezifische_Wärmekapazität
ENTHALPY_OF_VAPORIZATION_WATER_100C = 2257e3    # enthalpy of vaporization of liquid water https://en.wikipedia.org/wiki/Enthalpy_of_vaporization
EARTH_RADIUS = 6371000                          # Earth radius in meters


def get_dew_point(temperature: float, humidity_rel: float) -> float:
    """
    Calculate dew point temperature in °C

    The dew point is the temperature at which dew forms and is a measure of atmospheric moisture. It is the temperature to which air must be cooled
    at constant pressure and water content to reach saturation.

    Check wikipedia for more info: https://de-academic.com/dic.nsf/dewiki/478957

    Liegt ein Taupunkt bei Temperaturen unterhalb der Frostgrenze, so dass sich als Kondensat Eis bildet, wird ein solcher Taupunkt alternativ auch Frostpunkt,
    Eispunkt oder Reifpunkt genannt. Der Frostpunkt bezeichnet also Taupunkte an der Phasengrenze fest-gasförmig, welche im Bereich der Sublimation bzw.
    Resublimation liegen. Man bezeichnet daher auch die zugehörige Phasengrenzlinie, welche sich vom absoluten Nullpunkt bis zum Tripelpunkt erstreckt,
    als Sublimationskurve.

    This dew point calculator uses the Magnus-Tetens formula (Lawrence2005) that allows us to obtain accurate results (with an uncertainty of 0.35 °C) for temperatures ranging from -45 °C to 60 °C.

    :param temperature: current ambient temperature in °C
    :param humidity_rel: relative humidity in %
    :return:  dew point temperature in °C
    """

    magnus_coe = MAGNUS_COEFFICIENTS['positive'] if temperature > 0 else MAGNUS_COEFFICIENTS['negative']

    alpha = ((magnus_coe['b'] * temperature) / (magnus_coe['c'] + temperature)) + math.log(humidity_rel / 100.0)
    return round((magnus_coe['c'] * alpha) / (magnus_coe['b'] - alpha), 1)


def get_abs_hum(temperature: float, humidity_rel: float) -> float:
    """
    Return the absolute humidity in g/cm3 from the relative humidity in % and temperature (Celsius)

    :param temperature: temperature in °C
    :param humidity_rel: relative humidity in %
    :return: absolute humidity in g/cm3
    """

    return round(10 ** 5 * M_WASSERDAMPF / R * water_vapor_pressure(temperature, humidity_rel) / (temperature + ZERO_CELSIUS_IN_KELVIN), 1)


def get_windchill(temperature: float, wind_speed: float, units: str = 'imperial') -> Union[float, None]:
    """
    Compute the wind chill

    Wind-chill or windchill (popularly wind chill factor) is the lowering of body temperature due to the passing-flow of lower-temperature air.
    Wind chill numbers are always lower than the air temperature for values where the formula is valid.
    When the apparent temperature is higher than the air temperature, the heat index is used instead.
    Wind Chill Temperature is only defined for temperatures at or below 50 F and wind speeds above 3 mph.

    Check wikipedia for more info:
        https://en.wikipedia.org/wiki/Wind_chill

    Formula details:
        https://www.wpc.ncep.noaa.gov/html/windchill.shtml

    :param temperature: current ambient temperature in °Fahrenheit / °Celsius
    :param wind_speed: wind speed in miles/hour or km/h
    :return: the wind chill index
    :param units: unit system used for temperature (imperial: temperatur in °F and wind speed kn miles/hour; metric: temperature in °C and wind speed in km/h)
    """

    if units not in ['imperial', 'metric']:
        return

    if units == 'metric':
        T = env.c_to_f(temperature)
        V = env.kmh_to_mph(wind_speed)
    else:
        T = temperature
        V = wind_speed

    if T <= 50 and V >= 3:
        WCI = math.fsum([
            13.12,
            0.6215 * T,
            -11.37 * math.pow(V, 0.16),
            0.3965 * T * math.pow(V, 0.16),
        ])
    else:
        WCI = T

    if units == 'metric':
        return round(env.f_to_c(WCI), 1)

    return round(WCI, 1)


def get_heat_index(temperature: float, humidity_rel: float, units: str = 'imperial') -> Union[float, None]:
    """
    Compute the heat index using metric temperature in °Fahrenheit / °Celsius

    Heat Index or humiture or "feels like temperature" is an index that combines air temperature and relative humidity in an attempt to determine the
    human-perceived equivalent temperature.
    Heat Index is useful only when the temperature is minimally 80 F with a relative humidity of >= 40%.

    Check wikipedia for more info:
        https://en.wikipedia.org/wiki/Heat_index

    Formula details:
        http://www.wpc.ncep.noaa.gov/html/heatindex_equation.shtml

    :param temperature: current ambient temperature in °Fahrenheit / °Celsius
    :param humidity_rel: rel humidity
    :param units: unit system used for temperature (imperial: temperatur in °F; metric: temperature in °C)

    :return: the heat index
    """

    if units not in ['imperial', 'metric']:
        return

    if units == 'metric':
        temperature = env.c_to_f(temperature)

    T = temperature
    RH = humidity_rel
    c1 = -42.379
    c2 = 2.04901523
    c3 = 10.14333127
    c4 = -0.22475541
    c5 = -6.83783e-3
    c6 = -5.481717e-2
    c7 = 1.22874e-3
    c8 = 8.5282e-4
    c9 = -1.99e-6

    # calculate heat index using °Fahrenheit for temperature
    HI = 0.5 * (T + 61.0 + (T - 68.0) * 1.2 + RH * 0.094)

    if HI >= 80:
        HI = math.fsum([
            c1,
            c2 * T,
            c3 * RH,
            c4 * T * RH,
            c5 * T ** 2,
            c6 * RH ** 2,
            c7 * T ** 2 * RH,
            c8 * T * RH ** 2,
            c9 * T ** 2 * RH ** 2,
        ])
        if RH < 13 and 80 <= T <= 112:
            HI = HI - ((13 - RH) / 4) * math.sqrt((17 - math.fabs(T - 95.0)) / 17)
            if RH > 85 and 80 <= T <= 87:
                HI = HI + ((RH - 85) / 10) * ((87 - T) / 5)

    if units == 'metric':
        return round(env.f_to_c(HI), 1)

    return round(HI, 1)


def get_feels_like_temperature(temperature: float, humidity_rel: float, wind_speed: float, units: str = 'imperial') -> Union[float, None]:
    """Calculate Feels Like temperature based on NOAA.

    Logic:
    * Wind Chill: temperature <= 50 F and wind > 3 mph
    * Heat Index: temperature >= 80 F
    * Temperature as is: all other cases

    :param temperature: temperature value in Fahrenheit or Temp instance.
    :param humidity_rel: relative humidity in % (1-100)
    :param wind_speed: wind speed in mph
    :param units: unit system used for temperature (imperial: temperatur in °F and wind speed kn miles/hour; metric: temperature in °C and wind speed in km/h)
    :returns: Feels Like value
    """

    if units not in ['imperial', 'metric']:
        return

    if units == 'metric':
        T = env.c_to_f(temperature)
        V = env.kmh_to_mph(wind_speed)
    else:
        T = temperature
        V = wind_speed

    if T <= 50 and V > 3:
        # Wind Chill for low temp cases (and wind)
        FEELS_LIKE = get_windchill(T, V, units='imperial')
    elif T >= 80:
        # Heat Index for High temp cases
        FEELS_LIKE = get_heat_index(T, humidity_rel, units='imperial')
    else:
        FEELS_LIKE = temperature

    if units == 'metric':
        return round(env.f_to_c(FEELS_LIKE), 1)

    return round(FEELS_LIKE, 1)


def get_weather_now(pressure: float, lang: str = 'de') -> str:
    """
    Computes text for current weather condition

    :param pressure: current air pressure in hpa
    :param lang: acronym of language
    :return: weather description as string
    """

    _weather_now_de = ["stürmisch, Regen", "regnerisch", "wechselhaft", "sonnig", "trocken, Gewitter"]
    _weather_now_en = ["stormy, rainy", "rainy", "unstable", "sunny", "dry, thunderstorm"]
    _weather_now = _weather_now_de if lang == "de" else _weather_now_en

    if pressure <= 980:
        entry = 0  # stürmisch, Regen
    elif pressure <= 1000:
        entry = 1  # regnerisch
    elif pressure <= 1020:
        entry = 2  # wechselhaft
    elif pressure <= 1040:
        entry = 3  # sonnig
    else:
        entry = 4  # trocken, Gewitter

    return _weather_now[entry]


def get_weather_forecast(pressure_differance: float, lang: str = 'de') -> str:
    """
    Computes weather forecast based on changes for relative air pressure

    :param pressure_differance: pressure difference between now and 3 hours ago
    :param lang: acronym of language
    :return: weather forecast string
    """

    _weather_forecast_de = ["Sturm mit Hagel", "Regen/Unwetter", "regnerisch", "baldiger Regen", "gleichbleibend", "lange schön", "schön & labil", "Sturmwarnung"]
    _weather_forecast_en = ["storm with hail", "rain/storm", "rainy", "soon rain", "constant", "nice for a long time", "nice & unstable", "storm warning"]
    _weather_forecast = _weather_forecast_de if lang == "de" else _weather_forecast_en

    if pressure_differance <= -8:
        wproglvl = 0  # Sturm mit Hagel
    elif pressure_differance <= -5:
        wproglvl = 1  # Regen/Unwetter
    elif pressure_differance <= -3:
        wproglvl = 2  # regnerisch
    elif pressure_differance <= -0.5:
        wproglvl = 3  # baldiger Regen
    elif pressure_differance <= 0.5:
        wproglvl = 4  # gleichbleibend
    elif pressure_differance <= 3:
        wproglvl = 5  # lange schön
    elif pressure_differance <= 5:
        wproglvl = 6  # schön & labil
    else:
        wproglvl = 7  # Sturmwarnung

    return _weather_forecast[wproglvl]


def get_cloud_ceiling(temperature: float, humidity_rel: float) -> float:
    """
    Computes cloud ceiling (Wolkenuntergrenze/Konvektionskondensationsniveau)
    Faustformel für die Berechnung der Höhe der Wolkenuntergrenze von Quellwolken: Höhe in Meter = 122 x Spread (Taupunktdifferenz)

    :param temperature: outside temperatur in °C
    :param humidity_rel: rel humidity
    :return: cloud ceiling in meter
    """

    return int(round((temperature - get_dew_point(temperature, humidity_rel)) * 122, 1))


def get_aqi_from_pm25(pm25_value):
    if type(pm25_value) != float:
        return -9999
    elif pm25_value < 12.1:
        I_high = 50
        I_low = 0
        C_high = 12
        C_low = 0
    elif pm25_value < 35.5:
        I_high = 100
        I_low = 51
        C_high = 35.4
        C_low = 12.1
    elif pm25_value < 55.5:
        I_high = 150
        I_low = 101
        C_high = 55.4
        C_low = 35.5
    elif pm25_value < 150.5:
        I_high = 200
        I_low = 151
        C_high = 150.4
        C_low = 55.5
    elif pm25_value < 250.5:
        I_high = 300
        I_low = 201
        C_high = 250.4
        C_low = 150.5
    elif pm25_value < 350.5:
        I_high = 400
        I_low = 301
        C_high = 350.4
        C_low = 250.5
    else:
        I_high = 500
        I_low = 401
        C_high = 500.4
        C_low = 350.5
    return int(round((I_high - I_low) / (C_high - C_low) * (pm25_value - C_low) + I_low))


def get_aqi_from_pm10(pm10_value):
    if type(pm10_value) != float:
        return -9999
    elif pm10_value < 55:
        I_high = 50
        I_low = 0
        C_high = 54
        C_low = 0
    elif pm10_value < 155:
        I_high = 100
        I_low = 51
        C_high = 154
        C_low = 55
    elif pm10_value < 255:
        I_high = 150
        I_low = 101
        C_high = 254
        C_low = 155
    elif pm10_value < 355:
        I_high = 200
        I_low = 151
        C_high = 354
        C_low = 255
    elif pm10_value < 425:
        I_high = 300
        I_low = 201
        C_high = 424
        C_low = 355
    elif pm10_value < 505:
        I_high = 400
        I_low = 301
        C_high = 504
        C_low = 425
    else:
        I_high = 500
        I_low = 401
        C_high = 604
        C_low = 505
    return int(round((I_high - I_low) / (C_high - C_low) * (pm10_value - C_low) + I_low))


def get_aqi_level_from_aqi(aqi):  # US AQI
    level = 0
    try:
        if aqi <= 50:
            level = 1  # 0 to 50     Good                            Green
        elif aqi <= 100:
            level = 2  # 51 to 100   Moderate                        Yellow
        elif aqi <= 150:
            level = 3  # 101 to 150  Unhealthy for Sensitive Groups  Orange
        elif aqi <= 200:
            level = 4  # 151 to 200  Unhealthy                       Red
        elif aqi <= 300:
            level = 5  # 201 to 300  Very Unhealthy                  Purple
        else:
            level = 6  # 301 to 500  Hazardous                       Maroon
    except ValueError:
        pass
    return level


def get_co2_level(co2):  # according to https://www.breeze-technologies.de/de/blog/calculating-an-actionable-indoor-air-quality-index/ and https://sensebox.de/docs/CO2-Ampel_Lehrhandreichung.pdf
    level = 0
    try:
        if co2 <= 400:
            level = 1  # 0 to 400     Excellent                      Green
        elif co2 <= 1000:
            level = 2  # 400 to 1000  Fine, unbedenklich             Green
        elif co2 <= 1500:
            level = 3  # 1000 to 1500 Moderate, Lueften              Yellow
        elif co2 <= 2000:
            level = 4  # 1500 to 2000 Poor, Lueften!                 Red
        elif co2 <= 5000:
            level = 5  # 2000 to 5000 Very Poor, inakzeptabel        Purple
        else:
            level = 6  # from 5000    Severe                         Maroon
    except ValueError:
        pass
    return level


def saturated_water_vapor_pressure(temperature: float):
    """
    Compute saturated water vapor pressure (Sättigungsdampfdruck) in hPa

    :param temperature: temperature in °C
    :return: saturated water vapor pressure in hPa
    """

    magnus_coe = MAGNUS_COEFFICIENTS['positive'] if temperature > 0 else MAGNUS_COEFFICIENTS['negative']
    return magnus_coe['a'] * math.exp((magnus_coe['b'] * temperature) / (magnus_coe['c'] + temperature))


def water_vapor_pressure(temperature: float, humidity_rel: float):
    """
    Compute actual water vapor pressure (Dampfdruck) in hPa

    :param temperature: temperature in °C
    :param humidity_rel: humidity_rel in %
    :return: water vapor pressure in hPa
    """

    return humidity_rel / 100 * saturated_water_vapor_pressure(temperature)


def f_to_c(temp_f, dec: int = 1) -> float:
    """Convert fahrenheit to degree celsius"""

    return round(env.f_to_c(temp_f), dec)


def mph_to_ms(mph: float, dec: int = 1) -> float:
    """Convert mph to m/s"""

    return round(env.kmh_to_ms(env.mph_to_kmh(mph)), dec)


def in_to_hpa(f: float, dec: int = 2) -> float:
    """Convert inHg to hPa"""

    return round(float(f) / 0.02953, dec)


def hpa_to_in(f: float, dec: int = 1) -> float:
    """Convert hPa to inHg"""

    return round(float(f) / 33.87, dec)


def in_to_mm(f: float, dec: int = 2) -> float:
    """Convert in to mm"""

    return round(float(f) * 25.4, dec)


def get_distance(lat1, lon1, lat2, lon2) -> float:
    """
    Calculate distance between two geographical points
    """

    # deltas
    dlat = math.radians(lat2) - math.radians(lat1)
    dlon = math.radians(lon2) - math.radians(lon1)

    # calculate distance
    arch = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    arch_sin = 2 * math.asin(math.sqrt(arch))

    return EARTH_RADIUS * arch_sin


def solar_rad_to_brightness(solar_radiation: float, dec: int = 0) -> float:
    """Convert solar radiation in W/m² to Lux using 1W/m² = 126.7 lux"""
    return round(float(solar_radiation) * S2B, dec)


def condensation(temperature: float, humidity_rel: float) -> tuple:

    dew_point = get_dew_point(temperature, humidity_rel)

    if dew_point >= temperature:
        if temperature <= 0:
            return True, 'Reif'
        return True, 'Tau'
    return False, 'Nein'


def get_comfort_from_dewpoint(dew_point: float, lang: str = 'de') -> str:

    comfort_de = ('etwas zu trocken', 'trocken und komfortabel', 'stickig', 'unangenehm', 'mäßige Schwüle', 'starke Schwüle', 'extreme Schwüle')
    comfort_en = ('A bit dry for some', 'dry and comfortable', 'getting sticky', 'Unpleasant, lots of moisture in the air', 'oppressive, even dangerous')

    comfort = comfort_de if lang == "de" else comfort_en

    if dew_point < 10:
        return comfort[0]
    if dew_point < 16:
        return comfort[1]
    if dew_point < 17:
        return comfort[2]
    if dew_point < 20:
        return comfort[3]
    if dew_point >= 20:
        return comfort[4]


def get_thermophysiological_strain(feels_like_temp: float) -> tuple:
    """
    Thermisches Empfinden and thermophysiologische Beanspruchung for feels-like temperature

    :param feels_like_temp: feels like temperature in °C
    :return: thermophysiologische Beanspruchung als tuple(str, str)
    """

    if feels_like_temp <= -39:
        return 'sehr kalt', 'extremer Kältestress'
    if feels_like_temp <= -26:
        return 'kalt', 'starker Kältestress'
    if feels_like_temp <= -13:
        return 'kühl', 'mäßiger Kältestress'
    if feels_like_temp <= 20:
        return 'behaglich', 'Komfort möglich'
    if feels_like_temp <= 26:
        return 'leicht warm', 'schwache Wärmebelastung'
    if feels_like_temp <= 32:
        return 'warm', 'mäßige Wärmebelastung'
    if feels_like_temp <= 38:
        return 'heiß', 'starke Wärmebelastung'
    if feels_like_temp > 38:
        return 'sehr heiß', 'extreme Wärmebelastung'
