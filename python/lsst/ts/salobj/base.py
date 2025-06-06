# This file is part of ts_salobj.
#
# Developed for the Rubin Observatory Telescope and Site System.
# This product includes software developed by the LSST Project
# (https://www.lsst.org).
# See the COPYRIGHT file at the top-level directory of this distribution
# for details of code ownership.
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

__all__ = [
    "LOCAL_HOST",
    "MAX_SAL_INDEX",
    "AckError",
    "AckTimeoutError",
    "ExpectedError",
    "get_user_host",
    "name_to_name_index",
    "WildcardIndexError",
]

import getpass
import re
import socket
import typing

from lsst.ts.xml import sal_enums

LOCAL_HOST = "127.0.0.1"

# Maximum allowed SAL index (inclusive)
MAX_SAL_INDEX = (1 << 31) - 1

# Regex for a SAL component name encoded as <name>[:<index>]
_NAME_REGEX = re.compile(r"(?P<name>[a-zA-Z_-][a-zA-Z0-9_-]*)(:(?P<index>\d+|\*))?$")


def _ackcmd_str(ackcmd: typing.Any) -> str:
    """Format an Ack as a string"""
    return (
        f"(ackcmd private_seqNum={ackcmd.private_seqNum}, "
        f"ack={sal_enums.as_salRetCode(ackcmd.ack)!r}, error={ackcmd.error}, result={ackcmd.result!r})"
    )


class AckError(Exception):
    """Exception raised if a command fails.

    Parameters
    ----------
    msg : `str`
        Error message
    ackcmd : ``AckCmdType``
        Command acknowledgement.
    """

    def __init__(self, msg: str, ackcmd: typing.Any) -> None:
        super().__init__(msg)
        self.ackcmd = ackcmd
        """Command acknowledgement."""

    def __str__(self) -> str:
        return f"msg={self.args[0]!r}, ackcmd={_ackcmd_str(self.ackcmd)}"

    def __repr__(self) -> str:
        return f"{type(self).__name__}({self!s})"


class AckTimeoutError(AckError):
    """Exception raised if waiting for a command acknowledgement times out.

    The ``ackcmd`` attribute is the last ackcmd seen.
    If no command acknowledgement was received then
    the ack code will be `SalRetCode.CMD_NOACK`.
    """

    pass


class ExpectedError(Exception):
    """Report an error that does not benefit from a traceback.

    For example, a command is invalid in the current state.
    """

    pass


def get_user_host() -> str:
    """Get the username and host as user@host

    host is the fully qualified domain name.
    """
    return f"{getpass.getuser()}@{socket.getfqdn()}"


class WildcardIndexError(ValueError):
    """Custom exception to signify that the index is a wildcard ('*')."""

    def __init__(self, name: str):
        super().__init__(f"The index for component '{name}' is a wildcard ('*').")
        self.name = name


def name_to_name_index(name: str) -> tuple[str, int]:
    """Parse a SAL component name of the form name[:index].

    Parameters
    ----------
    name : `str`
        Component name of the form ``name`` or ``name:index``.
        The default index is 0.

    Returns
    -------
    name_int : `tuple`
        A tuple containing the component name (str) and index (int).
        The index is 0 if the input did not specify.

    Raises
    ------
    ValueError
        If the name cannot be parsed.

    Notes
    -----
    Examples:

    * ``"Script" -> ("Script", 0)``
    * ``"Script:0" -> ("Script", 0)``
    * ``"Script:15" -> ("Script", 15)``
    * ``" Script:15" -> raise ValueError (leading space)``
    * ``"Script:15 " -> raise ValueError (trailing space)``
    * ``"Script:" -> raise ValueError (colon with no index)``
    * ``"Script:zero" -> raise ValueError (index not an integer)``
    """
    match = _NAME_REGEX.match(name)
    if not match:
        raise ValueError(f"name {name!r} is not of the form 'name' or 'name:index'")
    name = match["name"]
    index_str = match["index"]

    if index_str is None:
        return name, 0  # Default index is 0
    elif index_str == "*":
        raise WildcardIndexError(name)  # Raise custom exception for wildcard
    else:
        return name, int(index_str)
