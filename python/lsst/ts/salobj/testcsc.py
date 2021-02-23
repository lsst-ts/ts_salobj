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

__all__ = ["TestCsc"]

import asyncio
import string

import numpy as np

from .base_csc import State
from .configurable_csc import ConfigurableCsc
from . import __version__
from .config_schema import CONFIG_SCHEMA


class TestCsc(ConfigurableCsc):
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
    config_dir : `str`, optional
        Path to configuration files.
    initial_state : `salobj.State`, optional
        The initial state of the CSC. Typically one of:

        * `salobj.State.ENABLED` if you want the CSC immediately usable.
        * `salobj.State.STANDBY` if you want full emulation of a CSC.
    settings_to_apply : `str`, optional
        Settings to apply if ``initial_state`` is `State.DISABLED`
        or `State.ENABLED`.
    simulation_mode : `int`, optional
        Simulation mode. The only allowed value is 0.
    schema_path : `str`, `pathlib.Path` or `None`, optional
        Path to a schema file used to validate configuration files.
        This is only for testing the deprecated ``schema_path``
        `ConfigurableCsc` constructor argument;
        real CSCs should _not_ provide this argument.
        If not None then `ConfigurableCsc` is called with this,
        instead of the ``config_schema`` argument.


    Raises
    ------
    ValueError
        If ``config_dir`` is not a directory or ``initial_state`` is invalid.
    salobj.ExpectedError
        If ``simulation_mode`` is invalid.
        Note: you will only see this error if you await `start_task`.

    Notes
    -----
    Unlike a normal CSC this one does not output telemetry at regular
    intervals. Instead, in order to simplify unit tests, it outputs
    the ``arrays`` and ``scalars`` telemetry topics in reponse to
    the ``setArrays`` or ``setScalars`` command (just like the ``arrays``
    and ``scalars`` events). That makes it more predictable when this
    data will appear. Note that the ``heartbeat`` event is output at
    regular intervals, as for any CSC.

    Also, unlike most normal configurable CSCs, this one does not need to be
    configured in order to be used (though self.config will be None).
    Thus it is safe to start this CSC in the `salobj.State.ENABLED` state.

    **Error Codes**

    * 1: the fault command was executed
    """

    enable_cmdline_state = True
    valid_simulation_modes = [0]
    version = __version__
    __test__ = False  # stop pytest from warning that this is not a test

    def __init__(
        self,
        index,
        config_dir=None,
        initial_state=State.STANDBY,
        settings_to_apply="",
        simulation_mode=0,
        schema_path=None,
    ):
        if schema_path is not None:
            config_kwargs = dict(schema_path=schema_path)
        else:
            config_kwargs = dict(config_schema=CONFIG_SCHEMA)
        print("config_kwargs=", config_kwargs)
        super().__init__(
            "Test",
            config_dir=config_dir,
            index=index,
            initial_state=initial_state,
            settings_to_apply=settings_to_apply,
            simulation_mode=simulation_mode,
            **config_kwargs,
        )
        self.cmd_wait.allow_multiple_callbacks = True
        self.config = None

    def do_setArrays(self, data):
        """Execute the setArrays command."""
        self.assert_enabled()
        self.log.info("executing setArrays")
        data_dict = self.as_dict(data, self.arrays_fields)
        self.evt_arrays.set(**data_dict)
        self.tel_arrays.set(**data_dict)
        self.evt_arrays.put()
        self.tel_arrays.put()

    def do_setScalars(self, data):
        """Execute the setScalars command."""
        self.assert_enabled()
        self.log.info("executing setScalars")
        data_dict = self.as_dict(data, self.scalars_fields)
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

    def do_fault(self, data):
        """Execute the fault command.

        Change the summary state to State.FAULT
        """
        self.log.warning("executing the fault command")
        self.fault(code=1, report="executing the fault command")

    async def do_wait(self, data):
        """Execute the wait command by waiting for the specified duration.

        If duration is negative then wait for abs(duration) but do not
        acknowledge the command as "in progress". This is useful for
        testing command timeout.
        """
        self.assert_enabled()
        if data.duration >= 0:
            self.cmd_wait.ack_in_progress(data, timeout=data.duration)
        await asyncio.sleep(abs(data.duration))

    @property
    def field_type(self):
        """Get a dict of field_name: element type."""
        return dict(
            boolean0=bool,
            byte0=np.uint8,
            char0=str,
            short0=np.int16,
            int0=np.int32,
            long0=np.int32,
            longLong0=np.int64,
            octet0=np.uint8,
            unsignedShort0=np.uint16,
            unsignedInt0=np.uint32,
            unsignedLong0=np.uint32,
            float0=np.single,
            double0=np.double,
            string0=str,
        )

    @property
    def arrays_fields(self):
        """Get a tuple of the fields in an arrays struct."""
        return (
            "boolean0",
            "byte0",
            "short0",
            "int0",
            "long0",
            "longLong0",
            "octet0",
            "unsignedShort0",
            "unsignedInt0",
            "unsignedLong0",
            "float0",
            "double0",
        )

    @property
    def scalars_fields(self):
        """Get a tuple of the fields in a scalars struct."""
        return (
            "boolean0",
            "byte0",
            "char0",
            "short0",
            "int0",
            "long0",
            "longLong0",
            "octet0",
            "unsignedShort0",
            "unsignedInt0",
            "unsignedLong0",
            "float0",
            "double0",
            "string0",
        )

    @property
    def int_fields(self):
        """Get a tuple of the integer fields in a struct."""
        return (
            "byte0",
            "short0",
            "int0",
            "long0",
            "longLong0",
            "octet0",
            "unsignedShort0",
            "unsignedInt0",
            "unsignedLong0",
        )

    def assert_arrays_equal(self, arrays1, arrays2):
        """Assert that two arrays data structs are equal.

        The types need not match; each struct can be command, event
        or telemetry data.
        """
        # use reversed so boolean0 is not compared first,
        # as a discrepancy there is harder to interpret
        for field in reversed(self.arrays_fields):
            field_arr1 = getattr(arrays1, field)
            field_arr2 = getattr(arrays2, field)
            if not np.array_equal(field_arr1, field_arr2):
                raise AssertionError(
                    f"arrays1.{field} = {field_arr1} != {field_arr2} = arrays2.{field}"
                )

    def assert_scalars_equal(self, scalars1, scalars2):
        """Assert that two scalars data structs are equal.

        The types need not match; each struct can be command, event
        or telemetry data.
        """
        # use reversed so boolean0 is not compared first,
        # as a discrepancy there is harder to interpret
        for field in reversed(self.scalars_fields):
            field_val1 = getattr(scalars1, field)
            field_val2 = getattr(scalars2, field)
            if field_val1 != field_val2:
                raise AssertionError(
                    f"scalars1.{field} = {field_val1} != {field_val2} = scalars2.{field}"
                )

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
        data = dtype()
        nelts = len(data.boolean0)
        data.boolean0 = np.random.choice([False, True], size=(nelts,))
        for field in self.int_fields:
            field_type = self.field_type[field]
            nelts = len(getattr(data, field))
            iinfo = np.iinfo(field_type)
            field_data = np.random.randint(
                iinfo.min, iinfo.max, size=(nelts,), dtype=field_type
            )
            setattr(data, field, field_data)
        for field in ("float0", "double0"):
            field_type = self.field_type[field]
            nelts = len(getattr(data, field))
            field_data = np.array(
                np.random.uniform(-1e5, 1e5, size=(nelts,)), dtype=field_type
            )
            setattr(data, field, field_data)
        return data

    def _make_random_scalars(self, dtype):
        """Make random data for cmd_setScalars using numpy.random."""
        data = dtype()
        data.boolean0 = np.random.choice([False, True])
        printable_chars = [c for c in string.printable]
        data.char0 = "".join(np.random.choice(printable_chars, size=(20,)))
        data.string0 = "".join(np.random.choice(printable_chars, size=(20,)))
        for field in self.int_fields:
            field_type = self.field_type[field]
            iinfo = np.iinfo(field_type)
            field_data = np.random.randint(iinfo.min, iinfo.max, dtype=field_type)
            setattr(data, field, field_data)
        for field in ("float0", "double0"):
            field_type = self.field_type[field]
            field_data = field_type(np.random.uniform(-1e5, 1e5))
            setattr(data, field, field_data)

        data.float0 = np.array(np.random.uniform(-1e5, 1e5), dtype=np.single)
        data.double0 = np.random.uniform(-1e5, 1e5)
        return data

    @staticmethod
    def get_config_pkg():
        return "ts_config_ocs"

    async def configure(self, config):
        self.config = config
