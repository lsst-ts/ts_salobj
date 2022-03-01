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
from lsst.ts import utils

# Long enough to perform any reasonable operation
# including starting a CSC or loading a script (seconds)
STD_TIMEOUT = 60

np.random.seed(47)

TEST_DATA_DIR = pathlib.Path(__file__).resolve().parent / "data"
TEST_CONFIGS_ROOT = TEST_DATA_DIR / "configs"


class ConfigurationTestCase(salobj.BaseCscTestCase, unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        super().setUp()
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

    async def test_no_config_specified(self) -> None:
        config_dir = TEST_CONFIGS_ROOT / "good_with_site_file"
        async with self.make_csc(
            initial_state=salobj.State.STANDBY, config_dir=config_dir
        ):
            await self.assert_next_summary_state(salobj.State.STANDBY)

            await self.remote.cmd_start.start(timeout=STD_TIMEOUT)
            await self.assert_next_summary_state(salobj.State.DISABLED)
            config = self.csc.config
            for key, expected_value in self.default_dict.items():
                assert getattr(config, key) == expected_value

            # Test the softwareVersions event.
            # Assume the string length is the same for each field.
            metadata = self.csc.salinfo.metadata
            await self.assert_next_sample(
                topic=self.remote.evt_softwareVersions,
                xmlVersion=metadata.xml_version,
                salVersion=metadata.sal_version,
                openSpliceVersion=salobj.get_dds_version(),
                cscVersion=salobj.__version__,
            )
            await self.assert_next_sample(
                topic=self.remote.evt_configurationApplied,
                configurations="_init.yaml,_test.yaml",
            )

    async def test_bad_site(self) -> None:
        config_dir = TEST_CONFIGS_ROOT / "good_with_site_file"
        with utils.modify_environ(LSST_SITE="no_such_site"):
            async with self.make_csc(
                initial_state=salobj.State.STANDBY,
                config_dir=config_dir,
            ):
                await self.assert_next_summary_state(salobj.State.STANDBY)

                with salobj.assertRaisesAckError():
                    await self.remote.cmd_start.start(timeout=STD_TIMEOUT)

    async def test_default_config_dir(self) -> None:
        async with self.make_csc(initial_state=salobj.State.STANDBY, config_dir=None):
            await self.assert_next_summary_state(salobj.State.STANDBY)
            expected_config_url = self.csc.config_dir.as_uri()
            data = await self.assert_next_sample(
                topic=self.remote.evt_configurationsAvailable,
                url=expected_config_url,
                schemaVersion="v2",
            )
            assert len(data.version) > 0

    async def test_bad_config_dirs(self) -> None:
        for bad_config_dir in TEST_CONFIGS_ROOT.glob("bad_*"):
            async with self.make_csc(
                initial_state=salobj.State.STANDBY, config_dir=bad_config_dir
            ):
                await self.assert_next_summary_state(salobj.State.STANDBY)
                with salobj.assertRaisesAckError():
                    await self.remote.cmd_start.set_start(
                        configurationOverride="", timeout=STD_TIMEOUT
                    )

    async def test_override_some_fields(self) -> None:
        """Test an override with some fields set to valid values."""
        config_dir = TEST_CONFIGS_ROOT / "good_no_site_file"
        override = "some_fields.yaml"

        async with self.make_csc(
            initial_state=salobj.State.STANDBY, config_dir=config_dir
        ):
            await self.assert_next_summary_state(salobj.State.STANDBY)

            expected_overrides = ",".join(
                (
                    "all_fields.yaml",
                    "bad_extra_field.yaml",
                    "bad_field_type.yaml",
                    "bad_format.yaml",
                    "empty.yaml",
                    "some_fields.yaml",
                )
            )
            expected_config_url = pathlib.Path(config_dir).resolve().as_uri()
            data = await self.assert_next_sample(
                topic=self.remote.evt_configurationsAvailable,
                overrides=expected_overrides,
                url=expected_config_url,
                schemaVersion="v2",
            )
            assert len(data.version) > 0

            await self.remote.cmd_start.set_start(
                configurationOverride=override, timeout=STD_TIMEOUT
            )
            await self.assert_next_summary_state(salobj.State.DISABLED)

            config = self.csc.config
            override_path = os.path.join(self.csc.config_dir, override)
            with open(override_path, "r") as f:
                config_yaml = f.read()
            config_from_file = yaml.safe_load(config_yaml)
            for key, default_value in self.default_dict.items():
                if key in config_from_file:
                    assert getattr(config, key) == config_from_file[key]
                    assert getattr(config, key) != default_value
                else:
                    assert getattr(config, key) == default_value

            await self.assert_next_sample(
                topic=self.remote.evt_configurationApplied,
                configurations=f"_init.yaml,{override}",
            )

    async def test_override_with_hash(self) -> None:
        """Test an override specified by filename:hash."""
        config_dir = TEST_CONFIGS_ROOT / "good_no_site_file"
        override = "some_fields.yaml"

        async with self.make_csc(
            initial_state=salobj.State.STANDBY, config_dir=config_dir
        ):
            await self.assert_next_summary_state(salobj.State.STANDBY)
            await self.remote.cmd_start.set_start(
                configurationOverride=f"{override}:HEAD", timeout=STD_TIMEOUT
            )
            await self.assert_next_summary_state(salobj.State.DISABLED)
            config = self.csc.config
            override_path = os.path.join(self.csc.config_dir, override)
            with open(override_path, "r") as f:
                config_yaml = f.read()
            config_from_file = yaml.safe_load(config_yaml)
            for key, default_value in self.default_dict.items():
                if key in config_from_file:
                    assert getattr(config, key) == config_from_file[key]
                    assert getattr(config, key) != default_value
                else:
                    assert getattr(config, key) == default_value

            await self.assert_next_sample(
                topic=self.remote.evt_configurationApplied,
                configurations=f"_init.yaml,{override}",
            )

    async def test_minimal_config_dir(self) -> None:
        config_dir = TEST_CONFIGS_ROOT / "good_minimal"

        async with self.make_csc(
            initial_state=salobj.State.STANDBY, config_dir=config_dir
        ):
            await self.assert_next_summary_state(salobj.State.STANDBY)
            expected_config_url = pathlib.Path(config_dir).resolve().as_uri()
            data = await self.assert_next_sample(
                topic=self.remote.evt_configurationsAvailable,
                overrides="",
                url=expected_config_url,
                schemaVersion="v2",
            )
            assert len(data.version) > 0

            await self.remote.cmd_start.set_start(timeout=STD_TIMEOUT)
            await self.assert_next_summary_state(salobj.State.DISABLED)
            config = self.csc.config
            config_path = os.path.join(self.csc.config_dir, "_init.yaml")
            with open(config_path, "r") as f:
                config_yaml = f.read()
            config_from_file = yaml.safe_load(config_yaml)
            for key in self.config_fields:
                assert getattr(config, key) == config_from_file[key]

            await self.assert_next_sample(
                topic=self.remote.evt_configurationApplied,
                configurations="_init.yaml",
            )

    async def test_override_all_fields(self) -> None:
        """Test an override that sets all fields to valid values."""
        config_dir = TEST_CONFIGS_ROOT / "good_no_site_file"
        override = "all_fields.yaml"

        async with self.make_csc(
            initial_state=salobj.State.STANDBY, config_dir=config_dir
        ):
            await self.assert_next_summary_state(salobj.State.STANDBY)
            await self.remote.cmd_start.set_start(
                configurationOverride=override, timeout=STD_TIMEOUT
            )
            await self.assert_next_summary_state(salobj.State.DISABLED)
            config = self.csc.config
            override_path = os.path.join(self.csc.config_dir, override)
            with open(override_path, "r") as f:
                config_yaml = f.read()
            config_from_file = yaml.safe_load(config_yaml)
            for key in self.config_fields:
                assert getattr(config, key) == config_from_file[key]

            await self.assert_next_sample(
                topic=self.remote.evt_configurationApplied,
                configurations=f"_init.yaml,{override}",
            )

    async def test_invalid_configs(self) -> None:
        config_dir = TEST_CONFIGS_ROOT / "good_no_site_file"

        async with self.make_csc(
            initial_state=salobj.State.STANDBY, config_dir=config_dir
        ):
            await self.assert_next_summary_state(salobj.State.STANDBY)
            for name in ("all_bad_types", "bad_format", "one_bad_type", "extra_field"):
                config_file = f"invalid_{name}.yaml"
                with self.subTest(config_file=config_file):
                    with salobj.assertRaisesAckError(ack=salobj.SalRetCode.CMD_FAILED):
                        await self.remote.cmd_start.set_start(
                            configurationOverride=config_file, timeout=STD_TIMEOUT
                        )
                    data = self.remote.evt_summaryState.get()
                    assert self.csc.summary_state == salobj.State.STANDBY
                    assert data.summaryState == salobj.State.STANDBY

            # Make sure the CSC can still be started.
            await self.remote.cmd_start.set_start(
                configurationOverride="all_fields.yaml", timeout=10
            )
            assert self.csc.summary_state == salobj.State.DISABLED
            await self.assert_next_summary_state(salobj.State.DISABLED)
