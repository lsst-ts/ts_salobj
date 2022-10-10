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

import asyncio
import typing
import unittest
from collections.abc import Iterable

import numpy as np
import pytest
from lsst.ts import salobj, utils

np.random.seed(47)

index_gen = utils.index_generator()

# Standard timeout (sec)
# Long to avoid unnecessary timeouts on slow CI systems.
STD_TIMEOUT = 60


class ControllerWithDoMethods(salobj.Controller):
    """A Test controller with a trivial do_<name> method for each
    specified command name.

    Parameters
    ----------
    command_names : `iterable` of `str`
        List of command names for which to make trivial ``do_<name>``
        methods.
    allow_missing_callbacks : `bool`, optional
        Allow missing ``do_<name>`` callback methods? Missing callback
        methods will be replaced with one that raises salobj.ExpectedError.
        This is intended for mock controllers, which may only support
        a subset of commands.
    """

    def __init__(
        self, command_names: Iterable[str], allow_missing_callbacks: bool = False
    ) -> None:
        index = next(index_gen)
        for name in command_names:
            setattr(self, f"do_{name}", self.mock_do_method)
        super().__init__(
            "Test",
            index,
            do_callbacks=True,
            allow_missing_callbacks=allow_missing_callbacks,
        )

    def mock_do_method(self, *args: typing.Any, **kwargs: typing.Any) -> None:
        pass


class ControllerConstructorTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        salobj.set_random_topic_subname()

    async def test_do_callbacks_false(self) -> None:
        index = next(index_gen)
        async with salobj.Controller("Test", index, do_callbacks=False) as controller:
            command_names = controller.salinfo.command_names
            for name in command_names:
                with self.subTest(name=name):
                    cmd = getattr(controller, "cmd_" + name)
                    assert not cmd.has_callback

            assert controller.salinfo.identity == f"Test:{index}"

    async def test_do_callbacks_true(self) -> None:
        index = next(index_gen)
        async with salobj.Domain() as domain, salobj.SalInfo(
            domain=domain, name="Test", index=index
        ) as salinfo:
            command_names = salinfo.command_names

        # Build a controller and check that callbacks are assigned.
        async with ControllerWithDoMethods(command_names) as controller:
            for cmd_name in command_names:
                with self.subTest(cmd_name=cmd_name):
                    cmd = getattr(controller, "cmd_" + cmd_name)
                    assert cmd.has_callback

        # do_setAuthList and do_setLogLevel are provided by Controller
        skip_names = {"setAuthList", "setLogLevel"}
        for missing_name in command_names:
            if missing_name in skip_names:
                continue
            with self.subTest(missing_name=missing_name):
                incomplete_names = [
                    name for name in command_names if name != missing_name
                ]
                # With allow_missing_callbacks=False (the default)
                # missing do_{command} methods should raise TypeError
                with pytest.raises(TypeError):
                    ControllerWithDoMethods(incomplete_names)

            # With allow_missing_callbacks=True missing do_{command} callbacks
            # should be allowed, and the associated command topic(s)
            # should have callback controller._unsupported_cmd_callback.
            # Note that command callbacks are not assigned until
            # the CSC is started.
            controller = ControllerWithDoMethods(
                incomplete_names, allow_missing_callbacks=True
            )
            await asyncio.wait_for(controller.start_task, timeout=STD_TIMEOUT)
            for name in command_names:
                command_topic = getattr(controller, f"cmd_{name}")
                if name == missing_name:
                    assert (
                        command_topic.callback == controller._unsupported_cmd_callback
                    )
                else:
                    do_method = getattr(controller, f"do_{name}")
                    assert command_topic.callback == do_method

        extra_names = list(command_names) + ["extra_command"]
        with pytest.raises(TypeError):
            ControllerWithDoMethods(extra_names)

    async def test_write_only_true(self) -> None:
        index = next(index_gen)
        # Build a controller and check that callbacks are assigned.
        async with salobj.Controller(
            name="Test", index=index, write_only=True
        ) as controller:
            for name in controller.salinfo.command_names:
                assert not hasattr(controller, f"cmd_{name}")

            for name in controller.salinfo.event_names:
                assert hasattr(controller, f"evt_{name}")

            for name in controller.salinfo.telemetry_names:
                assert hasattr(controller, f"tel_{name}")

        # Check that do_callbacks cannot be true if write_only is true.
        with pytest.raises(ValueError):
            salobj.Controller(
                name="Test", index=index, do_callbacks=True, write_only=True
            )
