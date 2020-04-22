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

__all__ = [
    "LOCAL_HOST",
    "MASTER_PRIORITY_ENV_VAR",
    "MAX_SAL_INDEX",
    "MJD_MINUS_UNIX_SECONDS",
    "SECONDS_PER_DAY",
    "AckError",
    "AckTimeoutError",
    "ExpectedError",
    "astropy_time_from_tai_unix",
    "index_generator",
    "make_done_future",
    "name_to_name_index",
    "current_tai",
    "tai_from_utc",
    "tai_from_utc_unix",
]

import asyncio
import concurrent
import logging
import re
import time

import astropy.time
import astropy.utils.iers
import astropy._erfa

from . import sal_enums

LOCAL_HOST = "127.0.0.1"

# Name of the environment variable that specifies the Master Priority.
# See the `Domain` doc string for details.
MASTER_PRIORITY_ENV_VAR = "OSPL_MASTER_PRIORITY"

# Maximum allowed SAL index (inclusive)
MAX_SAL_INDEX = (1 << 31) - 1

SECONDS_PER_DAY = 24 * 60 * 60

# MJD - unix seconds, in seconds
MJD_MINUS_UNIX_SECONDS = (
    astropy.time.Time(0, scale="utc", format="unix").utc.mjd * SECONDS_PER_DAY
)

JD_MINUS_MJD = 2400000.5

# Regex for a SAL componet name encoded as <name>[:<index>]
_NAME_REGEX = re.compile(r"(?P<name>[a-zA-Z_-]+)(:(?P<index>\d+))?$")

# When to update the leap second table, in days before expiration.
_LEAP_SECOND_TABLE_UPDATE_MARGIN_DAYS = 10


def _ackcmd_str(ackcmd):
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


def astropy_time_from_tai_unix(tai_unix):
    """Get astropy time from TAI in unix seconds.

    Parameters
    ----------
    tai_unix : `float`
        TAI time as unix seconds, e.g. the time returned by CLOCK_TAI
        on linux systems.
    """
    tai_mjd = (MJD_MINUS_UNIX_SECONDS + tai_unix) / SECONDS_PER_DAY
    return astropy.time.Time(tai_mjd, scale="tai", format="mjd")


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
    return tai_from_utc_unix(time.time())


def tai_from_utc(utc, format="unix"):
    """Return TAI in unix seconds, given UTC or any `astropy.time.Time`.

    Parameters
    ----------
    utc : `float`, `str` or `astropy.time.Time`
        UTC time in the specified format.
    format : `str` or `None`
        Format of the UTC time, as an `astropy.time` format name,
        or `None` to have astropy guess.
        Ignored if ``utc`` is an instance of `astropy.time.Time`.

    Returns
    -------
    tai_unix : `float`
        TAI time in unix seconds.

    Raises
    ------
    ValueError
        If the date is earlier than 1972 (which is before integer leap seconds)
        or within one day of the expiration date of the leap second table
        (which is automatically updated).

    Notes
    -----
    If you have UTC in floating point format and performance is an issue,
    please call `tai_from_utc_unix` to avoid the overhead of converting
    your time to an `astropy.time.Time`.

    This function will be deprecated once we upgrade to a version of
    ``astropy`` that supports TAI seconds. `tai_from_utc_unix` will remain.

    **Leap Seconds on the Day Before a Leap Second**

    This routine may not behave as you expect on the day before a leap second.
    Specify the date in ISO format if you want the correct answer.

    When UTC is expressed as unix time, Julian Day, or Modified Julian Day
    the answer is ambiguous, so the result can be off by up to a second from
    what you might expect. This function follows `astropy.time` and
    Standards of Fundamental Astronomy (SOFA) by shrinking or stretching
    unix time, Julian Day, and Modified Julian Day, as needed, so that
    exactly one day of 86400 seconds (of modified duration) elapses.
    This leads to TAI-UTC varying continuously on that day,
    instead of being an integer number of seconds.
    See https://github.com/astropy/astropy/issues/10055

    Also note that the behavior of the unix clock is not well defined
    on the day before a leap second. Both ntp and ptp can be configured
    to make the clock jump or smear in some way.
    https://developers.redhat.com/blog/2016/12/28/leap-second-i-belong-to-you/

    In theory the datetime format could work as well as ISO format,
    but in practice it does not. The `datetime` library does not handle
    leap seconds, and the datetime representation in `astropy.time`
    raises an exception if the date has 60 in the seconds field.

    On Linux an excellent way to get *current* TAI on the day of a leap second
    is to configure ntp or ptp to maintain a leap second table, then use
    the ``CLOCK_TAI`` clock (which is only available on Linux).

    The leap second table is automatically updated.
    """
    if isinstance(utc, float) and format == "unix":
        utc_unix = utc
    elif isinstance(utc, astropy.time.Time):
        utc_unix = utc.unix
    else:
        utc_unix = astropy.time.Time(utc, scale="utc", format=format).unix
    return tai_from_utc_unix(utc_unix)


def tai_from_utc_unix(utc_unix):
    """Return TAI in unix seconds, given UTC in unix seconds.

    Parameters
    ----------
    utc_unix : `float`
        UTC time in unix seconds.

    Returns
    -------
    tai_unix : `float`
        TAI time in unix seconds.

    Raises
    ------
    ValueError
        If the date is earlier than 1972 (which is before integer leap seconds)
        or within one day of the expiration date of the leap second table
        (which is automatically updated).

    Notes
    -----
    See the notes for `tai_from_utc` for information about
    possibly unexpected behavior on the day before a leap second.
    """
    # Use a local pointer, to prevent race conditions while the
    # global table is being replaced by `_update_leap_second_table`.
    utc_mjd = (utc_unix + MJD_MINUS_UNIX_SECONDS) / SECONDS_PER_DAY
    tai_jd1, tai_jd2 = astropy._erfa.utctai(JD_MINUS_MJD, utc_mjd)
    # I expect tai_jd1 to be exactly JD_MINUS_MJD, but in case not...
    tai_mjd = (tai_jd1 - JD_MINUS_MJD) + tai_jd2
    return tai_mjd * SECONDS_PER_DAY - MJD_MINUS_UNIX_SECONDS


async def _auto_update_leap_second_table_loop():
    """Automatically keep astropy's leap second table updated.

    Notes
    -----
    This should be started as a task when this module is loaded.

    The leap table will typically have an expiry date that is
    many months away, so it will be rare for auto update to occur.
    """
    log = logging.getLogger("lsst.ts.salobj.base")
    current_leap_second_table = astropy.utils.iers.LeapSeconds.open(
        file="erfa", cache=True
    )
    while True:
        expires_utc_unix = current_leap_second_table.expires.unix
        margin_sec = _LEAP_SECOND_TABLE_UPDATE_MARGIN_DAYS * SECONDS_PER_DAY
        update_at_utc_unix = expires_utc_unix - margin_sec
        update_delay_sec = update_at_utc_unix - time.time()
        log.info(
            f"_auto_update_leap_second_table_loop: sleep for {update_delay_sec:0.0f} seconds"
        )
        await asyncio.sleep(update_delay_sec)

        log.info(f"_auto_update_leap_second_table_loop: updating the leap second table")
        loop = asyncio.get_event_loop()
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            new_leap_second_table = await loop.run_in_executor(
                pool, astropy.utils.iers.LeapSeconds.auto_open
            )
            astropy._erfa.leap_seconds.set(new_leap_second_table)

        current_leap_second_table = new_leap_second_table


_AUTO_UPDATE_TASK = make_done_future()


def auto_update_leap_second_table():
    """Automatically keep astropy's leap second table updated.

    This code starts the auto update loop and returns.
    I don't know how to start a background task on import
    so I call this in Domain's constructor.

    If the task is already running then do nothing
    and return a Future that is already done.
    """
    global _AUTO_UPDATE_TASK
    if not _AUTO_UPDATE_TASK.done():
        return make_done_future()

    _AUTO_UPDATE_TASK = asyncio.create_task(_auto_update_leap_second_table_loop())
    return _AUTO_UPDATE_TASK
