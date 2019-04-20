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
           "index_generator", "make_done_future", "MAX_SAL_INDEX", "tai_from_utc"]

import asyncio

from . import sal_enums

MAX_SAL_INDEX = (1 << 31) - 1


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


def tai_from_utc(utc):
    """Return TAI unix seconds, given UTC in unix seconds.

    TODO DM-19791: replace this with code that uses ts_sal's solution

    This function is only intended for current time;
    it makes no attempt to be correct for historical dates.
    """
    return utc + 37
