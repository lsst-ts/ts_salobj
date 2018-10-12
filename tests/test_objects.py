import asyncio
import time
import unittest

import numpy as np

try:
    import SALPY_Test
except ImportError:
    SALPY_Test = None
import salobj

np.random.seed(47)


class Harness:
    def __init__(self, initial_state):
        index = salobj.test_utils.get_test_index()
        salobj.test_utils.set_random_lsst_dds_domain()
        self.csc = salobj.test_utils.TestCsc(index=index, initial_state=initial_state)
        self.remote = salobj.Remote(SALPY_Test, index)


@unittest.skipIf(SALPY_Test is None, "Could not import SALPY_Test")
class CommunicateTestCase(unittest.TestCase):
    def test_setArrays_command(self):
        async def doit():
            harness = Harness(initial_state=salobj.State.ENABLED)
            # until the controller gets its first setArrays
            # it will not send any arrays events or telemetry
            self.assertIsNone(harness.remote.evt_arrays.get())
            self.assertIsNone(harness.remote.tel_arrays.get())

            # send the setArrays command with random data
            # but first start looking for the event that should be triggered
            evt_coro = harness.remote.evt_arrays.next(flush=True, timeout=1)
            cmd_data_sent = harness.csc.make_random_cmd_arrays()
            await harness.remote.cmd_setArrays.start(cmd_data_sent, timeout=1)

            # see if new data is being broadcast correctly
            evt_data = await evt_coro
            harness.csc.assert_arrays_equal(cmd_data_sent, evt_data)
            tel_data = await harness.remote.tel_arrays.next(flush=True, timeout=1)
            harness.csc.assert_arrays_equal(cmd_data_sent, tel_data)

            # also test get
            harness.csc.assert_arrays_equal(cmd_data_sent, harness.remote.tel_arrays.get())
            harness.csc.assert_arrays_equal(cmd_data_sent, harness.remote.evt_arrays.get())

        asyncio.get_event_loop().run_until_complete(doit())

    def test_setScalars_command(self):
        async def doit():
            harness = Harness(initial_state=salobj.State.ENABLED)
            # until the controller gets its first setArrays
            # it will not send any arrays events or telemetry
            self.assertIsNone(harness.remote.evt_scalars.get())
            self.assertIsNone(harness.remote.tel_scalars.get())

            # send the setScalars command with random data
            # but first start looking for the event that should be triggered
            evt_coro = harness.remote.evt_scalars.next(flush=True, timeout=1)
            cmd_data_sent = harness.csc.make_random_cmd_scalars()
            await harness.remote.cmd_setScalars.start(cmd_data_sent, timeout=1)

            # see if new data is being broadcast correctly
            evt_data = await evt_coro
            harness.csc.assert_scalars_equal(cmd_data_sent, evt_data)
            tel_data = await harness.remote.tel_scalars.next(flush=True, timeout=1)
            harness.csc.assert_scalars_equal(cmd_data_sent, tel_data)

            # also test get
            harness.csc.assert_scalars_equal(cmd_data_sent, harness.remote.tel_scalars.get())
            harness.csc.assert_scalars_equal(cmd_data_sent, harness.remote.evt_scalars.get())

        asyncio.get_event_loop().run_until_complete(doit())

    def test_command_timeout(self):
        harness = Harness(initial_state=salobj.State.ENABLED)
        sallib = harness.remote.salinfo.lib

        async def doit():
            wait_data = harness.remote.cmd_wait.DataType()
            wait_data.duration = 5
            wait_data.ack = sallib.SAL__CMD_COMPLETE
            result = await harness.remote.cmd_wait.start(wait_data, timeout=0.5)
            self.assertEqual(result.ack.ack, sallib.SAL__CMD_TIMEOUT)

        asyncio.get_event_loop().run_until_complete(doit())

    def test_multiple_commands(self):
        """Test that we can have multiple instances of the same command
            running at the same time.
            """
        harness = Harness(initial_state=salobj.State.ENABLED)
        sallib = harness.remote.salinfo.lib
        self.assertTrue(harness.csc.cmd_wait.has_callback)
        self.assertTrue(harness.csc.cmd_wait.allow_multiple_callbacks)
        wait_data = harness.remote.cmd_wait.DataType()
        durations = (0.4, 0.3)  # seconds

        async def doit():
            futures = []
            for duration in durations:
                wait_data.duration = duration
                wait_data.ack = sallib.SAL__CMD_COMPLETE
                futures.append(harness.remote.cmd_wait.start(wait_data, timeout=5))
            results = await asyncio.gather(*futures)
            for result in results:
                self.assertEqual(result.ack.ack, sallib.SAL__CMD_COMPLETE)

        start_time = time.time()
        asyncio.get_event_loop().run_until_complete(doit())
        duration = time.time() - start_time
        self.assertLess(duration, np.sum(durations))

    def test_multiple_sequential_commands(self):
        """Test that commands prohibig multiple callbacks are executed
        one after the other.
        """
        harness = Harness(initial_state=salobj.State.ENABLED)
        sallib = harness.remote.salinfo.lib
        self.assertTrue(harness.csc.cmd_wait.has_callback)
        # make the wait commands execute sequentially
        harness.csc.cmd_wait.allow_multiple_callbacks = False
        self.assertFalse(harness.csc.cmd_wait.allow_multiple_callbacks)
        wait_data = harness.remote.cmd_wait.DataType()
        durations = (0.4, 0.3)  # seconds

        async def doit():
            futures = []
            for duration in durations:
                wait_data.duration = duration
                wait_data.ack = sallib.SAL__CMD_COMPLETE
                futures.append(harness.remote.cmd_wait.start(wait_data, timeout=5))
            results = await asyncio.gather(*futures)
            for result in results:
                self.assertEqual(result.ack.ack, sallib.SAL__CMD_COMPLETE)

        start_time = time.time()
        asyncio.get_event_loop().run_until_complete(doit())
        duration = time.time() - start_time
        self.assertGreaterEqual(duration, np.sum(durations))

    def test_asynchronous_event_callback(self):
        harness = Harness(initial_state=salobj.State.ENABLED)
        cmd_scalars_data = harness.csc.make_random_cmd_scalars()
        # just making it variable doesn't work;
        # the callback can declare it global, but setting it
        # still doesn't affect the value
        self.event_seen = False

        async def scalars_callback(scalars):
            harness.csc.assert_scalars_equal(scalars, cmd_scalars_data)
            self.event_seen = True

        async def doit():
            # send the setScalars command with random data
            # but first start looking for the event that should be triggered
            harness.remote.evt_scalars.callback = scalars_callback
            await harness.remote.cmd_setScalars.start(cmd_scalars_data, timeout=1)

        asyncio.get_event_loop().run_until_complete(doit())
        self.assertTrue(self.event_seen)

    def test_ynchronous_event_callback(self):
        harness = Harness(initial_state=salobj.State.ENABLED)
        cmd_scalars_data = harness.csc.make_random_cmd_scalars()
        self.event_seen = False

        def scalars_callback(scalars):
            harness.csc.assert_scalars_equal(scalars, cmd_scalars_data)
            self.event_seen = True

        async def doit():
            # send the setScalars command with random data
            # but first start looking for the event that should be triggered
            harness.remote.evt_scalars.callback = scalars_callback
            await harness.remote.cmd_setScalars.start(cmd_scalars_data, timeout=1)

        asyncio.get_event_loop().run_until_complete(doit())
        self.assertTrue(self.event_seen)

    def test_standard_state_transitions(self):
        """Test standard CSC state transitions.

        The initial state is STANDBY.
        The standard commands and associated state transitions are:

        * start: STANDBY to DISABLED
        * enable: DISABLED to ENABLED

        * disable: ENABLED to DISABLED
        * standby: DISABLED to STANDBY
        * exitControl: STANDBY, FAULT to OFFLINE (quit)
        """
        async def doit():
            harness = Harness(initial_state=salobj.State.STANDBY)
            commands = ("start", "enable", "disable", "exitControl", "standby",
                        "setArrays", "setScalars")
            self.assertEqual(harness.csc.summary_state, salobj.State.STANDBY)

            for bad_command in commands:
                if bad_command in ("start", "exitControl"):
                    continue  # valid command in STANDBY state
                with self.subTest(bad_command=bad_command):
                    cmd_attr = getattr(harness.remote, f"cmd_{bad_command}")
                    id_ack = await cmd_attr.start(cmd_attr.DataType())
                    self.assertEqual(id_ack.ack.ack, harness.remote.salinfo.lib.SAL__CMD_FAILED)
                    self.assertNotEqual(id_ack.ack.error, 0)
                    self.assertNotEqual(id_ack.ack.result, "")

            # send start; new state is DISABLED
            cmd_attr = getattr(harness.remote, f"cmd_start")
            state_coro = harness.remote.evt_summaryState.next()
            id_ack = await cmd_attr.start(cmd_attr.DataType())
            state = await state_coro
            self.assertEqual(id_ack.ack.ack, harness.remote.salinfo.lib.SAL__CMD_COMPLETE)
            self.assertEqual(id_ack.ack.error, 0)
            self.assertEqual(harness.csc.summary_state, salobj.State.DISABLED)
            self.assertEqual(state.summaryState, salobj.State.DISABLED)

            for bad_command in commands:
                if bad_command in ("enable", "standby"):
                    continue  # valid command in DISABLED state
                with self.subTest(bad_command=bad_command):
                    cmd_attr = getattr(harness.remote, f"cmd_{bad_command}")
                    id_ack = await cmd_attr.start(cmd_attr.DataType())
                    self.assertEqual(id_ack.ack.ack, harness.remote.salinfo.lib.SAL__CMD_FAILED)
                    self.assertNotEqual(id_ack.ack.error, 0)
                    self.assertNotEqual(id_ack.ack.result, "")

            # send enable; new state is ENABLED
            cmd_attr = getattr(harness.remote, f"cmd_enable")
            state_coro = harness.remote.evt_summaryState.next()
            id_ack = await cmd_attr.start(cmd_attr.DataType())
            state = await state_coro
            self.assertEqual(id_ack.ack.ack, harness.remote.salinfo.lib.SAL__CMD_COMPLETE)
            self.assertEqual(id_ack.ack.error, 0)
            self.assertEqual(harness.csc.summary_state, salobj.State.ENABLED)
            self.assertEqual(state.summaryState, salobj.State.ENABLED)

            for bad_command in commands:
                if bad_command in ("disable", "setArrays", "setScalars"):
                    continue  # valid command in DISABLED state
                with self.subTest(bad_command=bad_command):
                    cmd_attr = getattr(harness.remote, f"cmd_{bad_command}")
                    id_ack = await cmd_attr.start(cmd_attr.DataType())
                    self.assertEqual(id_ack.ack.ack, harness.remote.salinfo.lib.SAL__CMD_FAILED)
                    self.assertNotEqual(id_ack.ack.error, 0)
                    self.assertNotEqual(id_ack.ack.result, "")

            # send disable; new state is DISABLED
            cmd_attr = getattr(harness.remote, f"cmd_disable")
            id_ack = await cmd_attr.start(cmd_attr.DataType())
            self.assertEqual(id_ack.ack.ack, harness.remote.salinfo.lib.SAL__CMD_COMPLETE)
            self.assertEqual(id_ack.ack.error, 0)
            self.assertEqual(harness.csc.summary_state, salobj.State.DISABLED)

            # send standby; new state is STANDBY
            cmd_attr = getattr(harness.remote, f"cmd_standby")
            id_ack = await cmd_attr.start(cmd_attr.DataType())
            self.assertEqual(id_ack.ack.ack, harness.remote.salinfo.lib.SAL__CMD_COMPLETE)
            self.assertEqual(id_ack.ack.error, 0)
            self.assertEqual(harness.csc.summary_state, salobj.State.STANDBY)

            # send exitControl; new state is OFFLINE
            cmd_attr = getattr(harness.remote, f"cmd_exitControl")
            id_ack = await cmd_attr.start(cmd_attr.DataType())
            self.assertEqual(id_ack.ack.ack, harness.remote.salinfo.lib.SAL__CMD_COMPLETE)
            self.assertEqual(id_ack.ack.error, 0)
            self.assertEqual(harness.csc.summary_state, salobj.State.OFFLINE)

        asyncio.get_event_loop().run_until_complete(doit())


@unittest.skipIf(SALPY_Test is None, "Could not import SALPY_Test")
class RemoteConstructorTestCase(unittest.TestCase):
    def test_remote_include_exclude(self):
        """Test the include and exclude arguments for salobj.Remote"""
        index = salobj.test_utils.get_test_index()
        salinfo = salobj.SalInfo(SALPY_Test, index)
        manager = salinfo.manager

        # all possible expected topic names
        all_command_topic_names = set(manager.getCommandNames())
        all_event_topic_names = set(manager.getEventNames())
        all_telemetry_topic_names = set(manager.getTelemetryNames())

        # the associated method names
        all_command_method_names = set(f"cmd_{name}" for name in all_command_topic_names)
        all_event_method_names = set(f"evt_{name}" for name in all_event_topic_names)
        all_telemetry_method_names = set(f"tel_{name}" for name in all_telemetry_topic_names)

        # remote0 specifies neither include nor exclude; it should have everything
        remote0 = salobj.Remote(SALPY_Test, index)
        remote_command_names = set([name for name in dir(remote0) if name.startswith("cmd_")])
        self.assertEqual(remote_command_names, all_command_method_names)
        remote_event_names = set([name for name in dir(remote0) if name.startswith("evt_")])
        self.assertEqual(remote_event_names, all_event_method_names)
        remote_telemetry_names = set([name for name in dir(remote0) if name.startswith("tel_")])
        self.assertEqual(remote_telemetry_names, all_telemetry_method_names)

        # remote1 uses the include argument
        include = ["errorCode", "scalars"]
        remote1 = salobj.Remote(SALPY_Test, index=index, include=include)
        remote1_command_names = set([name for name in dir(remote1) if name.startswith("cmd_")])
        self.assertEqual(remote1_command_names, all_command_method_names)
        remote1_event_names = set([name for name in dir(remote1) if name.startswith("evt_")])
        self.assertEqual(remote1_event_names, set(f"evt_{name}" for name in include
                                                  if name in all_event_topic_names))
        remote1_telemetry_names = set([name for name in dir(remote1) if name.startswith("tel_")])
        self.assertEqual(remote1_telemetry_names, set(f"tel_{name}" for name in include
                                                      if name in all_telemetry_topic_names))

        # remote2 uses the exclude argument
        exclude = ["appliedSettingsMatchStart", "arrays"]
        remote2 = salobj.Remote(SALPY_Test, index=index, exclude=exclude)
        remote2_command_names = set([name for name in dir(remote2) if name.startswith("cmd_")])
        self.assertEqual(remote2_command_names, all_command_method_names)
        remote2_event_names = set([name for name in dir(remote2) if name.startswith("evt_")])
        self.assertEqual(remote2_event_names, set(f"evt_{name}" for name in all_event_topic_names
                                                  if name not in exclude))
        remote2_telemetry_names = set([name for name in dir(remote2) if name.startswith("tel_")])
        self.assertEqual(remote2_telemetry_names, set(f"tel_{name}" for name in all_telemetry_topic_names
                                                      if name not in exclude))

        # make sure one cannot specify both include and exclude
        with self.assertRaises(ValueError):
            salobj.Remote(SALPY_Test, index=index, include=include, exclude=exclude)


if __name__ == "__main__":
    unittest.main()
