# This file is part of salobj.
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

__all__ = ["get_test_index", "set_random_lsst_dds_domain", "TestCsc"]

import asyncio
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
from . import base
from . import base_csc


_LAST_TEST_INDEX = 0


def get_test_index():
    """Return a new index for the Test component."""
    global _LAST_TEST_INDEX
    _LAST_TEST_INDEX += 1
    return _LAST_TEST_INDEX


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
    """A trivial Test component for unit testing

    This component responds to the setScalars and setArrays comments
    by copying the provided values to the corresponding event and
    telemetry topics. The event topic is output on change.
    The telemetry topics are output at regular intervals
    but only after the first command that sets the appropriate
    values is received.

    It shuts down on receipt of the disable command.

    Note that this component ignores all other commands.

    Parameters
    ----------
    index : `int`
        Index of Test component; each unit test method
        should use a different index.
    initial_state : `salobj.State`
        The initial state of the CSC. Typically one of:
        - State.ENABLED if you want the CSC immediately usable.
        - State.OFFLINE if you want full emulation of a CSC.
    arrays_interval : `float` (optional)
        Interval between arrays telemetry outputs (sec).
    scalars_interval : `float` (optional)
        Interval between scalars telemetry outputs (sec).

    """
    __test__ = False  # stop pytest from warning that this is not a test

    def __init__(self, index, initial_state, arrays_interval=0.1, scalars_interval=0.06):
        if initial_state not in base_csc.State:
            raise ValueError(f"intial_state={initial_state} is not a salobj.State enum")
        super().__init__(SALPY_Test, index)
        self.state = initial_state
        self.arrays_interval = float(arrays_interval)
        self.scalars_interval = float(scalars_interval)
        self.evt_arrays_data = self.evt_arrays.DataType()
        self.evt_scalars_data = self.evt_scalars.DataType()
        self.tel_arrays_data = self.tel_arrays.DataType()
        self.tel_scalars_data = self.tel_scalars.DataType()
        self._enable_arrays_telemetry = False
        self._enable_scalars_telemetry = False

    async def run_arrays_telemetry(self):
        """Output arrays telemetry at regular intervals."""
        while True:
            self.tel_arrays.put(self.tel_arrays_data)
            await asyncio.sleep(self.arrays_interval)

    async def run_scalars_telemetry(self):
        """Output scalars telemetry at regular intervals."""
        while True:
            self.tel_scalars.put(self.tel_scalars_data)
            await asyncio.sleep(self.arrays_interval)

    def do_setArrays(self, id_data):
        """Execute the setArrays command."""
        if self.state != base_csc.State.ENABLED:
            raise base.ExpectedError(f"setArrays not allowed in {self.state} state")
        self.copy_arrays(id_data.data, self.evt_arrays_data)
        self.copy_arrays(id_data.data, self.tel_arrays_data)
        self.assert_arrays_equal(id_data.data, self.evt_arrays_data)
        self.assert_arrays_equal(id_data.data, self.tel_arrays_data)
        self.evt_arrays.put(self.evt_arrays_data, 1)
        if not self._enable_arrays_telemetry:
            self._enable_arrays_telemetry = True
            asyncio.ensure_future(self.run_arrays_telemetry())

    def do_setScalars(self, id_data):
        """Execute the setScalars command."""
        if self.state != base_csc.State.ENABLED:
            raise base.ExpectedError(f"setArrays not allowed in {self.state} state")
        self.copy_scalars(id_data.data, self.evt_scalars_data)
        self.copy_scalars(id_data.data, self.tel_scalars_data)
        self.evt_scalars.put(self.evt_scalars_data, 1)
        if not self._enable_scalars_telemetry:
            self._enable_scalars_telemetry = True
            asyncio.ensure_future(self.run_scalars_telemetry())

    def do_fault(self, id_data):
        """Execute the fault command.

        Change the summary state to State.FAULT
        """
        self.fault()

    def do_wait(self, id_data):
        """Execute the wait command.

        Wait for the specified time and then acknowledge the command
        using the specified ack code.
        """
        asyncio.ensure_future(self._impl_wait(id_data))
        return self.salinfo.makeAck(self.salinfo.lib.SAL__CMD_INPROGRESS)

    async def _impl_wait(self, id_data):
        """Implement the wait command."""
        await asyncio.sleep(id_data.data.duration)
        ack = self.salinfo.makeAck(ack=id_data.data.ack, result="Wait done")
        self.cmd_wait.ack(id_data, ack)

    @property
    def arrays_fields(self):
        """Get a tuple of the fields in an arrays struct."""
        return (
            "boolean_1", "byte_1", "char_1", "short_1",
            "int_1", "long_1", "long_long_1", "octet_1",
            "unsigned_short_1", "unsigned_int_1", "unsigned_long_1",
            "float_1", "double_1")

    @property
    def scalars_fields(self):
        """Get a tuple of the fields in a scalars struct."""
        return (
            "boolean_1", "byte_1", "char_1", "short_1",
            "int_1", "long_1", "long_long_1", "octet_1",
            "unsigned_short_1", "unsigned_int_1", "unsigned_long_1",
            "float_1", "double_1", "string_1")

    def assert_arrays_equal(self, arrays1, arrays2):
        """Assert that two arrays data structs are equal.

        The types need not match; each struct can be command, event
        or telemetry data.
        """
        for field in self.arrays_fields:
            if np.any(getattr(arrays1, field) != getattr(arrays2, field)):
                raise AssertionError("arrays1.{} = {} != {} = arrays2.{}".format(
                    field, getattr(arrays1, field), getattr(arrays2, field), field))

    def assert_scalars_equal(self, scalars1, scalars2):
        """Assert that two scalars data structs are equal.

        The types need not match; each struct can be command, event
        or telemetry data.
        """
        for field in self.scalars_fields:
            if getattr(scalars1, field) != getattr(scalars2, field):
                raise AssertionError("scalars1.{} = {} != {} = scalars2.{}".format(
                    field, getattr(scalars1, field), getattr(scalars2, field), field))

    def copy_arrays(self, src_arrays, dest_arrays):
        """Copy arrays data from one struct to another.

        The types need not match; each struct can be command, event
        or telemetry data.
        """
        for field_name in self.arrays_fields:
            data = getattr(src_arrays, field_name)
            if isinstance(data, np.ndarray):
                getattr(dest_arrays, field_name)[:] = data
            else:
                setattr(dest_arrays, field_name, data)

    def copy_scalars(self, src_scalars, dest_scalars):
        """Copy scalars data from one struct to another.

        The types need not match; each struct can be command, event
        or telemetry data.
        """
        for field_name in self.scalars_fields:
            setattr(dest_scalars, field_name, getattr(src_scalars, field_name))

    def make_random_cmd_arrays(self):
        """Make random data for cmd_setArrays using numpy.random."""
        nelts = 5
        data = self.cmd_setArrays.DataType()
        data.boolean_1[:] = np.random.choice([False, True], size=(nelts,))
        printable_chars = [c for c in string.ascii_letters + string.digits]
        data.char_1 = "".join(np.random.choice(printable_chars, size=(nelts,)))
        for field_name in (
            "byte_1",
            "octet_1",
            "short_1",
            "long_1",
            "long_long_1",
            "unsigned_short_1",
            "unsigned_int_1",
            "unsigned_long_1",
        ):
            field = getattr(data, field_name)
            iinfo = np.iinfo(field.dtype)
            field[:] = np.random.randint(iinfo.min, iinfo.max, size=(nelts,), dtype=field.dtype)
        data.float_1[:] = np.random.uniform(-1e5, 1e5, size=(nelts,))
        data.double_1[:] = np.random.uniform(-1e5, 1e5, size=(nelts,))
        return data

    def make_random_cmd_scalars(self):
        """Make random data for cmd_setScalars using numpy.random."""
        data = self.cmd_setScalars.DataType()
        # also make an empty arrays struct to get dtype of int fields,
        # since that information is lost in the scalars pybind11 wrapper
        empty_arrays = self.cmd_setArrays.DataType()
        data.boolean_1 = np.random.choice([False, True])
        printable_chars = [c for c in string.ascii_letters + string.digits]
        data.char_1 = np.random.choice(printable_chars)
        data.string_1 = "".join(np.random.choice(printable_chars, size=(20,)))
        for field_name in (
            "byte_1",
            "octet_1",
            "short_1",
            "long_1",
            "long_long_1",
            "unsigned_short_1",
            "unsigned_int_1",
            "unsigned_long_1",
        ):
            dtype = getattr(empty_arrays, field_name).dtype
            # work around a bug in numpy 1.14.5 that causes
            # TypeError: 'numpy.dtype' object is not callable
            if dtype == np.int64:
                dtype = np.int64
            iinfo = np.iinfo(dtype)
            setattr(data, field_name, np.random.randint(iinfo.min, iinfo.max, dtype=dtype))
        data.float_1 = np.random.uniform(-1e5, 1e5)
        data.double_1 = np.random.uniform(-1e5, 1e5)
        return data
