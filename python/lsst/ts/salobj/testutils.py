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
    "assert_black_formatted",
    "set_random_lsst_dds_domain",  # Deprecated
    "set_random_lsst_dds_partition_prefix",
    "modify_environ",
]

import contextlib
import os
import random
import socket
import subprocess
import time
import unittest.mock
import typing
import warnings

import astropy.coordinates
import astropy.units as u

from . import type_hints
from .base import AckError, AckTimeoutError, angle_diff


AngleOrDegType = typing.Union[astropy.coordinates.Angle, float]


def assertAnglesAlmostEqual(
    angle1: AngleOrDegType, angle2: AngleOrDegType, max_diff: AngleOrDegType = 1e-5
) -> None:
    """Raise AssertionError if angle1 and angle2 are too different,
    ignoring wrap.

    Parameters
    ----------
    angle1 : `astropy.coordinates.Angle` or `float`
        Angle 1; if a float then in degrees
    angle2 : `astropy.coordinates.Angle` or `float`
        Angle 2; if a float then in degrees
    max_diff : `astropy.coordinates.Angle` or `float`
        Maximum allowed difference; if a float then in degrees

    Raises
    ------
    AssertionError
        If `angle_diff` of angle1 and angle2 exceeds max_diff.
    """
    diff = abs(angle_diff(angle1, angle2))
    if diff > astropy.coordinates.Angle(max_diff, u.deg):
        raise AssertionError(f"{angle1} and {angle2} differ by {diff} > {max_diff}")


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


def assert_black_formatted(dirpath: type_hints.PathType) -> None:
    """Assert that all Python files in a directory, or any subdirectory
    of that directory, are formatted with black.

    To call this from a unit test (see ``tests/test_black.py``)::

        salobj.assert_black_formatted(pathlib.Path(__file__).parents[1])

    Parameters
    ----------
    dirpath : `pathlib.Path` or `str`
        Path to root directory; typically this will be the root
        directory of a package, such as ts_salobj.

    Raises
    ------
    AssertionError
        If any files are not formatted with ``black``.

    Notes
    -----
    For this test to exclude ``version.py``, list it in ``.gitignore``
    as ``version.py``, rather than by the full path
    (e.g. not `python/lsst/ts/salobj/version.py`).
    This may be a bug in black 19.10b0.
    """
    result = subprocess.run(
        ["black", "--check", str(dirpath)],
        capture_output=True,
    )
    if result.returncode != 0:
        raise AssertionError(result.stderr)


def set_random_lsst_dds_partition_prefix() -> None:
    """Set a random value for environment variable LSST_DDS_PARTITION_PREFIX

    Call this for each unit test method that uses SAL message passing,
    in order to avoid collisions with other tests. Note that pytest
    can run unit test methods in parallel.

    The set name will contain the hostname and current time
    as well as a random integer.

    The random value is generated using the `random` library,
    so call ``random.seed(...)`` to seed this value.
    """
    hostname = socket.gethostname()
    curr_time = time.time()
    random_int = random.randint(0, 999999)
    name = f"Test-{hostname}-{curr_time}-{random_int}".replace(".", "_")
    os.environ["LSST_DDS_PARTITION_PREFIX"] = name


def set_random_lsst_dds_domain() -> None:
    """Deprecated version of `set_random_lsst_dds_partition_prefix`."""
    warnings.warn(
        "Use set_random_lsst_dds_partition_prefix instead", DeprecationWarning
    )
    set_random_lsst_dds_partition_prefix()


@contextlib.contextmanager
def modify_environ(**kwargs: typing.Any) -> typing.Generator[None, None, None]:
    """Context manager to temporarily patch os.environ.

    This calls `unittest.mock.patch` and is only intended for unit tests.

    Parameters
    ----------
    kwargs : `dict` [`str`, `str` or `None`]
        Environment variables to set or clear.
        Each key is the name of an environment variable (with correct case);
        it need not already exist. Each value must be one of:

        * A string value to set the env variable.
        * None to delete the env variable, if present.

    Raises
    ------
    RuntimeError
        If any value in kwargs is not of type `str` or `None`.

    Notes
    -----
    Example of use::

        from lsst.ts import salobj
        ...
        def test_foo(self):
            set_value = "Value for $ENV_TO_SET"
            with salobj.modify_environ(
                HOME=None,  # Delete this env var
                ENV_TO_SET=set_value,  # Set this env var
            ):
                self.assertNotIn("HOME", os.environ)
                self.assert(os.environ["ENV_TO_SET"], set_value)
    """
    bad_value_strs = [
        f"{name}: {value!r}"
        for name, value in kwargs.items()
        if not isinstance(value, str) and value is not None
    ]
    if bad_value_strs:
        raise RuntimeError(
            "The following arguments are not of type str or None: "
            + ", ".join(bad_value_strs)
        )

    new_environ = os.environ.copy()
    for name, value in kwargs.items():
        if value is None:
            new_environ.pop(name, None)
        else:
            new_environ[name] = value
    with unittest.mock.patch("os.environ", new_environ):
        yield
