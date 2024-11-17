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
#                             Utility functions
# ============================================================================


from datetime import datetime, timezone
import re
import socket
import time
from typing import Union


def natural_sort_dict(source_dict: dict) -> dict:
    """
    Return a dict sorted naturally by key.
    """
    return dict(sorted(source_dict.items()))


def bytes_to_hex(iterable: bytes, separator: str = ' ', caps: bool = True) -> str:
    """Produce a hex string representation of a sequence of bytes."""

    try:
        hex_str = iterable.hex()
        if caps:
            hex_str = hex_str.upper()
        return separator.join(hex_str[i:i + 2] for i in range(0, len(hex_str), 2))
    except (TypeError, AttributeError):
        # TypeError - 'iterable' is not iterable
        # AttributeError - likely because separator is None either way we can't represent as a string of hex bytes
        return f"cannot represent '{iterable}' as hexadecimal bytes"


def byte_to_int(rawbytes: bytes, signed: bool = False) -> int:
    """
    Convert bytearray to value with respect to sign format

    :parameter rawbytes: Bytes to convert
    :parameter signed: True if result should be a signed int, False for unsigned

    """

    return int.from_bytes(rawbytes, byteorder='little', signed=signed)


def int_to_bytes(value: int, length: int = 1, signed: bool = False) -> bytes:
    """
    Convert value to bytearray with respect to defined length and sign format.
    Value exceeding limit set by length and sign will be truncated

    :parameter value: Value to convert
    :parameter length: number of bytes to create
    :parameter signed: True if result should be a signed int, False for unsigned
    :return: Converted value

    """

    value = value % (2 ** (length * 8))
    return value.to_bytes(length, byteorder='big', signed=signed)


def timestamp_to_string(ts: int, format_str: str = "%Y-%m-%d %H:%M:%S %Z") -> Union[str, None]:
    """Return a string formatted from the timestamp"""

    if ts is not None:
        return "%s (%d)" % (time.strftime(format_str, time.localtime(ts)), ts)
    else:
        return "******* N/A *******     (    N/A   )"


def ver_str_to_num(s: str) -> Union[None, int]:
    """Extract Version Number of Firmware out of String"""

    try:
        vpos = s.index("V")+1
        return int(s[vpos:].replace(".", ""))
    except ValueError:
        return


def to_int(value) -> int:
    try:
        return int(value)
    except (ValueError, TypeError):
        return 0


def to_float(value) -> float:
    """convert numeric str to float"""

    try:
        return float(value)
    except (ValueError, TypeError):
        return 0


def obfuscate_passwords(msg: str) -> str:
    """Hide password"""
    return re.sub(r'(PASSWORD|PASSKEY)=[^&]+', r'\1=XXXX', msg)


def is_port_valid(port: int) -> bool:
    """check if port is between 1 and 65535"""
    return True if 1 <= port <= 65535 else False


def is_port_in_use(port: int) -> bool:
    """Check if default port for tcp server is free and can be used"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(('127.0.0.1', port)) == 0


def utcdatetimestr_to_datetime(utc_datetime_str: str) -> Union[datetime, None]:
    """Decodes string in datetime format to datetime object"""
    try:
        dt = datetime.strptime(utc_datetime_str, "%Y-%m-%d+%H:%M:%S").replace(tzinfo=timezone.utc).astimezone(tz=None)
    except ValueError:
        return None
    else:
        return dt


def datetime_to_string(dt: datetime) -> str:
    """Converts datetime object to string"""
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def utc_to_local(utc_dt: datetime) -> datetime:
    return utc_dt.replace(tzinfo=timezone.utc).astimezone(tz=None)
