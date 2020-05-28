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

import asyncio
import itertools
import logging
import os
import pathlib
import sys
import unittest

import asynctest
import numpy as np
import yaml

from lsst.ts import salobj

# Long enough to perform any reasonable operation
# including starting a CSC or loading a script (seconds)
STD_TIMEOUT = 60
# Timeout for when we expect no new data (seconds).
NODATA_TIMEOUT = 0.1

np.random.seed(47)

index_gen = salobj.index_generator()
TEST_DATA_DIR = TEST_CONFIG_DIR = pathlib.Path(__file__).resolve().parent / "data"
TEST_CONFIG_DIR = TEST_DATA_DIR / "config"


class FailInReportFaultCsc(salobj.TestCsc):
    """A Test CSC that fails in report_summary_state when reporting fault.

    This CSC always starts up in the ENABLED state.

    Used to test for infinite loops and other issues when something
    goes wrong while going to the fault state.

    Parameters
    ----------
    index : `int`
        SAL index.
    doraise : `bool`
        Raise in report_summary_state?
        If false then call fault instead.
    report_first : `bool`
        Call super().report_summary_state first in report_summary_state?
        If false then call it last.
    """

    def __init__(self, index, doraise, report_first):
        super().__init__(index=index, initial_state=salobj.State.ENABLED)
        self.doraise = doraise
        self.report_first = report_first

    def report_summary_state(self):
        if self.report_first:
            super().report_summary_state()
        if self.summary_state == salobj.State.FAULT:
            if self.doraise:
                raise RuntimeError(
                    "Intentionally raise an exception when going to the FAULT state"
                )
            else:
                self.fault(
                    code=10934,
                    report="a report that will be ignored",
                    traceback="a traceback that will be ignored",
                )
        if not self.report_first:
            super().report_summary_state()


class CommunicateTestCase(salobj.BaseCscTestCase, asynctest.TestCase):
    def basic_make_csc(self, initial_state, config_dir, simulation_mode):
        return salobj.TestCsc(
            self.next_index(),
            initial_state=initial_state,
            config_dir=config_dir,
            simulation_mode=simulation_mode,
        )

    async def test_heartbeat(self):
        async with self.make_csc(initial_state=salobj.State.STANDBY):
            self.csc.heartbeat_interval = 0.1
            await self.remote.evt_heartbeat.next(flush=True, timeout=STD_TIMEOUT)
            await self.remote.evt_heartbeat.next(flush=True, timeout=0.2)
            await self.remote.evt_heartbeat.next(flush=True, timeout=0.2)
            await self.remote.evt_heartbeat.next(flush=True, timeout=0.2)

    async def test_bin_script(self):
        """Test running the Test CSC from the bin script.

        Note that the bin script calls class method ``amain``.
        """
        index = self.next_index()
        await self.check_bin_script(
            name="Test", index=index, exe_name="run_test_csc.py"
        )

    async def test_deprecated_main(self):
        """Test running from cmd line using deprecated class method ``main``.
        """
        exe_path = TEST_DATA_DIR / "run_test_using_deprecated_main.py"

        index = self.next_index()
        process = await asyncio.create_subprocess_exec(str(exe_path), str(index))
        try:
            async with salobj.Domain() as domain, salobj.Remote(
                domain=domain, name="Test", index=index
            ) as remote:
                await self.assert_next_summary_state(
                    salobj.State.STANDBY, remote=remote, timeout=STD_TIMEOUT
                )

                ackcmd = await remote.cmd_exitControl.start(timeout=STD_TIMEOUT)
                self.assertEqual(ackcmd.ack, salobj.SalRetCode.CMD_COMPLETE)
                await self.assert_next_summary_state(
                    salobj.State.OFFLINE, remote=remote
                )

                await asyncio.wait_for(process.wait(), 5)
        except Exception:
            if process.returncode is None:
                process.terminate()
            raise

    async def test_log_level(self):
        """Test that specifying a log level to make_csc works."""
        # If specified then log level is the value given.
        async with self.make_csc(
            initial_state=salobj.State.STANDBY, log_level=logging.DEBUG
        ):
            self.assertEqual(self.csc.log.getEffectiveLevel(), logging.DEBUG)

        async with self.make_csc(
            initial_state=salobj.State.STANDBY, log_level=logging.WARNING
        ):
            self.assertEqual(self.csc.log.getEffectiveLevel(), logging.WARNING)

        # At this point log level is WARNING; now check that by default
        # log verbosity is increased (log level decreased) to INFO.
        async with self.make_csc(initial_state=salobj.State.STANDBY):
            self.assertEqual(self.csc.log.getEffectiveLevel(), logging.INFO)

    async def test_setArrays_command(self):
        async with self.make_csc(initial_state=salobj.State.ENABLED):
            # until the controller gets its first setArrays
            # it will not send any arrays events or telemetry
            self.assertFalse(self.csc.evt_arrays.has_data)
            self.assertFalse(self.csc.tel_arrays.has_data)
            self.assertFalse(self.remote.evt_arrays.has_data)
            self.assertFalse(self.remote.tel_arrays.has_data)
            self.assertIsNone(self.remote.evt_arrays.get())
            self.assertIsNone(self.remote.tel_arrays.get())

            # check that info level messages are enabled
            await self.assert_next_sample(
                topic=self.remote.evt_logLevel, level=logging.INFO
            )

            # purge any existing messages
            self.remote.evt_logMessage.flush()

            # send the setArrays command with random data
            cmd_data_sent = self.csc.make_random_cmd_arrays()
            await self.remote.cmd_setArrays.start(cmd_data_sent, timeout=STD_TIMEOUT)

            log_message = await self.remote.evt_logMessage.next(
                flush=False, timeout=STD_TIMEOUT
            )
            self.assertEqual(log_message.level, logging.INFO)
            self.assertIn("setArrays", log_message.message)

            # see if new data was broadcast correctly
            evt_data = await self.remote.evt_arrays.next(
                flush=False, timeout=STD_TIMEOUT
            )
            self.csc.assert_arrays_equal(cmd_data_sent, evt_data)
            tel_data = await self.remote.tel_arrays.next(
                flush=False, timeout=STD_TIMEOUT
            )
            self.csc.assert_arrays_equal(cmd_data_sent, tel_data)

            self.assertTrue(self.csc.evt_arrays.has_data)
            self.assertTrue(self.csc.tel_arrays.has_data)
            self.assertTrue(self.remote.evt_arrays.has_data)
            self.assertTrue(self.remote.tel_arrays.has_data)

            # also test get
            self.csc.assert_arrays_equal(cmd_data_sent, self.remote.tel_arrays.get())
            self.csc.assert_arrays_equal(cmd_data_sent, self.remote.evt_arrays.get())

    async def test_setScalars_command(self):
        async with self.make_csc(initial_state=salobj.State.ENABLED):
            # until the controller gets its first setArrays
            # it will not send any arrays events or telemetry
            self.assertFalse(self.csc.evt_scalars.has_data)
            self.assertFalse(self.csc.tel_scalars.has_data)
            self.assertFalse(self.remote.evt_scalars.has_data)
            self.assertFalse(self.remote.tel_scalars.has_data)
            self.assertIsNone(self.remote.evt_scalars.get())
            self.assertIsNone(self.remote.tel_scalars.get())

            # check that info level messages are enabled
            await self.assert_next_sample(
                topic=self.remote.evt_logLevel, level=logging.INFO
            )

            # purge any existing messages
            self.remote.evt_logMessage.flush()

            # send the setScalars command with random data
            cmd_data_sent = self.csc.make_random_cmd_scalars()
            await self.remote.cmd_setScalars.start(cmd_data_sent, timeout=STD_TIMEOUT)
            log_message = await self.remote.evt_logMessage.next(
                flush=False, timeout=STD_TIMEOUT
            )
            self.assertEqual(log_message.level, logging.INFO)
            self.assertIn("setScalars", log_message.message)

            # see if new data is being broadcast correctly
            evt_data = await self.remote.evt_scalars.next(
                flush=False, timeout=STD_TIMEOUT
            )
            self.csc.assert_scalars_equal(cmd_data_sent, evt_data)
            tel_data = await self.remote.tel_scalars.next(
                flush=False, timeout=STD_TIMEOUT
            )
            self.csc.assert_scalars_equal(cmd_data_sent, tel_data)

            self.assertTrue(self.csc.evt_scalars.has_data)
            self.assertTrue(self.csc.tel_scalars.has_data)
            self.assertTrue(self.remote.evt_scalars.has_data)
            self.assertTrue(self.remote.tel_scalars.has_data)

            # also test get
            self.csc.assert_scalars_equal(cmd_data_sent, self.remote.tel_scalars.get())
            self.csc.assert_scalars_equal(cmd_data_sent, self.remote.evt_scalars.get())

    async def test_fault_state_transitions(self):
        """Test CSC state transitions into fault and out again.

        Going into the fault state is done via the ``fault`` command.
        """
        for initial_state in salobj.State:
            if initial_state == salobj.State.OFFLINE:
                # Not a valid initial state
                continue
            if initial_state == salobj.State.FAULT:
                # The ``fault`` command does nothing if TestCsc
                # is already in the FAULT state
                continue
            with self.subTest(initial_state=initial_state):
                async with self.make_csc(initial_state=initial_state):
                    await self.assert_next_summary_state(initial_state)

                    # Issue the ``fault`` command
                    # and check the state and error code.
                    await self.remote.cmd_fault.start(timeout=STD_TIMEOUT)
                    await self.assert_next_summary_state(salobj.State.FAULT)
                    await self.assert_next_sample(
                        topic=self.remote.evt_errorCode, errorCode=1
                    )

                    # Issue the ``standby`` command to recover.
                    await self.remote.cmd_standby.start(timeout=STD_TIMEOUT)
                    await self.assert_next_summary_state(salobj.State.STANDBY)

    async def test_fault_method(self):
        """Test BaseCsc.fault with and without optional arguments."""
        async with self.make_csc(initial_state=salobj.State.STANDBY):
            await self.assert_next_summary_state(salobj.State.STANDBY)
            with self.assertRaises(asyncio.TimeoutError):
                await self.remote.evt_errorCode.next(
                    flush=False, timeout=NODATA_TIMEOUT
                )

            code = 52
            report = "Report for error code"
            traceback = "Traceback for error code"

            # if code not specified (deprecated) then errorCode is not output
            with self.assertWarns(DeprecationWarning):
                self.csc.fault()
            await self.assert_next_summary_state(salobj.State.FAULT)
            with self.assertRaises(asyncio.TimeoutError):
                await self.remote.evt_errorCode.next(
                    flush=False, timeout=NODATA_TIMEOUT
                )

            await self.remote.cmd_standby.start(timeout=STD_TIMEOUT)
            await self.assert_next_summary_state(salobj.State.STANDBY)

            # if code not specified (deprecated) then errorCode is not output
            with self.assertWarns(DeprecationWarning):
                self.csc.fault(report=report, traceback=traceback)
            await self.assert_next_summary_state(salobj.State.FAULT)
            with self.assertRaises(asyncio.TimeoutError):
                await self.remote.evt_errorCode.next(
                    flush=False, timeout=NODATA_TIMEOUT
                )

            await self.remote.cmd_standby.start(timeout=STD_TIMEOUT)
            await self.assert_next_summary_state(salobj.State.STANDBY)

            # if an invalid code is specified then errorCode is not output
            # but the CSC stil goes into a FAULT state
            self.csc.fault(code="not a valid code")
            await self.assert_next_summary_state(salobj.State.FAULT)
            with self.assertRaises(asyncio.TimeoutError):
                await self.remote.evt_errorCode.next(
                    flush=False, timeout=NODATA_TIMEOUT
                )

            await self.remote.cmd_standby.start(timeout=STD_TIMEOUT)
            await self.assert_next_summary_state(salobj.State.STANDBY)

            # if code is specified then errorReport is output;
            # first test with report and traceback specified,
            # then without, to make sure those values are not cached
            self.csc.fault(code=code, report=report, traceback=traceback)
            await self.assert_next_summary_state(salobj.State.FAULT)
            await self.assert_next_sample(
                topic=self.remote.evt_errorCode,
                errorCode=code,
                errorReport=report,
                traceback=traceback,
            )

            # Try a disallowed command and check that the error report
            # is part of the traceback.
            with salobj.assertRaisesAckError(result_contains=report):
                await self.remote.cmd_wait.set_start(duration=5, timeout=STD_TIMEOUT)

            await self.remote.cmd_standby.start(timeout=STD_TIMEOUT)
            await self.assert_next_summary_state(salobj.State.STANDBY)

            self.csc.fault(code=code)
            await self.assert_next_summary_state(salobj.State.FAULT)
            await self.assert_next_sample(
                topic=self.remote.evt_errorCode,
                errorCode=code,
                errorReport="",
                traceback="",
            )

            await self.remote.cmd_standby.start(timeout=STD_TIMEOUT)
            await self.remote.cmd_exitControl.start(timeout=STD_TIMEOUT)

    async def test_fault_problems(self):
        """Test BaseCsc.fault when report_summary_state misbehaves."""
        index = next(index_gen)
        for doraise, report_first in itertools.product((False, True), (False, True)):
            with self.subTest(doraise=doraise, report_first=report_first):
                async with FailInReportFaultCsc(
                    index=index, doraise=doraise, report_first=report_first
                ) as csc, salobj.Remote(
                    domain=csc.domain, name="Test", index=index
                ) as remote:
                    await self.assert_next_summary_state(
                        salobj.State.ENABLED, remote=remote
                    )

                    code = 51
                    report = "Report for error code"
                    traceback = "Traceback for error code"
                    csc.fault(code=code, report=report, traceback=traceback)

                    await self.assert_next_summary_state(
                        salobj.State.FAULT, remote=remote
                    )
                    await self.assert_next_sample(
                        topic=remote.evt_errorCode,
                        errorCode=code,
                        errorReport=report,
                        traceback=traceback,
                    )

                    # make sure FAULT state and errorCode are only sent once
                    with self.assertRaises(asyncio.TimeoutError):
                        await remote.evt_summaryState.next(
                            flush=False, timeout=NODATA_TIMEOUT
                        )
                    with self.assertRaises(asyncio.TimeoutError):
                        await remote.evt_errorCode.next(
                            flush=False, timeout=NODATA_TIMEOUT
                        )

    async def test_make_csc_timeout(self):
        """Test that setting the timeout argument to make_csc works.
        """
        with self.assertRaises(asyncio.TimeoutError):
            # Use such a short timeout that make_csc times out
            async with self.make_csc(initial_state=salobj.State.STANDBY, timeout=0):
                pass

    async def test_standard_state_transitions(self):
        """Test standard CSC state transitions.

        The initial state is STANDBY.
        The standard commands and associated state transitions are:

        * start: STANDBY to DISABLED
        * enable: DISABLED to ENABLED

        * disable: ENABLED to DISABLED
        * standby: DISABLED or FAULT to STANDBY
        * exitControl: STANDBY to OFFLINE (quit)
        """
        async with self.make_csc(initial_state=salobj.State.STANDBY):
            await self.check_standard_state_transitions(
                enabled_commands=("setArrays", "setScalars", "wait"),
                skip_commands=("fault",),
            )


class NoIndexCsc(salobj.TestCsc):
    """A CSC whose constructor has no index argument."""

    def __init__(self, arg1, arg2, config_dir=None):
        super().__init__(index=next(index_gen), config_dir=config_dir)
        self.arg1 = arg1
        self.arg2 = arg2


class SeveralSimulationModesCsc(salobj.TestCsc):
    """A variant of TestCsc with several allowed simulation modes."""

    AllowedSimulationModes = (0, 1, 3)

    async def implement_simulation_mode(self, simulation_mode):
        if simulation_mode not in self.AllowedSimulationModes:
            raise salobj.ExpectedError(f"invalid simulation_mode={simulation_mode}")


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
        salobj.set_random_lsst_dds_domain()

    async def test_initial_state(self):
        """Test all allowed initial_state values, both as enums and ints."""
        for initial_state in salobj.State:
            if initial_state == salobj.State.OFFLINE:
                continue
            with self.subTest(initial_state=initial_state):
                # Test initial_state as an enum.
                index = next(index_gen)
                async with salobj.TestCsc(
                    index=index, initial_state=initial_state
                ) as csc:
                    self.assertEqual(csc.summary_state, initial_state)

                # Test initial_state as an integer.
                index = next(index_gen)
                async with salobj.TestCsc(
                    index=index, initial_state=int(initial_state)
                ) as csc:
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

    async def test_simulation_mode(self):
        """Test simulation_mode and initial_simulation_mode constructor
        arguments.
        """
        # Test valid simulation modes.
        for simulation_mode in SeveralSimulationModesCsc.AllowedSimulationModes:
            with self.subTest(simulation_mode=simulation_mode):
                async with SeveralSimulationModesCsc(
                    index=1, config_dir=TEST_CONFIG_DIR, simulation_mode=simulation_mode
                ) as csc:
                    await csc.start_task
                    self.assertEqual(csc.simulation_mode, simulation_mode)

                if simulation_mode == 0:
                    # No deprecation warning expected.
                    async with SeveralSimulationModesCsc(
                        index=1,
                        config_dir=TEST_CONFIG_DIR,
                        initial_simulation_mode=simulation_mode,
                    ) as csc:
                        await csc.start_task
                        self.assertEqual(csc.simulation_mode, simulation_mode)
                else:
                    # Deprecation warning expected.
                    with self.assertWarns(DeprecationWarning):
                        async with SeveralSimulationModesCsc(
                            index=1,
                            config_dir=TEST_CONFIG_DIR,
                            initial_simulation_mode=simulation_mode,
                        ) as csc:
                            await csc.start_task
                            self.assertEqual(csc.simulation_mode, simulation_mode)

        # Test that simulation_mode and initial_simulation_mode cannot both be
        # nonzero. This is caught by the constructor, so there is no need to
        # wait for the CSC to start.
        for mode1, mode2 in itertools.product((1, 2), (1, 2)):
            with self.subTest(mode1=mode1, mode2=mode2):
                with self.assertRaises(ValueError):
                    SeveralSimulationModesCsc(
                        index=1,
                        config_dir=TEST_CONFIG_DIR,
                        simulation_mode=mode1,
                        initial_simulation_mode=mode2,
                    )

        # Test invalid simulation modes. These are are caught by the
        # ``implement_simulation_mode`` method, which is called by the
        # ``start`` method, so we must wait for the CSC to start.
        for bad_simulation_mode in (
            min(SeveralSimulationModesCsc.AllowedSimulationModes) - 1,
            max(SeveralSimulationModesCsc.AllowedSimulationModes) + 1,
        ):
            with self.subTest(bad_simulation_mode=bad_simulation_mode):
                with self.assertRaises(salobj.ExpectedError):
                    async with SeveralSimulationModesCsc(
                        index=1,
                        config_dir=TEST_CONFIG_DIR,
                        simulation_mode=bad_simulation_mode,
                    ):
                        pass

                # The constructor issues a deprecation warning,
                # then later the ``start`` method raises.
                with self.assertWarns(DeprecationWarning):
                    with self.assertRaises(salobj.ExpectedError):
                        async with SeveralSimulationModesCsc(
                            index=1,
                            config_dir=TEST_CONFIG_DIR,
                            initial_simulation_mode=bad_simulation_mode,
                        ):
                            pass

    async def test_wrong_config_pkg(self):
        with self.assertRaises(RuntimeError):
            WrongConfigPkgCsc(index=next(index_gen), initial_state=salobj.State.STANDBY)

    async def test_invalid_initial_state(self):
        """Test that invalid integer initial_state is rejected."""
        for invalid_state in (min(salobj.State) - 1, max(salobj.State) + 1):
            with self.subTest(invalid_state=invalid_state):
                with self.assertRaises(ValueError):
                    salobj.TestCsc(index=next(index_gen), initial_state=invalid_state)


class ConfigurationTestCase(salobj.BaseCscTestCase, asynctest.TestCase):
    def setUp(self):
        # defaults hard-coded in <ts_salobj_root>/schema/Test.yaml
        self.default_dict = dict(
            string0="default value for string0",
            bool0=True,
            int0=5,
            float0=3.14,
            intarr0=[-1, 1],
        )
        self.config_fields = self.default_dict.keys()

    def basic_make_csc(self, initial_state, config_dir, simulation_mode):
        return salobj.TestCsc(
            self.next_index(),
            initial_state=initial_state,
            config_dir=config_dir,
            simulation_mode=simulation_mode,
        )

    async def check_settings_events(self, config_file):
        """Check the settingsApplied and appliedSettingsMatchStart events.

        Parameters
        ----------
        config_file : `str`
            The name of the config file, or "" if none specified.
        """
        # settingsVersion.settingsApplied should start with
        # the config file name followed by a colon
        data = await self.assert_next_sample(topic=self.remote.evt_settingsApplied,)
        desired_prefix = config_file + ":"
        self.assertEqual(data.settingsVersion[: len(desired_prefix)], desired_prefix)

        # appliedSettingsMatchStartIsTrue.appliedSettingsMatchStartIsTrue
        # should be True after being configured.
        await self.assert_next_sample(
            topic=self.remote.evt_appliedSettingsMatchStart,
            appliedSettingsMatchStartIsTrue=True,
        )

    async def test_no_config_specified(self):
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
            kwargs = dict()
            if self.remote.salinfo.metadata.xml_version is not None:
                kwargs["xmlVersion"] = self.remote.salinfo.metadata.xml_version
            if self.remote.salinfo.metadata.sal_version is not None:
                kwargs["salVersion"] = self.remote.salinfo.metadata.sal_version
            await self.assert_next_sample(
                topic=self.remote.evt_softwareVersions, **kwargs
            )

            await self.check_settings_events("")

    async def test_default_config_dir(self):
        async with self.make_csc(initial_state=salobj.State.STANDBY, config_dir=None):
            await self.assert_next_summary_state(salobj.State.STANDBY)
            data = await self.remote.evt_settingVersions.next(
                flush=False, timeout=STD_TIMEOUT
            )
            self.assertTrue(len(data.recommendedSettingsVersion) > 0)
            self.assertEqual(data.settingsUrl[0:8], "file:///")
            config_path = pathlib.Path(data.settingsUrl[7:])
            self.assertTrue(config_path.samefile(self.csc.config_dir))

    async def test_empty_label(self):
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

    async def test_some_fields_label(self):
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

    async def test_some_fields_file_no_hash(self):
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

    async def test_some_fields_file_with_hash(self):
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

    async def test_all_fields_label(self):
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

    async def test_invalid_configs(self):
        async with self.make_csc(
            initial_state=salobj.State.STANDBY, config_dir=TEST_CONFIG_DIR
        ):
            await self.assert_next_summary_state(salobj.State.STANDBY)
            for name in ("all_bad_types", "bad_format", "one_bad_type", "extra_field"):
                config_file = f"invalid_{name}.yaml"
                with self.subTest(config_file=config_file):
                    with self.assertRaises(salobj.AckError):
                        await self.remote.cmd_start.set_start(
                            settingsToApply=config_file, timeout=STD_TIMEOUT
                        )
                    data = self.remote.evt_summaryState.get()
                    self.assertEqual(self.csc.summary_state, salobj.State.STANDBY)
                    self.assertEqual(data.summaryState, salobj.State.STANDBY)


class FailedCallbackCsc(salobj.TestCsc):
    """A CSC whose do_wait command raises a RuntimeError"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.exc_msg = "do_wait raised an exception on purpose"

    async def do_wait(self, data):
        raise RuntimeError(self.exc_msg)


class ControllerCommandLoggingTestCase(salobj.BaseCscTestCase, asynctest.TestCase):
    def basic_make_csc(self, initial_state, config_dir, simulation_mode):
        return FailedCallbackCsc(
            initial_state=initial_state,
            index=self.next_index(),
            config_dir=config_dir,
            simulation_mode=simulation_mode,
        )

    async def test_logging(self):
        async with self.make_csc(
            initial_state=salobj.State.ENABLED, config_dir=TEST_CONFIG_DIR
        ):
            logLevel = await self.remote.evt_logLevel.next(
                flush=False, timeout=STD_TIMEOUT
            )
            self.assertEqual(logLevel.level, logging.INFO)

            # purge any existing messages
            self.remote.evt_logMessage.flush()

            info_message = "test info message"
            self.csc.log.info(info_message)
            msg = await self.remote.evt_logMessage.next(
                flush=False, timeout=STD_TIMEOUT
            )
            self.assertEqual(msg.message, info_message)
            self.assertEqual(msg.level, logging.INFO)
            self.assertEqual(msg.traceback, "")
            self.assertTrue(
                msg.filePath.endswith("tests/test_csc.py"),
                f"{msg.filePath} does not end with " f"'tests/test_csc.py'",
            )
            self.assertEqual(msg.functionName, "test_logging")
            self.assertGreater(msg.lineNumber, 0)
            self.assertEqual(msg.process, os.getpid())

            warn_message = "test warn message"
            self.csc.log.warning(warn_message)
            msg = await self.remote.evt_logMessage.next(
                flush=False, timeout=STD_TIMEOUT
            )
            self.assertEqual(msg.message, warn_message)
            self.assertEqual(msg.level, logging.WARNING)
            self.assertEqual(msg.traceback, "")

            with self.assertRaises(asyncio.TimeoutError):
                await self.remote.evt_logMessage.next(
                    flush=False, timeout=NODATA_TIMEOUT
                )

            await self.remote.cmd_setLogLevel.set_start(
                level=logging.ERROR, timeout=STD_TIMEOUT
            )

            logLevel = await self.remote.evt_logLevel.next(
                flush=False, timeout=STD_TIMEOUT
            )
            self.assertEqual(logLevel.level, logging.ERROR)

            info_message = "test info message"
            self.csc.log.info(info_message)
            with self.assertRaises(asyncio.TimeoutError):
                await self.remote.evt_logMessage.next(
                    flush=False, timeout=NODATA_TIMEOUT
                )

            warn_message = "test warn message"
            self.csc.log.warning(warn_message)
            with self.assertRaises(asyncio.TimeoutError):
                await self.remote.evt_logMessage.next(
                    flush=False, timeout=NODATA_TIMEOUT
                )

            with salobj.assertRaisesAckError():
                await self.remote.cmd_wait.set_start(duration=5, timeout=STD_TIMEOUT)

            msg = await self.remote.evt_logMessage.next(
                flush=False, timeout=STD_TIMEOUT
            )
            self.assertIn(self.csc.exc_msg, msg.traceback)
            self.assertIn("Traceback", msg.traceback)
            self.assertIn("RuntimeError", msg.traceback)
            self.assertEqual(msg.level, logging.ERROR)
            self.assertTrue(msg.filePath.endswith("topics/controller_command.py"))
            self.assertNotEqual(msg.functionName, "")
            self.assertGreater(msg.lineNumber, 0)
            self.assertEqual(msg.process, os.getpid())


class BaseCscMakeFromCmdLineTestCase(asynctest.TestCase):
    def setUp(self):
        salobj.set_random_lsst_dds_domain()
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
                    await csc.do_exitControl(data=None)
                    await asyncio.wait_for(csc.done_task, timeout=5)

    async def test_specified_index(self):
        sys.argv = [sys.argv[0]]
        index = next(index_gen)
        async with salobj.TestCsc.make_from_cmd_line(index=index) as csc:
            self.assertEqual(csc.salinfo.index, index)
            await csc.do_exitControl(data=None)
            await asyncio.wait_for(csc.done_task, timeout=5)

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
            await csc.do_exitControl(data=None)
            await asyncio.wait_for(csc.done_task, timeout=5)

    async def test_config_from_argument(self):
        index = next(index_gen)
        sys.argv = [sys.argv[0], str(index), "--config", str(TEST_CONFIG_DIR)]
        async with salobj.TestCsc.make_from_cmd_line(index=True) as csc:
            self.assertEqual(csc.salinfo.index, index)
            self.assertEqual(csc.config_dir, TEST_CONFIG_DIR)
            await csc.do_exitControl(data=None)
            await asyncio.wait_for(csc.done_task, timeout=5)


if __name__ == "__main__":
    unittest.main()
