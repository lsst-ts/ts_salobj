# This file is part of ts_salobj.
#
# Developed for the LSST Telescope and Site Systems.
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

__all__ = ["AckError", "AckTimeoutError", "ExpectedError",
           "index_generator", "make_done_future", "MAX_SAL_INDEX",
           "name_to_name_index", "current_tai", "tai_from_utc"]

import asyncio
import re
import time

import astropy.time
import astropy.units as u

from . import sal_enums

MAX_SAL_INDEX = (1 << 31) - 1

_NAME_REGEX = re.compile(r"(?P<name>[a-zA-Z_-]+)(:(?P<index>\d+))?$")


def _ackcmd_str(ackcmd):
    """Format an Ack as a string"""
    return f"(ackcmd private_seqNum={ackcmd.private_seqNum}, " \
        f"ack={sal_enums.as_salRetCode(ackcmd.ack)!r}, error={ackcmd.error}, result={ackcmd.result!r})"


class AckError(Exception):
    """Exception raised if a command fails.

    Parameters
    ----------
    msg : `str`
        Error message
    ackcmd : ``AckType``
        Command acknowledgement.
    """
    def __init__(self, msg, ackcmd):
        super().__init__(msg)
        self.ackcmd = ackcmd
        """Command acknowledgement."""

    def __str__(self):
        return f"msg={self.args[0]!r}, ackcmd={_ackcmd_str(self.ackcmd)}"

    def __repr__(self):
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


def index_generator(imin=1, imax=MAX_SAL_INDEX, i0=None):
    """Sequential index generator.

    Returns values i0, i0+1, i0+2, ..., max, min, min+1, ...

    Parameters
    ----------
    imin : `int` (optional)
        Minimum index (inclusive).
    imax : `int` (optional)
        Maximum index (inclusive).
    i0 : `int` (optional)
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
    def index_impl():
        index = i0 - 1
        while True:
            index += 1
            if index > imax:
                index = imin

            yield index

    return index_impl()


def make_done_future():
    future = asyncio.Future()
    future.set_result(None)
    return future


def name_to_name_index(name):
    """Parse a SAL component name of the form name[:index].

    Parameters
    ----------
    name : `str`
        Component name of the form ``name`` or ``name:index``.
        The default index is 0.

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
    index = match["index"]
    index = 0 if index is None else int(index)
    return (name, index)


def current_tai():
    """Return the current TAI in unix seconds.

    TODO: DM-21097: improve accuracy near a leap second transition.
    """
    return tai_from_utc(time.time())


def tai_from_utc(utc, format="unix"):
    """Return TAI in unix seconds, given UTC.

    Parameters
    ----------
    utc : `float` or `str`
        UTC time in the specified format.
    format : `str` or `None`
        Format of the UTC time, as an astropy.time format name,
        or `None` to have astropy guess.
    """
    astropy_utc = astropy.time.Time(utc, scale="utc", format=format)
    if format == "unix":
        utc_unix = utc
    else:
        utc_unix = astropy_utc.utc.unix
    try:
        dt_utc = astropy_utc.utc.to_datetime()
        dt_tai = astropy_utc.tai.to_datetime()
    except ValueError:
        # datetime cannot have 60 in the seconds field; back off a second
        astropy_utc = astropy_utc - 1 * u.second
        dt_utc = astropy_utc.utc.to_datetime()
        dt_tai = astropy_utc.tai.to_datetime()
    tai_minus_utc = (dt_tai - dt_utc).total_seconds()
    return utc_unix + tai_minus_utc
