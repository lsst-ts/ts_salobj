import asyncio
import logging
import os
import pathlib
import shutil
import sys
import unittest

import numpy as np
import yaml

from lsst.ts import salobj

SHOW_LOG_MESSAGES = False

STD_TIMEOUT = 5  # timeout for command ack
LONG_TIMEOUT = 30  # timeout for CSCs to start
EVENT_DELAY = 0.1  # time for events to be output as a result of a command
NODATA_TIMEOUT = 0.1  # timeout for when we expect no new data

np.random.seed(47)

index_gen = salobj.index_generator()
TEST_CONFIG_DIR = pathlib.Path(__file__).resolve().parent.joinpath("data", "config")


class Harness:
    def __init__(self, initial_state, config_dir=None, CscClass=salobj.TestCsc):
        index = next(index_gen)
        self.csc = CscClass(index=index, config_dir=config_dir, initial_state=initial_state)
        if SHOW_LOG_MESSAGES:
            handler = logging.StreamHandler()
            self.csc.log.addHandler(handler)
        self.remote = salobj.Remote(domain=self.csc.domain, name="Test", index=index)

    async def __aenter__(self):
        await self.csc.start_task
        await self.remote.start_task
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.remote.close()
        await self.csc.close()


class CommunicateTestCase(unittest.TestCase):
    def setUp(self):
        salobj.set_random_lsst_dds_domain()

    def test_heartbeat(self):
        async def doit():
            async with Harness(initial_state=salobj.State.ENABLED) as harness:
                await harness.remote.evt_summaryState.next(flush=False, timeout=LONG_TIMEOUT)
                harness.csc.heartbeat_interval = 0.1
                await harness.remote.evt_heartbeat.next(flush=True, timeout=STD_TIMEOUT)
                await harness.remote.evt_heartbeat.next(flush=True, timeout=0.2)
                await harness.remote.evt_heartbeat.next(flush=True, timeout=0.2)
                await harness.remote.evt_heartbeat.next(flush=True, timeout=0.2)

        asyncio.get_event_loop().run_until_complete(doit())

    def test_main(self):
        exe_name = "run_test_csc.py"
        exe_path = shutil.which(exe_name)
        if exe_path is None:
            self.fail(f"Could not find bin script {exe_name}; did you setup and scons this package?")

        async def doit():
            index = next(index_gen)
            process = await asyncio.create_subprocess_exec(exe_name, str(index))
            async with salobj.Domain() as domain:
                try:
                    remote = salobj.Remote(domain=domain, name="Test", index=index)
                    summaryState_data = await remote.evt_summaryState.next(flush=False, timeout=60)
                    self.assertEqual(summaryState_data.summaryState, salobj.State.STANDBY)

                    ackcmd = await remote.cmd_exitControl.start(timeout=STD_TIMEOUT)
                    self.assertEqual(ackcmd.ack, salobj.SalRetCode.CMD_COMPLETE)
                    summaryState_data = await remote.evt_summaryState.next(flush=False, timeout=LONG_TIMEOUT)
                    self.assertEqual(summaryState_data.summaryState, salobj.State.OFFLINE)

                    await asyncio.wait_for(process.wait(), 5)

                except Exception:
                    if process.returncode is None:
                        process.terminate()
                    raise

        asyncio.get_event_loop().run_until_complete(doit())

    def test_setArrays_command(self):
        async def doit():
            async with Harness(initial_state=salobj.State.ENABLED) as harness:
                await harness.remote.evt_summaryState.next(flush=False, timeout=LONG_TIMEOUT)

                # until the controller gets its first setArrays
                # it will not send any arrays events or telemetry
                self.assertFalse(harness.csc.evt_arrays.has_data)
                self.assertFalse(harness.csc.tel_arrays.has_data)
                self.assertFalse(harness.remote.evt_arrays.has_data)
                self.assertFalse(harness.remote.tel_arrays.has_data)
                self.assertIsNone(harness.remote.evt_arrays.get())
                self.assertIsNone(harness.remote.tel_arrays.get())

                # check that info level messages are enabled
                logLevel = await harness.remote.evt_logLevel.next(flush=False, timeout=STD_TIMEOUT)
                self.assertEqual(logLevel.level, logging.INFO)

                # purge any existing messages
                harness.remote.evt_logMessage.flush()

                # send the setArrays command with random data
                cmd_data_sent = harness.csc.make_random_cmd_arrays()
                await harness.remote.cmd_setArrays.start(cmd_data_sent, timeout=STD_TIMEOUT)

                log_message = await harness.remote.evt_logMessage.next(flush=False, timeout=STD_TIMEOUT)
                self.assertEqual(log_message.level, logging.INFO)
                self.assertIn("setArrays", log_message.message)

                # see if new data was broadcast correctly
                evt_data = await harness.remote.evt_arrays.next(flush=False, timeout=STD_TIMEOUT)
                harness.csc.assert_arrays_equal(cmd_data_sent, evt_data)
                tel_data = await harness.remote.tel_arrays.next(flush=False, timeout=STD_TIMEOUT)
                harness.csc.assert_arrays_equal(cmd_data_sent, tel_data)

                self.assertTrue(harness.csc.evt_arrays.has_data)
                self.assertTrue(harness.csc.tel_arrays.has_data)
                self.assertTrue(harness.remote.evt_arrays.has_data)
                self.assertTrue(harness.remote.tel_arrays.has_data)

                # also test get
                harness.csc.assert_arrays_equal(cmd_data_sent, harness.remote.tel_arrays.get())
                harness.csc.assert_arrays_equal(cmd_data_sent, harness.remote.evt_arrays.get())

        asyncio.get_event_loop().run_until_complete(doit())

    def test_setScalars_command(self):
        async def doit():
            async with Harness(initial_state=salobj.State.ENABLED) as harness:
                await harness.remote.evt_summaryState.next(flush=False, timeout=LONG_TIMEOUT)

                # until the controller gets its first setArrays
                # it will not send any arrays events or telemetry
                self.assertFalse(harness.csc.evt_scalars.has_data)
                self.assertFalse(harness.csc.tel_scalars.has_data)
                self.assertFalse(harness.remote.evt_scalars.has_data)
                self.assertFalse(harness.remote.tel_scalars.has_data)
                self.assertIsNone(harness.remote.evt_scalars.get())
                self.assertIsNone(harness.remote.tel_scalars.get())

                # check that info level messages are enabled
                logLevel = await harness.remote.evt_logLevel.next(flush=False, timeout=STD_TIMEOUT)
                self.assertEqual(logLevel.level, logging.INFO)

                # purge any existing messages
                harness.remote.evt_logMessage.flush()

                # send the setScalars command with random data
                cmd_data_sent = harness.csc.make_random_cmd_scalars()
                await harness.remote.cmd_setScalars.start(cmd_data_sent, timeout=STD_TIMEOUT)
                log_message = await harness.remote.evt_logMessage.next(flush=False, timeout=STD_TIMEOUT)
                self.assertEqual(log_message.level, logging.INFO)
                self.assertIn("setScalars", log_message.message)

                # see if new data is being broadcast correctly
                evt_data = await harness.remote.evt_scalars.next(flush=False, timeout=STD_TIMEOUT)
                harness.csc.assert_scalars_equal(cmd_data_sent, evt_data)
                tel_data = await harness.remote.tel_scalars.next(flush=False, timeout=STD_TIMEOUT)
                harness.csc.assert_scalars_equal(cmd_data_sent, tel_data)

                self.assertTrue(harness.csc.evt_scalars.has_data)
                self.assertTrue(harness.csc.tel_scalars.has_data)
                self.assertTrue(harness.remote.evt_scalars.has_data)
                self.assertTrue(harness.remote.tel_scalars.has_data)

                # also test get
                harness.csc.assert_scalars_equal(cmd_data_sent, harness.remote.tel_scalars.get())
                harness.csc.assert_scalars_equal(cmd_data_sent, harness.remote.evt_scalars.get())

        asyncio.get_event_loop().run_until_complete(doit())

    def test_fault_state_transitions(self):
        """Test CSC state transitions into fault and out again.

        The initial state is STANDBY.
        The standard commands and associated state transitions are:

        * start: STANDBY to DISABLED
        * enable: DISABLED to ENABLED

        * disable: ENABLED to DISABLED
        * standby: DISABLED or FAULT to STANDBY
        * exitControl: STANDBY or FAULT to OFFLINE (quit)
        """
        async def doit():
            async with Harness(initial_state=salobj.State.STANDBY) as harness:
                await harness.remote.evt_summaryState.next(flush=False, timeout=LONG_TIMEOUT)

                fault_data = harness.csc.cmd_fault.DataType()
                standby_data = harness.csc.cmd_standby.DataType()
                exitControl_data = harness.csc.cmd_exitControl.DataType()

                for state in salobj.State:
                    if state == salobj.State.OFFLINE:
                        continue
                    harness.csc._summary_state = state
                    self.assertEqual(harness.csc.summary_state, state)

                    # make sure we can go from any non-OFFLINE state to FAULT
                    await harness.remote.cmd_fault.start(fault_data, timeout=STD_TIMEOUT)
                    self.assertEqual(harness.csc.summary_state, salobj.State.FAULT)

                    await harness.remote.cmd_standby.start(standby_data, timeout=STD_TIMEOUT)
                    self.assertEqual(harness.csc.summary_state, salobj.State.STANDBY)

                # send exitControl; new state is OFFLINE
                await harness.remote.cmd_exitControl.start(exitControl_data, timeout=STD_TIMEOUT)
                self.assertEqual(harness.csc.summary_state, salobj.State.OFFLINE)

                await asyncio.wait_for(harness.csc.done_task, 5)

        asyncio.get_event_loop().run_until_complete(doit())

    def test_fault_method(self):
        """Test BaseCsc.fault with and without optional arguments."""
        async def doit():
            async with Harness(initial_state=salobj.State.STANDBY) as harness:
                state = await harness.remote.evt_summaryState.next(flush=False, timeout=STD_TIMEOUT)
                self.assertEqual(state.summaryState, salobj.State.STANDBY)
                with self.assertRaises(asyncio.TimeoutError):
                    await harness.remote.evt_errorCode.next(flush=False, timeout=NODATA_TIMEOUT)

                code = 52
                report = "Report for error code"
                traceback = "Traceback for error code"

                # if code not specified then errorCode is not output
                harness.csc.fault()
                state = await harness.remote.evt_summaryState.next(flush=False, timeout=STD_TIMEOUT)
                self.assertEqual(state.summaryState, salobj.State.FAULT)
                with self.assertRaises(asyncio.TimeoutError):
                    await harness.remote.evt_errorCode.next(flush=False, timeout=NODATA_TIMEOUT)

                await harness.remote.cmd_standby.start(timeout=STD_TIMEOUT)
                state = await harness.remote.evt_summaryState.next(flush=False, timeout=STD_TIMEOUT)
                self.assertEqual(state.summaryState, salobj.State.STANDBY)

                # if code not specified then errorCode is not output
                harness.csc.fault(report=report, traceback=traceback)
                state = await harness.remote.evt_summaryState.next(flush=False, timeout=STD_TIMEOUT)
                self.assertEqual(state.summaryState, salobj.State.FAULT)
                with self.assertRaises(asyncio.TimeoutError):
                    await harness.remote.evt_errorCode.next(flush=False, timeout=NODATA_TIMEOUT)

                await harness.remote.cmd_standby.start(timeout=STD_TIMEOUT)
                state = await harness.remote.evt_summaryState.next(flush=False, timeout=STD_TIMEOUT)
                self.assertEqual(state.summaryState, salobj.State.STANDBY)

                # if code is specified then errorReport is output;
                # output with report and traceback specified,
                #  before testing with the defaults of "",
                # to make sure report and traceback are not cached
                harness.csc.fault(code=code, report=report, traceback=traceback)
                state = await harness.remote.evt_summaryState.next(flush=False, timeout=STD_TIMEOUT)
                self.assertEqual(state.summaryState, salobj.State.FAULT)
                data = await harness.remote.evt_errorCode.next(flush=False, timeout=NODATA_TIMEOUT)
                self.assertEqual(data.errorCode, code)
                self.assertEqual(data.errorReport, report)
                self.assertEqual(data.traceback, traceback)

                await harness.remote.cmd_standby.start(timeout=STD_TIMEOUT)
                state = await harness.remote.evt_summaryState.next(flush=False, timeout=STD_TIMEOUT)
                self.assertEqual(state.summaryState, salobj.State.STANDBY)

                harness.csc.fault(code=code)
                state = await harness.remote.evt_summaryState.next(flush=False, timeout=STD_TIMEOUT)
                self.assertEqual(state.summaryState, salobj.State.FAULT)
                data = await harness.remote.evt_errorCode.next(flush=False, timeout=NODATA_TIMEOUT)
                self.assertEqual(data.errorCode, code)
                self.assertEqual(data.errorReport, "")
                self.assertEqual(data.traceback, "")

                await harness.remote.cmd_standby.start(timeout=STD_TIMEOUT)
                await harness.remote.cmd_exitControl.start(timeout=STD_TIMEOUT)

        asyncio.get_event_loop().run_until_complete(doit())

    def test_standard_state_transitions(self):
        """Test standard CSC state transitions.

        The initial state is STANDBY.
        The standard commands and associated state transitions are:

        * start: STANDBY to DISABLED
        * enable: DISABLED to ENABLED

        * disable: ENABLED to DISABLED
        * standby: DISABLED or FAULT to STANDBY
        * exitControl: STANDBY to OFFLINE (quit)
        """
        async def doit():
            async with Harness(initial_state=salobj.State.STANDBY) as harness:
                commands = ("start", "enable", "disable", "exitControl", "standby",
                            "setArrays", "setScalars")
                self.assertEqual(harness.csc.summary_state, salobj.State.STANDBY)
                # make sure start_task completes
                await asyncio.wait_for(harness.csc.start_task, timeout=LONG_TIMEOUT)

                state = await harness.remote.evt_summaryState.next(flush=False, timeout=STD_TIMEOUT)
                self.assertEqual(state.summaryState, salobj.State.STANDBY)

                for bad_command in commands:
                    if bad_command in ("start", "exitControl"):
                        continue  # valid command in STANDBY state
                    with self.subTest(bad_command=bad_command):
                        cmd_attr = getattr(harness.remote, f"cmd_{bad_command}")
                        with salobj.assertRaisesAckError(
                                ack=salobj.SalRetCode.CMD_FAILED):
                            await cmd_attr.start(timeout=STD_TIMEOUT)

                # send start; new state is DISABLED
                ackcmd = await harness.remote.cmd_start.start(timeout=STD_TIMEOUT)
                self.assertEqual(ackcmd.ack, salobj.SalRetCode.CMD_COMPLETE)
                self.assertEqual(ackcmd.error, 0)
                self.assertEqual(harness.csc.summary_state, salobj.State.DISABLED)
                state = await harness.remote.evt_summaryState.next(flush=False, timeout=STD_TIMEOUT)
                self.assertEqual(state.summaryState, salobj.State.DISABLED)

                for bad_command in commands:
                    if bad_command in ("enable", "standby"):
                        continue  # valid command in DISABLED state
                    with self.subTest(bad_command=bad_command):
                        cmd_attr = getattr(harness.remote, f"cmd_{bad_command}")
                        with salobj.assertRaisesAckError(
                                ack=salobj.SalRetCode.CMD_FAILED):
                            await cmd_attr.start(timeout=STD_TIMEOUT)

                # send enable; new state is ENABLED
                ackcmd = await harness.remote.cmd_enable.start(timeout=STD_TIMEOUT)
                self.assertEqual(ackcmd.ack, salobj.SalRetCode.CMD_COMPLETE)
                self.assertEqual(ackcmd.error, 0)
                self.assertEqual(harness.csc.summary_state, salobj.State.ENABLED)
                state = await harness.remote.evt_summaryState.next(flush=False, timeout=STD_TIMEOUT)
                self.assertEqual(state.summaryState, salobj.State.ENABLED)

                for bad_command in commands:
                    if bad_command in ("disable", "setArrays", "setScalars"):
                        continue  # valid command in DISABLED state
                    with self.subTest(bad_command=bad_command):
                        cmd_attr = getattr(harness.remote, f"cmd_{bad_command}")
                        with salobj.assertRaisesAckError(
                                ack=salobj.SalRetCode.CMD_FAILED):
                            await cmd_attr.start(timeout=STD_TIMEOUT)

                # send disable; new state is DISABLED
                ackcmd = await harness.remote.cmd_disable.start(timeout=STD_TIMEOUT)
                self.assertEqual(ackcmd.ack, salobj.SalRetCode.CMD_COMPLETE)
                self.assertEqual(ackcmd.error, 0)
                self.assertEqual(harness.csc.summary_state, salobj.State.DISABLED)
                state = await harness.remote.evt_summaryState.next(flush=False, timeout=STD_TIMEOUT)
                self.assertEqual(state.summaryState, salobj.State.DISABLED)

                # send standby; new state is STANDBY
                ackcmd = await harness.remote.cmd_standby.start(timeout=STD_TIMEOUT)
                self.assertEqual(ackcmd.ack, salobj.SalRetCode.CMD_COMPLETE)
                self.assertEqual(ackcmd.error, 0)
                self.assertEqual(harness.csc.summary_state, salobj.State.STANDBY)
                state = await harness.remote.evt_summaryState.next(flush=False, timeout=STD_TIMEOUT)
                self.assertEqual(state.summaryState, salobj.State.STANDBY)

                # send exitControl; new state is OFFLINE
                ackcmd = await harness.remote.cmd_exitControl.start(timeout=STD_TIMEOUT)
                self.assertEqual(ackcmd.ack, salobj.SalRetCode.CMD_COMPLETE)
                self.assertEqual(ackcmd.error, 0)
                self.assertEqual(harness.csc.summary_state, salobj.State.OFFLINE)
                state = await harness.remote.evt_summaryState.next(flush=False, timeout=STD_TIMEOUT)
                self.assertEqual(state.summaryState, salobj.State.OFFLINE)

                await asyncio.wait_for(harness.csc.done_task, 5)

        asyncio.get_event_loop().run_until_complete(doit())

    def test_simulation_mode(self):
        """Test simulation mode command and event.

        Changing simulation mode can only be done in states STANDBY
        and DISABLED.
        """
        async def doit():
            # start in STANDBY and verify that simulation mode is reported
            async with Harness(initial_state=salobj.State.STANDBY) as harness:
                sm_data = await harness.remote.evt_simulationMode.next(flush=False, timeout=LONG_TIMEOUT)
                self.assertEqual(sm_data.mode, 0)

                # check that simulation mode can be set
                await self.check_simulate_mode_ok(harness)

                # enter DISABLED state and check simulation mode can be set
                harness.csc.summary_state = salobj.State.DISABLED
                await self.check_simulate_mode_ok(harness)

                # enter enabled mode and check simulation mode cannot be set
                harness.csc.summary_state = salobj.State.ENABLED
                await self.check_simulate_mode_bad(harness)

                # enter fault state and check simulate mode cannot be set
                harness.csc.summary_state = salobj.State.FAULT
                await self.check_simulate_mode_bad(harness)

        asyncio.get_event_loop().run_until_complete(doit())

    def test_initial_simulation_mode(self):
        """Test initial_simulation_mode argument of TestCsc constructor.

        The only allowed value is 0.
        """
        async def doit():
            for initial_simulation_mode in (1, 3):
                with self.assertRaises(salobj.ExpectedError):
                    async with salobj.TestCsc(index=1, config_dir=TEST_CONFIG_DIR,
                                              initial_simulation_mode=initial_simulation_mode) as csc:
                        pass

            async with salobj.TestCsc(index=1, config_dir=TEST_CONFIG_DIR, initial_simulation_mode=0) as csc:
                await csc.start_task
                self.assertEqual(csc.simulation_mode, 0)

        asyncio.get_event_loop().run_until_complete(doit())

    async def check_simulate_mode_ok(self, harness):
        """Check that we can set simulation mode to 0 but not other values."""
        setsm_data = harness.remote.cmd_setSimulationMode.DataType()

        setsm_data.mode = 0
        await harness.remote.cmd_setSimulationMode.start(setsm_data, timeout=STD_TIMEOUT)
        sm_data = await harness.remote.evt_simulationMode.next(flush=False, timeout=STD_TIMEOUT)
        self.assertEqual(sm_data.mode, 0)

        for bad_mode in (1, 10, -1):
            setsm_data.mode = 1
            with self.subTest(bad_mode=bad_mode):
                with salobj.assertRaisesAckError():
                    await harness.remote.cmd_setSimulationMode.start(setsm_data, timeout=STD_TIMEOUT)

    async def check_simulate_mode_bad(self, harness):
        """Check that we cannot set simulation mode to 0 or any other value."""
        setsm_data = harness.remote.cmd_setSimulationMode.DataType()

        for bad_mode in (0, 1, 10, -1):
            setsm_data.mode = 1
            with self.subTest(bad_mode=bad_mode):
                with salobj.assertRaisesAckError():
                    await harness.remote.cmd_setSimulationMode.start(setsm_data, timeout=STD_TIMEOUT)


class NoIndexCsc(salobj.TestCsc):
    """A CSC whose constructor has no index argument"""
    def __init__(self, arg1, arg2, config_dir=None):
        super().__init__(index=next(index_gen), config_dir=TEST_CONFIG_DIR)
        self.arg1 = arg1
        self.arg2 = arg2


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


class TestCscConstructorTestCase(unittest.TestCase):
    def setUp(self):
        salobj.set_random_lsst_dds_domain()

    def test_integer_initial_state(self):
        """Test that initial_state can be an integer."""
        async def doit():

            for state in (min(salobj.State), max(salobj.State)):
                int_state = int(state)
                index = next(index_gen)
                with self.subTest(initial_state=int_state):
                    async with salobj.TestCsc(index=index, initial_state=int_state) as csc:
                        self.assertEqual(csc.summary_state, state)

        asyncio.get_event_loop().run_until_complete(doit())

    def test_invalid_config_dir(self):
        """Test that invalid integer initial_state is rejected."""
        with self.assertRaises(ValueError):
            salobj.TestCsc(index=next(index_gen), initial_state=salobj.State.STANDBY,
                           config_dir=TEST_CONFIG_DIR / "not_a_directory")

    def test_invalid_config_pkg(self):
        with self.assertRaises(RuntimeError):
            InvalidPkgNameCsc(index=next(index_gen), initial_state=salobj.State.STANDBY)

    def test_wrong_config_pkg(self):
        with self.assertRaises(RuntimeError):
            WrongConfigPkgCsc(index=next(index_gen), initial_state=salobj.State.STANDBY)

    def test_invalid_initial_state(self):
        """Test that invalid integer initial_state is rejected."""
        for invalid_state in (min(salobj.State) - 1,
                              max(salobj.State) + 1):
            with self.subTest(invalid_state=invalid_state):
                with self.assertRaises(ValueError):
                    salobj.TestCsc(index=next(index_gen), initial_state=invalid_state)


class ConfigurationTestCase(unittest.TestCase):
    def setUp(self):
        salobj.set_random_lsst_dds_domain()
        # defaults hard-coded in <ts_salobj_root>/schema/Test.yaml
        self.default_dict = dict(string0="default value for string0",
                                 bool0=True,
                                 int0=5,
                                 float0=3.14,
                                 intarr0=[-1, 1],
                                 )
        self.config_fields = self.default_dict.keys()

    def test_no_config_specified(self):
        async def doit():
            async with Harness(initial_state=salobj.State.STANDBY, config_dir=TEST_CONFIG_DIR) as harness:
                data = await harness.remote.evt_summaryState.next(flush=False, timeout=LONG_TIMEOUT)
                self.assertEqual(data.summaryState, salobj.State.STANDBY)
                data = await harness.remote.evt_settingVersions.next(flush=False, timeout=STD_TIMEOUT)
                self.assertEqual(pathlib.Path(TEST_CONFIG_DIR).resolve().as_uri(), data.settingsUrl)
                self.assertTrue(len(data.recommendedSettingsVersion) > 0)
                expected_labels = (
                    "all_fields", "empty", "some_fields",
                    "long_label1_in_an_attempt_to_make_recommendedSettingsLabels_go_over_256_chars",
                    "long_label2_in_an_attempt_to_make_recommendedSettingsLabels_go_over_256_chars",
                    "long_label3_in_an_attempt_to_make_recommendedSettingsLabels_go_over_256_chars",
                    "long_label4_in_an_attempt_to_make_recommendedSettingsLabels_go_over_256_chars",
                    "long_label5_in_an_attempt_to_make_recommendedSettingsLabels_go_over_256_chars",
                )
                self.assertEqual(data.recommendedSettingsLabels, ",".join(expected_labels))
                await harness.remote.cmd_start.start(timeout=STD_TIMEOUT)
                data = await harness.remote.evt_summaryState.next(flush=False, timeout=STD_TIMEOUT)
                self.assertEqual(data.summaryState, salobj.State.DISABLED)
                config = harness.csc.config
                for key, expected_value in self.default_dict.items():
                    self.assertEqual(getattr(config, key), expected_value)

        asyncio.get_event_loop().run_until_complete(doit())

    def test_default_config_dir(self):
        async def doit():
            async with Harness(initial_state=salobj.State.STANDBY, config_dir=None) as harness:
                data = await harness.remote.evt_summaryState.next(flush=False, timeout=LONG_TIMEOUT)
                self.assertEqual(data.summaryState, salobj.State.STANDBY)
                data = await harness.remote.evt_settingVersions.next(flush=False, timeout=STD_TIMEOUT)
                self.assertTrue(len(data.recommendedSettingsVersion) > 0)
                self.assertEqual(data.settingsUrl[0:8], "file:///")
                config_path = pathlib.Path(data.settingsUrl[7:])
                self.assertTrue(config_path.samefile(harness.csc.config_dir))

        asyncio.get_event_loop().run_until_complete(doit())

    def test_empty_label(self):
        config_name = "empty"

        async def doit():
            async with Harness(initial_state=salobj.State.STANDBY, config_dir=TEST_CONFIG_DIR) as harness:
                data = await harness.remote.evt_summaryState.next(flush=False, timeout=LONG_TIMEOUT)
                self.assertEqual(data.summaryState, salobj.State.STANDBY)
                await harness.remote.cmd_start.set_start(settingsToApply=config_name, timeout=STD_TIMEOUT)
                data = await harness.remote.evt_summaryState.next(flush=False, timeout=STD_TIMEOUT)
                self.assertEqual(data.summaryState, salobj.State.DISABLED)
                config = harness.csc.config
                for key, expected_value in self.default_dict.items():
                    self.assertEqual(getattr(config, key), expected_value)

        asyncio.get_event_loop().run_until_complete(doit())

    def test_some_fields_label(self):
        """Test a config with some fields set to valid values."""
        config_label = "some_fields"
        config_file = "some_fields.yaml"

        async def doit():
            async with Harness(initial_state=salobj.State.STANDBY, config_dir=TEST_CONFIG_DIR) as harness:
                data = await harness.remote.evt_summaryState.next(flush=False, timeout=LONG_TIMEOUT)
                self.assertEqual(data.summaryState, salobj.State.STANDBY)
                await harness.remote.cmd_start.set_start(settingsToApply=config_label, timeout=STD_TIMEOUT)
                data = await harness.remote.evt_summaryState.next(flush=False, timeout=STD_TIMEOUT)
                self.assertEqual(data.summaryState, salobj.State.DISABLED)
                config = harness.csc.config
                config_path = os.path.join(harness.csc.config_dir, config_file)
                with open(config_path, "r") as f:
                    config_yaml = f.read()
                config_from_file = yaml.safe_load(config_yaml)
                for key, default_value in self.default_dict.items():
                    if key in config_from_file:
                        self.assertEqual(getattr(config, key), config_from_file[key])
                        self.assertNotEqual(getattr(config, key), default_value)
                    else:
                        self.assertEqual(getattr(config, key), default_value)

        asyncio.get_event_loop().run_until_complete(doit())

    def test_some_fields_file(self):
        """Test a config with some fields set to valid values."""
        config_file = "some_fields.yaml"

        async def doit():
            async with Harness(initial_state=salobj.State.STANDBY, config_dir=TEST_CONFIG_DIR) as harness:
                data = await harness.remote.evt_summaryState.next(flush=False, timeout=LONG_TIMEOUT)
                self.assertEqual(data.summaryState, salobj.State.STANDBY)
                await harness.remote.cmd_start.set_start(settingsToApply=config_file, timeout=STD_TIMEOUT)
                data = await harness.remote.evt_summaryState.next(flush=False, timeout=STD_TIMEOUT)
                self.assertEqual(data.summaryState, salobj.State.DISABLED)
                config = harness.csc.config
                config_path = os.path.join(harness.csc.config_dir, config_file)
                with open(config_path, "r") as f:
                    config_yaml = f.read()
                config_from_file = yaml.safe_load(config_yaml)
                for key, default_value in self.default_dict.items():
                    if key in config_from_file:
                        self.assertEqual(getattr(config, key), config_from_file[key])
                        self.assertNotEqual(getattr(config, key), default_value)
                    else:
                        self.assertEqual(getattr(config, key), default_value)

        asyncio.get_event_loop().run_until_complete(doit())

    def test_all_fields_label(self):
        """Test a config with all fields set to valid values."""
        config_name = "all_fields"
        config_file = "all_fields.yaml"

        async def doit():
            async with Harness(initial_state=salobj.State.STANDBY, config_dir=TEST_CONFIG_DIR) as harness:
                data = await harness.remote.evt_summaryState.next(flush=False, timeout=LONG_TIMEOUT)
                self.assertEqual(data.summaryState, salobj.State.STANDBY)
                await harness.remote.cmd_start.set_start(settingsToApply=config_name, timeout=STD_TIMEOUT)
                data = await harness.remote.evt_summaryState.next(flush=False, timeout=STD_TIMEOUT)
                self.assertEqual(data.summaryState, salobj.State.DISABLED)
                config = harness.csc.config
                config_path = os.path.join(harness.csc.config_dir, config_file)
                with open(config_path, "r") as f:
                    config_yaml = f.read()
                config_from_file = yaml.safe_load(config_yaml)
                for key in self.config_fields:
                    self.assertEqual(getattr(config, key), config_from_file[key])

        asyncio.get_event_loop().run_until_complete(doit())

    def test_invalid_configs(self):
        async def doit():
            async with Harness(initial_state=salobj.State.STANDBY, config_dir=TEST_CONFIG_DIR) as harness:
                data = await harness.remote.evt_summaryState.next(flush=False, timeout=LONG_TIMEOUT)
                self.assertEqual(data.summaryState, salobj.State.STANDBY)
                for name in ("all_bad_types", "bad_format", "one_bad_type", "extra_field"):
                    config_file = f"invalid_{name}.yaml"
                    with self.subTest(config_file=config_file):
                        with self.assertRaises(salobj.AckError):
                            await harness.remote.cmd_start.set_start(settingsToApply=config_file,
                                                                     timeout=STD_TIMEOUT)
                        data = harness.remote.evt_summaryState.get()
                        self.assertEqual(harness.csc.summary_state, salobj.State.STANDBY)
                        self.assertEqual(data.summaryState, salobj.State.STANDBY)

        asyncio.get_event_loop().run_until_complete(doit())


class FailedCallbackCsc(salobj.TestCsc):
    """A CSC whose do_wait command raises a RuntimeError"""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.exc_msg = "do_wait raised an exception on purpose"

    async def do_wait(self, data):
        raise RuntimeError(self.exc_msg)


class ControllerCommandLoggingTestCase(unittest.TestCase):
    def setUp(self):
        salobj.set_random_lsst_dds_domain()

    def test_logging(self):
        async def doit():
            async with Harness(initial_state=salobj.State.ENABLED,
                               config_dir=TEST_CONFIG_DIR,
                               CscClass=FailedCallbackCsc) as harness:
                await harness.remote.evt_summaryState.next(flush=False, timeout=LONG_TIMEOUT)

                logLevel = await harness.remote.evt_logLevel.next(flush=False, timeout=STD_TIMEOUT)
                self.assertEqual(logLevel.level, logging.INFO)

                # purge any existing messages
                harness.remote.evt_logMessage.flush()

                info_message = "test info message"
                harness.csc.log.info(info_message)
                msg = await harness.remote.evt_logMessage.next(flush=False, timeout=STD_TIMEOUT)
                self.assertEqual(msg.message, info_message)
                self.assertEqual(msg.level, logging.INFO)
                self.assertEqual(msg.traceback, "")

                warn_message = "test warn message"
                harness.csc.log.warning(warn_message)
                msg = await harness.remote.evt_logMessage.next(flush=False, timeout=STD_TIMEOUT)
                self.assertEqual(msg.message, warn_message)
                self.assertEqual(msg.level, logging.WARNING)
                self.assertEqual(msg.traceback, "")

                with self.assertRaises(asyncio.TimeoutError):
                    await harness.remote.evt_logMessage.next(flush=False, timeout=NODATA_TIMEOUT)

                await harness.remote.cmd_setLogLevel.set_start(level=logging.ERROR, timeout=STD_TIMEOUT)

                logLevel = await harness.remote.evt_logLevel.next(flush=False, timeout=STD_TIMEOUT)
                self.assertEqual(logLevel.level, logging.ERROR)

                info_message = "test info message"
                harness.csc.log.info(info_message)
                with self.assertRaises(asyncio.TimeoutError):
                    await harness.remote.evt_logMessage.next(flush=False, timeout=NODATA_TIMEOUT)

                warn_message = "test warn message"
                harness.csc.log.warning(warn_message)
                with self.assertRaises(asyncio.TimeoutError):
                    await harness.remote.evt_logMessage.next(flush=False, timeout=NODATA_TIMEOUT)

                with salobj.assertRaisesAckError():
                    await harness.remote.cmd_wait.set_start(duration=5, timeout=STD_TIMEOUT)

                msg = await harness.remote.evt_logMessage.next(flush=False, timeout=STD_TIMEOUT)
                self.assertIn(harness.csc.exc_msg, msg.traceback)
                self.assertIn("Traceback", msg.traceback)
                self.assertIn("RuntimeError", msg.traceback)
                self.assertEqual(msg.level, logging.ERROR)

        asyncio.get_event_loop().run_until_complete(doit())


class BaseCscMainTestCase(unittest.TestCase):
    def setUp(self):
        salobj.set_random_lsst_dds_domain()
        self.original_argv = sys.argv[:]

    def tearDown(self):
        sys.argv = self.original_argv

    def test_no_index(self):
        async def doit(index):
            sys.argv = [sys.argv[0]]
            arg1 = "astring"
            arg2 = 2.75
            async with NoIndexCsc.main(index=index, arg1=arg1, arg2=arg2, run_loop=False) as csc:
                self.assertEqual(csc.arg1, arg1)
                self.assertEqual(csc.arg2, arg2)
                await csc.do_exitControl(data=None)
                await asyncio.wait_for(csc.done_task, timeout=5)

        for index in (False, None):
            with self.subTest(index=index):
                asyncio.get_event_loop().run_until_complete(doit(index=index))

    def test_specified_index(self):
        async def doit():
            sys.argv = [sys.argv[0]]
            index = next(index_gen)
            async with salobj.TestCsc.main(index=index, run_loop=False) as csc:
                self.assertEqual(csc.salinfo.index, index)
                await csc.do_exitControl(data=None)
                await asyncio.wait_for(csc.done_task, timeout=5)

        asyncio.get_event_loop().run_until_complete(doit())

    def test_index_from_argument_and_default_config_dir(self):
        async def doit():
            index = next(index_gen)
            sys.argv = [sys.argv[0], str(index)]
            async with salobj.TestCsc.main(index=True, run_loop=False) as csc:
                self.assertEqual(csc.salinfo.index, index)

                desired_config_pkg_name = "ts_config_ocs"
                desired_config_env_name = desired_config_pkg_name.upper() + "_DIR"
                desird_config_pkg_dir = os.environ[desired_config_env_name]
                desired_config_dir = pathlib.Path(desird_config_pkg_dir) / "Test/v1"
                self.assertEqual(csc.get_config_pkg(), desired_config_pkg_name)
                self.assertEqual(csc.config_dir, desired_config_dir)
                await csc.do_exitControl(data=None)
                await asyncio.wait_for(csc.done_task, timeout=5)

        asyncio.get_event_loop().run_until_complete(doit())

    def test_config_from_argument(self):
        async def doit():
            index = next(index_gen)
            sys.argv = [sys.argv[0], str(index), "--config", str(TEST_CONFIG_DIR)]
            async with salobj.TestCsc.main(index=True, run_loop=False) as csc:
                self.assertEqual(csc.salinfo.index, index)
                self.assertEqual(csc.config_dir, TEST_CONFIG_DIR)
                await csc.do_exitControl(data=None)
                await asyncio.wait_for(csc.done_task, timeout=5)

        asyncio.get_event_loop().run_until_complete(doit())


if __name__ == "__main__":
    unittest.main()
