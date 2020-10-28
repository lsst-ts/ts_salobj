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

import pathlib
import unittest

import asynctest
import numpy as np

from lsst.ts import salobj

np.random.seed(47)

index_gen = salobj.index_generator()
TEST_DATA_DIR = TEST_CONFIG_DIR = pathlib.Path(__file__).resolve().parent / "data"
TEST_CONFIG_DIR = TEST_DATA_DIR / "config"


class InvalidPkgNameCsc(salobj.TestCsc):
    """A CSC whose get_pkg_name classmethod returns a nonexistent package.
    """

    @staticmethod
    def get_config_pkg():
        """Return a name of a non-existent package."""
        return "not_a_valid_pkg_name"


class WrongConfigPkgCsc(salobj.TestCsc):
    """A CSC whose get_pkg_name classmethod returns the wrong package.
    """

    @staticmethod
    def get_config_pkg():
        """Return a package that does not have a Test subdirectory."""
        return "ts_salobj"


class TestCscConstructorTestCase(asynctest.TestCase):
    """Test the TestCsc constructor.

    Note: all of these tests must run async because the constructor
    requires an event loop.
    """

    def setUp(self):
        salobj.set_random_lsst_dds_partition_prefix()

    async def test_class_attributes(self):
        self.assertEqual(list(salobj.TestCsc.valid_simulation_modes), [0])
        self.assertEqual(salobj.TestCsc.version, salobj.__version__)

    async def test_initial_state(self):
        """Test all allowed initial_state values, both as enums and ints."""
        for initial_state in salobj.State:
            if initial_state == salobj.State.FAULT:
                continue
            with self.subTest(initial_state=initial_state):
                await self.check_initial_state(initial_state)
                await self.check_initial_state(int(initial_state))

    async def check_initial_state(self, initial_state):
        """Check that specifying the initial_state constructur argument
        sets the initial reported state to match.
        """
        index = next(index_gen)
        async with salobj.TestCsc(index=index, initial_state=int(initial_state)) as csc:
            self.assertEqual(csc.summary_state, initial_state)

    async def test_invalid_config_dir(self):
        """Test that invalid integer initial_state is rejected."""
        with self.assertRaises(ValueError):
            salobj.TestCsc(
                index=next(index_gen),
                initial_state=salobj.State.STANDBY,
                config_dir=TEST_CONFIG_DIR / "not_a_directory",
            )

    async def test_invalid_config_pkg(self):
        with self.assertRaises(RuntimeError):
            InvalidPkgNameCsc(index=next(index_gen), initial_state=salobj.State.STANDBY)

    async def test_wrong_config_pkg(self):
        with self.assertRaises(RuntimeError):
            WrongConfigPkgCsc(index=next(index_gen), initial_state=salobj.State.STANDBY)

    async def test_invalid_initial_state(self):
        """Test that invalid integer initial_state is rejected."""
        for invalid_state in (
            salobj.State.FAULT,
            min(salobj.State) - 1,
            max(salobj.State) + 1,
        ):
            with self.subTest(invalid_state=invalid_state):
                with self.assertRaises(ValueError):
                    salobj.TestCsc(index=next(index_gen), initial_state=invalid_state)

    async def test_late_callback_assignment(self):
        """Test that command callbacks are not assigned until start
        is called.
        """
        index = next(index_gen)
        csc = salobj.TestCsc(index=index)
        try:
            cmd_topics = [
                getattr(csc, f"cmd_{name}") for name in csc.salinfo.command_names
            ]
            for topic in cmd_topics:
                self.assertIsNone(topic.callback)

            await csc.start_task
            for topic in cmd_topics:
                self.assertIsNotNone(topic.callback)
        finally:
            await csc.close()


if __name__ == "__main__":
    unittest.main()
