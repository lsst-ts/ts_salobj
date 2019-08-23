import asyncio
import logging
import random
import time
import unittest

import numpy as np

from lsst.ts import salobj

SHOW_LOG_MESSAGES = False

STD_TIMEOUT = 10  # timeout for command ack
EVENT_DELAY = 0.1  # time for events to be output as a result of a command
NODATA_TIMEOUT = 0.1  # timeout for when we expect no new data

np.random.seed(47)

index_gen = salobj.index_generator()


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


class TopicsTestCase(unittest.TestCase):
    def setUp(self):
        salobj.set_random_lsst_dds_domain()

    def test_attributes(self):
        async def doit():
            async with Harness(initial_state=salobj.State.ENABLED) as harness:
                for obj in (harness.remote, harness.csc):
                    for cmd_name in obj.salinfo.command_names:
                        cmd = getattr(obj, f"cmd_{cmd_name}")
                        self.assertEqual(cmd.name, cmd_name)
                        self.assertEqual(cmd.attr_name, "cmd_" + cmd_name)
                        self.assertEqual(cmd.sal_name, "command_" + cmd_name)
                        self.assertEqual(cmd.dds_name,
                                         cmd.salinfo.name + "_" + cmd.sal_name + "_" + cmd.rev_code)
                        self.assertTrue(cmd.volatile)

                    for evt_name in obj.salinfo.event_names:
                        evt = getattr(obj, f"evt_{evt_name}")
                        self.assertEqual(evt.name, evt_name)
                        self.assertEqual(evt.attr_name, "evt_" + evt_name)
                        self.assertEqual(evt.sal_name, "logevent_" + evt_name)
                        self.assertEqual(evt.dds_name,
                                         evt.salinfo.name + "_" + evt.sal_name + "_" + evt.rev_code)
                        self.assertFalse(evt.volatile)

                    for tel_name in obj.salinfo.telemetry_names:
                        tel = getattr(obj, f"tel_{tel_name}")
                        self.assertEqual(tel.name, tel_name)
                        self.assertEqual(tel.attr_name, "tel_" + tel_name)
                        self.assertEqual(tel.sal_name, tel_name)
                        self.assertEqual(tel.dds_name,
                                         tel.salinfo.name + "_" + tel.sal_name + "_" + tel.rev_code)
                        self.assertFalse(tel.volatile)

                # cannot add new topics to the existing salinfos
                # (because the read loop has started) so create a new one
                salinfo = salobj.SalInfo(domain=harness.csc.salinfo.domain,
                                         name=harness.csc.salinfo.name,
                                         index=harness.csc.salinfo.index)
                for ackcmd in (salobj.topics.AckCmdReader(salinfo=salinfo),
                               salobj.topics.AckCmdWriter(salinfo=salinfo)):
                    self.assertEqual(ackcmd.name, "ackcmd")
                    self.assertEqual(ackcmd.attr_name, "ack_" + ackcmd.name)
                    self.assertEqual(ackcmd.sal_name, ackcmd.name)
                    self.assertEqual(ackcmd.dds_name,
                                     ackcmd.salinfo.name + "_" + ackcmd.sal_name + "_" + ackcmd.rev_code)
                    self.assertTrue(ackcmd.volatile)

        asyncio.get_event_loop().run_until_complete(doit())

    def test_base_topic_constructor_good(self):
        async def doit():

            async with salobj.Domain() as domain:
                salinfo = salobj.SalInfo(domain=domain, name="Test", index=1)

                for cmd_name in salinfo.command_names:
                    cmd = salobj.topics.BaseTopic(salinfo=salinfo, name=cmd_name, sal_prefix="command_")
                    self.assertEqual(cmd.name, cmd_name)

                for evt_name in salinfo.event_names:
                    evt = salobj.topics.BaseTopic(salinfo=salinfo, name=evt_name, sal_prefix="logevent_")
                    self.assertEqual(evt.name, evt_name)

                for tel_name in salinfo.telemetry_names:
                    tel = salobj.topics.BaseTopic(salinfo=salinfo, name=tel_name, sal_prefix="")
                    self.assertEqual(tel.name, tel_name)

        asyncio.get_event_loop().run_until_complete(doit())

    def test_base_topic_constructor_errors(self):
        async def doit():

            async with salobj.Domain() as domain:
                salinfo = salobj.SalInfo(domain=domain, name="Test", index=1)

                for good_name in ("setScalars", "scalars"):
                    for bad_prefix in (
                        "_",
                        "invalid_",
                        "logevent",  # no trailing underscore
                        "command",  # no trailing underscore
                    ):
                        with self.assertRaises(RuntimeError):
                            salobj.topics.BaseTopic(salinfo=salinfo, name=good_name, sal_prefix=bad_prefix)

                for good_prefix in ("", "command_", "logevent_"):
                    for bad_name in ("", "no_such_topic"):
                        with self.assertRaises(RuntimeError):
                            salobj.topics.BaseTopic(salinfo=salinfo, name=bad_name, sal_prefix=good_prefix)

                for cmd_name in salinfo.command_names:
                    for non_cmd_prefix in ("", "logevent_"):
                        with self.assertRaises(RuntimeError):
                            salobj.topics.BaseTopic(salinfo=salinfo, name=cmd_name, sal_prefix=non_cmd_prefix)

                # there is overlap between event and telemetry names
                # so just use the command_ prefix as the invalid prefix
                non_evt_prefix = "command_"
                for evt_name in salinfo.event_names:
                    with self.assertRaises(RuntimeError):
                        salobj.topics.BaseTopic(salinfo=salinfo, name=evt_name, sal_prefix=non_evt_prefix)

                # there is overlap between event and telemetry names
                # so just use the command_ prefix as the invalid prefix
                non_tel_prefix = "command_"
                for tel_name in salinfo.telemetry_names:
                    with self.assertRaises(RuntimeError):
                        salobj.topics.BaseTopic(salinfo=salinfo, name=tel_name, sal_prefix=non_tel_prefix)

        asyncio.get_event_loop().run_until_complete(doit())

    def test_command_isolation(self):
        """Test that multiple RemoteCommands for one command only see
        cmdack replies to their own samples.

        Note that the RemoteCommands must each have a different Domain,
        as the isolation is based on Domain properties.
        In order to avoid making extra domains, the command reader uses one of
        those two domains.
        """
        async def doit():

            async with salobj.Domain() as domain1, salobj.Domain() as domain2:
                self.assertNotEqual(domain1.host, domain2.host)
                salinfo1 = salobj.SalInfo(domain=domain1, name="Test", index=1)
                salinfo2 = salobj.SalInfo(domain=domain2, name="Test", index=1)
                cmdreader = salobj.topics.ControllerCommand(salinfo=salinfo1, name="wait")
                # set the random seed before each call so both writers
                # use the same initial seqNum
                random.seed(52)
                cmdwriter1 = salobj.topics.RemoteCommand(salinfo=salinfo1, name="wait")
                random.seed(52)
                cmdwriter2 = salobj.topics.RemoteCommand(salinfo=salinfo2, name="wait")
                await salinfo1.start()
                await salinfo2.start()

                def reader_callback(data):
                    ackcmd = cmdreader.salinfo.AckCmdType(private_seqNum=data.private_seqNum,
                                                          ack=salobj.SalRetCode.CMD_COMPLETE)
                    cmdreader.ack(data=data, ackcmd=ackcmd)

                cmdreader.callback = reader_callback
                num_commands = 3
                for i in range(num_commands):
                    ack1 = await cmdwriter1.start(timeout=STD_TIMEOUT)
                    ack2 = await cmdwriter2.start(timeout=STD_TIMEOUT)
                    self.assertEqual(ack1.private_seqNum, ack2.private_seqNum)
                    self.assertEqual(ack1.host, domain1.host)
                    self.assertEqual(ack2.host, domain2.host)

        asyncio.get_event_loop().run_until_complete(doit())

    def test_controller_telemetry_put(self):
        """Test ControllerTelemetry.put using data=None and providing data.
        """
        async def doit():
            async with Harness(initial_state=salobj.State.ENABLED) as harness:
                # until put is called nothing has been sent
                self.assertFalse(harness.csc.tel_scalars.has_data)
                self.assertFalse(harness.remote.tel_scalars.has_data)
                self.assertIsNone(harness.remote.tel_scalars.get())

                # put random telemetry data using data=None
                tel_data1 = harness.csc.make_random_tel_scalars()
                harness.csc.tel_scalars.data = tel_data1
                self.assertTrue(harness.csc.tel_scalars.has_data)
                harness.csc.assert_scalars_equal(tel_data1, harness.csc.tel_scalars.data)
                harness.csc.tel_scalars.put()
                data = await harness.remote.tel_scalars.next(flush=False, timeout=STD_TIMEOUT)
                with self.assertRaises(asyncio.TimeoutError):
                    await harness.remote.tel_scalars.next(flush=False, timeout=NODATA_TIMEOUT)
                harness.csc.assert_scalars_equal(data, harness.csc.tel_scalars.data)

                # put random telemetry data specifying the data
                tel_data2 = harness.csc.make_random_tel_scalars()
                harness.csc.tel_scalars.put(tel_data2)
                harness.csc.assert_scalars_equal(tel_data2, harness.csc.tel_scalars.data)
                data = await harness.remote.tel_scalars.next(flush=False, timeout=STD_TIMEOUT)
                harness.csc.assert_scalars_equal(data, harness.csc.tel_scalars.data)
                with self.assertRaises(asyncio.TimeoutError):
                    await harness.remote.tel_scalars.next(flush=False, timeout=NODATA_TIMEOUT)

        asyncio.get_event_loop().run_until_complete(doit())

    def test_controller_event_put(self):
        """Test ControllerEvent.put using data=None and providing data.

        Also test setting metadata fields private_host, private_origin,
        private_sndStamp and private_rcvStamp
        """
        async def doit():
            async with Harness(initial_state=salobj.State.ENABLED) as harness:
                # until put is called nothing has been sent
                self.assertFalse(harness.csc.evt_scalars.has_data)
                self.assertFalse(harness.remote.evt_scalars.has_data)
                self.assertIsNone(harness.remote.evt_scalars.get())

                # put random event data using data=None
                evt_data1 = harness.csc.make_random_evt_scalars()
                harness.csc.evt_scalars.data = evt_data1
                self.assertTrue(harness.csc.evt_scalars.has_data)
                harness.csc.assert_scalars_equal(evt_data1, harness.csc.evt_scalars.data)
                send_utc0 = time.time()
                send_tai0 = salobj.tai_from_utc(send_utc0)
                harness.csc.evt_scalars.put()
                data = await harness.remote.evt_scalars.next(flush=False, timeout=STD_TIMEOUT)
                rcv_utc0 = time.time()
                rcv_tai0 = salobj.tai_from_utc(rcv_utc0)
                harness.csc.assert_scalars_equal(data, harness.csc.evt_scalars.data)
                with self.assertRaises(asyncio.TimeoutError):
                    await harness.remote.evt_scalars.next(flush=False, timeout=NODATA_TIMEOUT)
                self.assertEqual(evt_data1.private_host, harness.csc.domain.host)
                self.assertEqual(evt_data1.private_origin, harness.csc.domain.origin)
                self.assertAlmostEqual(evt_data1.private_sndStamp, send_tai0, places=1)
                self.assertAlmostEqual(data.private_rcvStamp, rcv_tai0, places=1)

                # put random event data specifying the data
                evt_data2 = harness.csc.make_random_evt_scalars()
                harness.csc.evt_scalars.put(evt_data2)
                harness.csc.assert_scalars_equal(evt_data2, harness.csc.evt_scalars.data)
                data = await harness.remote.evt_scalars.next(flush=False, timeout=STD_TIMEOUT)
                harness.csc.assert_scalars_equal(data, harness.csc.evt_scalars.data)
                with self.assertRaises(asyncio.TimeoutError):
                    await harness.remote.evt_scalars.next(flush=False, timeout=NODATA_TIMEOUT)

        asyncio.get_event_loop().run_until_complete(doit())

    def test_controller_telemetry_set_set_put(self):
        """Test ControllerTelemetry.set_put.
        """
        async def doit():
            async with Harness(initial_state=salobj.State.ENABLED) as harness:
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
                data = await harness.remote.tel_scalars.next(flush=False, timeout=STD_TIMEOUT)
                harness.csc.assert_scalars_equal(data, tel_data1)
                with self.assertRaises(asyncio.TimeoutError):
                    await harness.remote.tel_scalars.next(flush=False, timeout=NODATA_TIMEOUT)

                # set_put the same data again; the telemetry should be sent
                harness.csc.tel_scalars.set_put(**dict_data1)
                self.assertTrue(harness.csc.tel_scalars.has_data)
                harness.csc.assert_scalars_equal(tel_data1, harness.csc.tel_scalars.data)
                data = await harness.remote.tel_scalars.next(flush=False, timeout=STD_TIMEOUT)
                harness.csc.assert_scalars_equal(data, tel_data1)
                with self.assertRaises(asyncio.TimeoutError):
                    await harness.remote.tel_scalars.next(flush=False, timeout=NODATA_TIMEOUT)

                # use None for values to set_put; same telemetry should be sent
                none_dict = dict((key, None) for key in dict_data1)
                harness.csc.tel_scalars.set_put(**none_dict)
                self.assertTrue(harness.csc.tel_scalars.has_data)
                harness.csc.assert_scalars_equal(tel_data1, harness.csc.tel_scalars.data)
                data = await harness.remote.tel_scalars.next(flush=False, timeout=STD_TIMEOUT)
                harness.csc.assert_scalars_equal(data, tel_data1)
                with self.assertRaises(asyncio.TimeoutError):
                    await harness.remote.tel_scalars.next(flush=False, timeout=NODATA_TIMEOUT)

                # try an invalid key
                with self.assertRaises(AttributeError):
                    harness.csc.tel_scalars.set_put(no_such_attribute=None)

                # try an invalid value
                with self.assertRaises(ValueError):
                    harness.csc.evt_scalars.set_put(int0="not an int")
                with self.assertRaises(ValueError):
                    harness.csc.evt_scalars.set_put(int0="not an int", force_output=True)

                nint0 = len(harness.csc.evt_arrays.data.int0)

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
                # this raised an exception for SALPY but dds ignores
                # the extra elements
                # bad_int0 = np.arange(nint0+1, dtype=int)
                # with self.assertRaises(ValueError):
                #     harness.csc.tel_arrays.set_put(int0=bad_int0)

        asyncio.get_event_loop().run_until_complete(doit())

    def test_controller_event_set_set_put(self):
        """Test ControllerEvent.set_put.
        """
        async def doit():
            async with Harness(initial_state=salobj.State.ENABLED) as harness:
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
                data = await harness.remote.evt_scalars.next(flush=False, timeout=STD_TIMEOUT)
                harness.csc.assert_scalars_equal(data, evt_data1)
                with self.assertRaises(asyncio.TimeoutError):
                    await harness.remote.evt_scalars.next(flush=False, timeout=NODATA_TIMEOUT)

                # set_put with None values; the event should *not* be sent
                none_dict = dict((key, None) for key in dict_data1)
                did_put = harness.csc.evt_scalars.set_put(**none_dict)
                self.assertFalse(did_put)
                with self.assertRaises(asyncio.TimeoutError):
                    await harness.remote.evt_scalars.next(flush=False, timeout=NODATA_TIMEOUT)

                # set_put with None values and force_output=True
                none_dict = dict((key, None) for key in dict_data1)
                did_put = harness.csc.evt_scalars.set_put(**none_dict, force_output=True)
                self.assertTrue(did_put)
                harness.csc.assert_scalars_equal(evt_data1, harness.csc.evt_scalars.data)
                data = await harness.remote.evt_scalars.next(flush=False, timeout=STD_TIMEOUT)
                harness.csc.assert_scalars_equal(data, evt_data1)
                with self.assertRaises(asyncio.TimeoutError):
                    await harness.remote.evt_scalars.next(flush=False, timeout=NODATA_TIMEOUT)

                # set_put the same data again; the event should *not* be sent
                did_put = harness.csc.evt_scalars.set_put(**dict_data1)
                self.assertFalse(did_put)
                with self.assertRaises(asyncio.TimeoutError):
                    await harness.remote.evt_scalars.next(flush=False, timeout=NODATA_TIMEOUT)

                # set_put the same data again with force_output=True
                did_put = harness.csc.evt_scalars.set_put(**dict_data1, force_output=True)
                self.assertTrue(did_put)
                harness.csc.assert_scalars_equal(evt_data1, harness.csc.evt_scalars.data)
                data = await harness.remote.evt_scalars.next(flush=False, timeout=STD_TIMEOUT)
                harness.csc.assert_scalars_equal(data, evt_data1)
                with self.assertRaises(asyncio.TimeoutError):
                    await harness.remote.evt_scalars.next(flush=False, timeout=NODATA_TIMEOUT)

                # change one field of the data and set_put again
                dict_data1["int0"] = dict_data1["int0"] + 1
                did_put = harness.csc.evt_scalars.set_put(**dict_data1)
                self.assertTrue(did_put)
                with self.assertRaises(AssertionError):
                    harness.csc.assert_scalars_equal(evt_data1, harness.csc.evt_scalars.data)
                evt_data1.int0 += 1
                harness.csc.assert_scalars_equal(evt_data1, harness.csc.evt_scalars.data)
                data = await harness.remote.evt_scalars.next(flush=False, timeout=STD_TIMEOUT)
                harness.csc.assert_scalars_equal(data, evt_data1)
                with self.assertRaises(asyncio.TimeoutError):
                    await harness.remote.evt_scalars.next(flush=False, timeout=NODATA_TIMEOUT)

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

                nint0 = len(harness.csc.evt_arrays.data.int0)

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
                # this raised an exception for SALPY but dds ignores
                # the extra elements
                # bad_int0 = np.arange(nint0+1, dtype=int)
                # with self.assertRaises(ValueError):
                #     harness.csc.evt_arrays.set_put(int0=bad_int0)

        asyncio.get_event_loop().run_until_complete(doit())

    async def set_and_get_scalars(self, harness, num_commands):
        """Send the setScalars command repeatedly and return what was sent.

        Each command is sent with new random data. Each command triggers
        one sample each of ``scalars`` event and ``scalars`` telemetry.

        Parameters
        ----------
        harness : `Harness`
            Test harness.
        num_commands : `int`
            The number of setScalars commands to send.
        """
        # until the controller gets its first setArrays
        # it will not send any scalars events or telemetry
        self.assertIsNone(harness.remote.evt_scalars.get())
        self.assertIsNone(harness.remote.tel_scalars.get())

        # send the setScalars command with random data
        cmd_data_list = [harness.csc.make_random_cmd_scalars() for i in range(num_commands)]
        for cmd_data in cmd_data_list:
            await harness.remote.cmd_setScalars.start(cmd_data, timeout=STD_TIMEOUT)
        return cmd_data_list

    def test_aget(self):
        async def doit():
            async with Harness(initial_state=salobj.State.ENABLED) as harness:
                with self.assertRaises(asyncio.TimeoutError):
                    await harness.remote.evt_scalars.aget(timeout=NODATA_TIMEOUT)
                with self.assertRaises(asyncio.TimeoutError):
                    await harness.remote.tel_scalars.aget(timeout=NODATA_TIMEOUT)

                # start waiting for both events, then trigger multiple events
                evt_task = asyncio.ensure_future(harness.remote.evt_scalars.aget(timeout=STD_TIMEOUT))
                tel_task = asyncio.ensure_future(harness.remote.tel_scalars.aget(timeout=STD_TIMEOUT))

                num_commands = 3
                cmd_data_list = await self.set_and_get_scalars(harness, num_commands=num_commands)

                # the pending aget calls should receive the first event sent
                evt_data, tel_data = await asyncio.gather(evt_task, tel_task)
                harness.csc.assert_scalars_equal(cmd_data_list[0], evt_data)
                harness.csc.assert_scalars_equal(cmd_data_list[0], tel_data)

                # wait for all remaining events to be received
                await asyncio.sleep(EVENT_DELAY)

                # aget should return the last value seen,
                # no matter now many times it is called
                evt_data_list = [await harness.remote.evt_scalars.aget() for i in range(5)]
                for evt_data in evt_data_list:
                    self.assertIsNotNone(evt_data)
                    harness.csc.assert_scalars_equal(cmd_data_list[-1], evt_data)

                # aget should return the last value seen,
                # no matter now many times it is called
                tel_data_list = [await harness.remote.tel_scalars.aget() for i in range(5)]
                for tel_data in tel_data_list:
                    self.assertIsNotNone(tel_data)
                    harness.csc.assert_scalars_equal(cmd_data_list[-1], tel_data)

        asyncio.get_event_loop().run_until_complete(doit())

    def test_get(self):
        async def doit():
            async with Harness(initial_state=salobj.State.ENABLED) as harness:
                num_commands = 3
                cmd_data_list = await self.set_and_get_scalars(harness, num_commands=num_commands)
                # wait for all events
                await asyncio.sleep(EVENT_DELAY)

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

    def test_get_oldest(self):
        async def doit():
            async with Harness(initial_state=salobj.State.ENABLED) as harness:
                num_commands = 3
                cmd_data_list = await self.set_and_get_scalars(harness, num_commands=num_commands)
                # wait for all events
                await asyncio.sleep(EVENT_DELAY)

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

    def test_next(self):
        async def doit():
            async with Harness(initial_state=salobj.State.ENABLED) as harness:
                num_commands = 3
                cmd_data_list = await self.set_and_get_scalars(harness, num_commands=num_commands)

                evt_data_list = []
                while True:
                    try:
                        evt_data = await harness.remote.evt_scalars.next(flush=False, timeout=NODATA_TIMEOUT)
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
                        tel_data = await harness.remote.tel_scalars.next(flush=False, timeout=NODATA_TIMEOUT)
                        self.assertIsNotNone(tel_data)
                        tel_data_list.append(tel_data)
                    except asyncio.TimeoutError:
                        break
                self.assertEqual(len(tel_data_list), num_commands)
                for cmd_data, tel_data in zip(cmd_data_list, tel_data_list):
                    harness.csc.assert_scalars_equal(cmd_data, tel_data)

        asyncio.get_event_loop().run_until_complete(doit())

    def test_callbacks(self):
        async def doit():
            evt_data_list = []

            def evt_callback(data):
                evt_data_list.append(data)

            tel_data_list = []

            def tel_callback(data):
                tel_data_list.append(data)

            num_commands = 3
            async with Harness(initial_state=salobj.State.ENABLED) as harness:
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
                # give the wait loops time to finish
                await asyncio.sleep(EVENT_DELAY)

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
        async def doit():
            async with Harness(initial_state=salobj.State.ENABLED) as harness:
                with self.assertRaises(TypeError):
                    # telemetry/event mismatch
                    harness.csc.evt_scalars.put(harness.csc.tel_scalars.DataType())
                with self.assertRaises(TypeError):
                    # telemetry/event mismatch
                    harness.csc.tel_scalars.put(harness.csc.evt_scalars.DataType())
                with self.assertRaises(TypeError):
                    await harness.remote.cmd_wait.start(harness.csc.cmd_setScalars.DataType())

        asyncio.get_event_loop().run_until_complete(doit())

    def test_put_id(self):
        """Test that one can set the TestID field of a write topic
        if index=0 and not otherwise.
        """
        async def doit():
            async with salobj.Controller(name="Test", index=0) as controller0:
                async with salobj.Controller(name="Test", index=1) as controller1:
                    for ind in (0, 1, 2, 3):
                        # for a controller with zero index
                        # TestID will be whatever you set it to
                        controller0.evt_scalars.set_put(TestID=ind)
                        self.assertEqual(controller0.evt_scalars.data.TestID, ind)
                        # for a controller with non-zero index
                        # TestID always matches that index
                        controller1.evt_scalars.set_put(TestID=ind)
                        self.assertEqual(controller1.evt_scalars.data.TestID, 1)

        asyncio.get_event_loop().run_until_complete(doit())

    def test_command_timeout(self):
        async def doit():
            async with Harness(initial_state=salobj.State.ENABLED) as harness:
                with salobj.assertRaisesAckTimeoutError(ack=salobj.SalRetCode.CMD_INPROGRESS):
                    await harness.remote.cmd_wait.set_start(duration=5, ack=salobj.SalRetCode.CMD_COMPLETE,
                                                            timeout=0.5)

        asyncio.get_event_loop().run_until_complete(doit())

    def test_controller_command_get_next(self):
        """Test ControllerCommand get and next methods.

        This requires unsetting the callback function for a command
        and thus not awaiting the start command.
        """
        async def doit():
            async with Harness(initial_state=salobj.State.ENABLED) as harness:
                # next fails if there is a callback
                with self.assertRaises(RuntimeError):
                    await harness.csc.cmd_wait.next()

                harness.csc.cmd_wait.callback = None

                duration = 1
                task1 = asyncio.ensure_future(harness.remote.cmd_wait.set_start(duration=duration))
                next_data = await harness.csc.cmd_wait.next(timeout=STD_TIMEOUT)
                get_data = harness.csc.cmd_wait.get()
                self.assertIsNotNone(get_data)
                self.assertEqual(get_data.duration, duration)
                self.assertEqual(next_data.duration, duration)

                # show that get() flushes the queue
                with self.assertRaises(asyncio.TimeoutError):
                    await harness.csc.cmd_wait.next(timeout=NODATA_TIMEOUT)

                duration = 2
                task2 = asyncio.ensure_future(harness.remote.cmd_wait.set_start(duration=duration))
                await asyncio.sleep(0.5)
                get_data = harness.csc.cmd_wait.get(flush=False)
                next_data = await harness.csc.cmd_wait.next(timeout=STD_TIMEOUT)
                self.assertIsNotNone(get_data)
                self.assertEqual(get_data.duration, duration)
                self.assertEqual(next_data.duration, duration)

                task1.cancel()
                task2.cancel()

        asyncio.get_event_loop().run_until_complete(doit())

    def test_controller_command_callback(self):
        """Test getting and setting a callback for a ControllerCommand.
        """
        async def doit():
            async with Harness(initial_state=salobj.State.ENABLED) as harness:
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
        async def doit():
            async with Harness(initial_state=salobj.State.ENABLED) as harness:
                self.assertTrue(harness.csc.cmd_wait.has_callback)
                self.assertTrue(harness.csc.cmd_wait.allow_multiple_callbacks)

                durations = (0.4, 0.2)  # seconds
                t0 = time.time()
                tasks = []
                for duration in durations:
                    task = asyncio.ensure_future(harness.remote.cmd_wait.set_start(
                        duration=duration, ack=salobj.SalRetCode.CMD_COMPLETE, timeout=STD_TIMEOUT+duration))
                    # make sure the command is sent before the command data
                    # is modified by the next loop iteration
                    await asyncio.sleep(0)
                    tasks.append(task)
                ackcmds = await asyncio.gather(*tasks)
                measured_duration = time.time() - t0
                for ackcmd in ackcmds:
                    self.assertEqual(ackcmd.ack, salobj.SalRetCode.CMD_COMPLETE)

                expected_duration = max(*durations)
                self.assertLess(abs(measured_duration - expected_duration), 0.1)

        asyncio.get_event_loop().run_until_complete(doit())

    def test_multiple_sequential_commands(self):
        """Test that commands prohibiting multiple callbacks are executed
        one after the other.
        """
        async def doit():
            async with Harness(initial_state=salobj.State.ENABLED) as harness:
                self.assertTrue(harness.csc.cmd_wait.has_callback)
                harness.csc.cmd_wait.allow_multiple_callbacks = False
                self.assertFalse(harness.csc.cmd_wait.allow_multiple_callbacks)

                durations = (0.4, 0.2)  # seconds
                t0 = time.time()

                tasks = []
                for duration in durations:
                    task = asyncio.ensure_future(harness.remote.cmd_wait.set_start(
                        duration=duration, ack=salobj.SalRetCode.CMD_COMPLETE, timeout=STD_TIMEOUT+duration))
                    tasks.append(task)
                    # make sure the command is sent before the command data
                    # is modified by the next loop iteration
                    await asyncio.sleep(0)
                ackcmds = await asyncio.gather(*tasks)
                measured_duration = time.time() - t0
                for ackcmd in ackcmds:
                    self.assertEqual(ackcmd.ack, salobj.SalRetCode.CMD_COMPLETE)

                expected_duration = np.sum(durations)
                self.assertLess(abs(measured_duration - expected_duration), 0.1)

        asyncio.get_event_loop().run_until_complete(doit())

    def test_asynchronous_event_callback(self):
        async def doit():
            async with Harness(initial_state=salobj.State.ENABLED) as harness:
                cmd_scalars_data = harness.csc.make_random_cmd_scalars()
                callback_data = None

                async def scalars_callback(scalars):
                    nonlocal callback_data
                    callback_data = scalars

                # send the setScalars command with random data
                # but first set a callback for event that should be triggered
                harness.remote.evt_scalars.callback = scalars_callback
                await harness.remote.cmd_setScalars.start(cmd_scalars_data, timeout=STD_TIMEOUT)
                # give the callback time to be called
                await asyncio.sleep(EVENT_DELAY)
                harness.csc.assert_scalars_equal(callback_data, cmd_scalars_data)

        asyncio.get_event_loop().run_until_complete(doit())

    def test_synchronous_event_callback(self):
        """Like test_asynchronous_event_callback but the callback function
        is synchronous"""
        async def doit():
            async with Harness(initial_state=salobj.State.ENABLED) as harness:
                cmd_scalars_data = harness.csc.make_random_cmd_scalars()
                callback_data = None

                def scalars_callback(scalars):
                    nonlocal callback_data
                    callback_data = scalars

                # send the setScalars command with random data
                # but first set a callback for event that should be triggered
                harness.remote.evt_scalars.callback = scalars_callback
                await harness.remote.cmd_setScalars.start(cmd_scalars_data, timeout=STD_TIMEOUT)
                # give the callback time to be called
                await asyncio.sleep(EVENT_DELAY)
                harness.csc.assert_scalars_equal(callback_data, cmd_scalars_data)

        asyncio.get_event_loop().run_until_complete(doit())

    def test_command_next_ack(self):
        async def doit():
            async with Harness(initial_state=salobj.State.ENABLED) as harness:
                ackcmd1 = await harness.remote.cmd_wait.set_start(duration=0.1, wait_done=False,
                                                                  timeout=STD_TIMEOUT)
                self.assertEqual(ackcmd1.ack, salobj.SalRetCode.CMD_ACK)
                ackcmd2 = await harness.remote.cmd_wait.next_ackcmd(ackcmd1, wait_done=False,
                                                                    timeout=STD_TIMEOUT)
                self.assertEqual(ackcmd2.ack, salobj.SalRetCode.CMD_INPROGRESS)
                ackcmd3 = await harness.remote.cmd_wait.next_ackcmd(ackcmd2, wait_done=True,
                                                                    timeout=STD_TIMEOUT)
                self.assertEqual(ackcmd3.ack, salobj.SalRetCode.CMD_COMPLETE)

                # now try a timeout
                ackcmd1 = await harness.remote.cmd_wait.set_start(duration=5, wait_done=False,
                                                                  timeout=STD_TIMEOUT)
                self.assertEqual(ackcmd1.ack, salobj.SalRetCode.CMD_ACK)
                with salobj.assertRaisesAckTimeoutError(ack=salobj.SalRetCode.CMD_INPROGRESS):
                    await harness.remote.cmd_wait.next_ackcmd(ackcmd1, wait_done=True, timeout=NODATA_TIMEOUT)

        asyncio.get_event_loop().run_until_complete(doit())

    def test_command_seq_num(self):
        async def doit():
            async with Harness(initial_state=salobj.State.ENABLED) as harness:
                prev_max_seq_num = None
                for cmd_name in harness.remote.salinfo.command_names:
                    cmd = getattr(harness.remote, f"cmd_{cmd_name}")
                    cmd.put()
                    seq_num = cmd.data.private_seqNum
                    cmd.put()
                    seq_num2 = cmd.data.private_seqNum
                    if seq_num < cmd.max_seq_num:
                        self.assertEqual(seq_num2, seq_num+1)
                    if prev_max_seq_num is None:
                        self.assertEqual(cmd.min_seq_num, 1)
                    else:
                        self.assertEqual(cmd.min_seq_num, prev_max_seq_num + 1)
                    prev_max_seq_num = cmd.max_seq_num

        asyncio.get_event_loop().run_until_complete(doit())

    def test_partitions(self):
        """Test specifying a DDS partition with $LSST_DDS_DOMAIN."""
        async def doit():
            async with salobj.Domain() as domain:
                salinfo1 = salobj.SalInfo(domain=domain, name="Test", index=0)
                salobj.set_random_lsst_dds_domain()
                salinfo2 = salobj.SalInfo(domain=domain, name="Test", index=0)
                writer1 = salobj.topics.ControllerEvent(salinfo=salinfo1, name="errorCode")
                writer2 = salobj.topics.ControllerEvent(salinfo=salinfo2, name="errorCode")

                # write late joiner data (before we have readers);
                # only the last value should be seen
                for i in (3, 4, 5):
                    writer1.set_put(errorCode=10+i)
                    writer2.set_put(errorCode=20+i)

                # create readers and set callbacks for them
                reader1 = salobj.topics.RemoteEvent(salinfo=salinfo1, name="errorCode")
                reader2 = salobj.topics.RemoteEvent(salinfo=salinfo2, name="errorCode")
                await salinfo1.start()
                await salinfo2.start()

                # write more data now that we have readers;
                # they should see all of it
                for i in (6, 7, 8):
                    writer1.set_put(errorCode=10+i)
                    writer2.set_put(errorCode=20+i)

                read_codes1 = []
                read_codes2 = []
                try:
                    for i in range(5):
                        data1 = await reader1.next(flush=False, timeout=NODATA_TIMEOUT)
                        read_codes1.append(data1.errorCode)
                except asyncio.TimeoutError:
                    pass
                try:
                    for i in range(5):
                        data2 = await reader2.next(flush=False, timeout=NODATA_TIMEOUT)
                        read_codes2.append(data2.errorCode)
                except asyncio.TimeoutError:
                    pass
                expected_codes1 = [15, 16, 17, 18]
                expected_codes2 = [25, 26, 27, 28]
                self.assertEqual(read_codes1, expected_codes1)
                self.assertEqual(read_codes2, expected_codes2)

        asyncio.get_event_loop().run_until_complete(doit())

    def test_sal_index(self):
        """Test separation of data using SAL index.

        Readers with index=0 should see data from all writers of that topic,
        regardless of index.
        Readers with a non-zero SAL index should only see data
        from a writer with the same index.
        """
        async def doit():
            async with salobj.Domain() as domain:
                salinfo0 = salobj.SalInfo(domain=domain, name="Test", index=0)
                salinfo1 = salobj.SalInfo(domain=domain, name="Test", index=1)
                salinfo2 = salobj.SalInfo(domain=domain, name="Test", index=2)
                writer0 = salobj.topics.ControllerEvent(salinfo=salinfo0, name="errorCode")
                writer1 = salobj.topics.ControllerEvent(salinfo=salinfo1, name="errorCode")
                writer2 = salobj.topics.ControllerEvent(salinfo=salinfo2, name="errorCode")

                # write late joiner data (before we have readers);
                # only the last value should be seen
                for i in (3, 4, 5):
                    writer0.set_put(errorCode=i)
                    await asyncio.sleep(0.001)
                    writer1.set_put(errorCode=10+i)
                    await asyncio.sleep(0.001)
                    writer2.set_put(errorCode=20+i)
                    await asyncio.sleep(0.001)

                # create readers and set callbacks for them
                # the index 0 reader should data from all writers;
                # the index 1 and 2 readers should only see data from
                # the writer with the same index
                reader0 = salobj.topics.RemoteEvent(salinfo=salinfo0, name="errorCode")
                reader1 = salobj.topics.RemoteEvent(salinfo=salinfo1, name="errorCode")
                reader2 = salobj.topics.RemoteEvent(salinfo=salinfo2, name="errorCode")
                await salinfo0.start()
                await salinfo1.start()
                await salinfo2.start()

                # write more data now that we have readers;
                # they should see all of it
                for i in (6, 7, 8):
                    writer0.set_put(errorCode=i)
                    await asyncio.sleep(0.001)
                    writer1.set_put(errorCode=10+i)
                    await asyncio.sleep(0.001)
                    writer2.set_put(errorCode=20+i)
                    await asyncio.sleep(0.001)

                read_codes0 = []
                read_codes1 = []
                read_codes2 = []
                expected_codes0 = [25, 6, 16, 26, 7, 17, 27, 8, 18, 28]
                expected_codes1 = [15, 16, 17, 18]
                expected_codes2 = [25, 26, 27, 28]
                try:
                    for i in range(len(expected_codes0)):
                        data0 = await reader0.next(flush=False, timeout=NODATA_TIMEOUT)
                        read_codes0.append(data0.errorCode)
                except asyncio.TimeoutError:
                    pass
                try:
                    for i in range(len(expected_codes1)):
                        data1 = await reader1.next(flush=False, timeout=NODATA_TIMEOUT)
                        read_codes1.append(data1.errorCode)
                except asyncio.TimeoutError:
                    pass
                try:
                    for i in range(len(expected_codes2)):
                        data2 = await reader2.next(flush=False, timeout=NODATA_TIMEOUT)
                        read_codes2.append(data2.errorCode)
                except asyncio.TimeoutError:
                    pass
                self.assertEqual(read_codes0, expected_codes0)
                self.assertEqual(read_codes1, expected_codes1)
                self.assertEqual(read_codes2, expected_codes2)

        asyncio.get_event_loop().run_until_complete(doit())

    def test_topic_repr(self):
        async def doit():
            async with Harness(initial_state=salobj.State.ENABLED) as harness:
                salinfo = harness.remote.salinfo

                for obj, classSuffix in (
                    (harness.csc, "Controller"),
                    (harness.remote, "Remote"),
                ):
                    with self.subTest(obj=obj, classSuffix=classSuffix):
                        for cmd_name in salinfo.command_names:
                            cmd = getattr(obj, "cmd_" + cmd_name)
                            cmd_repr = repr(cmd)
                            self.assertIn(cmd_name, cmd_repr)
                            self.assertIn("Test", cmd_repr)
                            self.assertIn(classSuffix + "Command", cmd_repr)
                        for evt_name in salinfo.event_names:
                            evt = getattr(obj, "evt_" + evt_name)
                            evt_repr = repr(evt)
                            self.assertIn(evt_name, evt_repr)
                            self.assertIn("Test", evt_repr)
                            self.assertIn(classSuffix + "Event", evt_repr)
                        for tel_name in salinfo.telemetry_names:
                            tel = getattr(obj, "tel_" + tel_name)
                            tel_repr = repr(tel)
                            self.assertIn(tel_name, tel_repr)
                            self.assertIn("Test", tel_repr)
                            self.assertIn(classSuffix + "Telemetry", tel_repr)

        asyncio.get_event_loop().run_until_complete(doit())


if __name__ == "__main__":
    unittest.main()
