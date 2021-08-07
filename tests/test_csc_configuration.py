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

import os
import pathlib
import typing
import unittest

import numpy as np
import yaml

from lsst.ts import salobj

# Long enough to perform any reasonable operation
# including starting a CSC or loading a script (seconds)
STD_TIMEOUT = 60

np.random.seed(47)

TEST_DATA_DIR = TEST_CONFIG_DIR = pathlib.Path(__file__).resolve().parent / "data"
TEST_CONFIG_DIR = TEST_DATA_DIR / "config"


class ConfigurationTestCase(salobj.BaseCscTestCase, unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        # defaults hard-coded in <ts_salobj_root>/schema/Test.yaml
        self.default_dict = dict(
            string0="default value for string0",
            bool0=True,
            int0=5,
            float0=3.14,
            intarr0=[-1, 1],
        )
        self.config_fields = self.default_dict.keys()

    def basic_make_csc(
        self,
        initial_state: typing.Union[salobj.State, int],
        config_dir: typing.Union[str, pathlib.Path, None],
        simulation_mode: int,
    ) -> salobj.BaseCsc:
        return salobj.TestCsc(
            self.next_index(),
            initial_state=initial_state,
            config_dir=config_dir,
            simulation_mode=simulation_mode,
        )

    async def check_settings_events(self, config_file: str) -> None:
        """Check the settingsApplied and appliedSettingsMatchStart events.

        Parameters
        ----------
        config_file : `str`
            The name of the config file, or "" if none specified.
        """
        # settingsVersion.settingsApplied should start with
        # the config file name followed by a colon
        data = await self.assert_next_sample(
            topic=self.remote.evt_settingsApplied,
        )
        desired_prefix = config_file + ":"
        self.assertEqual(data.settingsVersion[: len(desired_prefix)], desired_prefix)

        # appliedSettingsMatchStartIsTrue.appliedSettingsMatchStartIsTrue
        # should be True after being configured.
        await self.assert_next_sample(
            topic=self.remote.evt_appliedSettingsMatchStart,
            appliedSettingsMatchStartIsTrue=True,
        )

    async def test_no_config_specified(self) -> None:
        async with self.make_csc(
            initial_state=salobj.State.STANDBY, config_dir=TEST_CONFIG_DIR
        ):
            await self.assert_next_summary_state(salobj.State.STANDBY)

            expected_settings_url = pathlib.Path(TEST_CONFIG_DIR).resolve().as_uri()
            expected_settings_labels = ",".join(
                (
                    "all_fields",
                    "empty",
                    "some_fields",
                    "long_label1_in_an_attempt_to_make_recommendedSettingsLabels_go_over_256_chars",
                    "long_label2_in_an_attempt_to_make_recommendedSettingsLabels_go_over_256_chars",
                    "long_label3_in_an_attempt_to_make_recommendedSettingsLabels_go_over_256_chars",
                    "long_label4_in_an_attempt_to_make_recommendedSettingsLabels_go_over_256_chars",
                    "long_label5_in_an_attempt_to_make_recommendedSettingsLabels_go_over_256_chars",
                )
            )
            data = await self.assert_next_sample(
                topic=self.remote.evt_settingVersions,
                settingsUrl=expected_settings_url,
                recommendedSettingsLabels=expected_settings_labels,
            )
            self.assertTrue(len(data.recommendedSettingsVersion) > 0)
            await self.remote.cmd_start.start(timeout=STD_TIMEOUT)
            await self.assert_next_summary_state(salobj.State.DISABLED)
            config = self.csc.config
            for key, expected_value in self.default_dict.items():
                self.assertEqual(getattr(config, key), expected_value)

            # Test the softwareVersions event.
            # Assume the string length is the same for each field.
            metadata = self.csc.salinfo.metadata
            data = await self.assert_next_sample(
                topic=self.remote.evt_softwareVersions,
                xmlVersion=metadata.xml_version,
                salVersion=metadata.sal_version,
                openSpliceVersion=salobj.get_dds_version(),
                cscVersion=salobj.__version__,
            )
            await self.check_settings_events("")

    async def test_default_config_dir(self) -> None:
        async with self.make_csc(initial_state=salobj.State.STANDBY, config_dir=None):
            await self.assert_next_summary_state(salobj.State.STANDBY)
            data = await self.remote.evt_settingVersions.next(
                flush=False, timeout=STD_TIMEOUT
            )
            self.assertTrue(len(data.recommendedSettingsVersion) > 0)
            self.assertEqual(data.settingsUrl[0:8], "file:///")
            config_path = pathlib.Path(data.settingsUrl[7:])
            self.assertTrue(config_path.samefile(self.csc.config_dir))

    async def test_empty_label(self) -> None:
        config_name = "empty"

        async with self.make_csc(
            initial_state=salobj.State.STANDBY, config_dir=TEST_CONFIG_DIR
        ):
            await self.assert_next_summary_state(salobj.State.STANDBY)
            await self.remote.cmd_start.set_start(
                settingsToApply=config_name, timeout=STD_TIMEOUT
            )
            await self.assert_next_summary_state(salobj.State.DISABLED)
            config = self.csc.config
            for key, expected_value in self.default_dict.items():
                self.assertEqual(getattr(config, key), expected_value)

            await self.check_settings_events("empty.yaml")

    async def test_some_fields_label(self) -> None:
        """Test a config with some fields set to valid values."""
        config_label = "some_fields"
        config_file = "some_fields.yaml"

        async with self.make_csc(
            initial_state=salobj.State.STANDBY, config_dir=TEST_CONFIG_DIR
        ):
            await self.assert_next_summary_state(salobj.State.STANDBY)
            await self.remote.cmd_start.set_start(
                settingsToApply=config_label, timeout=STD_TIMEOUT
            )
            await self.assert_next_summary_state(salobj.State.DISABLED)
            config = self.csc.config
            config_path = os.path.join(self.csc.config_dir, config_file)
            with open(config_path, "r") as f:
                config_yaml = f.read()
            config_from_file = yaml.safe_load(config_yaml)
            for key, default_value in self.default_dict.items():
                if key in config_from_file:
                    self.assertEqual(getattr(config, key), config_from_file[key])
                    self.assertNotEqual(getattr(config, key), default_value)
                else:
                    self.assertEqual(getattr(config, key), default_value)

            await self.check_settings_events(config_file)

    async def test_some_fields_file_no_hash(self) -> None:
        """Test a config specified by filename."""
        config_file = "some_fields.yaml"

        async with self.make_csc(
            initial_state=salobj.State.STANDBY, config_dir=TEST_CONFIG_DIR
        ):
            await self.assert_next_summary_state(salobj.State.STANDBY)
            await self.remote.cmd_start.set_start(
                settingsToApply=config_file, timeout=STD_TIMEOUT
            )
            await self.assert_next_summary_state(salobj.State.DISABLED)
            config = self.csc.config
            config_path = os.path.join(self.csc.config_dir, config_file)
            with open(config_path, "r") as f:
                config_yaml = f.read()
            config_from_file = yaml.safe_load(config_yaml)
            for key, default_value in self.default_dict.items():
                if key in config_from_file:
                    self.assertEqual(getattr(config, key), config_from_file[key])
                    self.assertNotEqual(getattr(config, key), default_value)
                else:
                    self.assertEqual(getattr(config, key), default_value)

            await self.check_settings_events(config_file)

    async def test_some_fields_file_with_hash(self) -> None:
        """Test a config specified by filename:hash."""
        config_file = "some_fields.yaml"

        async with self.make_csc(
            initial_state=salobj.State.STANDBY, config_dir=TEST_CONFIG_DIR
        ):
            await self.assert_next_summary_state(salobj.State.STANDBY)
            await self.remote.cmd_start.set_start(
                settingsToApply=f"{config_file}:HEAD", timeout=STD_TIMEOUT
            )
            await self.assert_next_summary_state(salobj.State.DISABLED)
            config = self.csc.config
            config_path = os.path.join(self.csc.config_dir, config_file)
            with open(config_path, "r") as f:
                config_yaml = f.read()
            config_from_file = yaml.safe_load(config_yaml)
            for key, default_value in self.default_dict.items():
                if key in config_from_file:
                    self.assertEqual(getattr(config, key), config_from_file[key])
                    self.assertNotEqual(getattr(config, key), default_value)
                else:
                    self.assertEqual(getattr(config, key), default_value)

            await self.check_settings_events(config_file)

    async def test_all_fields_label(self) -> None:
        """Test a config with all fields set to valid values."""
        config_name = "all_fields"
        config_file = "all_fields.yaml"

        async with self.make_csc(
            initial_state=salobj.State.STANDBY, config_dir=TEST_CONFIG_DIR
        ):
            await self.assert_next_summary_state(salobj.State.STANDBY)
            await self.remote.cmd_start.set_start(
                settingsToApply=config_name, timeout=STD_TIMEOUT
            )
            await self.assert_next_summary_state(salobj.State.DISABLED)
            config = self.csc.config
            config_path = os.path.join(self.csc.config_dir, config_file)
            with open(config_path, "r") as f:
                config_yaml = f.read()
            config_from_file = yaml.safe_load(config_yaml)
            for key in self.config_fields:
                self.assertEqual(getattr(config, key), config_from_file[key])

            await self.check_settings_events(config_file)

    async def test_invalid_configs(self) -> None:
        async with self.make_csc(
            initial_state=salobj.State.STANDBY, config_dir=TEST_CONFIG_DIR
        ):
            await self.assert_next_summary_state(salobj.State.STANDBY)
            for name in ("all_bad_types", "bad_format", "one_bad_type", "extra_field"):
                config_file = f"invalid_{name}.yaml"
                with self.subTest(config_file=config_file):
                    with salobj.assertRaisesAckError(ack=salobj.SalRetCode.CMD_FAILED):
                        await self.remote.cmd_start.set_start(
                            settingsToApply=config_file, timeout=STD_TIMEOUT
                        )
                    data = self.remote.evt_summaryState.get()
                    self.assertEqual(self.csc.summary_state, salobj.State.STANDBY)
                    self.assertEqual(data.summaryState, salobj.State.STANDBY)

            # Make sure the CSC can still be started.
            await self.remote.cmd_start.set_start(
                settingsToApply="all_fields.yaml", timeout=10
            )
            self.assertEqual(self.csc.summary_state, salobj.State.DISABLED)
            await self.assert_next_summary_state(salobj.State.DISABLED)


if __name__ == "__main__":
    unittest.main()
