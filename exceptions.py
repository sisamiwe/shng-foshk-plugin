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
#                           Gateway Error classes
# ============================================================================


class InvalidApiResponse(Exception):
    """Exception raised when an API call response is invalid."""


class InvalidChecksum(Exception):
    """Exception raised when an API call response contains an invalid checksum."""


class GatewayIOError(Exception):
    """Exception raised when an input/output error with the Ecowitt Gateway is encountered."""


class UnknownApiCommand(Exception):
    """Exception raised when an unknown API command is used."""


class UnknownHttpCommand(Exception):
    """Exception raised when an unknown HTTP command was selected."""


class GatewayConnectError(Exception):
    """Exception raised when a connection to the gateway could not be established."""
