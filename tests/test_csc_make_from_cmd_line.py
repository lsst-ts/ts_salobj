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

import enum
import os
import pathlib
import sys
import unittest

import numpy as np

from lsst.ts import salobj

np.random.seed(47)

index_gen = salobj.index_generator()
TEST_DATA_DIR = TEST_CONFIG_DIR = pathlib.Path(__file__).resolve().parent / "data"
TEST_CONFIG_DIR = TEST_DATA_DIR / "config"


class NoIndexCsc(salobj.TestCsc):
    """A CSC whose constructor has no index argument."""

    def __init__(
        self,
        arg1,
        arg2,
        initial_state=salobj.State.STANDBY,
        settings_to_apply="",
        config_dir=None,
    ):
        super().__init__(
            index=next(index_gen),
            initial_state=initial_state,
            settings_to_apply=settings_to_apply,
            config_dir=config_dir,
        )
        self.arg1 = arg1
        self.arg2 = arg2


class TestCscSettingsRequired(salobj.TestCsc):
    """A variant of TestCsc that has require_settings=True."""

    require_settings = True


class TestCscSettingsRequiredNoCmdLineState(salobj.TestCsc):
    """An invalid variant of TestCsc with require_settings=True
    and enable_cmdline_state=True.

    This should raise RuntimeError in make_from_cmd_line.
    """

    require_settings = True
    enable_cmdline_state = False


class CscMakeFromCmdLineTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        salobj.set_random_lsst_dds_partition_prefix()
        self.original_argv = sys.argv[:]

    def tearDown(self):
        sys.argv = self.original_argv

    async def test_no_index(self):
        for index in (0, None):
            with self.subTest(index=index):
                sys.argv = [sys.argv[0]]
                arg1 = "astring"
                arg2 = 2.75
                async with NoIndexCsc.make_from_cmd_line(
                    index=index, arg1=arg1, arg2=arg2
                ) as csc:
                    self.assertEqual(csc.arg1, arg1)
                    self.assertEqual(csc.arg2, arg2)
                    await csc.close()

    async def test_specified_index(self):
        sys.argv = [sys.argv[0]]
        index = next(index_gen)
        async with salobj.TestCsc.make_from_cmd_line(index=index) as csc:
            self.assertEqual(csc.salinfo.index, index)
            await csc.close()

    async def test_enum_index(self):
        class SalIndex(enum.IntEnum):
            ONE = 1
            TWO = 2

        for item in SalIndex:
            index = item.value
            sys.argv = [sys.argv[0], str(index)]
            async with salobj.TestCsc.make_from_cmd_line(index=SalIndex) as csc:
                self.assertEqual(csc.salinfo.index, index)
                await csc.close()

    async def test_index_from_argument_and_default_config_dir(self):
        index = next(index_gen)
        sys.argv = [sys.argv[0], str(index)]
        async with salobj.TestCsc.make_from_cmd_line(index=True) as csc:
            self.assertEqual(csc.salinfo.index, index)

            desired_config_pkg_name = "ts_config_ocs"
            desired_config_env_name = desired_config_pkg_name.upper() + "_DIR"
            desird_config_pkg_dir = os.environ[desired_config_env_name]
            desired_config_dir = pathlib.Path(desird_config_pkg_dir) / "Test/v1"
            self.assertEqual(csc.get_config_pkg(), desired_config_pkg_name)
            self.assertEqual(csc.config_dir, desired_config_dir)
            await csc.close()

    async def test_config_from_argument(self):
        index = next(index_gen)
        sys.argv = [sys.argv[0], str(index), "--config", str(TEST_CONFIG_DIR)]
        async with salobj.TestCsc.make_from_cmd_line(index=True) as csc:
            self.assertEqual(csc.salinfo.index, index)
            self.assertEqual(csc.config_dir, TEST_CONFIG_DIR)
            await csc.close()

    async def test_state_good(self):
        """Test valid --state and --settings arguments."""
        for state, settings in (
            (salobj.State.OFFLINE, ""),
            (salobj.State.STANDBY, ""),
            (salobj.State.DISABLED, "all_fields.yaml"),
            (salobj.State.ENABLED, ""),
        ):
            state_name = state.name.lower()
            index = next(index_gen)
            sys.argv = [
                sys.argv[0],
                str(index),
                "--config",
                str(TEST_CONFIG_DIR),
                "--state",
                state_name,
                "--settings",
                settings,
            ]
            async with salobj.TestCsc.make_from_cmd_line(index=True) as csc:
                self.assertEqual(csc.salinfo.index, index)
                self.assertEqual(csc.summary_state, state)
                if state not in (salobj.State.DISABLED, salobj.State.ENABLED):
                    # Configuration not applied.
                    self.assertIsNone(csc.config)
                elif settings == "all_fields.yaml":
                    self.assertEqual(csc.config.string0, "an arbitrary string")
                elif settings == "":
                    self.assertEqual(csc.config.string0, "default value for string0")
                else:
                    self.fail("Unhandled case.")
                await csc.close()

    async def test_state_bad(self):
        """Test invalid --state or --settings arguments."""
        # The only allowed --state values are "standby", "disabled",
        # and "enabled".
        for bad_state_name in ("fault", "not_a_state"):
            index = next(index_gen)
            sys.argv = [sys.argv[0], str(index), "--state", bad_state_name]
            with self.assertRaises(SystemExit):
                salobj.TestCsc.make_from_cmd_line(index=True)

        # Test that require_settings=True makes --settings required
        # if state is "disabled" or "enabled".
        for state_name in ("disabled", "enabled"):
            index = next(index_gen)
            sys.argv = [sys.argv[0], str(index), "--state", state_name]
            with self.assertRaises(SystemExit):
                TestCscSettingsRequired.make_from_cmd_line(index=True)

        # Test that require_settings=True requires enable_cmdline_state=True.
        # This is caught in the constructor, not the argument parser,
        # in order to make sure the developer sees it.
        index = next(index_gen)
        with self.assertRaises(RuntimeError):
            TestCscSettingsRequiredNoCmdLineState(index=True)


if __name__ == "__main__":
    unittest.main()
