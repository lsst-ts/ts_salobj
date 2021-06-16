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
import bisect
import datetime
import getpass
import logging
import math
import re
import socket
import subprocess
import threading
import time

import astropy.time
import astropy.utils.iers
import astropy.coordinates
import astropy.units as u

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

# Regex for a SAL component name encoded as <name>[:<index>]
_NAME_REGEX = re.compile(r"(?P<name>[a-zA-Z_-][a-zA-Z0-9_-]*)(:(?P<index>\d+))?$")

# OpenSplice version; None until get_opensplice_version is first called.
_OPENSPLICE_VERSION = None

# A list of (utc_unix_seconds, TAI-UTC seconds);
# automatically updated by `_update_leap_second_table`.
_UTC_LEAP_SECOND_TABLE = None
# A list of (tai_unix_seconds, TAI-UTC seconds);
# automatically updated by `_update_leap_second_table`.
_TAI_LEAP_SECOND_TABLE = None
# A threading timer that schedules automatic update of the leap second table.
_LEAP_SECOND_TABLE_UPDATE_TIMER = None
# When to update the leap second table, in days before expiration.
_LEAP_SECOND_TABLE_UPDATE_MARGIN_DAYS = 10

_MIDDLE_WRAP_ANGLE = astropy.coordinates.Angle(180, u.deg)
_POSITIVE_WRAP_ANGLE = astropy.coordinates.Angle(360, u.deg)


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
    ackcmd : ``AckCmdType``
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


def angle_diff(angle1, angle2):
    """Return angle1 - angle2 wrapped into the range [-180, 180) deg.

    Parameters
    ----------
    angle1 : `astropy.coordinates.Angle` or `float`
        Angle 1; if a float then in degrees
    angle2 : `astropy.coordinates.Angle` or `float`
        Angle 2; if a float then in degrees

    Returns
    -------
    diff : `astropy.coordinates.Angle`
        angle1 - angle2 wrapped into the range -180 <= diff < 180 deg.
    """
    return angle_wrap_center(
        astropy.coordinates.Angle(angle1, u.deg)
        - astropy.coordinates.Angle(angle2, u.deg)
    )


def angle_wrap_center(angle):
    """Return an angle wrapped into the range [-180, 180) deg.

    Parameters
    ----------
    angle : `astropy.coordinates.Angle` or `float`
        Angle; if a float then in degrees

    Returns
    -------
    wrapped : `astropy.coordinates.Angle`
        angle wrapped into the range -180 <= wrapped < 180 deg.
    """
    return astropy.coordinates.Angle(angle, u.deg).wrap_at(_MIDDLE_WRAP_ANGLE)


def angle_wrap_nonnegative(angle):
    """Return an angle wrapped into the range [0, 360) deg.

    Parameters
    ----------
    angle : `astropy.coordinates.Angle` or `float`
        Angle; if a float then in degrees

    Returns
    -------
    wrapped : `astropy.coordinates.Angle`
        angle wrapped into the range 0 <= wrapped < 360 deg.
    """
    return astropy.coordinates.Angle(angle, u.deg).wrap_at(_POSITIVE_WRAP_ANGLE)


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


def get_opensplice_version():
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


def get_user_host():
    """Get the username and host as user@host

    host is the fully qualified domain name.
    """
    return f"{getpass.getuser()}@{socket.getfqdn()}"


def index_generator(imin=1, imax=MAX_SAL_INDEX, i0=None):
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


def current_tai_from_utc():
    """Return the current TAI in unix seconds, using `tai_from_utc`."""
    return tai_from_utc_unix(time.time())


def tai_from_utc(utc, format="unix"):
    """Return TAI in unix seconds, given UTC or any `astropy.time.Time`.

    Smear UTC time out evenly on the day before a leap second,
    so the day has exactly 86400 UTC seconds (of modified duration).
    Thus the difference between TAI and UTC is not an integer on those days.
    See the notes for more information.

    Because of the smearing, this function should only be used for scalar
    measures of UTC, such as unix seconds, Julian Date or Modified Julian Date.
    It should not be used for ISO-formatted date strings.

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
    **Smearing During the Day Before a Leap Second**

    On the day before a leap second this routine follows `astropy.time` and
    Standards of Fundamental Astronomy (SOFA): by "smearing" UTC over the
    whole day, so the day has exactly 86400 seconds of modified duration.
    This leads to TAI-UTC varying continuously on that day,
    instead of being an integer number of seconds.
    See https://github.com/astropy/astropy/issues/10055

    The reason for this smearing is to make the function single-valued
    and continuous near a leap second. This avoids two issues when computing
    TAI from a scalar value of UTC during a leap second; depending
    on the sign of the leap second:

    * In one case there is a one second period during which
      there are two possible values of TAI, both equally valid.
    * In the other case there is a one second gap in TAI.

    To convert UTC to TAI without this smearing: use astropy.time
    to convert the value, and express the UTC date as an ISO string.
    ISO format supports 60 <= seconds < 61, whereas scalar representations
    cannot. Do not use datetime format because neither the datetime library
    nor astropy.time support datetimes with 60 <= seconds < 61.

    On Linux an excellent way to get *current* TAI on the day of a leap second
    is to configure ntp or ptp to maintain a leap second table, then use
    the ``CLOCK_TAI`` clock (which is only available on Linux).
    If you do this then you must configure npt or ptp to make the realtime
    clock jump at a leap second (rather than smearing over some duration),
    because on Linux the difference between ``REALTIME_CLOCK`` and
    ``CLOCK_TAI`` is always an integer number of seconds.

    **Updating the Leap Second Table**

    The leap second table is automatically updated in the background
    (though updates are very infrequent).
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

    Smear UTC time out evenly on the day before a leap second,
    so the day has exactly 86400 UTC seconds (of modified duration).
    Thus the difference between TAI and UTC is not an integer on those days.
    See the notes for `tai_from_utc` for more information.

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
    """
    # Use a local pointer, to prevent race conditions while the
    # global table is being replaced by `_update_leap_second_table`.
    global _UTC_LEAP_SECOND_TABLE
    utc_leap_second_table = _UTC_LEAP_SECOND_TABLE
    if utc_unix > utc_leap_second_table[-1][0] - SECONDS_PER_DAY:
        raise ValueError(
            f"{utc_unix} > {utc_leap_second_table[-1][0] - SECONDS_PER_DAY} = "
            "utc_unix expiry date of leap second table - 1 day"
        )
    i = bisect.bisect(utc_leap_second_table, (utc_unix, math.inf))
    if i == 0:
        raise ValueError(
            f"{utc_unix} < start of integer leap seconds "
            f"= {utc_leap_second_table[0][0]}"
        )
    utc0, tai_minus_utc0 = utc_leap_second_table[i - 1]
    utc1, tai_minus_utc1 = utc_leap_second_table[i]
    if utc_unix + SECONDS_PER_DAY > utc1:
        # utc_unix is within the day before a leap second.
        # Smear the UTC time uniformly over the whole day,
        # so that there are exactly 86400 seconds in the day.
        utc_days = utc_unix / SECONDS_PER_DAY
        frac_day = utc_days - math.floor(utc_days)
        tai_minus_utc = tai_minus_utc0 + (tai_minus_utc1 - tai_minus_utc0) * frac_day
    else:
        tai_minus_utc = tai_minus_utc0
    return utc_unix + tai_minus_utc


def utc_from_tai_unix(tai_unix):
    """Return UTC in unix seconds, given TAI in unix seconds.

    The difference is always an integer. Thus this is not the inverse
    of `tai_from_utc_unix`, because that function smears UTC time
    on the day before a leap second.

    Parameters
    ----------
    tai_unix : `float`
        TAI time in unix seconds.

    Returns
    -------
    utc_unix : `float`
        UTC time in unix seconds.

    Raises
    ------
    ValueError
        If the date is earlier than 1972 (which is before integer leap seconds)
        or within one day of the expiration date of the leap second table
        (which is automatically updated).
    """
    # Use a local pointer, to prevent race conditions while the
    # global table is being replaced by `_update_leap_second_table`.
    global _TAI_LEAP_SECOND_TABLE
    tai_leap_second_table = _TAI_LEAP_SECOND_TABLE
    if tai_unix > tai_leap_second_table[-1][0]:
        raise ValueError(
            f"{tai_unix} > {tai_leap_second_table[-1][0]} = "
            "tai_unix expiry date of leap second table"
        )
    i = bisect.bisect(tai_leap_second_table, (tai_unix, math.inf))
    if i == 0:
        raise ValueError(
            f"{tai_unix} < start of integer leap seconds "
            f"= {tai_leap_second_table[0][0]}"
        )
    tai_minus_utc = tai_leap_second_table[i - 1][1]
    return tai_unix - tai_minus_utc


_log = logging.getLogger("lsst.ts.salobj.base")


def _update_leap_second_table():
    """Update the leap second table.

    Notes
    -----
    This should be called when this module is loaded.
    When called, it obtains the current table from AstroPy,
    then schedules a background (daemon) thread to call itself
    to update the table ``_LEAP_SECOND_TABLE_UPDATE_MARGIN_DAYS``
    before the table expires.

    The leap table will typically have an expiry date that is
    many months away, so it will be rare for auto update to occur.
    """
    _log.info("Update leap second table")
    global _UTC_LEAP_SECOND_TABLE
    global _TAI_LEAP_SECOND_TABLE
    global _LEAP_SECOND_TABLE_UPDATE_TIMER
    ap_table = astropy.utils.iers.LeapSeconds.auto_open()
    utc_leap_second_table = [
        (
            astropy.time.Time(
                datetime.datetime(row["year"], row["month"], 1, 0, 0, 0), scale="utc"
            ).unix,
            float(row["tai_utc"]),
        )
        for row in ap_table
        if row["year"] >= 1972
    ]
    expiry_date_utc_unix = ap_table.expires.unix
    last_tai_utc = utc_leap_second_table[-1][1]
    utc_leap_second_table.append((expiry_date_utc_unix, last_tai_utc))
    tai_leap_second_table = [
        (unix_seconds + tai_utc, tai_utc)
        for (unix_seconds, tai_utc) in utc_leap_second_table
    ]
    _UTC_LEAP_SECOND_TABLE = utc_leap_second_table
    _TAI_LEAP_SECOND_TABLE = tai_leap_second_table

    update_date = (
        expiry_date_utc_unix - _LEAP_SECOND_TABLE_UPDATE_MARGIN_DAYS * SECONDS_PER_DAY
    )
    update_delay = update_date - time.time()
    if _LEAP_SECOND_TABLE_UPDATE_TIMER is not None:
        _LEAP_SECOND_TABLE_UPDATE_TIMER.cancel()
    _log.debug(
        f"Schedule a timer to call _update_leap_second_table in {update_delay} seconds"
    )
    _LEAP_SECOND_TABLE_UPDATE_TIMER = threading.Timer(
        update_delay, _update_leap_second_table
    )
    _LEAP_SECOND_TABLE_UPDATE_TIMER.daemon = True
    _LEAP_SECOND_TABLE_UPDATE_TIMER.start()


_update_leap_second_table()


def _get_current_tai_function():
    """Return a function returns the current TAI in unix seconds
    (and which takes no arguments).

    If ``time.clock_gettime(CLOCK_TAI)`` is available (only on linux)
    and gives a reasonable answer, then return that. Otherwise return
    `current_tai_from_utc`, which works on all operating systems, but is
    slower and can be off by up to a second on the day of a leap second.
    """
    if not hasattr(time, "clock_gettime"):
        _log.info(
            "current_tai uses current_tai_from_utc; your operating system does not support clock_gettime"
        )
        return current_tai_from_utc

    try:
        # The clock constant CLOCK_TAI will be available in Python 3.9;
        # meanwhile, the standard value 11 works just fine.
        clock_tai = getattr(time, "CLOCK_TAI", 11)

        def system_tai():
            """Return current TAI in unix seconds, using clock_gettime."""
            return time.clock_gettime(clock_tai)

        # Call current_tai_from_utc once before using the returned value,
        # to make sure the leap second table is downloaded.
        current_tai_from_utc()
        tslow = current_tai_from_utc()
        tfast = system_tai()
        time_error = tslow - tfast
        # Give margin for being on the day of a leap second
        # (max error is 1 second)
        if abs(time_error) > 1.1:
            _log.warning(
                "current_tai uses current_tai_from_utc; "
                f"clock_gettime(CLOCK_TAI) is off by {time_error:0.1f} seconds"
            )
            return current_tai_from_utc

        _log.info("current_tai uses the system TAI clock")
        return system_tai
    except Exception as e:
        _log.warning(
            f"current_tai uses current_tai_from_utc; error determining if clock_gettime is usable: {e}"
        )
        return current_tai_from_utc


current_tai = _get_current_tai_function()
