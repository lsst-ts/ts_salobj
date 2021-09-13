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
    "MASTER_PRIORITY_ENV_VAR",
    "MAX_SAL_INDEX",
    "MJD_MINUS_UNIX_SECONDS",
    "SECONDS_PER_DAY",
    "AckError",
    "AckTimeoutError",
    "ExpectedError",
    "angle_diff",
    "angle_wrap_center",
    "angle_wrap_nonnegative",
    "astropy_time_from_tai_unix",
    "get_opensplice_version",
    "get_user_host",
    "index_generator",
    "make_done_future",
    "name_to_name_index",
    "current_tai",
    "tai_from_utc",
    "tai_from_utc_unix",
    "utc_from_tai_unix",
]

import asyncio
import getpass
import logging
import re
import socket
import subprocess
import threading
import time
import typing
import warnings

import astropy.time
import astropy.utils.iers
import astropy.coordinates
import astropy.units as u

from lsst.ts import utils
from . import sal_enums

LOCAL_HOST = "127.0.0.1"


# Name of the environment variable that specifies the Master Priority.
# See the `Domain` doc string for details.
MASTER_PRIORITY_ENV_VAR = "OSPL_MASTER_PRIORITY"

# Maximum allowed SAL index (inclusive)
MAX_SAL_INDEX = (1 << 31) - 1

# TODO DM-31660: Remove this deprecated wrapper
SECONDS_PER_DAY = utils.SECONDS_PER_DAY

# MJD - unix seconds, in seconds
# TODO DM-31660: Remove this deprecated wrapper
MJD_MINUS_UNIX_SECONDS = utils.MJD_MINUS_UNIX_SECONDS

# Regex for a SAL component name encoded as <name>[:<index>]
_NAME_REGEX = re.compile(r"(?P<name>[a-zA-Z_-][a-zA-Z0-9_-]*)(:(?P<index>\d+))?$")

# OpenSplice version; None until get_opensplice_version is first called.
_OPENSPLICE_VERSION: typing.Optional[str] = None

# A list of (utc_unix_seconds, TAI-UTC seconds);
# automatically updated by `_update_leap_second_table`.
_UTC_LEAP_SECOND_TABLE: typing.Optional[
    typing.Sequence[typing.Tuple[float, float]]
] = None
# A list of (tai_unix_seconds, TAI-UTC seconds);
# automatically updated by `_update_leap_second_table`.
_TAI_LEAP_SECOND_TABLE: typing.Optional[
    typing.Sequence[typing.Tuple[float, float]]
] = None
# A threading timer that schedules automatic update of the leap second table.
_LEAP_SECOND_TABLE_UPDATE_TIMER: typing.Optional[threading.Timer] = None
# When to update the leap second table, in days before expiration.
_LEAP_SECOND_TABLE_UPDATE_MARGIN_DAYS = 10

_MIDDLE_WRAP_ANGLE = astropy.coordinates.Angle(180, u.deg)
_POSITIVE_WRAP_ANGLE = astropy.coordinates.Angle(360, u.deg)


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


# TODO DM-31660: Remove this deprecated wrapper
def angle_diff(
    angle1: typing.Union[astropy.coordinates.Angle, float],
    angle2: typing.Union[astropy.coordinates.Angle, float],
) -> astropy.coordinates.Angle:
    """Deprecated version of lsst.ts.utils.angle_diff."""
    warnings.warn("Use lsst.ts.utils.angle_diff instead", DeprecationWarning)
    return utils.angle_diff(angle1, angle2)


# TODO DM-31660: Remove this deprecated wrapper
def angle_wrap_center(
    angle: typing.Union[astropy.coordinates.Angle, float]
) -> astropy.coordinates.Angle:
    """Deprecated version of lsst.ts.utils.angle_wrap_center."""
    warnings.warn("Use lsst.ts.utils.angle_wrap_center instead", DeprecationWarning)
    return utils.angle_wrap_center(angle)


# TODO DM-31660: Remove this deprecated wrapper
def angle_wrap_nonnegative(
    angle: typing.Union[astropy.coordinates.Angle, float]
) -> astropy.coordinates.Angle:
    """Deprecated version of lsst.ts.utils.angle_wrap_nonnegative."""
    warnings.warn(
        "Use lsst.ts.utils.angle_wrap_nonnegative instead", DeprecationWarning
    )
    return utils.angle_wrap_nonnegative(angle)


# TODO DM-31660: Remove this deprecated wrapper
def astropy_time_from_tai_unix(tai_unix: float) -> astropy.time.Time:
    """Get astropy time from TAI in unix seconds.

    Parameters
    ----------
    tai_unix : `float`
        TAI time as unix seconds, e.g. the time returned by CLOCK_TAI
        on linux systems.
    """
    warnings.warn(
        "Use lsst.ts.utils.astropy_time_from_tai_unix instead", DeprecationWarning
    )
    return utils.astropy_time_from_tai_unix(tai_unix)


_log = logging.getLogger("lsst.ts.salobj.base")


def get_opensplice_version() -> str:
    """Get the version of OpenSplice as a string.

    The form of the version string is:

        major.minor.build

    Where:

        * major: an integer
        * minor: an integer
        * build: an integer followed by a patch string, with no delimiter
          between the two.

    Example version: "6.9.190705OSS"

    If the version can not be determined then the returned value is "?".
    """
    global _OPENSPLICE_VERSION
    if _OPENSPLICE_VERSION is None:
        _OPENSPLICE_VERSION = "?"  # Fallback value
        try:
            result = subprocess.run(["idlpp", "-v"], capture_output=True)
            vers_str = result.stdout.decode()
            match = re.match(r"^[^:]+ +: +(\d+\.\d+\.\d+.*)\n$", vers_str)
            if match:
                _OPENSPLICE_VERSION = match.group(1)
            else:
                _log.warning(f"Could not parse {vers_str} as OpenSplice version")
        except Exception as e:
            _log.warning(f"Could not get OpenSplice version: {e}")
    return _OPENSPLICE_VERSION


def get_user_host() -> str:
    """Get the username and host as user@host

    host is the fully qualified domain name.
    """
    return f"{getpass.getuser()}@{socket.getfqdn()}"


def index_generator(
    imin: int = 1, imax: int = MAX_SAL_INDEX, i0: typing.Optional[int] = None
) -> typing.Generator[int, None, None]:
    """Sequential index generator.

    Returns values i0, i0+1, i0+2, ..., max, min, min+1, ...

    Parameters
    ----------
    imin : `int`, optional
        Minimum index (inclusive).
    imax : `int`, optional
        Maximum index (inclusive).
    i0 : `int`, optional
        Initial index; if None then use ``imin``.

    Raises
    ------
    ValueError
        If imin >= imax
    """
    imin = int(imin)
    imax = int(imax)
    i0 = imin if i0 is None else int(i0)
    if imax <= imin:
        raise ValueError(f"imin={imin} must be less than imax={imax}")
    if not imin <= i0 <= imax:
        raise ValueError(f"i0={i0} must be >= imin={imin} and <= imax={imax}")

    # define an inner generator and return that
    # in order to get immediate argument checking
    def index_impl() -> typing.Generator[int, None, None]:
        index = i0 - 1  # type: ignore
        while True:
            index += 1
            if index > imax:
                index = imin

            yield index

    return index_impl()


# TODO DM-31660: Remove this deprecated wrapper
def make_done_future() -> asyncio.Future:
    """Deprecated version of lsst.ts.utils.make_done_future."""
    warnings.warn("Use lsst.ts.utils.make_done_future instead", DeprecationWarning)
    return utils.make_done_future()


def name_to_name_index(name: str) -> typing.Tuple[str, int]:
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
    index = 0 if index_str is None else int(index_str)
    return (name, index)


def current_tai_from_utc() -> float:
    """Return the current TAI in unix seconds, using `tai_from_utc`."""
    return tai_from_utc_unix(time.time())


# TODO DM-31660: Remove this deprecated wrapper
def tai_from_utc(
    utc: typing.Union[float, str, astropy.time.Time],
    format: typing.Optional[str] = "unix",
) -> float:
    """Deprecated version of lsst.ts.utils.tai_from_utc."""
    warnings.warn("Use lsst.ts.utils.tai_from_utc instead", DeprecationWarning)
    return utils.tai_from_utc(utc=utc, format=format)


# TODO DM-31660: Remove this deprecated wrapper
def tai_from_utc_unix(utc_unix: float) -> float:
    """Deprecated version of lsst.ts.utils.tai_from_utc_unix."""
    warnings.warn("Use lsst.ts.utils.tai_from_utc_unix instead", DeprecationWarning)
    return utils.tai_from_utc_unix(utc_unix)


# TODO DM-31660: Remove this deprecated wrapper
def utc_from_tai_unix(tai_unix: float) -> float:
    """Deprecated version of lsst.ts.utils.utc_from_tai_unix."""
    warnings.warn("Use lsst.ts.utils.utc_from_tai_unix instead", DeprecationWarning)
    return utils.utc_from_tai_unix(tai_unix)


# TODO DM-31660: Remove this deprecated wrapper
def current_tai() -> float:
    """Deprecated version of lsst.ts.utils.current_tai."""
    warnings.warn("Use lsst.ts.utils.current_tai instead", DeprecationWarning)
    return utils.current_tai()
