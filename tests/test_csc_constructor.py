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

import pathlib
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
# Long to avoid unnecessary timeouts on slow CI systems.
STD_TIMEOUT = 60


class InvalidPkgNameCsc(salobj.TestCsc):
    """A CSC whose get_pkg_name classmethod returns a nonexistent package."""

    @staticmethod
    def get_config_pkg() -> str:
        """Return a name of a non-existent package."""
        return "not_a_valid_pkg_name"


class MissingVersionCsc(salobj.BaseCsc):
    """A CSC with no ``version`` class variable."""

    valid_simulation_modes = (0,)

    def __init__(self, index: int) -> None:
        super().__init__(name="Test", index=index)


class ValidSimulationModesNoneCsc(salobj.TestCsc):
    """A CSC with ``valid_simulation_modes = None``."""

    valid_simulation_modes = None


class WrongConfigPkgCsc(salobj.TestCsc):
    """A CSC whose get_pkg_name classmethod returns the wrong package."""

    @staticmethod
    def get_config_pkg() -> str:
        """Return a package that does not have a Test subdirectory."""
        return "ts_salobj"


class MissingDoMethodCsc(salobj.BaseCsc):
    """A CSC that is missing one or more do_ methods."""

    version = "a version"

    def __init__(self, index: int, allow_missing_callbacks: bool) -> None:
        super().__init__(
            name="Test", index=index, allow_missing_callbacks=allow_missing_callbacks
        )


class TestCscConstructorTestCase(
    salobj.BaseCscTestCase, unittest.IsolatedAsyncioTestCase
):
    """Test the TestCsc constructor.

    Note: all of these tests must run async because the constructor
    requires an event loop.
    """

    def basic_make_csc(
        self,
        initial_state: salobj.State | int,
        config_dir: str | pathlib.Path | None,
        simulation_mode: int,
    ) -> salobj.BaseCsc:
        return salobj.TestCsc(
            self.next_index(),
            initial_state=initial_state,
            config_dir=config_dir,
            simulation_mode=simulation_mode,
        )

    def run(self, result: typing.Any) -> None:  # type: ignore
        """Override `run` to set a random LSST_TOPIC_SUBNAME
        and set LSST_SITE=test for every test.

        https://stackoverflow.com/a/11180583
        """
        salobj.set_test_topic_subname()
        with utils.modify_environ(LSST_SITE="test"):
            super().run(result)

    async def test_class_attributes(self) -> None:
        assert list(salobj.TestCsc.valid_simulation_modes) == [0]
        assert salobj.TestCsc.version == salobj.__version__

    async def test_initial_state(self) -> None:
        """Test all allowed initial_state values, both as enums and ints."""
        for initial_state in salobj.State:
            if initial_state == salobj.State.FAULT:
                continue
            with self.subTest(initial_state=initial_state):
                await self.check_initial_state(initial_state)
                await self.check_initial_state(int(initial_state))

    async def check_initial_state(self, initial_state: salobj.State) -> None:
        """Check that specifying the initial_state constructur argument
        sets the initial reported state to match.
        """
        index = next(index_gen)
        async with salobj.TestCsc(index=index, initial_state=int(initial_state)) as csc:
            assert csc.summary_state == initial_state

    async def test_invalid_config_dir(self) -> None:
        """Test that invalid integer initial_state is rejected."""
        with pytest.raises(ValueError):
            salobj.TestCsc(
                index=next(index_gen),
                initial_state=salobj.State.STANDBY,
                config_dir=TEST_CONFIG_DIR / "not_a_directory",
            )

    async def test_invalid_config_pkg(self) -> None:
        with pytest.raises(RuntimeError):
            InvalidPkgNameCsc(index=next(index_gen), initial_state=salobj.State.STANDBY)

    async def test_wrong_config_pkg(self) -> None:
        with pytest.raises(RuntimeError):
            WrongConfigPkgCsc(index=next(index_gen), initial_state=salobj.State.STANDBY)

    async def test_invalid_initial_state(self) -> None:
        """Test that invalid integer initial_state is rejected."""
        for invalid_state in (
            salobj.State.FAULT,
            min(salobj.State) - 1,
            max(salobj.State) + 1,
        ):
            with self.subTest(invalid_state=invalid_state):
                with pytest.raises(ValueError):
                    salobj.TestCsc(index=next(index_gen), initial_state=invalid_state)

    async def test_late_callback_assignment(self) -> None:
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
                assert topic.callback is None

            await csc.start_task
            for topic in cmd_topics:
                assert topic.callback is not None
        finally:
            await csc.close()

    async def test_missing_version(self) -> None:
        index = next(index_gen)
        with pytest.raises(RuntimeError):
            MissingVersionCsc(index=index)

    async def test_missing_callbacks(self) -> None:
        index = next(index_gen)
        with pytest.raises(TypeError):
            MissingDoMethodCsc(index=index, allow_missing_callbacks=False)

        index = next(index_gen)
        async with MissingDoMethodCsc(index=index, allow_missing_callbacks=True) as csc:
            for command_topic in (
                csc.cmd_setArrays,
                csc.cmd_setScalars,
                csc.cmd_wait,
                csc.cmd_fault,
            ):
                assert command_topic.callback == csc._unsupported_cmd_callback

    async def test_valid_simulation_modes_none(self) -> None:
        index = next(index_gen)
        with pytest.raises(RuntimeError):
            ValidSimulationModesNoneCsc(index=index)

    async def test_check_if_duplicate(self) -> None:
        index = next(index_gen)
        csc = salobj.TestCsc(index=index)
        assert not csc.check_if_duplicate
        await csc.close()

        for check_if_duplicate in (False, True):
            with self.subTest(check_if_duplicate=check_if_duplicate):
                index = next(index_gen)
                csc = salobj.TestCsc(index=index, check_if_duplicate=check_if_duplicate)
                assert csc.check_if_duplicate == check_if_duplicate
                await csc.close()
