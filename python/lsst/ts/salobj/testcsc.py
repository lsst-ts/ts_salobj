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

__all__ = ["TestCsc", "run_test_csc"]

import asyncio
import string
import types
import typing
from collections.abc import Sequence

import numpy as np
from lsst.ts.xml import type_hints

from . import __version__
from .base_csc import State
from .config_schema import CONFIG_SCHEMA
from .configurable_csc import ConfigurableCsc


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
    check_if_duplicate : `bool`, optional
        Check for heartbeat events from the same SAL name and index
        at startup (before starting the heartbeat loop)?
        Defaults to False in order to speed up unit tests,
        but `amain` sets it true.
    initial_state : `salobj.State`, optional
        The initial state of the CSC. Typically one of:

        * `salobj.State.ENABLED` if you want the CSC immediately usable.
        * `salobj.State.STANDBY` if you want full emulation of a CSC.
    override : `str`, optional
        Configuration override file to apply if ``initial_state`` is
        `State.DISABLED` or `State.ENABLED`.
    simulation_mode : `int`, optional
        Simulation mode. The only allowed value is 0.


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
    __test__ = False  # Stop pytest from warning that this is not a test.

    def __init__(
        self,
        index: int,
        config_dir: type_hints.PathType | None = None,
        check_if_duplicate: bool = False,
        initial_state: State = State.STANDBY,
        override: str = "",
        simulation_mode: int = 0,
    ):
        super().__init__(
            name="Test",
            index=index,
            config_schema=CONFIG_SCHEMA,
            config_dir=config_dir,
            check_if_duplicate=check_if_duplicate,
            initial_state=initial_state,
            override=override,
            simulation_mode=simulation_mode,
            extra_commands={"newCommand"},
        )
        self.cmd_wait.allow_multiple_callbacks = True  # type: ignore
        self.config: types.SimpleNamespace | None = None

    def as_dict(self, data: typing.Any, fields: Sequence[str]) -> dict[str, typing.Any]:
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

    async def do_setArrays(self, data: type_hints.BaseMsgType) -> None:
        """Execute the setArrays command."""
        self.assert_enabled()
        self.log.info("executing setArrays")
        data_dict = self.as_dict(data, self.arrays_fields)
        await self.evt_arrays.set_write(**data_dict)  # type: ignore
        await self.tel_arrays.set_write(**data_dict)  # type: ignore

    async def do_setScalars(self, data: type_hints.BaseMsgType) -> None:
        """Execute the setScalars command."""
        self.assert_enabled()
        self.log.info("executing setScalars")
        data_dict = self.as_dict(data, self.scalars_fields)
        await self.evt_scalars.set_write(**data_dict)  # type: ignore
        await self.tel_scalars.set_write(**data_dict)  # type: ignore

    async def do_fault(self, data: type_hints.BaseMsgType) -> None:
        """Execute the fault command.

        Change the summary state to State.FAULT
        """
        self.log.warning("executing the fault command")
        await self.fault(code=1, report="executing the fault command")

    async def do_wait(self, data: type_hints.BaseMsgType) -> None:
        """Execute the wait command by waiting for the specified duration.

        If duration is negative then wait for abs(duration) but do not
        acknowledge the command as "in progress". This is useful for
        testing command timeout.
        """
        self.assert_enabled()
        duration: float = data.duration  # type: ignore
        if duration >= 0:
            await self.cmd_wait.ack_in_progress(data, timeout=duration)  # type: ignore
        await asyncio.sleep(abs(duration))

    async def do_newCommand(self, data: type_hints.BaseMsgType) -> None:
        """This method is defined here to provide a test to the
        extra_commands features in CSC.

        Warning: DO NOTE REMOVE THIS COMMAND.
        """
        pass

    @property
    def field_type(self) -> dict[str, typing.Any]:
        """Get a dict of field_name: element type."""
        return dict(
            boolean0=bool,
            byte0=np.uint8,
            short0=np.int16,
            int0=np.int32,
            long0=np.int32,
            longLong0=np.int64,
            unsignedShort0=np.uint16,
            unsignedInt0=np.uint32,
            float0=np.single,
            double0=np.double,
            string0=str,
        )

    @property
    def arrays_fields(self) -> Sequence[str]:
        """Get a tuple of the fields in an arrays struct."""
        return (
            "boolean0",
            "byte0",
            "short0",
            "int0",
            "long0",
            "longLong0",
            "unsignedShort0",
            "unsignedInt0",
            "float0",
            "double0",
        )

    @property
    def scalars_fields(self) -> Sequence[str]:
        """Get a tuple of the fields in a scalars struct."""
        return (
            "boolean0",
            "byte0",
            "short0",
            "int0",
            "long0",
            "longLong0",
            "unsignedShort0",
            "unsignedInt0",
            "float0",
            "double0",
            "string0",
        )

    @property
    def int_fields(self) -> Sequence[str]:
        """Get a tuple of the integer fields in a struct."""
        return (
            "byte0",
            "short0",
            "int0",
            "long0",
            "longLong0",
            "unsignedShort0",
            "unsignedInt0",
        )

    def assert_arrays_equal(self, arrays1: typing.Any, arrays2: typing.Any) -> None:
        """Assert that two arrays data structs are equal.

        The types need not match; each struct can be command, event
        or telemetry data, or a dict of field: value.
        """
        # use reversed so boolean0 is not compared first,
        # as a discrepancy there is harder to interpret
        if isinstance(arrays1, dict):
            arrays1 = types.SimpleNamespace(**arrays1)
        if isinstance(arrays2, dict):
            arrays2 = types.SimpleNamespace(**arrays2)
        for field in reversed(self.arrays_fields):
            field_arr1 = getattr(arrays1, field)
            field_arr2 = getattr(arrays2, field)
            is_float = field in ("float0", "double0")
            if not np.array_equal(  # type: ignore
                field_arr1, field_arr2, equal_nan=is_float
            ):
                raise AssertionError(
                    f"arrays1.{field} = {field_arr1} != {field_arr2} = arrays2.{field}"
                )

    def assert_scalars_equal(self, scalars1: typing.Any, scalars2: typing.Any) -> None:
        """Assert that two scalars data structs are equal.

        The types need not match; each struct can be command, event
        or telemetry data, or a dict of field: value.
        """
        if isinstance(scalars1, dict):
            scalars1 = types.SimpleNamespace(**scalars1)
        if isinstance(scalars2, dict):
            scalars2 = types.SimpleNamespace(**scalars2)

        # use reversed so boolean0 is not compared first,
        # as a discrepancy there is harder to interpret
        for field in reversed(self.scalars_fields):
            field_val1 = getattr(scalars1, field)
            field_val2 = getattr(scalars2, field)
            is_float = field in ("float0", "double0")
            if not np.array_equal(  # type: ignore
                field_val1, field_val2, equal_nan=is_float
            ):
                raise AssertionError(
                    f"scalars1.{field} = {field_val1} != {field_val2} = scalars2.{field}"
                )

    def make_random_arrays_dict(self) -> dict[str, typing.Any]:
        """Make a random arrays data dict."""
        arrays_dict: dict[str, typing.Any] = dict()
        blank_arrays_data = self.evt_arrays.DataType()  # type: ignore
        nelts = len(blank_arrays_data.boolean0)
        arrays_dict["boolean0"] = np.random.choice([False, True], size=(nelts,))
        for field in self.int_fields:
            field_type = self.field_type[field]
            nelts = len(getattr(blank_arrays_data, field))
            iinfo = np.iinfo(field_type)
            arrays_dict[field] = np.random.randint(
                iinfo.min, iinfo.max, size=(nelts,), dtype=field_type
            )
        for field in ("float0", "double0"):
            field_type = self.field_type[field]
            nelts = len(getattr(blank_arrays_data, field))
            arrays_dict[field] = np.array(
                np.random.uniform(-1e5, 1e5, size=(nelts,)), dtype=field_type
            )
        return arrays_dict

    def make_random_scalars_dict(self) -> dict[str, typing.Any]:
        """Make a random arrays data dict."""
        scalars_dict: dict[str, typing.Any] = dict()
        scalars_dict["boolean0"] = bool(np.random.choice([False, True]))
        printable_chars = [c for c in string.printable]
        scalars_dict["string0"] = "".join(np.random.choice(printable_chars, size=(20,)))
        for field in self.int_fields:
            field_type = self.field_type[field]
            iinfo = np.iinfo(field_type)
            scalars_dict[field] = np.random.randint(
                iinfo.min, iinfo.max, dtype=field_type
            )
        for field in ("float0", "double0"):
            field_type = self.field_type[field]
            scalars_dict[field] = field_type(np.random.uniform(-1e5, 1e5))
        return scalars_dict

    @staticmethod
    def get_config_pkg() -> str:
        return "ts_config_ocs"

    async def configure(self, config: types.SimpleNamespace) -> None:
        self.config = config


def run_test_csc() -> None:
    """Run the Test CSC from the command line."""
    asyncio.run(TestCsc.amain(index=True))
