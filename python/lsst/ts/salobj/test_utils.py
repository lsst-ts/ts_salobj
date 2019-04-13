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

__all__ = ["assertRaisesAckError", "set_random_lsst_dds_domain"]

import contextlib
import os
import random
import socket
import time

from .base import AckError


@contextlib.contextmanager
def assertRaisesAckError(ack=None, error=None):
    """Assert that code raises a salobj.AckError

    Parameters
    ----------
    ack : `int` (optional)
        Ack code, typically a SAL__CMD_<x> constant.
        If None then the ack code is not checked.
    error : `int`
        Error code. If None then the error value is not checked.
    """
    try:
        yield
        raise AssertionError("AckError not raised")
    except AckError as e:
        if ack is not None and e.ack.ack != ack:
            raise AssertionError(f"ack.ack={e.ack.ack} instead of {ack}")
        if error is not None and e.ack.error != error:
            raise AssertionError(f"ack.error={e.ack.error} instead of {error}")


def set_random_lsst_dds_domain():
    """Set a random value for environment variable LSST_DDS_DOMAIN

    Call this for each unit test method that uses SAL message passing,
    in order to avoid collisions with other tests. Note that pytest
    can run unit test methods in parallel.

    The set name will contain the hostname and current time
    as well as a random integer.
    """
    hostname = socket.gethostname()
    curr_time = time.time()
    random_int = random.randint(0, 999999)
    os.environ["LSST_DDS_DOMAIN"] = f"Test-{hostname}-{curr_time}-{random_int}"
