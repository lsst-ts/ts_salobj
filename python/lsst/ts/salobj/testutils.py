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
    "assertRaisesAckError",
    "assertRaisesAckTimeoutError",
    "set_test_topic_subname",
    "set_random_lsst_dds_partition_prefix",
]

import base64
import contextlib
import os
from collections.abc import Generator
import warnings
from collections.abc import Generator

import astropy.coordinates

from .base import AckError, AckTimeoutError

AngleOrDegType = astropy.coordinates.Angle | float


@contextlib.contextmanager
def assertRaisesAckError(
    ack: int | None = None,
    error: int | None = None,
    result_contains: str | None = None,
) -> Generator[None, None, None]:
    """Assert that code raises a salobj.AckError

    Parameters
    ----------
    ack : `int`, optional
        Ack code, almost always a `SalRetCode` ``CMD_<x>`` constant.
        If None then the ack code is not checked.
    error : `int`, optional
        Error code. If None then the error value is not checked.
    result_contains : `str`, optional
        If not None then the result value must contain this string.
    """
    try:
        yield
        raise AssertionError("AckError not raised")
    except AckError as e:
        if ack is not None and e.ackcmd.ack != ack:
            raise AssertionError(f"ackcmd.ack={e.ackcmd.ack} instead of {ack}")
        if error is not None and e.ackcmd.error != error:
            raise AssertionError(f"ackcmd.error={e.ackcmd.error} instead of {error}")
        if result_contains is not None and result_contains not in e.ackcmd.result:
            raise AssertionError(
                f"ackcmd.result={e.ackcmd.result} does not contain {result_contains}"
            )


@contextlib.contextmanager
def assertRaisesAckTimeoutError(
    ack: int | None = None, error: int | None = None
) -> Generator[None, None, None]:
    """Assert that code raises a salobj.AckTimeoutError

    Parameters
    ----------
    ack : `int`, optional
        Ack code of the last ack seen, almost always a `SalRetCode`
        ``CMD_<x>`` constant. If None then the ack code is not checked.
    error : `int`, optional
        Error code. If None then the error value is not checked.
    """
    try:
        yield
        raise AssertionError("AckError not raised")
    except AckTimeoutError as e:
        if ack is not None and e.ackcmd.ack != ack:
            raise AssertionError(f"ackcmd.ack={e.ackcmd.ack} instead of {ack}")
        if error is not None and e.ackcmd.error != error:
            raise AssertionError(f"ackcmd.error={e.ackcmd.error} instead of {error}")


def set_test_topic_subname(randomize: bool = False) -> None:
    """Set a test value for environment variable LSST_TOPIC_SUBNAME

    Parameters
    ----------
    randomize :  `bool`
        If set to `True` create a random topic subname.

    Notes
    -----
    Call this for each unit test method that uses SAL message passing,
    in order to avoid collisions with other tests. Note that pytest
    can run unit test methods in parallel.

    By default (randomize=False), the topic subname value is generated using
    the os.getpid(). Since parallel tests in pytest uses different processes,
    this avoids collisions with previous test runs and reduces the number of
    schema and topics creation.

    If a more fine grained isolation mechanism is needed one can pass
    randomize=True, which will generate a random unique topic subname using
    os.urandom.
    """
    pid = os.getpid()
    length = (pid.bit_length() + 7) // 8
    root_value = (
        pid.to_bytes(length=length, byteorder="big")
        if not randomize
        else os.urandom(12)
    )

    topic_subname_suffix = (
        base64.urlsafe_b64encode(root_value).decode().replace("=", "")
    )
    os.environ["LSST_TOPIC_SUBNAME"] = f"test_{topic_subname_suffix}"


def set_random_lsst_dds_partition_prefix() -> None:
    """A deprecated synonym for set_random_topic_subname."""
    warnings.warn("Call set_random_topic_subname instead", DeprecationWarning)
    set_test_topic_subname()
