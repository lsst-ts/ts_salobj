import asyncio
import logging
import shutil
import sys
import time
import unittest

import numpy as np

try:
    import SALPY_Test
except ImportError:
    SALPY_Test = None
from lsst.ts import salobj

np.random.seed(47)

index_gen = salobj.index_generator()


class Harness:
    def __init__(self, initial_state):
        index = next(index_gen)
        salobj.set_random_lsst_dds_domain()
        self.csc = salobj.TestCsc(index=index, initial_state=initial_state)
        self.remote = salobj.Remote(SALPY_Test, index)


@unittest.skipIf(SALPY_Test is None, "Could not import SALPY_Test")
class CommunicateTestCase(unittest.TestCase):
    def test_heartbeat(self):
        async def doit():
            harness = Harness(initial_state=salobj.State.ENABLED)
            start_time = time.time()
            await harness.remote.evt_heartbeat.next(flush=True, timeout=2)
            await harness.remote.evt_heartbeat.next(flush=True, timeout=2)
            duration = time.time() - start_time
            self.assertLess(abs(duration - 2), 0.5)

            harness.csc.heartbeat_interval = 0.1
            await harness.remote.evt_heartbeat.next(flush=True, timeout=2)
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
            salobj.set_random_lsst_dds_domain()
            process = await asyncio.create_subprocess_exec(exe_name, str(index))
            try:
                remote = salobj.Remote(SALPY_Test, index)
                summaryState_data = await remote.evt_summaryState.next(flush=False, timeout=10)
                self.assertEqual(summaryState_data.summaryState, salobj.State.STANDBY)

                id_ack = await remote.cmd_exitControl.start(timeout=2)
                self.assertEqual(id_ack.ack.ack, remote.salinfo.lib.SAL__CMD_COMPLETE)
                summaryState_data = await remote.evt_summaryState.next(flush=False, timeout=10)
                self.assertEqual(summaryState_data.summaryState, salobj.State.OFFLINE)

                await asyncio.wait_for(process.wait(), 2)
            except Exception:
                if process.returncode is None:
                    process.terminate()
                raise

        asyncio.get_event_loop().run_until_complete(doit())

    def test_setArrays_command(self):
        async def doit():
            harness = Harness(initial_state=salobj.State.ENABLED)
            # until the controller gets its first setArrays
            # it will not send any arrays events or telemetry
            self.assertFalse(harness.csc.evt_arrays.has_data)
            self.assertFalse(harness.csc.tel_arrays.has_data)
            self.assertFalse(harness.remote.evt_arrays.has_data)
            self.assertFalse(harness.remote.tel_arrays.has_data)
            self.assertIsNone(harness.remote.evt_arrays.get())
            self.assertIsNone(harness.remote.tel_arrays.get())

            # send the setArrays command with random data
            cmd_data_sent = harness.csc.make_random_cmd_arrays()
            await harness.remote.cmd_setArrays.start(cmd_data_sent, timeout=1)

            # by default log level does not include INFO messages, so expect nothing
            with self.assertRaises(asyncio.TimeoutError):
                await harness.remote.evt_logMessage.next(flush=False, timeout=0.2)

            # see if new data was broadcast correctly
            evt_data = await harness.remote.evt_arrays.next(flush=False, timeout=1)
            harness.csc.assert_arrays_equal(cmd_data_sent, evt_data)
            tel_data = await harness.remote.tel_arrays.next(flush=False, timeout=1)
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
            harness = Harness(initial_state=salobj.State.ENABLED)
            # until the controller gets its first setArrays
            # it will not send any arrays events or telemetry
            self.assertFalse(harness.csc.evt_scalars.has_data)
            self.assertFalse(harness.csc.tel_scalars.has_data)
            self.assertFalse(harness.remote.evt_scalars.has_data)
            self.assertFalse(harness.remote.tel_scalars.has_data)
            self.assertIsNone(harness.remote.evt_scalars.get())
            self.assertIsNone(harness.remote.tel_scalars.get())

            # enable info level messages
            logLevel = harness.remote.evt_logLevel.get()
            self.assertEqual(logLevel.level, logging.WARNING)
            harness.remote.cmd_setLogLevel.set(level=logging.INFO)
            await harness.remote.cmd_setLogLevel.start(timeout=2)
            logLevel = harness.remote.evt_logLevel.get()
            self.assertEqual(logLevel.level, logging.INFO)

            # send the setScalars command with random data
            cmd_data_sent = harness.csc.make_random_cmd_scalars()
            await harness.remote.cmd_setScalars.start(cmd_data_sent, timeout=1)
            log_message = await harness.remote.evt_logMessage.next(flush=False, timeout=1)
            self.assertIsNotNone(log_message)
            self.assertEqual(log_message.level, logging.INFO)
            self.assertIn("setscalars", log_message.message.lower())

            # see if new data is being broadcast correctly
            evt_data = await harness.remote.evt_scalars.next(flush=False, timeout=1)
            harness.csc.assert_scalars_equal(cmd_data_sent, evt_data)
            tel_data = await harness.remote.tel_scalars.next(flush=False, timeout=1)
            harness.csc.assert_scalars_equal(cmd_data_sent, tel_data)

            self.assertTrue(harness.csc.evt_scalars.has_data)
            self.assertTrue(harness.csc.tel_scalars.has_data)
            self.assertTrue(harness.remote.evt_scalars.has_data)
            self.assertTrue(harness.remote.tel_scalars.has_data)

            # also test get
            harness.csc.assert_scalars_equal(cmd_data_sent, harness.remote.tel_scalars.get())
            harness.csc.assert_scalars_equal(cmd_data_sent, harness.remote.evt_scalars.get())

        asyncio.get_event_loop().run_until_complete(doit())

    def test_controller_telemetry_put(self):
        """Test ControllerTelemetry.put using data=None and providing data.
        """
        async def doit():
            harness = Harness(initial_state=salobj.State.ENABLED)

            # until put is called nothing has been sent
            self.assertFalse(harness.csc.tel_scalars.has_data)
            self.assertFalse(harness.remote.tel_scalars.has_data)
            self.assertIsNone(harness.remote.tel_scalars.get())

            initial_tel_data = harness.csc.tel_scalars.data
            harness.csc.assert_scalars_equal(initial_tel_data, harness.remote.tel_scalars.data)

            # put random telemetry data using data=None
            tel_data1 = harness.csc.make_random_tel_scalars()
            harness.csc.tel_scalars.data = tel_data1
            self.assertTrue(harness.csc.tel_scalars.has_data)
            harness.csc.assert_scalars_equal(tel_data1, harness.csc.tel_scalars.data)
            harness.csc.tel_scalars.put()
            data = await harness.remote.tel_scalars.next(flush=False, timeout=1)
            with self.assertRaises(asyncio.TimeoutError):
                await harness.remote.tel_scalars.next(flush=False, timeout=0.1)
            harness.csc.assert_scalars_equal(data, harness.csc.tel_scalars.data)

            # put random telemetry data specifying the data
            tel_data2 = harness.csc.make_random_tel_scalars()
            harness.csc.tel_scalars.put(tel_data2)
            harness.csc.assert_scalars_equal(tel_data2, harness.csc.tel_scalars.data)
            data = await harness.remote.tel_scalars.next(flush=False, timeout=1)
            with self.assertRaises(asyncio.TimeoutError):
                await harness.remote.tel_scalars.next(flush=False, timeout=0.1)
            harness.csc.assert_scalars_equal(data, harness.csc.tel_scalars.data)

        asyncio.get_event_loop().run_until_complete(doit())

    def test_controller_event_put(self):
        """Test ControllerEvent.put using data=None and providing data.
        """
        async def doit():
            harness = Harness(initial_state=salobj.State.ENABLED)

            # until put is called nothing has been sent
            self.assertFalse(harness.csc.evt_scalars.has_data)
            self.assertFalse(harness.remote.evt_scalars.has_data)
            self.assertIsNone(harness.remote.evt_scalars.get())

            initial_evt_data = harness.csc.evt_scalars.data
            harness.csc.assert_scalars_equal(initial_evt_data, harness.remote.evt_scalars.data)

            # put random event data using data=None
            evt_data1 = harness.csc.make_random_evt_scalars()
            harness.csc.evt_scalars.data = evt_data1
            self.assertTrue(harness.csc.evt_scalars.has_data)
            harness.csc.assert_scalars_equal(evt_data1, harness.csc.evt_scalars.data)
            harness.csc.evt_scalars.put()
            data = await harness.remote.evt_scalars.next(flush=False, timeout=1)
            with self.assertRaises(asyncio.TimeoutError):
                await harness.remote.evt_scalars.next(flush=False, timeout=0.1)
            harness.csc.assert_scalars_equal(data, harness.csc.evt_scalars.data)

            # put random event data specifying the data
            evt_data2 = harness.csc.make_random_evt_scalars()
            harness.csc.evt_scalars.put(evt_data2)
            harness.csc.assert_scalars_equal(evt_data2, harness.csc.evt_scalars.data)
            data = await harness.remote.evt_scalars.next(flush=False, timeout=1)
            with self.assertRaises(asyncio.TimeoutError):
                await harness.remote.evt_scalars.next(flush=False, timeout=0.1)
            harness.csc.assert_scalars_equal(data, harness.csc.evt_scalars.data)

        asyncio.get_event_loop().run_until_complete(doit())

    def test_controller_telemetry_set_set_put(self):
        """Test ControllerTelemetry.set_put.
        """
        async def doit():
            harness = Harness(initial_state=salobj.State.ENABLED)

            # until set_put is called nothing has been sent
            self.assertFalse(harness.csc.tel_scalars.has_data)
            self.assertFalse(harness.remote.tel_scalars.has_data)
            self.assertIsNone(harness.remote.tel_scalars.get())

            # put random telemetry data using set and set_put
            tel_data1 = harness.csc.make_random_tel_scalars()
            dict_data1 = harness.csc.as_dict(tel_data1, harness.csc.scalars_fields)
            harness.csc.tel_scalars.set(**dict_data1)
            harness.csc.tel_scalars.put()
            self.assertTrue(harness.csc.tel_scalars.has_data)
            harness.csc.assert_scalars_equal(tel_data1, harness.csc.tel_scalars.data)
            data = await harness.remote.tel_scalars.next(flush=False, timeout=1)
            with self.assertRaises(asyncio.TimeoutError):
                await harness.remote.tel_scalars.next(flush=False, timeout=0.1)
            harness.csc.assert_scalars_equal(data, tel_data1)
            harness.csc.assert_scalars_equal(data, harness.remote.tel_scalars.data)

            # set_put the same data again; the telemetry should be sent
            harness.csc.tel_scalars.set_put(**dict_data1)
            self.assertTrue(harness.csc.tel_scalars.has_data)
            harness.csc.assert_scalars_equal(tel_data1, harness.csc.tel_scalars.data)
            data = await harness.remote.tel_scalars.next(flush=False, timeout=1)
            with self.assertRaises(asyncio.TimeoutError):
                await harness.remote.tel_scalars.next(flush=False, timeout=0.1)
            harness.csc.assert_scalars_equal(data, tel_data1)
            harness.csc.assert_scalars_equal(data, harness.remote.tel_scalars.data)

            # use None for values to set_put; the same telemetry should be sent
            none_dict = dict((key, None) for key in dict_data1)
            harness.csc.tel_scalars.set_put(**none_dict)
            self.assertTrue(harness.csc.tel_scalars.has_data)
            harness.csc.assert_scalars_equal(tel_data1, harness.csc.tel_scalars.data)
            data = await harness.remote.tel_scalars.next(flush=False, timeout=1)
            with self.assertRaises(asyncio.TimeoutError):
                await harness.remote.tel_scalars.next(flush=False, timeout=0.1)
            harness.csc.assert_scalars_equal(data, tel_data1)
            harness.csc.assert_scalars_equal(data, harness.remote.tel_scalars.data)

            # try an invalid key
            with self.assertRaises(AttributeError):
                harness.csc.tel_scalars.set_put(no_such_attribute=None)

            # try an invalid value
            with self.assertRaises(ValueError):
                harness.csc.evt_scalars.set_put(int0="not an int")
            with self.assertRaises(ValueError):
                harness.csc.evt_scalars.set_put(int0="not an int", force_output=True)

            # set an array to a scalar; this should work
            nint0 = len(harness.csc.evt_arrays.data.int0)
            did_put = harness.csc.tel_arrays.set_put(int0=5)
            self.assertTrue(did_put)
            self.assertEqual(list(harness.csc.tel_arrays.data.int0), [5]*nint0)

            # set an array to an array of the correct length
            good_int0 = np.arange(nint0, dtype=int)
            did_put = harness.csc.tel_arrays.set_put(int0=good_int0)
            self.assertTrue(did_put)
            self.assertEqual(list(harness.csc.tel_arrays.data.int0), list(good_int0))

            # try an array that is too short
            bad_int0 = np.arange(nint0-1, dtype=int)
            with self.assertRaises(ValueError):
                harness.csc.tel_arrays.set_put(int0=bad_int0)

            # try an array that is too long
            bad_int0 = np.arange(nint0+1, dtype=int)
            with self.assertRaises(ValueError):
                harness.csc.tel_arrays.set_put(int0=bad_int0)

        asyncio.get_event_loop().run_until_complete(doit())

    def test_controller_event_set_set_put(self):
        """Test ControllerEvent.set_put.
        """
        async def doit():
            harness = Harness(initial_state=salobj.State.ENABLED)

            # until set_put is called nothing has been sent
            self.assertFalse(harness.csc.tel_scalars.has_data)
            self.assertFalse(harness.remote.tel_scalars.has_data)
            self.assertIsNone(harness.remote.tel_scalars.get())

            # set_put random event data
            evt_data1 = harness.csc.make_random_evt_scalars()
            dict_data1 = harness.csc.as_dict(evt_data1, harness.csc.scalars_fields)
            did_put = harness.csc.evt_scalars.set_put(**dict_data1)
            self.assertTrue(harness.csc.evt_scalars.has_data)
            self.assertTrue(did_put)
            harness.csc.assert_scalars_equal(evt_data1, harness.csc.evt_scalars.data)
            data = await harness.remote.evt_scalars.next(flush=False, timeout=1)
            with self.assertRaises(asyncio.TimeoutError):
                await harness.remote.evt_scalars.next(flush=False, timeout=0.1)
            harness.csc.assert_scalars_equal(data, evt_data1)
            harness.csc.assert_scalars_equal(data, harness.remote.evt_scalars.data)

            # set_put with None values; the event should *not* be sent
            none_dict = dict((key, None) for key in dict_data1)
            did_put = harness.csc.evt_scalars.set_put(**none_dict)
            self.assertFalse(did_put)
            with self.assertRaises(asyncio.TimeoutError):
                await harness.remote.evt_scalars.next(flush=False, timeout=0.1)

            # set_put with None values and force_output=True
            none_dict = dict((key, None) for key in dict_data1)
            did_put = harness.csc.evt_scalars.set_put(**none_dict, force_output=True)
            self.assertTrue(did_put)
            harness.csc.assert_scalars_equal(evt_data1, harness.csc.evt_scalars.data)
            data = await harness.remote.evt_scalars.next(flush=False, timeout=1)
            with self.assertRaises(asyncio.TimeoutError):
                await harness.remote.evt_scalars.next(flush=False, timeout=0.1)
            harness.csc.assert_scalars_equal(data, evt_data1)
            harness.csc.assert_scalars_equal(data, harness.remote.evt_scalars.data)

            # set_put the same data again; the event should *not* be sent
            did_put = harness.csc.evt_scalars.set_put(**dict_data1)
            self.assertFalse(did_put)
            with self.assertRaises(asyncio.TimeoutError):
                await harness.remote.evt_scalars.next(flush=False, timeout=0.1)

            # set_put the same data again with force_output=True
            did_put = harness.csc.evt_scalars.set_put(**dict_data1, force_output=True)
            self.assertTrue(did_put)
            harness.csc.assert_scalars_equal(evt_data1, harness.csc.evt_scalars.data)
            data = await harness.remote.evt_scalars.next(flush=False, timeout=1)
            with self.assertRaises(asyncio.TimeoutError):
                await harness.remote.evt_scalars.next(flush=False, timeout=0.1)
            harness.csc.assert_scalars_equal(data, evt_data1)
            harness.csc.assert_scalars_equal(data, harness.remote.evt_scalars.data)

            # change one field of the data and set_put again
            dict_data1["int0"] = dict_data1["int0"] + 1
            did_put = harness.csc.evt_scalars.set_put(**dict_data1)
            self.assertTrue(did_put)
            with self.assertRaises(AssertionError):
                harness.csc.assert_scalars_equal(evt_data1, harness.csc.evt_scalars.data)
            evt_data1.int0 += 1
            harness.csc.assert_scalars_equal(evt_data1, harness.csc.evt_scalars.data)
            data = await harness.remote.evt_scalars.next(flush=False, timeout=1)
            with self.assertRaises(asyncio.TimeoutError):
                await harness.remote.evt_scalars.next(flush=False, timeout=0.1)
            harness.csc.assert_scalars_equal(data, evt_data1)
            harness.csc.assert_scalars_equal(data, harness.remote.evt_scalars.data)

            # try an invalid key
            with self.assertRaises(AttributeError):
                harness.csc.evt_scalars.set_put(no_such_attribute=None)
            with self.assertRaises(AttributeError):
                harness.csc.evt_scalars.set_put(no_such_attribute=None, force_output=True)

            # try an invalid value
            with self.assertRaises(ValueError):
                harness.csc.evt_scalars.set_put(int0="not an int")
            with self.assertRaises(ValueError):
                harness.csc.evt_scalars.set_put(int0="not an int", force_output=True)

            # set an array to a scalar; this should work
            nint0 = len(harness.csc.evt_arrays.data.int0)
            did_put = harness.csc.evt_arrays.set_put(int0=5)
            self.assertTrue(did_put)
            self.assertEqual(list(harness.csc.evt_arrays.data.int0), [5]*nint0)

            # set an array to an array of the correct length
            good_int0 = np.arange(nint0, dtype=int)
            did_put = harness.csc.evt_arrays.set_put(int0=good_int0)
            self.assertTrue(did_put)
            self.assertEqual(list(harness.csc.evt_arrays.data.int0), list(good_int0))

            # try an array that is too short
            bad_int0 = np.arange(nint0-1, dtype=int)
            with self.assertRaises(ValueError):
                harness.csc.evt_arrays.set_put(int0=bad_int0)

            # try an array that is too long
            bad_int0 = np.arange(nint0+1, dtype=int)
            with self.assertRaises(ValueError):
                harness.csc.evt_arrays.set_put(int0=bad_int0)

        asyncio.get_event_loop().run_until_complete(doit())

    async def set_and_get_scalars(self, harness, num_commands):
        # until the controller gets its first setArrays
        # it will not send any scalars events or telemetry
        self.assertIsNone(harness.remote.evt_scalars.get())
        self.assertIsNone(harness.remote.tel_scalars.get())

        # send the setScalars command with random data
        cmd_data_list = [harness.csc.make_random_cmd_scalars() for i in range(num_commands)]
        for cmd_data in cmd_data_list:
            await harness.remote.cmd_setScalars.start(cmd_data, timeout=1)
        return cmd_data_list

    def test_remote_get_oldest(self):
        async def doit():
            num_commands = 3
            harness = Harness(initial_state=salobj.State.ENABLED)
            cmd_data_list = await self.set_and_get_scalars(harness, num_commands=num_commands)

            evt_data_list = []
            while True:
                data = harness.remote.evt_scalars.get_oldest()
                if data is None:
                    break
                evt_data_list.append(data)
            self.assertEqual(len(evt_data_list), num_commands)
            for cmd_data, evt_data in zip(cmd_data_list, evt_data_list):
                harness.csc.assert_scalars_equal(cmd_data, evt_data)

            tel_data_list = []
            while True:
                data = harness.remote.tel_scalars.get_oldest()
                if data is None:
                    break
                tel_data_list.append(data)
            self.assertEqual(len(tel_data_list), num_commands)
            for cmd_data, tel_data in zip(cmd_data_list, tel_data_list):
                harness.csc.assert_scalars_equal(cmd_data, tel_data)

        asyncio.get_event_loop().run_until_complete(doit())

    def test_remote_get(self):
        async def doit():
            num_commands = 3
            harness = Harness(initial_state=salobj.State.ENABLED)
            cmd_data_list = await self.set_and_get_scalars(harness, num_commands=num_commands)

            # get should return the last value seen,
            # no matter now many times it is called
            evt_data_list = [harness.remote.evt_scalars.get() for i in range(5)]
            for evt_data in evt_data_list:
                self.assertIsNotNone(evt_data)
                harness.csc.assert_scalars_equal(cmd_data_list[-1], evt_data)

            # get should return the last value seen,
            # no matter now many times it is called
            tel_data_list = [harness.remote.tel_scalars.get() for i in range(5)]
            for tel_data in tel_data_list:
                self.assertIsNotNone(tel_data)
                harness.csc.assert_scalars_equal(cmd_data_list[-1], tel_data)

        asyncio.get_event_loop().run_until_complete(doit())

    def test_remote_next(self):
        async def doit():
            num_commands = 3
            harness = Harness(initial_state=salobj.State.ENABLED)
            cmd_data_list = await self.set_and_get_scalars(harness, num_commands=num_commands)

            evt_data_list = []
            while True:
                try:
                    evt_data = await harness.remote.evt_scalars.next(flush=False, timeout=0.01)
                    self.assertIsNotNone(evt_data)
                    evt_data_list.append(evt_data)
                except asyncio.TimeoutError:
                    break
            self.assertEqual(len(evt_data_list), num_commands)
            for cmd_data, evt_data in zip(cmd_data_list, evt_data_list):
                harness.csc.assert_scalars_equal(cmd_data, evt_data)

            tel_data_list = []
            while True:
                try:
                    tel_data = await harness.remote.tel_scalars.next(flush=False, timeout=0.01)
                    self.assertIsNotNone(tel_data)
                    tel_data_list.append(tel_data)
                except asyncio.TimeoutError:
                    break
            self.assertEqual(len(tel_data_list), num_commands)
            for cmd_data, tel_data in zip(cmd_data_list, tel_data_list):
                harness.csc.assert_scalars_equal(cmd_data, tel_data)

        asyncio.get_event_loop().run_until_complete(doit())

    def test_remote_callbacks(self):
        async def doit():
            evt_data_list = []

            def evt_callback(data):
                evt_data_list.append(data)

            tel_data_list = []

            def tel_callback(data):
                tel_data_list.append(data)

            num_commands = 3
            harness = Harness(initial_state=salobj.State.ENABLED)
            harness.remote.evt_scalars.callback = evt_callback
            harness.remote.tel_scalars.callback = tel_callback

            with self.assertRaises(RuntimeError):
                harness.remote.evt_scalars.get_oldest()
            with self.assertRaises(RuntimeError):
                harness.remote.tel_scalars.get_oldest()
            with self.assertRaises(RuntimeError):
                harness.remote.evt_scalars.flush()
            with self.assertRaises(RuntimeError):
                harness.remote.tel_scalars.flush()
            with self.assertRaises(RuntimeError):
                await harness.remote.evt_scalars.next(flush=False)
            with self.assertRaises(RuntimeError):
                await harness.remote.tel_scalars.next(flush=False)

            cmd_data_list = await self.set_and_get_scalars(harness, num_commands=num_commands)
            await asyncio.sleep(0.2)  # give the wait loops time to finish

            self.assertEqual(len(evt_data_list), num_commands)
            for cmd_data, evt_data in zip(cmd_data_list, evt_data_list):
                harness.csc.assert_scalars_equal(cmd_data, evt_data)

            self.assertEqual(len(tel_data_list), num_commands)
            for cmd_data, tel_data in zip(cmd_data_list, tel_data_list):
                harness.csc.assert_scalars_equal(cmd_data, tel_data)

        asyncio.get_event_loop().run_until_complete(doit())

    def test_bad_put(self):
        """Try to put invalid data types.
        """
        harness = Harness(initial_state=salobj.State.ENABLED)

        async def doit():
            with self.assertRaises(TypeError):
                # telemetry/event mismatch
                harness.csc.evt_scalars.put(harness.csc.tel_scalars.DataType())
            with self.assertRaises(TypeError):
                # telemetry/event mismatch
                harness.csc.tel_scalars.put(harness.csc.evt_scalars.DataType())
            with self.assertRaises(TypeError):
                await harness.remote.cmd_wait.start(harness.csc.cmd_setScalars.DataType())

        asyncio.get_event_loop().run_until_complete(doit())

    def test_command_timeout(self):
        harness = Harness(initial_state=salobj.State.ENABLED)
        sallib = harness.remote.salinfo.lib

        async def doit():
            harness.remote.cmd_wait.set(duration=5, ack=sallib.SAL__CMD_COMPLETE)
            with salobj.assertRaisesAckError(
                    ack=harness.remote.salinfo.lib.SAL__CMD_NOACK):
                await harness.remote.cmd_wait.start(timeout=0.5)

        asyncio.get_event_loop().run_until_complete(doit())

    def test_controller_command_get_next(self):
        """Test ControllerCommand get and next methods.

        This requires unsetting the callback function for a command.
        """
        harness = Harness(initial_state=salobj.State.ENABLED)

        async def doit():
            # get and next fail if there is a callback
            with self.assertRaises(RuntimeError):
                harness.csc.cmd_wait.get()
            with self.assertRaises(RuntimeError):
                harness.csc.cmd_wait.next()

            harness.csc.cmd_wait.callback = None

            duration = 1
            harness.remote.cmd_wait.set(duration=duration)
            task1 = asyncio.ensure_future(harness.remote.cmd_wait.start())
            await asyncio.sleep(0.5)
            get_iddata = harness.csc.cmd_wait.get()
            self.assertIsNotNone(get_iddata)
            self.assertEqual(get_iddata.data.duration, duration)

            duration = 2
            harness.remote.cmd_wait.set(duration=duration)
            task2 = asyncio.ensure_future(harness.remote.cmd_wait.start())
            next_iddata = await asyncio.wait_for(harness.csc.cmd_wait.next(), 2)
            self.assertIsNotNone(next_iddata)
            self.assertEqual(next_iddata.data.duration, duration)

            task1.cancel()
            task2.cancel()

        asyncio.get_event_loop().run_until_complete(doit())

    def test_controller_command_callback(self):
        """Test getting and setting a callback for a ControllerCommand.
        """
        harness = Harness(initial_state=salobj.State.ENABLED)

        async def doit():
            self.assertTrue(harness.csc.cmd_wait.has_callback)
            self.assertEqual(harness.csc.cmd_wait.callback, harness.csc.do_wait)

            # replace callback
            with self.assertRaises(TypeError):
                harness.csc.cmd_wait.callback = "not callable"
            self.assertEqual(harness.csc.cmd_wait.callback, harness.csc.do_wait)

            def foo():
                pass
            harness.csc.cmd_wait.callback = foo
            self.assertEqual(harness.csc.cmd_wait.callback, foo)

        asyncio.get_event_loop().run_until_complete(doit())

    def test_multiple_commands(self):
        """Test that we can have multiple instances of the same command
            running at the same time.
            """
        harness = Harness(initial_state=salobj.State.ENABLED)
        sallib = harness.remote.salinfo.lib
        self.assertTrue(harness.csc.cmd_wait.has_callback)
        self.assertTrue(harness.csc.cmd_wait.allow_multiple_callbacks)
        durations = (0.4, 0.3)  # seconds

        async def doit():
            futures = []
            for duration in durations:
                harness.remote.cmd_wait.set(duration=duration, ack=sallib.SAL__CMD_COMPLETE)
                futures.append(harness.remote.cmd_wait.start(timeout=5))
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
        durations = (0.4, 0.3)  # seconds

        async def doit():
            futures = []
            for duration in durations:
                harness.remote.cmd_wait.set(duration=duration, ack=sallib.SAL__CMD_COMPLETE)
                futures.append(harness.remote.cmd_wait.start(timeout=5))
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
            # but first set a callback for the event that should be triggered
            harness.remote.evt_scalars.callback = scalars_callback
            await harness.remote.cmd_setScalars.start(cmd_scalars_data, timeout=1)

        asyncio.get_event_loop().run_until_complete(doit())
        self.assertTrue(self.event_seen)

    def test_synchronous_event_callback(self):
        """Like test_asynchronous_event_callback but the callback function
        is synchronous"""
        harness = Harness(initial_state=salobj.State.ENABLED)
        cmd_scalars_data = harness.csc.make_random_cmd_scalars()
        self.event_seen = False

        def scalars_callback(scalars):
            harness.csc.assert_scalars_equal(scalars, cmd_scalars_data)
            self.event_seen = True

        async def doit():
            # send the setScalars command with random data
            # but first set a callback for the event that should be triggered
            harness.remote.evt_scalars.callback = scalars_callback
            await harness.remote.cmd_setScalars.start(cmd_scalars_data, timeout=1)

        asyncio.get_event_loop().run_until_complete(doit())
        self.assertTrue(self.event_seen)

    def test_remote_command_next_ack(self):
        harness = Harness(initial_state=salobj.State.ENABLED)

        async def doit():
            harness.remote.cmd_wait.set(duration=0.1)
            id_ack1 = await harness.remote.cmd_wait.start(wait_done=False, timeout=2)
            self.assertEqual(id_ack1.ack.ack, SALPY_Test.SAL__CMD_ACK)
            id_ack2 = await harness.remote.cmd_wait.next_ack(id_ack1, wait_done=False, timeout=2)
            self.assertEqual(id_ack2.ack.ack, SALPY_Test.SAL__CMD_INPROGRESS)
            id_ack3 = await harness.remote.cmd_wait.next_ack(id_ack2, wait_done=True, timeout=2)
            self.assertEqual(id_ack3.ack.ack, SALPY_Test.SAL__CMD_COMPLETE)

            # now try a timeout
            harness.remote.cmd_wait.set(duration=5)
            id_ack1 = await harness.remote.cmd_wait.start(wait_done=False, timeout=2)
            self.assertEqual(id_ack1.ack.ack, SALPY_Test.SAL__CMD_ACK)
            with salobj.assertRaisesAckError(ack=SALPY_Test.SAL__CMD_NOACK):
                await harness.remote.cmd_wait.next_ack(id_ack1, wait_done=True, timeout=0.1)

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
            harness = Harness(initial_state=salobj.State.STANDBY)
            fault_data = harness.csc.cmd_fault.DataType()
            standby_data = harness.csc.cmd_standby.DataType()
            exitControl_data = harness.csc.cmd_exitControl.DataType()

            for state in salobj.State:
                if state == salobj.State.OFFLINE:
                    continue
                harness.csc._summary_state = state
                self.assertEqual(harness.csc.summary_state, state)

                # make sure we can go from any non-OFFLINE state to FAULT
                await harness.remote.cmd_fault.start(fault_data, timeout=2)
                self.assertEqual(harness.csc.summary_state, salobj.State.FAULT)
                log_message = await harness.remote.evt_logMessage.next(flush=False, timeout=1)
                self.assertIsNotNone(log_message)
                self.assertEqual(log_message.level, logging.WARNING)
                self.assertIn("fault", log_message.message.lower())

                await harness.remote.cmd_standby.start(standby_data, timeout=2)
                self.assertEqual(harness.csc.summary_state, salobj.State.STANDBY)

            # send exitControl; new state is OFFLINE
            await harness.remote.cmd_exitControl.start(exitControl_data, timeout=2)
            self.assertEqual(harness.csc.summary_state, salobj.State.OFFLINE)

            await asyncio.wait_for(harness.csc.done_task, 2)

        asyncio.get_event_loop().run_until_complete(doit())

    def test_fault_method(self):
        """Test BaseCsc.fault with and without optional arguments."""
        async def doit():
            harness = Harness(initial_state=salobj.State.STANDBY)
            state = await harness.remote.evt_summaryState.next(flush=False, timeout=1)
            self.assertEqual(state.summaryState, salobj.State.STANDBY)
            with self.assertRaises(asyncio.TimeoutError):
                await harness.remote.evt_errorCode.next(flush=False, timeout=0.1)

            code = 52
            report = "Report for error code"

            # if code not specified then errorCode is not output
            harness.csc.fault()
            state = await harness.remote.evt_summaryState.next(flush=False, timeout=1)
            self.assertEqual(state.summaryState, salobj.State.FAULT)
            with self.assertRaises(asyncio.TimeoutError):
                await harness.remote.evt_errorCode.next(flush=False, timeout=0.1)

            harness.remote.cmd_standby.start(timeout=1)
            state = await harness.remote.evt_summaryState.next(flush=False, timeout=1)
            self.assertEqual(state.summaryState, salobj.State.STANDBY)

            # if code not specified then errorCode is not output
            harness.csc.fault(report=report)
            state = await harness.remote.evt_summaryState.next(flush=False, timeout=1)
            self.assertEqual(state.summaryState, salobj.State.FAULT)
            with self.assertRaises(asyncio.TimeoutError):
                await harness.remote.evt_errorCode.next(flush=False, timeout=0.1)

            harness.remote.cmd_standby.start(timeout=1)
            state = await harness.remote.evt_summaryState.next(flush=False, timeout=1)
            self.assertEqual(state.summaryState, salobj.State.STANDBY)

            # if code is specified then errorReport is output;
            # output with report specified before testing with
            # the default of "" to make sure the report is not cached
            harness.csc.fault(code=code, report=report)
            state = await harness.remote.evt_summaryState.next(flush=False, timeout=1)
            self.assertEqual(state.summaryState, salobj.State.FAULT)
            data = await harness.remote.evt_errorCode.next(flush=False, timeout=0.1)
            self.assertEqual(data.errorCode, code)
            self.assertEqual(data.errorReport, report)

            harness.remote.cmd_standby.start(timeout=1)
            state = await harness.remote.evt_summaryState.next(flush=False, timeout=1)
            self.assertEqual(state.summaryState, salobj.State.STANDBY)

            harness.csc.fault(code=code)
            state = await harness.remote.evt_summaryState.next(flush=False, timeout=1)
            self.assertEqual(state.summaryState, salobj.State.FAULT)
            data = await harness.remote.evt_errorCode.next(flush=False, timeout=0.1)
            self.assertEqual(data.errorCode, code)
            self.assertEqual(data.errorReport, "")

            harness.remote.cmd_standby.start(timeout=1)
            harness.remote.cmd_exitControl.start(timeout=1)

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
            harness = Harness(initial_state=salobj.State.STANDBY)
            commands = ("start", "enable", "disable", "exitControl", "standby",
                        "setArrays", "setScalars")
            self.assertEqual(harness.csc.summary_state, salobj.State.STANDBY)
            # make sure start_task completes
            await asyncio.wait_for(harness.csc.start_task, timeout=2)

            state = await harness.remote.evt_summaryState.next(flush=False, timeout=2)
            self.assertEqual(state.summaryState, salobj.State.STANDBY)

            for bad_command in commands:
                if bad_command in ("start", "exitControl"):
                    continue  # valid command in STANDBY state
                with self.subTest(bad_command=bad_command):
                    cmd_attr = getattr(harness.remote, f"cmd_{bad_command}")
                    with salobj.assertRaisesAckError(
                            ack=harness.remote.salinfo.lib.SAL__CMD_FAILED):
                        await cmd_attr.start()

            # send start; new state is DISABLED
            id_ack = await harness.remote.cmd_start.start()
            self.assertEqual(id_ack.ack.ack, harness.remote.salinfo.lib.SAL__CMD_COMPLETE)
            self.assertEqual(id_ack.ack.error, 0)
            self.assertEqual(harness.csc.summary_state, salobj.State.DISABLED)
            state = await harness.remote.evt_summaryState.next(flush=False, timeout=2)
            self.assertEqual(state.summaryState, salobj.State.DISABLED)

            for bad_command in commands:
                if bad_command in ("enable", "standby"):
                    continue  # valid command in DISABLED state
                with self.subTest(bad_command=bad_command):
                    cmd_attr = getattr(harness.remote, f"cmd_{bad_command}")
                    with salobj.assertRaisesAckError(
                            ack=harness.remote.salinfo.lib.SAL__CMD_FAILED):
                        await cmd_attr.start()

            # send enable; new state is ENABLED
            id_ack = await harness.remote.cmd_enable.start()
            self.assertEqual(id_ack.ack.ack, harness.remote.salinfo.lib.SAL__CMD_COMPLETE)
            self.assertEqual(id_ack.ack.error, 0)
            self.assertEqual(harness.csc.summary_state, salobj.State.ENABLED)
            state = await harness.remote.evt_summaryState.next(flush=False, timeout=2)
            self.assertEqual(state.summaryState, salobj.State.ENABLED)

            for bad_command in commands:
                if bad_command in ("disable", "setArrays", "setScalars"):
                    continue  # valid command in DISABLED state
                with self.subTest(bad_command=bad_command):
                    cmd_attr = getattr(harness.remote, f"cmd_{bad_command}")
                    with salobj.assertRaisesAckError(
                            ack=harness.remote.salinfo.lib.SAL__CMD_FAILED):
                        await cmd_attr.start()

            # send disable; new state is DISABLED
            id_ack = await harness.remote.cmd_disable.start()
            self.assertEqual(id_ack.ack.ack, harness.remote.salinfo.lib.SAL__CMD_COMPLETE)
            self.assertEqual(id_ack.ack.error, 0)
            self.assertEqual(harness.csc.summary_state, salobj.State.DISABLED)
            state = await harness.remote.evt_summaryState.next(flush=False, timeout=2)
            self.assertEqual(state.summaryState, salobj.State.DISABLED)

            # send standby; new state is STANDBY
            id_ack = await harness.remote.cmd_standby.start()
            self.assertEqual(id_ack.ack.ack, harness.remote.salinfo.lib.SAL__CMD_COMPLETE)
            self.assertEqual(id_ack.ack.error, 0)
            self.assertEqual(harness.csc.summary_state, salobj.State.STANDBY)
            state = await harness.remote.evt_summaryState.next(flush=False, timeout=2)
            self.assertEqual(state.summaryState, salobj.State.STANDBY)

            # send exitControl; new state is OFFLINE
            id_ack = await harness.remote.cmd_exitControl.start()
            self.assertEqual(id_ack.ack.ack, harness.remote.salinfo.lib.SAL__CMD_COMPLETE)
            self.assertEqual(id_ack.ack.error, 0)
            self.assertEqual(harness.csc.summary_state, salobj.State.OFFLINE)
            state = await harness.remote.evt_summaryState.next(flush=False, timeout=2)
            self.assertEqual(state.summaryState, salobj.State.OFFLINE)

            await asyncio.wait_for(harness.csc.done_task, 2)

        asyncio.get_event_loop().run_until_complete(doit())

    def test_topic_repr(self):
        harness = Harness(initial_state=salobj.State.ENABLED)
        salinfo = harness.remote.salinfo

        for obj, classSuffix in (
            (harness.csc, "Controller"),
            (harness.remote, "Remote"),
        ):
            with self.subTest(obj=obj, classSuffix=classSuffix):
                for cmd_name in salinfo.manager.getCommandNames():
                    cmd = getattr(obj, "cmd_" + cmd_name)
                    cmd_repr = repr(cmd)
                    self.assertIn(cmd_name, cmd_repr)
                    self.assertIn("Test", cmd_repr)
                    self.assertIn(classSuffix + "Command", cmd_repr)
                for evt_name in salinfo.manager.getEventNames():
                    evt = getattr(obj, "evt_" + evt_name)
                    evt_repr = repr(evt)
                    self.assertIn(evt_name, evt_repr)
                    self.assertIn("Test", evt_repr)
                    self.assertIn(classSuffix + "Event", evt_repr)
                for tel_name in salinfo.manager.getTelemetryNames():
                    tel = getattr(obj, "tel_" + tel_name)
                    tel_repr = repr(tel)
                    self.assertIn(tel_name, tel_repr)
                    self.assertIn("Test", tel_repr)
                    self.assertIn(classSuffix + "Telemetry", tel_repr)

    def test_simulation_mode(self):
        """Test simulation mode command and event.

        Changing simulation mode can only be done in states STANDBY and DISABLED.
        """
        async def doit():
            # start in STANDBY and verify that simulation mode is reported
            harness = Harness(initial_state=salobj.State.STANDBY)
            sm_data = await harness.remote.evt_simulationMode.next(flush=False, timeout=2)
            self.assertEqual(sm_data.mode, 0)

            # check that simulation mode can be set
            await self.check_simulate_mode_ok(harness)

            # enter DISABLED state and check that simulation mode can be set
            harness.csc.summary_state = salobj.State.DISABLED
            await self.check_simulate_mode_ok(harness)

            # enter enabled mode and check that simulation mode cannot be set
            harness.csc.summary_state = salobj.State.ENABLED
            await self.check_simulate_mode_bad(harness)

            # enter fault state and check that simualte mode cannot be set
            harness.csc.summary_state = salobj.State.FAULT
            await self.check_simulate_mode_bad(harness)

        asyncio.get_event_loop().run_until_complete(doit())

    def test_initial_simulation_mode(self):
        """Test initial_simulation_mode argument of TestCsc constructor."""
        async def doit():
            salobj.set_random_lsst_dds_domain()
            for initial_simulation_mode in (1, 3, 4):
                csc = salobj.TestCsc(index=1, initial_simulation_mode=initial_simulation_mode)
                with self.assertRaises(salobj.ExpectedError):
                    await csc.start_task

            csc = salobj.TestCsc(index=1, initial_simulation_mode=0)
            await csc.start_task
            self.assertEqual(csc.simulation_mode, 0)

        asyncio.get_event_loop().run_until_complete(doit())

    async def check_simulate_mode_ok(self, harness):
        """Check that we can set simulation mode to 0 but not other values."""
        setsm_data = harness.remote.cmd_setSimulationMode.DataType()

        setsm_data.mode = 0
        await harness.remote.cmd_setSimulationMode.start(setsm_data, timeout=2)
        sm_data = await harness.remote.evt_simulationMode.next(flush=False, timeout=2)
        self.assertEqual(sm_data.mode, 0)

        for bad_mode in (1, 10, -1):
            setsm_data.mode = 1
            with self.subTest(bad_mode=bad_mode):
                with salobj.assertRaisesAckError():
                    await harness.remote.cmd_setSimulationMode.start(setsm_data, timeout=2)

    async def check_simulate_mode_bad(self, harness):
        """Check that we cannot set simulation mode to 0 or any other value."""
        setsm_data = harness.remote.cmd_setSimulationMode.DataType()

        for bad_mode in (0, 1, 10, -1):
            setsm_data.mode = 1
            with self.subTest(bad_mode=bad_mode):
                with salobj.assertRaisesAckError():
                    await harness.remote.cmd_setSimulationMode.start(setsm_data, timeout=2)


@unittest.skipIf(SALPY_Test is None, "Could not import SALPY_Test")
class RemoteConstructorTestCase(unittest.TestCase):
    def test_remote_include_exclude(self):
        """Test the include and exclude arguments for salobj.Remote"""
        index = next(index_gen)
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

        # remote3 omits commands
        remote3 = salobj.Remote(SALPY_Test, index=index, readonly=True)
        remote_command_names = set([name for name in dir(remote3) if name.startswith("cmd_")])
        self.assertEqual(remote_command_names, set())
        remote_event_names = set([name for name in dir(remote3) if name.startswith("evt_")])
        self.assertEqual(remote_event_names, all_event_method_names)
        remote_telemetry_names = set([name for name in dir(remote3) if name.startswith("tel_")])
        self.assertEqual(remote_telemetry_names, all_telemetry_method_names)

        # make sure one cannot specify both include and exclude
        with self.assertRaises(ValueError):
            salobj.Remote(SALPY_Test, index=index, include=include, exclude=exclude)


class ControllerWithDoMethods(salobj.Controller):
    """A Test controller with a trivial do_<name> method for each
    specified command name.

    Parameters
    ----------
    command_names : `iterable` of `str`
        List of command names for which to make trivial ``do_<name>``
        methods.
    """
    def __init__(self, command_names):
        def amethod(self, *args, **kwargs):
            pass

        index = next(index_gen)
        for name in command_names:
            setattr(self, f"do_{name}", amethod)
        super().__init__(SALPY_Test, index, do_callbacks=True)


@unittest.skipIf(SALPY_Test is None, "Could not import SALPY_Test")
class ControllerConstructorTestCase(unittest.TestCase):
    def setUp(self):
        salobj.set_random_lsst_dds_domain()

    def test_do_callbacks_false(self):
        index = next(index_gen)
        controller = salobj.Controller(SALPY_Test, index, do_callbacks=False)
        command_names = controller.salinfo.manager.getCommandNames()
        for name in command_names:
            with self.subTest(name=name):
                cmd = getattr(controller, "cmd_" + name)
                self.assertFalse(cmd.has_callback)

    def test_do_callbacks_true(self):
        index = next(index_gen)
        salinfo = salobj.SalInfo(SALPY_Test, index)
        command_names = salinfo.manager.getCommandNames()

        # make sure I can build one
        good_controller = ControllerWithDoMethods(command_names)
        for cmd_name in command_names:
            with self.subTest(cmd_name=cmd_name):
                cmd = getattr(good_controller, "cmd_" + cmd_name)
                self.assertTrue(cmd.has_callback)

        skip_names = salobj.OPTIONAL_COMMAND_NAMES.copy()
        # do_setLogLevel is provided by Controller
        skip_names.add("setLogLevel")
        for missing_name in command_names:
            if missing_name in skip_names:
                continue
            with self.subTest(missing_name=missing_name):
                bad_names = [name for name in command_names if name != missing_name]
                with self.assertRaises(TypeError):
                    ControllerWithDoMethods(bad_names)

        extra_names = command_names + ["extra_command"]
        with self.assertRaises(TypeError):
            ControllerWithDoMethods(extra_names)


class NoIndexCsc(salobj.TestCsc):
    """A CSC whose constructor has no index argument"""
    def __init__(self, arg1, arg2):
        super().__init__(index=next(index_gen))
        self.arg1 = arg1
        self.arg2 = arg2


@unittest.skipIf(SALPY_Test is None, "Could not import SALPY_Test")
class TestCscConstructorTestCase(unittest.TestCase):
    def setUp(self):
        salobj.set_random_lsst_dds_domain()

    def test_integer_initial_state(self):
        """Test that initial_state can be an integer."""
        for state in (min(salobj.State), max(salobj.State)):
            int_state = int(state)
            with self.subTest(initial_state=int_state):
                csc = salobj.TestCsc(index=next(index_gen), initial_state=int_state)
                self.assertEqual(csc.summary_state, state)

    def test_invalid_initial_state(self):
        """Test that invalid integer initial_state is rejected."""
        for invalid_state in (min(salobj.State) - 1,
                              max(salobj.State) + 1):
            with self.subTest(invalid_state=invalid_state):
                with self.assertRaises(ValueError):
                    salobj.TestCsc(index=next(index_gen), initial_state=invalid_state)


class FailedCallbackCsc(salobj.TestCsc):
    """A CSC whose do_wait command raises a RuntimeError"""
    def __init__(self, index, initial_state):
        super().__init__(index=index, initial_state=initial_state)
        self.exc_msg = "do_wait raised an exception on purpose"

    async def do_wait(self, id_data):
        raise RuntimeError(self.exc_msg)


@unittest.skipIf(SALPY_Test is None, "Could not import SALPY_Test")
class ControllerCommandLoggingTestCase(unittest.TestCase):
    def setUp(self):
        index = next(index_gen)
        salobj.set_random_lsst_dds_domain()
        self.csc = FailedCallbackCsc(index=index, initial_state=salobj.State.ENABLED)
        self.remote = salobj.Remote(SALPY_Test, index)

    def test_logging(self):
        async def doit():
            self.remote.cmd_wait.set(duration=5)
            with salobj.assertRaisesAckError():
                await self.remote.cmd_wait.start(timeout=2)

            msg = await self.remote.evt_logMessage.next(flush=False, timeout=1)
            self.assertEqual("coro cmd_wait callback failed", msg.message)
            self.assertIn(self.csc.exc_msg, msg.traceback)
            self.assertIn("Traceback", msg.traceback)
            self.assertIn("RuntimeError", msg.traceback)
            self.assertEqual(msg.level, logging.ERROR)

        asyncio.get_event_loop().run_until_complete(doit())


@unittest.skipIf(SALPY_Test is None, "Could not import SALPY_Test")
class BaseCscMainTestCase(unittest.TestCase):
    def setUp(self):
        salobj.set_random_lsst_dds_domain()

    def test_no_index(self):
        async def doit(index):
            arg1 = "astring"
            arg2 = 2.75
            csc = NoIndexCsc.main(index=index, arg1=arg1, arg2=arg2, run_loop=False)
            self.assertEqual(csc.arg1, arg1)
            self.assertEqual(csc.arg2, arg2)
            csc.do_exitControl(salobj.CommandIdData(cmd_id=1, data=None))
            await csc.done_task

        for index in (False, None):
            with self.subTest(index=index):
                asyncio.get_event_loop().run_until_complete(doit(index=index))

    def test_specified_index(self):
        async def doit():
            index = next(index_gen)
            csc = salobj.TestCsc.main(index=index, run_loop=False)
            self.assertEqual(csc.salinfo.index, index)
            csc.do_exitControl(salobj.CommandIdData(cmd_id=1, data=None))
            await csc.done_task

        asyncio.get_event_loop().run_until_complete(doit())

    def test_index_from_argument(self):
        async def doit():
            index = next(index_gen)
            original_argv = sys.argv[:]
            try:
                sys.argv[:] = [sys.argv[0], str(index)]
                csc = salobj.TestCsc.main(index=True, run_loop=False)
                self.assertEqual(csc.salinfo.index, index)
                csc.do_exitControl(salobj.CommandIdData(cmd_id=1, data=None))
                await csc.done_task
            finally:
                sys.argv[:] = original_argv

        asyncio.get_event_loop().run_until_complete(doit())


if __name__ == "__main__":
    unittest.main()
