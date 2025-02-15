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
import enum
import os
import pathlib
import sys
import typing
import unittest

import numpy as np
import pytest
from lsst.ts import salobj, utils

np.random.seed(47)

index_gen = utils.index_generator()
TEST_DATA_DIR = pathlib.Path(__file__).resolve().parent / "data"
TEST_CONFIG_DIR = TEST_DATA_DIR / "configs" / "good_no_site_file"

# Standard timeout (sec)
STD_TIMEOUT = 60


class NoIndexCsc(salobj.TestCsc):
    """A CSC whose constructor has no index argument."""

    def __init__(
        self,
        arg1: typing.Any,
        arg2: typing.Any,
        initial_state: salobj.State = salobj.State.STANDBY,
        override: str = "",
        config_dir: str | pathlib.Path | None = None,
    ) -> None:
        super().__init__(
            index=next(index_gen),
            initial_state=initial_state,
            override=override,
            config_dir=config_dir,
        )
        self.arg1 = arg1
        self.arg2 = arg2


class CscMakeFromCmdLineTestCase(unittest.IsolatedAsyncioTestCase):
    def run(self, result: typing.Any = None) -> None:  # type: ignore
        """Override `run` to set a random LSST_TOPIC_SUBNAME
        and set LSST_SITE=test for every test.

        https://stackoverflow.com/a/11180583
        """
        salobj.set_test_topic_subname()
        with utils.modify_environ(LSST_SITE="test"):
            super().run(result)

    async def test_no_index(self) -> None:
        for index in (0, None):
            with self.subTest(index=index):
                sys.argv = [sys.argv[0]]
                arg1 = "astring"
                arg2 = 2.75
                async with NoIndexCsc.make_from_cmd_line(
                    index=index, arg1=arg1, arg2=arg2
                ) as csc:
                    assert csc.arg1 == arg1
                    assert csc.arg2 == arg2

    async def test_specified_index(self) -> None:
        sys.argv = [sys.argv[0]]
        index = next(index_gen)
        async with salobj.TestCsc.make_from_cmd_line(index=index) as csc:
            assert csc.salinfo.index == index

    async def test_duplicate_rejection(self) -> None:
        sys.argv = [sys.argv[0]]
        index = next(index_gen)
        async with salobj.TestCsc.make_from_cmd_line(index=index) as csc:
            assert csc.salinfo.index == index
            assert not csc.check_if_duplicate
            await asyncio.wait_for(csc.start_task, timeout=STD_TIMEOUT)

            duplicate_csc = salobj.TestCsc.make_from_cmd_line(
                index=index, check_if_duplicate=True
            )
            try:
                # Change origin so heartbeat private_origin differs.
                duplicate_csc.salinfo.domain.origin += 1
                assert duplicate_csc.salinfo.index == index
                assert duplicate_csc.check_if_duplicate
                with pytest.raises(
                    salobj.ExpectedError, match="found another instance"
                ):
                    await asyncio.wait_for(duplicate_csc.done_task, timeout=STD_TIMEOUT)
            finally:
                await duplicate_csc.close()

    async def test_enum_index(self) -> None:
        class SalIndex(enum.IntEnum):
            ONE = 1
            TWO = 2

        for item in SalIndex:
            index = item.value
            sys.argv = [sys.argv[0], str(index)]
            async with salobj.TestCsc.make_from_cmd_line(index=SalIndex) as csc:
                assert csc.salinfo.index == index

    async def test_index_from_argument_and_default_config_dir(self) -> None:
        index = next(index_gen)
        sys.argv = [sys.argv[0], str(index)]
        async with salobj.TestCsc.make_from_cmd_line(index=True) as csc:
            assert csc.salinfo.index == index

            desired_config_pkg_name = "ts_config_ocs"
            desired_config_env_name = desired_config_pkg_name.upper() + "_DIR"
            desired_config_pkg_dir = os.environ[desired_config_env_name]
            desired_config_dir = pathlib.Path(desired_config_pkg_dir) / "Test/v2"
            assert csc.get_config_pkg() == desired_config_pkg_name
            assert csc.config_dir == desired_config_dir

    async def test_config_from_argument(self) -> None:
        index = next(index_gen)
        sys.argv = [sys.argv[0], str(index), "--configdir", str(TEST_CONFIG_DIR)]
        async with salobj.TestCsc.make_from_cmd_line(index=True) as csc:
            assert csc.salinfo.index == index
            assert csc.config_dir == TEST_CONFIG_DIR

    async def test_state_good(self) -> None:
        """Test valid --state and --override arguments."""
        for state, override in (
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
                "--configdir",
                str(TEST_CONFIG_DIR),
                "--state",
                state_name,
                "--override",
                override,
            ]
            async with salobj.TestCsc.make_from_cmd_line(index=True) as csc:
                assert csc.salinfo.index == index
                assert csc.summary_state == state
                if state not in (salobj.State.DISABLED, salobj.State.ENABLED):
                    # Configuration not applied.
                    assert csc.config is None
                elif override == "all_fields.yaml":
                    assert csc.config.string0 == "an arbitrary string"
                elif override == "":
                    assert csc.config.string0 == "default value for string0"
                else:
                    self.fail("Unhandled case.")

    async def test_state_bad(self) -> None:
        """Test invalid --state or --override arguments."""
        # The only allowed --state values are "standby", "disabled",
        # and "enabled".
        for bad_state_name in ("fault", "not_a_state"):
            index = next(index_gen)
            sys.argv = [sys.argv[0], str(index), "--state", bad_state_name]
            with pytest.raises(SystemExit):
                salobj.TestCsc.make_from_cmd_line(index=True)
