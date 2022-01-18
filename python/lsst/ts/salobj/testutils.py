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
    "assertAnglesAlmostEqual",
    "assertRaisesAckError",
    "assertRaisesAckTimeoutError",
    "set_random_topic_subname",
    "set_random_lsst_dds_partition_prefix",  # Deprecated
    "modify_environ",
]

import base64
import contextlib
import os
import typing
import warnings

import astropy.coordinates

from lsst.ts import utils
from .base import AckError, AckTimeoutError


AngleOrDegType = typing.Union[astropy.coordinates.Angle, float]


# TODO DM-31660: Remove this deprecated wrapper
def assertAnglesAlmostEqual(
    angle1: AngleOrDegType, angle2: AngleOrDegType, max_diff: AngleOrDegType = 1e-5
) -> None:
    """Deprecated version of lsst.ts.utils.assert_angles_almost_equal."""
    warnings.warn(
        "Use lsst.ts.utils.assert_angles_almost_equal instead", DeprecationWarning
    )
    utils.assert_angles_almost_equal(angle1=angle1, angle2=angle2, max_diff=max_diff)


# TODO DM-31660: Remove this deprecated wrapper
@contextlib.contextmanager
def assertRaisesAckError(
    ack: typing.Optional[int] = None,
    error: typing.Optional[int] = None,
    result_contains: typing.Optional[str] = None,
) -> typing.Generator[None, None, None]:
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
    ack: typing.Optional[int] = None, error: typing.Optional[int] = None
) -> typing.Generator[None, None, None]:
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


def set_random_topic_subname() -> None:
    """Set a random value for environment variable LSST_TOPIC_SUBNAME

    Call this for each unit test method that uses SAL message passing,
    in order to avoid collisions with other tests. Note that pytest
    can run unit test methods in parallel.

    The random value is generated using the os.urandom, so that it cannot
    be seeded. This avoids collisions with previous test runs.
    """
    random_str = base64.urlsafe_b64encode(os.urandom(12)).decode().replace("=", "_")
    os.environ["LSST_TOPIC_SUBNAME"] = f"test_{random_str}"


def set_random_lsst_dds_partition_prefix() -> None:
    """Deprecated version of `set_random_topic_subname`."""
    warnings.warn("Use set_random_topic_subname instead", DeprecationWarning)
    set_random_topic_subname()


@contextlib.contextmanager
def modify_environ(**kwargs: typing.Any) -> typing.Generator[None, None, None]:
    """Deprecated version of lsst.ts.utils.modify_environ."""
    warnings.warn("Use lsst.ts.utils.modify_environ instead", DeprecationWarning)
    with utils.modify_environ(**kwargs):
        yield
