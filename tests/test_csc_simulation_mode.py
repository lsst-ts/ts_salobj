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
import sys
import typing
import unittest

import numpy as np

from lsst.ts import salobj

np.random.seed(47)

index_gen = salobj.index_generator()


class SimulationModeTestCase(unittest.IsolatedAsyncioTestCase):
    """Test simulation mode handling, including the --simulate
    command-line argument.
    """

    def setUp(self) -> None:
        salobj.set_random_lsst_dds_partition_prefix()
        # Valid simulation modes that will exercise several things:
        # If 0 is present it is the default,
        # otherwise the first value is the default.
        # If 0 is present and there are two values then --simulate is a flag,
        # otherwise --simulate requires a value
        self.valid_simulation_modes_list = (
            (0, 1),
            (1, 0),
            (0, 3),
            (3, 0),
            (1, 2),
            (0, 1, 4),
            (4, 1, 0),
        )

    def make_csc_class(
        self, modes: typing.Optional[typing.Iterable[int]]
    ) -> salobj.TestCsc:
        """Make a subclass of TestCsc with specified valid simulation modes"""

        class TestCscWithSimulation(salobj.TestCsc):
            valid_simulation_modes = modes

        return TestCscWithSimulation

    async def test_invalid_simulation_modes(self) -> None:
        index = next(index_gen)
        for valid_simulation_modes in self.valid_simulation_modes_list:
            csc_class = self.make_csc_class(valid_simulation_modes)
            for bad_simulation_mode in range(-1, 5):
                if bad_simulation_mode in csc_class.valid_simulation_modes:
                    continue
                with self.assertRaises(ValueError):
                    csc_class(index=index, simulation_mode=bad_simulation_mode)

    async def test_valid_simulation_modes(self) -> None:
        for valid_simulation_modes in self.valid_simulation_modes_list:
            csc_class = self.make_csc_class(valid_simulation_modes)
            for simulation_mode in csc_class.valid_simulation_modes:
                index = next(index_gen)
                async with csc_class(
                    index=index, simulation_mode=simulation_mode
                ) as csc:
                    self.assertEqual(csc.simulation_mode, simulation_mode)

    async def test_simulate_cmdline_arg(self) -> None:
        orig_argv = sys.argv[:]
        try:
            for valid_simulation_modes in self.valid_simulation_modes_list:
                print(f"valid_simulation_modes={valid_simulation_modes}")
                if 0 in valid_simulation_modes:
                    default_simulation_mode = 0
                else:
                    default_simulation_mode = valid_simulation_modes[0]

                index = next(index_gen)
                csc_class = self.make_csc_class(valid_simulation_modes)
                if len(valid_simulation_modes) != 2 or 0 not in valid_simulation_modes:
                    # This should fail with no value
                    sys.argv = [
                        "test_csc.py",  # irrelevant
                        str(index),
                        "--simulate",
                    ]
                    with self.assertRaises(SystemExit):
                        csc_class.make_from_cmd_line(index=True)

                    # Test invalid simulation modes
                    for bad_simulation_mode in range(-1, 5):
                        if bad_simulation_mode in valid_simulation_modes:
                            continue
                        sys.argv = [
                            "test_csc.py",  # irrelevant
                            str(index),
                            "--simulate",
                            str(bad_simulation_mode),
                        ]
                        with self.assertRaises(SystemExit):
                            csc_class.make_from_cmd_line(index=True)

                    # Test valid simulation modes
                    for good_simulation_mode in valid_simulation_modes:
                        sys.argv = [
                            "test_csc.py",  # irrelevant
                            str(index),
                            "--simulate",
                            str(good_simulation_mode),
                        ]
                        csc = csc_class.make_from_cmd_line(index=True)
                        try:
                            # The simulation mode isn't assigned
                            # until the CSC starts.
                            await csc.start_task
                            self.assertEqual(csc.simulation_mode, good_simulation_mode)
                        finally:
                            await csc.do_exitControl(data=None)
                            await asyncio.wait_for(csc.done_task, timeout=5)

                else:
                    # This should fail with any value, valid or not
                    for simulation_mode in (0, 1):
                        sys.argv = [
                            "test_csc.py",  # irrelevant
                            str(index),
                            "--simulate",
                            str(simulation_mode),
                        ]
                        with self.assertRaises(SystemExit):
                            csc_class.make_from_cmd_line(index=True)

                    if valid_simulation_modes[0] == 0:
                        nondefault_simulation_mode = valid_simulation_modes[1]
                    else:
                        nondefault_simulation_mode = valid_simulation_modes[0]

                    index = next(index_gen)
                    sys.argv = [
                        "test_csc.py",  # irrelevant
                        str(index),
                        "--simulate",
                    ]
                    csc = csc_class.make_from_cmd_line(index=True)
                    try:
                        # The simulation mode isn't assigned
                        # until the CSC starts.
                        await csc.start_task
                        self.assertEqual(
                            csc.simulation_mode, nondefault_simulation_mode
                        )
                    finally:
                        await csc.do_exitControl(data=None)
                        await asyncio.wait_for(csc.done_task, timeout=5)

                # In all cases no --simulate arg should give the default.
                index = next(index_gen)
                sys.argv = [
                    "test_csc.py",  # irrelevant
                    str(index),
                ]
                csc = csc_class.make_from_cmd_line(index=True)
                try:
                    # The simulation mode isn't assigned until the CSC starts
                    await csc.start_task
                    self.assertEqual(csc.simulation_mode, default_simulation_mode)
                finally:
                    await csc.do_exitControl(data=None)
                    await asyncio.wait_for(csc.done_task, timeout=5)

        finally:
            sys.argv[:] = orig_argv

    async def test_none_valid_simulation_modes_simulation_mode(self) -> None:
        """Test that a CSC that uses the deprecated valid_simulation_modes=None
        checks simulation mode in start, not the constructor.

        The only valid simulation_mode is 0 because that's what BaseCsc
        supports and I didn't override that support.
        """
        TestCscWithDeprecatedSimulation = self.make_csc_class(None)

        self.assertEqual(TestCscWithDeprecatedSimulation.valid_simulation_modes, None)

        for bad_simulation_mode in (1, 2):
            index = next(index_gen)
            warning_regex = "valid_simulation_modes=None is deprecated"
            with self.assertWarnsRegex(DeprecationWarning, warning_regex):
                csc = TestCscWithDeprecatedSimulation(
                    index=index, simulation_mode=bad_simulation_mode
                )
            with self.assertRaises(salobj.base.ExpectedError):
                await csc.start_task

        # Test the one valid simulation mode
        index = next(index_gen)
        with self.assertWarnsRegex(DeprecationWarning, warning_regex):
            csc = TestCscWithDeprecatedSimulation(index=index, simulation_mode=0)
        try:
            await csc.start_task
            self.assertEqual(csc.simulation_mode, 0)
        finally:
            await csc.do_exitControl(data=None)
            await asyncio.wait_for(csc.done_task, timeout=5)

    async def test_none_valid_simulation_modes_cmdline(self) -> None:
        """Test that when valid_simulation_modes=None that the command
        parser does not add the --simulate argument.
        """
        TestCscWithDeprecatedSimulation = self.make_csc_class(None)

        self.assertEqual(TestCscWithDeprecatedSimulation.valid_simulation_modes, None)

        orig_argv = sys.argv[:]
        try:
            index = next(index_gen)
            # Try 0, the only valid value. This will still fail
            # because there is no --simulate command-line argument.
            simulation_mode = 0
            sys.argv = ["test_csc.py", str(index), "--simulate", str(simulation_mode)]
            with self.assertRaises(SystemExit):
                TestCscWithDeprecatedSimulation.make_from_cmd_line(index=True)
        finally:
            sys.argv[:] = orig_argv


if __name__ == "__main__":
    unittest.main()
