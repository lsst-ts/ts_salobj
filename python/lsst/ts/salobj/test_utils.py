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

__all__ = ["assertRaisesAckError", "set_random_lsst_dds_domain", "TestCsc"]

import asyncio
import contextlib
import os
import random
import socket
import string
import time
import warnings

import numpy as np

try:
    import SALPY_Test
except ImportError:
    warnings.warn("Could not import SALPY_Test; TestCsc will not work")
from .base import AckError
from . import base_csc


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


class TestCsc(base_csc.BaseCsc):
    """A simple CSC intended for unit testing.

    Supported commands:

    * ``setScalars`` and ``setArrays``: output the provided data using the
      corresponding event and telemetry topics. Note that this violates
      the convention that telemetry is output at regular intervals,
      but it makes unit tests much easier to write.
    * ``wait``: wait for the specified amount of time, and, if requested,
      raise an exception. One use for this is to test command timeout
      by specifying a long wait and waiting a shorter time for the command
      to finish. Another use is to test multiple simultaneous commands,
      since ``wait`` supports this.
    * The standard state transition commands do the usual thing
      and output the ``summaryState`` event. The ``exitControl``
      command shuts the CSC down.

    Parameters
    ----------
    index : `int`
        Index of Test component; each unit test method
        should use a different index.
    initial_state : `salobj.State` (optional)
        The initial state of the CSC. Typically one of:

        * `salobj.State.ENABLED` if you want the CSC immediately usable.
        * `salobj.State.STANDBY` if you want full emulation of a CSC.
    initial_simulation_mode : `int` (optional)
        Initial simulation mode. The only allowed value is 0.
    """
    __test__ = False  # stop pytest from warning that this is not a test

    def __init__(self, index, initial_state=base_csc.State.STANDBY, initial_simulation_mode=0):
        super().__init__(SALPY_Test, index=index, initial_state=initial_state,
                         initial_simulation_mode=initial_simulation_mode)
        self.cmd_wait.allow_multiple_callbacks = True

    def do_setArrays(self, id_data):
        """Execute the setArrays command."""
        self.assert_enabled("setArrays")
        data_dict = self.as_dict(id_data.data, self.arrays_fields)
        self.evt_arrays.set(**data_dict)
        self.tel_arrays.set(**data_dict)
        self.evt_arrays.put()
        self.tel_arrays.put()

    def do_setScalars(self, id_data):
        """Execute the setScalars command."""
        self.assert_enabled("setScalars")
        self.log.info("executing setScalars")
        data_dict = self.as_dict(id_data.data, self.scalars_fields)
        self.evt_scalars.set(**data_dict)
        self.tel_scalars.set(**data_dict)
        self.evt_scalars.put()
        self.tel_scalars.put()

    def as_dict(self, data, fields):
        """Return the specified fields from a data struct as a dict.

        Parameters
        ----------
        data : `any`
            The data to copy.
        fields : `list` [`str`]
            The names of the fields of ``data`` to copy.
        """
        ret = dict()
        for field in fields:
            ret[field] = getattr(data, field)
        return ret

    def do_fault(self, id_data):
        """Execute the fault command.

        Change the summary state to State.FAULT
        """
        self.log.warning("executing fault")
        self.fault()

    async def do_wait(self, id_data):
        """Execute the wait command.

        Wait for the specified time and then acknowledge the command
        using the specified ack code.
        """
        self.assert_enabled("wait")
        await asyncio.sleep(id_data.data.duration)

    @property
    def arrays_fields(self):
        """Get a tuple of the fields in an arrays struct."""
        return (
            "boolean0", "byte0", "char0", "short0",
            "int0", "long0", "longLong0", "octet0",
            "unsignedShort0", "unsignedInt0", "unsignedLong0",
            "float0", "double0")

    @property
    def scalars_fields(self):
        """Get a tuple of the fields in a scalars struct."""
        return (
            "boolean0", "byte0", "char0", "short0",
            "int0", "long0", "longLong0", "octet0",
            "unsignedShort0", "unsignedInt0", "unsignedLong0",
            "float0", "double0", "string0")

    def assert_arrays_equal(self, arrays1, arrays2):
        """Assert that two arrays data structs are equal.

        The types need not match; each struct can be command, event
        or telemetry data.
        """
        # use reversed so boolean0 is not compared first,
        # as a discrepancy there is harder to interpret
        for field in reversed(self.arrays_fields):
            if np.any(getattr(arrays1, field) != getattr(arrays2, field)):
                raise AssertionError("arrays1.{} = {} != {} = arrays2.{}".format(
                    field, getattr(arrays1, field), getattr(arrays2, field), field))

    def assert_scalars_equal(self, scalars1, scalars2):
        """Assert that two scalars data structs are equal.

        The types need not match; each struct can be command, event
        or telemetry data.
        """
        # use reversed so boolean0 is not compared first,
        # as a discrepancy there is harder to interpret
        for field in reversed(self.scalars_fields):
            if getattr(scalars1, field) != getattr(scalars2, field):
                raise AssertionError("scalars1.{} = {} != {} = scalars2.{}".format(
                    field, getattr(scalars1, field), getattr(scalars2, field), field))

    def make_random_cmd_arrays(self):
        return self._make_random_arrays(dtype=self.cmd_setArrays.DataType)

    def make_random_evt_arrays(self):
        return self._make_random_arrays(dtype=self.evt_arrays.DataType)

    def make_random_tel_arrays(self):
        return self._make_random_arrays(dtype=self.tel_arrays.DataType)

    def make_random_cmd_scalars(self):
        return self._make_random_scalars(dtype=self.cmd_setScalars.DataType)

    def make_random_evt_scalars(self):
        return self._make_random_scalars(dtype=self.evt_scalars.DataType)

    def make_random_tel_scalars(self):
        return self._make_random_scalars(dtype=self.tel_scalars.DataType)

    def _make_random_arrays(self, dtype):
        """Make random arrays data using numpy.random."""
        nelts = 5
        data = dtype()
        data.boolean0[:] = np.random.choice([False, True], size=(nelts,))
        printable_chars = [c for c in string.ascii_letters + string.digits]
        data.char0 = "".join(np.random.choice(printable_chars, size=(nelts,)))
        for field_name in (
            "byte0",
            "octet0",
            "short0",
            "int0",
            "long0",
            "longLong0",
            "unsignedShort0",
            "unsignedInt0",
            "unsignedLong0",
        ):
            field = getattr(data, field_name)
            iinfo = np.iinfo(field.dtype)
            print(f"{field_name} has type {field.dtype}")
            field[:] = np.random.randint(iinfo.min, iinfo.max, size=(nelts,), dtype=field.dtype)
        data.float0[:] = np.random.uniform(-1e5, 1e5, size=(nelts,))
        data.double0[:] = np.random.uniform(-1e5, 1e5, size=(nelts,))
        return data

    def _make_random_scalars(self, dtype):
        """Make random data for cmd_setScalars using numpy.random."""
        data = dtype()
        # also make an empty arrays struct to get dtype of int fields,
        # since that information is lost in the scalars pybind11 wrapper
        empty_arrays = self.cmd_setArrays.DataType()
        data.boolean0 = np.random.choice([False, True])
        printable_chars = [c for c in string.ascii_letters + string.digits]
        data.char0 = np.random.choice(printable_chars)
        data.string0 = "".join(np.random.choice(printable_chars, size=(20,)))
        for field_name in (
            "byte0",
            "octet0",
            "short0",
            "int0",
            "long0",
            "longLong0",
            "unsignedShort0",
            "unsignedInt0",
            "unsignedLong0",
        ):
            dtype = getattr(empty_arrays, field_name).dtype
            # work around a bug in numpy 1.14.5 that causes
            # TypeError: 'numpy.dtype' object is not callable
            if dtype == np.int64:
                dtype = np.int64
            iinfo = np.iinfo(dtype)
            setattr(data, field_name, np.random.randint(iinfo.min, iinfo.max, dtype=dtype))
        data.float0 = np.random.uniform(-1e5, 1e5)
        data.double0 = np.random.uniform(-1e5, 1e5)
        return data
