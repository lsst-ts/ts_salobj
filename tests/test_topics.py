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
import copy
import itertools
import math
import pathlib
import random
import time
import typing
import unittest

import numpy as np

from lsst.ts import salobj

# Long enough to perform any reasonable operation
# including starting a CSC or loading a script (seconds)
STD_TIMEOUT = 60
# Time for events to be output as a result of a command (seconds).
EVENT_DELAY = 0.1
# Timeout for when we expect no new data (seconds)
NODATA_TIMEOUT = 0.1

np.random.seed(47)


class TopicsTestCase(salobj.BaseCscTestCase, unittest.IsolatedAsyncioTestCase):
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

    def check_topic_metadata(self, topic: salobj.topics.BaseTopic) -> None:
        self.assertEqual(topic.metadata.sal_name, topic.sal_name)
        self.assertIs(topic.metadata, topic.salinfo.metadata.topic_info[topic.sal_name])

    async def test_attributes(self) -> None:
        async with self.make_csc(initial_state=salobj.State.ENABLED):
            for obj in (self.remote, self.csc):
                for cmd_name in obj.salinfo.command_names:
                    cmd = getattr(obj, f"cmd_{cmd_name}")
                    self.assertEqual(cmd.name, cmd_name)
                    self.assertEqual(cmd.attr_name, "cmd_" + cmd_name)
                    self.assertEqual(cmd.sal_name, "command_" + cmd_name)
                    self.assertEqual(
                        cmd.dds_name,
                        cmd.salinfo.name + "_" + cmd.sal_name + "_" + cmd.rev_code,
                    )
                    self.assertTrue(cmd.volatile)
                    self.check_topic_metadata(cmd)

                for evt_name in obj.salinfo.event_names:
                    evt = getattr(obj, f"evt_{evt_name}")
                    self.assertEqual(evt.name, evt_name)
                    self.assertEqual(evt.attr_name, "evt_" + evt_name)
                    self.assertEqual(evt.sal_name, "logevent_" + evt_name)
                    self.assertEqual(
                        evt.dds_name,
                        evt.salinfo.name + "_" + evt.sal_name + "_" + evt.rev_code,
                    )
                    self.assertFalse(evt.volatile)
                    self.check_topic_metadata(evt)

                for tel_name in obj.salinfo.telemetry_names:
                    tel = getattr(obj, f"tel_{tel_name}")
                    self.assertEqual(tel.name, tel_name)
                    self.assertEqual(tel.attr_name, "tel_" + tel_name)
                    self.assertEqual(tel.sal_name, tel_name)
                    self.assertEqual(
                        tel.dds_name,
                        tel.salinfo.name + "_" + tel.sal_name + "_" + tel.rev_code,
                    )
                    self.assertTrue(tel.volatile)
                    self.check_topic_metadata(tel)

            # cannot add new topics to the existing salinfos
            # (because the read loop has started) so create a new one
            salinfo = salobj.SalInfo(
                domain=self.csc.salinfo.domain,
                name=self.csc.salinfo.name,
                index=self.csc.salinfo.index,
            )
            for ackcmd in (
                salobj.topics.AckCmdReader(salinfo=salinfo),
                salobj.topics.AckCmdWriter(salinfo=salinfo),
            ):
                self.assertEqual(ackcmd.name, "ackcmd")
                self.assertEqual(ackcmd.attr_name, "ack_" + ackcmd.name)
                self.assertEqual(ackcmd.sal_name, ackcmd.name)
                self.assertEqual(
                    ackcmd.dds_name,
                    ackcmd.salinfo.name + "_" + ackcmd.sal_name + "_" + ackcmd.rev_code,
                )
                self.assertTrue(ackcmd.volatile)

    async def test_base_topic_constructor_good(self) -> None:
        async with salobj.Domain() as domain:
            salinfo = salobj.SalInfo(domain=domain, name="Test", index=1)

            for cmd_name in salinfo.command_names:
                cmd = salobj.topics.BaseTopic(
                    salinfo=salinfo, name=cmd_name, sal_prefix="command_"
                )
                self.assertEqual(cmd.name, cmd_name)

            for evt_name in salinfo.event_names:
                evt = salobj.topics.BaseTopic(
                    salinfo=salinfo, name=evt_name, sal_prefix="logevent_"
                )
                self.assertEqual(evt.name, evt_name)

            for tel_name in salinfo.telemetry_names:
                tel = salobj.topics.BaseTopic(
                    salinfo=salinfo, name=tel_name, sal_prefix=""
                )
                self.assertEqual(tel.name, tel_name)

    async def test_base_topic_constructor_errors(self) -> None:
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
                        salobj.topics.BaseTopic(
                            salinfo=salinfo, name=good_name, sal_prefix=bad_prefix
                        )

            for good_prefix in ("", "command_", "logevent_"):
                for bad_name in ("", "no_such_topic"):
                    with self.assertRaises(RuntimeError):
                        salobj.topics.BaseTopic(
                            salinfo=salinfo, name=bad_name, sal_prefix=good_prefix
                        )

            for cmd_name in salinfo.command_names:
                for non_cmd_prefix in ("", "logevent_"):
                    with self.assertRaises(RuntimeError):
                        salobj.topics.BaseTopic(
                            salinfo=salinfo, name=cmd_name, sal_prefix=non_cmd_prefix
                        )

            # there is overlap between event and telemetry names
            # so just use the command_ prefix as the invalid prefix
            non_evt_prefix = "command_"
            for evt_name in salinfo.event_names:
                with self.assertRaises(RuntimeError):
                    salobj.topics.BaseTopic(
                        salinfo=salinfo, name=evt_name, sal_prefix=non_evt_prefix
                    )

            # there is overlap between event and telemetry names
            # so just use the command_ prefix as the invalid prefix
            non_tel_prefix = "command_"
            for tel_name in salinfo.telemetry_names:
                with self.assertRaises(RuntimeError):
                    salobj.topics.BaseTopic(
                        salinfo=salinfo, name=tel_name, sal_prefix=non_tel_prefix
                    )

    async def test_command_isolation(self) -> None:
        """Test that multiple RemoteCommands for one command only see
        cmdack replies to their own samples.
        """
        async with salobj.Domain() as domain:
            salinfo = salobj.SalInfo(domain=domain, name="Test", index=1)
            cmdreader = salobj.topics.ReadTopic(
                salinfo=salinfo, name="wait", sal_prefix="command_", max_history=0
            )
            cmdwriter = salobj.topics.RemoteCommand(salinfo=salinfo, name="wait")
            cmdtype = salinfo.sal_topic_names.index(cmdwriter.sal_name)
            ackcmdwriter = salobj.topics.AckCmdWriter(salinfo=salinfo)

            # Also make an ackcmd reader that sees all data,
            # to test the ``filter_ackcmd`` argument.
            unfiltered_ackcmd_reader = salobj.topics.ReadTopic(
                salinfo=salinfo,
                name="wait",
                sal_prefix="command_",
                max_history=0,
                filter_ackcmd=False,
            )
            await salinfo.start()

            # Send and acknowledge 4 commands:
            # * The first is acknowledged with a different origin.
            # * The second is acknowledged with a different identity.
            # * The third is acknowledged with identity=""
            # * The last is acknowledged normally
            # The first three will not complete, the last will.
            nread = 0

            def reader_callback(data: salobj.BaseDdsDataType) -> None:
                nonlocal nread

                # Write initial ackcmd
                ackcmdwriter.set(
                    private_seqNum=data.private_seqNum,
                    origin=data.private_origin,
                    identity=data.private_identity,
                    cmdtype=cmdtype,
                    ack=salobj.SalRetCode.CMD_ACK,
                )
                ackcmdwriter.put()

                # Write final ackcmd, after tweaking data if appropriate.
                ackcmdwriter.set(ack=salobj.SalRetCode.CMD_COMPLETE)
                if nread == 0:
                    # Mismatched origin.
                    ackcmdwriter.set(origin=data.private_origin + 1)
                elif nread == 1:
                    # Mismatched identity.
                    ackcmdwriter.set(identity=data.private_identity + "extra")
                elif nread == 2:
                    # No identity.
                    ackcmdwriter.set(identity="")
                ackcmdwriter.put()
                nread += 1

            unfiltered_nread = 0

            def unfiltered_reader_callback(data: salobj.BaseDdsDataType) -> None:
                nonlocal unfiltered_nread
                unfiltered_nread += 1

            cmdreader.callback = reader_callback
            unfiltered_ackcmd_reader.callback = unfiltered_reader_callback

            tasks = []
            for i in range(4):
                tasks.append(asyncio.create_task(cmdwriter.start(timeout=STD_TIMEOUT)))
            await tasks[3]
            self.assertFalse(tasks[0].done())  # Origin did not match.
            self.assertFalse(tasks[1].done())  # Identity did not match.
            self.assertFalse(tasks[2].done())  # No identity.
            self.assertEqual(nread, 4)
            self.assertEqual(unfiltered_nread, 4)
            for task in tasks:
                task.cancel()

    async def test_controller_telemetry_put(self) -> None:
        """Test ControllerTelemetry.put using data=None and providing data."""
        async with self.make_csc(initial_state=salobj.State.ENABLED):
            # until put is called nothing has been sent
            self.assertFalse(self.csc.tel_scalars.has_data)
            self.assertFalse(self.remote.tel_scalars.has_data)
            self.assertIsNone(self.remote.tel_scalars.get())

            # put random telemetry data using data=None
            tel_data1 = self.csc.make_random_tel_scalars()
            self.csc.tel_scalars.data = tel_data1
            self.assertTrue(self.csc.tel_scalars.has_data)
            self.csc.assert_scalars_equal(tel_data1, self.csc.tel_scalars.data)
            self.csc.tel_scalars.put()
            data = await self.remote.tel_scalars.next(flush=False, timeout=STD_TIMEOUT)
            with self.assertRaises(asyncio.TimeoutError):
                await self.remote.tel_scalars.next(flush=False, timeout=NODATA_TIMEOUT)
            self.csc.assert_scalars_equal(data, self.csc.tel_scalars.data)

            # put random telemetry data specifying the data
            tel_data2 = self.csc.make_random_tel_scalars()
            self.csc.tel_scalars.put(tel_data2)
            self.csc.assert_scalars_equal(tel_data2, self.csc.tel_scalars.data)
            data = await self.remote.tel_scalars.next(flush=False, timeout=STD_TIMEOUT)
            self.csc.assert_scalars_equal(data, self.csc.tel_scalars.data)
            with self.assertRaises(asyncio.TimeoutError):
                await self.remote.tel_scalars.next(flush=False, timeout=NODATA_TIMEOUT)

    async def test_controller_event_put(self) -> None:
        """Test ControllerEvent.put using data=None and providing data.

        Also test setting metadata fields private_origin,
        private_sndStamp and private_rcvStamp
        """
        async with self.make_csc(initial_state=salobj.State.ENABLED):
            # until put is called nothing has been sent
            self.assertFalse(self.csc.evt_scalars.has_data)
            self.assertFalse(self.remote.evt_scalars.has_data)
            self.assertIsNone(self.remote.evt_scalars.get())

            # put random event data using data=None
            evt_data1 = self.csc.make_random_evt_scalars()
            self.csc.evt_scalars.data = evt_data1
            self.assertTrue(self.csc.evt_scalars.has_data)
            self.csc.assert_scalars_equal(evt_data1, self.csc.evt_scalars.data)
            send_tai0 = salobj.current_tai()
            self.csc.evt_scalars.put()
            data = await self.remote.evt_scalars.next(flush=False, timeout=STD_TIMEOUT)
            rcv_tai0 = salobj.current_tai()
            self.csc.assert_scalars_equal(data, self.csc.evt_scalars.data)
            with self.assertRaises(asyncio.TimeoutError):
                await self.remote.evt_scalars.next(flush=False, timeout=NODATA_TIMEOUT)
            self.assertEqual(evt_data1.private_origin, self.csc.domain.origin)
            self.assertAlmostEqual(evt_data1.private_sndStamp, send_tai0, places=1)
            self.assertAlmostEqual(data.private_rcvStamp, rcv_tai0, places=1)

            # put random event data specifying the data
            evt_data2 = self.csc.make_random_evt_scalars()
            self.csc.evt_scalars.put(evt_data2)
            self.csc.assert_scalars_equal(evt_data2, self.csc.evt_scalars.data)
            data = await self.remote.evt_scalars.next(flush=False, timeout=STD_TIMEOUT)
            self.csc.assert_scalars_equal(data, self.csc.evt_scalars.data)
            with self.assertRaises(asyncio.TimeoutError):
                await self.remote.evt_scalars.next(flush=False, timeout=NODATA_TIMEOUT)

    async def test_controller_set_and_set_put(self) -> None:
        """Test set and set_put methods of ControllerTelemetry
        and ControllerEvent.
        """
        async with self.make_csc(initial_state=salobj.State.ENABLED):
            for do_telemetry, do_arrays in itertools.product(
                (False, True), (False, True)
            ):
                with self.subTest(do_telmetry=do_telemetry, do_arrrays=do_arrays):
                    await self.check_controller_set_and_set_put(
                        do_telemetry=do_telemetry, do_arrays=do_arrays
                    )

    async def set_scalars(
        self, num_commands: int, assert_none: bool = True
    ) -> typing.List[salobj.BaseDdsDataType]:
        """Send the setScalars command repeatedly and return what was sent.

        Each command is sent with new random data. Each command triggers
        one sample each of ``scalars`` event and ``scalars`` telemetry.

        Parameters
        ----------
        num_commands : `int`
            The number of setScalars commands to send.
        assert_none : `bool`, optional
            Assert that evt_scalars and tel_scalars have seen no data?
            Set True unless you call this multiple times in one test.
        """
        # until the controller gets its first setArrays
        # it will not send any scalars events or telemetry
        if assert_none:
            self.assertIsNone(self.remote.evt_scalars.get())
            self.assertIsNone(self.remote.tel_scalars.get())

        # send the setScalars command with random data
        cmd_data_list = [
            self.csc.make_random_cmd_scalars() for i in range(num_commands)
        ]
        for cmd_data in cmd_data_list:
            await self.remote.cmd_setScalars.start(cmd_data, timeout=STD_TIMEOUT)
        return cmd_data_list

    async def test_aget(self) -> None:
        async with self.make_csc(initial_state=salobj.State.ENABLED):
            with self.assertRaises(asyncio.TimeoutError):
                await self.remote.evt_scalars.aget(timeout=NODATA_TIMEOUT)
            with self.assertRaises(asyncio.TimeoutError):
                await self.remote.tel_scalars.aget(timeout=NODATA_TIMEOUT)

            # start waiting for both events, then trigger multiple events
            evt_task = asyncio.create_task(
                self.remote.evt_scalars.aget(timeout=STD_TIMEOUT)
            )
            tel_task = asyncio.create_task(
                self.remote.tel_scalars.aget(timeout=STD_TIMEOUT)
            )

            num_commands = 3
            cmd_data_list = await self.set_scalars(num_commands=num_commands)

            # the pending aget calls should receive the first event sent
            evt_data, tel_data = await asyncio.gather(evt_task, tel_task)
            self.csc.assert_scalars_equal(cmd_data_list[0], evt_data)
            self.csc.assert_scalars_equal(cmd_data_list[0], tel_data)

            # wait for all remaining events to be received
            await asyncio.sleep(EVENT_DELAY)

            # aget should return the last value seen,
            # no matter now many times it is called
            evt_data_list = [await self.remote.evt_scalars.aget() for i in range(5)]
            for evt_data in evt_data_list:
                self.assertIsNotNone(evt_data)
                self.csc.assert_scalars_equal(cmd_data_list[-1], evt_data)

            # aget should return the last value seen,
            # no matter now many times it is called
            tel_data_list = [await self.remote.tel_scalars.aget() for i in range(5)]
            for tel_data in tel_data_list:
                self.assertIsNotNone(tel_data)
                self.csc.assert_scalars_equal(cmd_data_list[-1], tel_data)

    async def test_plain_get(self) -> None:
        """Test RemoteEvent.get and RemoteTelemetry.get."""
        async with self.make_csc(initial_state=salobj.State.ENABLED):
            is_first = True
            for read_topic in (self.remote.evt_scalars, self.remote.tel_scalars):
                if not is_first:
                    # Clear out data from previous iteration
                    read_topic.flush()
                num_commands = 3
                cmd_data_list = await self.set_scalars(
                    num_commands=num_commands, assert_none=is_first
                )
                # wait for all events
                await asyncio.sleep(EVENT_DELAY)

                # Test that get returns the last value seen,
                # no matter now many times it is called.
                # Use flush=False to leave queued data for a later
                # call to get that will flush the queue.
                data_list = [read_topic.get() for i in range(5)]
                for data in data_list:
                    self.assertIsNotNone(data)
                    self.csc.assert_scalars_equal(cmd_data_list[-1], data)

                # Make sure the data queue was not flushed.
                self.assertEqual(read_topic.nqueued, num_commands)

                # get with flush=False should warn and not flush the queue
                with self.assertWarnsRegex(
                    DeprecationWarning,
                    "Specifying a value for the flush argument is deprecated",
                ):
                    data = read_topic.get(flush=False)
                self.assertEqual(read_topic.nqueued, num_commands)
                self.csc.assert_scalars_equal(cmd_data_list[-1], data)

                # get with flush=True should warn and flush the queue
                with self.assertWarnsRegex(
                    DeprecationWarning, "flush=True is deprecated"
                ):
                    data = read_topic.get(flush=True)
                self.assertEqual(read_topic.nqueued, 0)
                self.csc.assert_scalars_equal(cmd_data_list[-1], data)

                is_first = False

    async def test_get_oldest(self) -> None:
        """Test that `get_oldest` returns the oldest sample."""
        async with self.make_csc(initial_state=salobj.State.ENABLED):
            num_commands = 3
            cmd_data_list = await self.set_scalars(num_commands=num_commands)
            # wait for all events
            await asyncio.sleep(EVENT_DELAY)

            evt_data_list = []
            while True:
                data = self.remote.evt_scalars.get_oldest()
                if data is None:
                    break
                evt_data_list.append(data)
            self.assertEqual(len(evt_data_list), num_commands)
            for cmd_data, evt_data in zip(cmd_data_list, evt_data_list):
                self.csc.assert_scalars_equal(cmd_data, evt_data)

            tel_data_list = []
            while True:
                data = self.remote.tel_scalars.get_oldest()
                if data is None:
                    break
                tel_data_list.append(data)
            self.assertEqual(len(tel_data_list), num_commands)
            for cmd_data, tel_data in zip(cmd_data_list, tel_data_list):
                self.csc.assert_scalars_equal(cmd_data, tel_data)

    async def test_next(self) -> None:
        async with self.make_csc(initial_state=salobj.State.ENABLED):
            num_commands = 3
            cmd_data_list = await self.set_scalars(num_commands=num_commands)

            evt_data_list = []
            while True:
                try:
                    evt_data = await self.remote.evt_scalars.next(
                        flush=False, timeout=NODATA_TIMEOUT
                    )
                    self.assertIsNotNone(evt_data)
                    evt_data_list.append(evt_data)
                except asyncio.TimeoutError:
                    break
            self.assertEqual(len(evt_data_list), num_commands)
            for cmd_data, evt_data in zip(cmd_data_list, evt_data_list):
                self.csc.assert_scalars_equal(cmd_data, evt_data)

            tel_data_list = []
            while True:
                try:
                    tel_data = await self.remote.tel_scalars.next(
                        flush=False, timeout=NODATA_TIMEOUT
                    )
                    self.assertIsNotNone(tel_data)
                    tel_data_list.append(tel_data)
                except asyncio.TimeoutError:
                    break
            self.assertEqual(len(tel_data_list), num_commands)
            for cmd_data, tel_data in zip(cmd_data_list, tel_data_list):
                self.csc.assert_scalars_equal(cmd_data, tel_data)

    async def test_multiple_next_readers(self) -> None:
        """Test multiple tasks simultaneously calling ``next``.

        Each reader should get the same data.
        """

        class Reader:
            """Read data from a ReadTopic using next

            Parameters
            ----------
            read_topic : `topics.ReadTopic`
                Topic to read.
            nitems : `int`
                Number of DDS samples to read.
            name : `str`
                Reader name
            """

            def __init__(
                self, read_topic: salobj.topics.ReadTopic, nitems: int, name: str
            ) -> None:
                self.read_topic = read_topic
                self.nitems = nitems
                self.name = name
                self.data: typing.List[salobj.BaseDdsDataType] = []
                self.read_loop_task = asyncio.create_task(self.read_loop())
                self.ready_to_read = asyncio.Event()

            async def close(self) -> None:
                self.read_loop_task.cancel()

            async def read_loop(self) -> None:
                while len(self.data) < self.nitems:
                    self.ready_to_read.set()
                    data = await self.read_topic.next(flush=False)
                    self.data.append(data)

        async with self.make_csc(initial_state=salobj.State.ENABLED):
            nreaders = 3
            nitems = 5
            data = list(range(nitems))
            readers = [
                Reader(read_topic=self.remote.tel_scalars, nitems=nitems, name=str(i))
                for i in range(nreaders)
            ]
            for item in data:
                await asyncio.wait_for(
                    asyncio.gather(
                        *[reader.ready_to_read.wait() for reader in readers]
                    ),
                    timeout=STD_TIMEOUT,
                )
                for reader in readers:
                    reader.ready_to_read.clear()
                self.csc.tel_scalars.set_put(int0=item)
            await asyncio.wait_for(
                asyncio.gather(*[reader.read_loop_task for reader in readers]),
                timeout=STD_TIMEOUT,
            )
            for reader in readers:
                read_data = [item.int0 for item in reader.data]
                self.assertEqual(data, read_data)

    async def test_callbacks(self) -> None:
        evt_data_list: typing.List[salobj.BaseDdsDataType] = []

        def evt_callback(data: salobj.BaseDdsDataType) -> None:
            evt_data_list.append(data)

        tel_data_list: typing.List[salobj.BaseDdsDataType] = []

        def tel_callback(data: salobj.BaseDdsDataType) -> None:
            tel_data_list.append(data)

        num_commands = 3
        async with self.make_csc(initial_state=salobj.State.ENABLED):
            self.remote.evt_scalars.callback = evt_callback
            self.remote.tel_scalars.callback = tel_callback

            with self.assertRaises(RuntimeError):
                self.remote.evt_scalars.get_oldest()
            with self.assertRaises(RuntimeError):
                self.remote.tel_scalars.get_oldest()
            with self.assertRaises(RuntimeError):
                self.remote.evt_scalars.flush()
            with self.assertRaises(RuntimeError):
                self.remote.tel_scalars.flush()
            with self.assertRaises(RuntimeError):
                await self.remote.evt_scalars.next(flush=False)
            with self.assertRaises(RuntimeError):
                await self.remote.tel_scalars.next(flush=False)

            cmd_data_list = await self.set_scalars(num_commands=num_commands)
            # give the wait loops time to finish
            await asyncio.sleep(EVENT_DELAY)

            self.assertEqual(len(evt_data_list), num_commands)
            for cmd_data, evt_data in zip(cmd_data_list, evt_data_list):
                self.csc.assert_scalars_equal(cmd_data, evt_data)

            self.assertEqual(len(tel_data_list), num_commands)
            for cmd_data, tel_data in zip(cmd_data_list, tel_data_list):
                self.csc.assert_scalars_equal(cmd_data, tel_data)

    async def test_bad_put(self) -> None:
        """Try to put invalid data types."""
        async with self.make_csc(initial_state=salobj.State.ENABLED):
            with self.assertRaises(TypeError):
                # telemetry/event mismatch
                self.csc.evt_scalars.put(self.csc.tel_scalars.DataType())
            with self.assertRaises(TypeError):
                # telemetry/event mismatch
                self.csc.tel_scalars.put(self.csc.evt_scalars.DataType())
            with self.assertRaises(TypeError):
                await self.remote.cmd_wait.start(self.csc.cmd_setScalars.DataType())

    async def test_put_id(self) -> None:
        """Test that one can set the TestID field of a write topic
        if index=0 and not otherwise.
        """
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

    async def test_command_timeout(self) -> None:
        async with self.make_csc(initial_state=salobj.State.ENABLED):
            # Test that a CMD_INPROGRESS command acknowledgement
            # extends the timeout.
            await self.remote.cmd_wait.set_start(duration=2, timeout=0.5)
            # Specify a negative duration in order to avoid the
            # CMD_INPROGRESS command ack that extends the timeout.
            # This should time out.
            with salobj.assertRaisesAckTimeoutError(ack=salobj.SalRetCode.CMD_ACK):
                await self.remote.cmd_wait.set_start(duration=-2, timeout=0.5)

    async def test_controller_command_get_next(self) -> None:
        """Test ControllerCommand get and next methods.

        This requires unsetting the callback function for a command
        and thus not awaiting the start command.
        """
        async with self.make_csc(initial_state=salobj.State.ENABLED):
            # next fails if there is a callback
            with self.assertRaises(RuntimeError):
                await self.csc.cmd_wait.next()

            self.csc.cmd_wait.callback = None

            duration = 1
            task1 = asyncio.create_task(
                self.remote.cmd_wait.set_start(duration=duration)
            )
            next_data = await self.csc.cmd_wait.next(timeout=STD_TIMEOUT)
            get_data = self.csc.cmd_wait.get()
            self.assertIsNotNone(get_data)
            self.assertEqual(get_data.duration, duration)
            self.assertEqual(next_data.duration, duration)

            # show that get() flushes the queue
            with self.assertRaises(asyncio.TimeoutError):
                await self.csc.cmd_wait.next(timeout=NODATA_TIMEOUT)

            duration = 2
            task2 = asyncio.create_task(
                self.remote.cmd_wait.set_start(duration=duration)
            )
            await asyncio.sleep(0.5)
            get_data = self.csc.cmd_wait.get()
            next_data = await self.csc.cmd_wait.next(timeout=STD_TIMEOUT)
            self.assertIsNotNone(get_data)
            self.assertEqual(get_data.duration, duration)
            self.assertEqual(next_data.duration, duration)

            task1.cancel()
            task2.cancel()

    async def test_controller_command_get_set_callback(self) -> None:
        """Test getting and setting a callback for a ControllerCommand."""
        async with self.make_csc(initial_state=salobj.State.ENABLED):
            self.assertTrue(self.csc.cmd_wait.has_callback)
            self.assertEqual(self.csc.cmd_wait.callback, self.csc.do_wait)

            # Set callback to non-callable should fail,
            # leaving the original callback.
            with self.assertRaises(TypeError):
                self.csc.cmd_wait.callback = "not callable"
            self.assertEqual(self.csc.cmd_wait.callback, self.csc.do_wait)

            # Set callback to a callable should succeed
            # (even if it has the wrong number of arguments).

            def foo() -> None:
                """A simple callable."""
                pass

            self.csc.cmd_wait.callback = foo
            self.assertEqual(self.csc.cmd_wait.callback, foo)

            # Set callback to None should clear it.
            self.csc.cmd_wait.callback = None
            self.assertFalse(self.csc.cmd_wait.has_callback)

    async def test_controller_command_success(self) -> None:
        """Test ack when a controller command succeeds."""
        async with self.make_csc(initial_state=salobj.State.ENABLED):
            ackcmd = await self.remote.cmd_wait.set_start(
                duration=0, timeout=STD_TIMEOUT
            )
            self.assertEqual(ackcmd.ack, salobj.SalRetCode.CMD_COMPLETE)

    async def test_controller_command_callback_return_failed_ackcmd(self) -> None:
        """Test exception raised by remote command when controller command
        callback returns an explicit failed ackcmd.
        """
        async with self.make_csc(initial_state=salobj.State.ENABLED):
            failed_ack = salobj.SalRetCode.CMD_NOPERM
            result = "return failed ackcmd"

            def return_ack(data: salobj.BaseDdsDataType) -> salobj.AckCmdDataType:
                return self.csc.salinfo.make_ackcmd(
                    private_seqNum=data.private_seqNum, ack=failed_ack, result=result
                )

            await self.check_controller_command_callback_failure(
                callback=return_ack,
                ack=failed_ack,
                result_contains=result,
            )

    async def test_controller_command_callback_raises_expected_error(self) -> None:
        """Test exception raised by remote command when controller command
        callback raises ExpectedError.
        """
        async with self.make_csc(initial_state=salobj.State.ENABLED):
            msg = "intentional failure"

            def fail_expected_exception(data: salobj.BaseDdsDataType) -> None:
                raise salobj.ExpectedError(msg)

            await self.check_controller_command_callback_failure(
                callback=fail_expected_exception,
                ack=salobj.SalRetCode.CMD_FAILED,
                result_contains=msg,
            )

    async def test_controller_command_callback_raises_exception(self) -> None:
        """Test exception raised by remote command when controller command
        callback raises an Exception.
        """
        async with self.make_csc(initial_state=salobj.State.ENABLED):
            msg = "intentional failure"

            def fail_exception(data: salobj.BaseDdsDataType) -> None:
                raise Exception(msg)

            await self.check_controller_command_callback_failure(
                callback=fail_exception,
                ack=salobj.SalRetCode.CMD_FAILED,
                result_contains=msg,
            )

    async def test_controller_command_callback_times_out(self) -> None:
        """Test exception raised by remote command when controller command
        callback times out (raises asyncio.TimeoutError).
        """
        async with self.make_csc(initial_state=salobj.State.ENABLED):

            def fail_timeout(data: salobj.BaseDdsDataType) -> None:
                raise asyncio.TimeoutError()

            await self.check_controller_command_callback_failure(
                callback=fail_timeout, ack=salobj.SalRetCode.CMD_TIMEOUT
            )

    async def test_controller_command_callback_canceled(self) -> None:
        """Test exception raised by remote command when controller command
        callback is cancelled (raises asyncio.CancelledError).
        """
        async with self.make_csc(initial_state=salobj.State.ENABLED):

            def fail_cancel(data: salobj.BaseDdsDataType) -> None:
                raise asyncio.CancelledError()

            await self.check_controller_command_callback_failure(
                callback=fail_cancel, ack=salobj.SalRetCode.CMD_ABORTED
            )

    async def check_controller_command_callback_failure(
        self,
        callback: typing.Callable,
        ack: salobj.SalRetCode,
        result_contains: typing.Optional[str] = None,
    ) -> None:
        """Check the exception raised by a remote command when the controller
        controller command raises an exception or returns a failed ackcmd.

        Parameters
        ----------
        callback : `callable`
            Callback function for controller command.
        ack : `SalRetCode`
            Expected ack value for the `AckError`
        result_contains : `str`, optional
            Expected substring of the result value of the `AckError`
        """
        self.csc.cmd_wait.callback = callback
        with salobj.assertRaisesAckError(ack=ack, result_contains=result_contains):
            await self.remote.cmd_wait.start(timeout=STD_TIMEOUT)

    async def check_controller_set_and_set_put(
        self, do_telemetry: bool = False, do_arrays: bool = False
    ) -> None:
        """Check set and set_put methods for `ControllerTelemetry`
        or `ControllerEvent`.
        """
        do_event = not do_telemetry
        if do_arrays:
            assert_data_equal = self.csc.assert_arrays_equal
            field_names = self.csc.arrays_fields
            if do_telemetry:
                make_random_data = self.csc.make_random_tel_arrays
                read_topic = self.remote.tel_arrays
                write_topic = self.csc.tel_arrays
            else:
                make_random_data = self.csc.make_random_evt_arrays
                read_topic = self.remote.evt_arrays
                write_topic = self.csc.evt_arrays
        else:
            assert_data_equal = self.csc.assert_scalars_equal
            field_names = self.csc.scalars_fields
            if do_telemetry:
                make_random_data = self.csc.make_random_tel_scalars
                read_topic = self.remote.tel_scalars
                write_topic = self.csc.tel_scalars
            else:
                make_random_data = self.csc.make_random_evt_scalars
                read_topic = self.remote.evt_scalars
                write_topic = self.csc.evt_scalars

        self.assertFalse(write_topic.has_data)
        self.assertFalse(read_topic.has_data)
        self.assertIsNone(read_topic.get())

        # put random telemetry data using set and set_put
        input_data = make_random_data()
        input_dict = self.csc.as_dict(input_data, field_names)
        write_topic.set(**input_dict)
        write_topic.put()
        self.assertTrue(write_topic.has_data)
        assert_data_equal(input_data, write_topic.data)
        data = await read_topic.next(flush=False, timeout=STD_TIMEOUT)
        assert_data_equal(data, input_data)
        with self.assertRaises(asyncio.TimeoutError):
            await read_topic.next(flush=False, timeout=NODATA_TIMEOUT)

        # set_put the same data again
        did_change = write_topic.set_put(**input_dict)
        self.assertFalse(did_change)
        self.assertTrue(write_topic.has_data)
        assert_data_equal(input_data, write_topic.data)
        if do_telemetry:
            # If telemetry, the data is sent
            data = await read_topic.next(flush=False, timeout=STD_TIMEOUT)
            assert_data_equal(data, input_data)

        # Use None for values to set_put; this just checks
        # that the fields exist without changing them
        none_dict = dict((key, None) for key in input_dict)
        did_change = write_topic.set_put(**none_dict)
        self.assertFalse(did_change)
        self.assertTrue(write_topic.has_data)
        assert_data_equal(input_data, write_topic.data)
        if do_telemetry:
            data = await read_topic.next(flush=False, timeout=STD_TIMEOUT)
            assert_data_equal(data, input_data)

        # Check that setting a NaN field to NaN again is not a change
        for field_name in ("float0", "double0"):
            original_value = copy.copy(getattr(input_data, field_name))
            if do_arrays:
                nan_value = copy.copy(original_value)
                self.assertGreaterEqual(len(nan_value), 4)
                nan_value[1] = math.nan
                nan_value[3] = math.nan
            else:
                nan_value = math.nan
            nan_kwarg = {field_name: nan_value}
            original_kwarg = {field_name: original_value}
            try:
                for i in range(2):
                    setattr(input_data, field_name, nan_value)
                    did_change = write_topic.set_put(**nan_kwarg)
                    if i == 0:
                        self.assertTrue(did_change)
                    else:
                        self.assertFalse(did_change)
                    self.assertTrue(write_topic.has_data)
                    assert_data_equal(input_data, write_topic.data)
                    if do_telemetry or did_change:
                        data = await read_topic.next(flush=False, timeout=STD_TIMEOUT)
                        assert_data_equal(data, input_data)
            finally:
                setattr(input_data, field_name, original_value)
                did_change = write_topic.set(**original_kwarg)
                self.assertTrue(did_change)

        # try an invalid key
        with self.assertRaises(AttributeError):
            write_topic.set_put(no_such_attribute=None)

        # try an invalid value
        if do_arrays:
            bad_int0_value = ["not an int"] * len(input_data.int0)  # type: ignore
        else:
            bad_int0_value = "not an int"  # type: ignore
        with self.assertRaises(ValueError):
            write_topic.set_put(int0=bad_int0_value)
        if do_event:
            # force_output is only available for events
            with self.assertRaises(ValueError):
                write_topic.set_put(int0=bad_int0_value, force_output=True)

        if do_arrays:
            # Try an array that is too short
            # (note: arrays that are too long are silently truncated)
            short_int0_value = np.arange(len(input_data.int0) - 1, dtype=int)
            with self.assertRaises(ValueError):
                write_topic.set_put(int0=short_int0_value)

        # Make sure no additional samples were written
        with self.assertRaises(asyncio.TimeoutError):
            await read_topic.next(flush=False, timeout=NODATA_TIMEOUT)

    async def test_multiple_commands(self) -> None:
        """Test that we can have multiple instances of the same command
        running at the same time.
        """
        async with self.make_csc(initial_state=salobj.State.ENABLED):
            self.assertTrue(self.csc.cmd_wait.has_callback)
            self.assertTrue(self.csc.cmd_wait.allow_multiple_callbacks)

            durations = (0.4, 0.2)  # seconds
            t0 = time.monotonic()
            tasks = []
            for duration in durations:
                task = asyncio.create_task(
                    self.remote.cmd_wait.set_start(
                        duration=duration,
                        timeout=STD_TIMEOUT + duration,
                    )
                )
                # make sure the command is sent before the command data
                # is modified by the next loop iteration
                await asyncio.sleep(0)
                tasks.append(task)
            ackcmds = await asyncio.gather(*tasks)
            measured_duration = time.monotonic() - t0
            for ackcmd in ackcmds:
                self.assertEqual(ackcmd.ack, salobj.SalRetCode.CMD_COMPLETE)

            expected_duration = max(*durations)
            self.assertLess(abs(measured_duration - expected_duration), 0.1)

    async def test_multiple_sequential_commands(self) -> None:
        """Test that commands prohibiting multiple callbacks are executed
        one after the other.
        """
        async with self.make_csc(initial_state=salobj.State.ENABLED):
            self.assertTrue(self.csc.cmd_wait.has_callback)
            self.csc.cmd_wait.allow_multiple_callbacks = False
            self.assertFalse(self.csc.cmd_wait.allow_multiple_callbacks)

            durations = (0.4, 0.2)  # seconds
            t0 = time.monotonic()

            tasks = []
            for duration in durations:
                task = asyncio.create_task(
                    self.remote.cmd_wait.set_start(
                        duration=duration,
                        timeout=STD_TIMEOUT + duration,
                    )
                )
                tasks.append(task)
                # make sure the command is sent before the command data
                # is modified by the next loop iteration
                await asyncio.sleep(0)
            ackcmds = await asyncio.gather(*tasks)
            measured_duration = time.monotonic() - t0
            for ackcmd in ackcmds:
                self.assertEqual(ackcmd.ack, salobj.SalRetCode.CMD_COMPLETE)

            expected_duration = np.sum(durations)
            self.assertLess(abs(measured_duration - expected_duration), 0.1)

    async def test_remote_command_not_ready(self) -> None:
        """Test RemoteCommand methods that should raise an exception when the
        read loop isn't running."""
        async with salobj.Domain() as domain:
            # Use a remote because commands are volatile and we want
            # at least one non-volatile topic
            # in order to slow down starting the event loop.
            remote = salobj.Remote(domain=domain, name="Test", index=self.next_index())
            topic = remote.cmd_fault
            with self.assertRaises(RuntimeError):
                # Use a timeout of 0 because the exception should occur
                # before the timeout is used, and we cannot afford to wait --
                # the read loop might start.
                await topic.start(timeout=0)
            with self.assertRaises(RuntimeError):
                await topic.set_start(timeout=0)
            await remote.close()

    async def test_remote_command_set(self) -> None:
        """Test that RemoteCommand.set and set_start use new data.

        Test that RemoteCommand.set and set_start both begin with a new sample
        for each call, rather than remembering anything from the previous
        command. This is different than WriteTopic.
        """
        async with salobj.Domain() as domain:
            salinfo = salobj.SalInfo(domain=domain, name="Test", index=1)
            cmdreader = salobj.topics.ControllerCommand(
                salinfo=salinfo, name="setScalars"
            )
            # set the random seed before each call so both writers
            # use the same initial seqNum
            random.seed(52)
            cmdwriter = salobj.topics.RemoteCommand(salinfo=salinfo, name="setScalars")
            await salinfo.start()
            read_data_list = []

            def reader_callback(data: salobj.BaseDdsDataType) -> None:
                read_data_list.append(data)
                ackcmd = cmdreader.salinfo.AckCmdType(
                    private_seqNum=data.private_seqNum,
                    ack=salobj.SalRetCode.CMD_COMPLETE,
                )
                cmdreader.ack(data=data, ackcmd=ackcmd)

            cmdreader.callback = reader_callback
            kwargs_list: typing.Iterable[typing.Dict[str, typing.Any]] = (
                dict(int0=1),
                dict(float0=1.3),
                dict(short0=-3, long0=47),
            )
            fields: typing.Set[str] = set()
            for kwargs in kwargs_list:
                fields.update(kwargs.keys())

            for kwargs in kwargs_list:
                cmdwriter.set(**kwargs)
                for field in fields:
                    self.assertAlmostEqual(
                        getattr(cmdwriter.data, field), kwargs.get(field, 0)
                    )

            for i, kwargs in enumerate(kwargs_list):
                await cmdwriter.set_start(**kwargs, timeout=STD_TIMEOUT)
                self.assertEqual(len(read_data_list), i + 1)
                read_data = read_data_list[-1]
                for field in fields:
                    self.assertAlmostEqual(
                        getattr(read_data, field), kwargs.get(field, 0)
                    )

    async def test_read_topic_not_ready(self) -> None:
        """Test ReadTopic for exceptions when the read loop isn't running."""
        async with salobj.Domain() as domain:
            salinfo = salobj.SalInfo(
                domain=domain, name="Test", index=self.next_index()
            )
            # Use a logevent topic because it is not volatile
            # (which might cause the read loop to start too quickly).
            topic = salobj.topics.ReadTopic(
                salinfo=salinfo, name="scalars", sal_prefix="logevent_", max_history=100
            )
            with self.assertRaises(RuntimeError):
                topic.has_data
            with self.assertRaises(RuntimeError):
                topic.get()
            with self.assertRaises(RuntimeError):
                topic.get_oldest()
            with self.assertRaises(RuntimeError):
                # Use a timeout of 0 because the exception
                # should occur before the timeout is used
                # and we cannot afford to wait -- the read loop might start.
                await topic.aget(timeout=0)
            with self.assertRaises(RuntimeError):
                await topic.next(flush=False, timeout=0)

    async def test_read_topic_constructor_errors_and_warnings(self) -> None:
        MIN_QUEUE_LEN = salobj.topics.MIN_QUEUE_LEN
        async with salobj.Domain() as domain:
            salinfo = salobj.SalInfo(
                domain=domain, name="Test", index=self.next_index()
            )
            # max_history must not be negative
            for bad_max_history in (-1, -10):
                for name, sal_prefix in (
                    ("ackcmd", ""),
                    ("setScalars", "command_"),
                    ("scalars", "logevent_"),
                    ("scalars", ""),
                ):
                    with self.assertRaises(ValueError):
                        salobj.topics.ReadTopic(
                            salinfo=salinfo,
                            name=name,
                            sal_prefix=sal_prefix,
                            max_history=bad_max_history,
                        )
            # queue_len must be be >= MIN_QUEUE_LEN
            for bad_queue_len in (-1, 0, MIN_QUEUE_LEN - 1):
                for name, sal_prefix in (
                    ("ackcmd", ""),
                    ("setScalars", "command_"),
                    ("scalars", "logevent_"),
                    ("scalars", ""),
                ):
                    with self.assertRaises(ValueError):
                        salobj.topics.ReadTopic(
                            salinfo=salinfo,
                            name=name,
                            sal_prefix=sal_prefix,
                            max_history=0,
                            queue_len=bad_queue_len,
                        )

            # Only events can have non-zero max_history
            for bad_max_history in (1, 10):
                for name, sal_prefix in (
                    ("ackcmd", ""),
                    ("setScalars", "command_"),
                    ("scalars", ""),
                ):
                    with self.assertRaises(ValueError):
                        salobj.topics.ReadTopic(
                            salinfo=salinfo,
                            name=name,
                            sal_prefix=sal_prefix,
                            max_history=bad_max_history,
                        )

            # An event can have non-zero max_history, but...
            # max_history must be <= queue_len
            for queue_len in (1, 10):
                for delta in (1, 5):
                    bad_max_history = queue_len + delta
            with self.assertRaises(ValueError):
                salobj.topics.ReadTopic(
                    salinfo=salinfo,
                    name="scalars",
                    sal_prefix="logevent_",
                    max_history=bad_max_history,
                    queue_len=queue_len,
                )

            # max_history > DDS queue length or
            # durability_service history_depth will warn.
            dds_history_depth = domain.event_qos_set.reader_qos.history.depth
            dds_durability_history_depth = (
                domain.event_qos_set.topic_qos.durability_service.history_depth
            )
            for warn_max_history in (
                dds_history_depth + 1,
                dds_durability_history_depth + 1,
            ):
                with self.assertWarnsRegex(
                    UserWarning, "max_history=.* > history depth"
                ):
                    salobj.topics.ReadTopic(
                        salinfo=salinfo,
                        name="scalars",
                        sal_prefix="logevent_",
                        max_history=warn_max_history,
                        queue_len=warn_max_history + MIN_QUEUE_LEN,
                    )

    async def test_asynchronous_event_callback(self) -> None:
        async with self.make_csc(initial_state=salobj.State.ENABLED):
            cmd_scalars_data = self.csc.make_random_cmd_scalars()
            callback_data = None

            async def scalars_callback(scalars: salobj.BaseDdsDataType) -> None:
                nonlocal callback_data
                callback_data = scalars

            # send the setScalars command with random data
            # but first set a callback for event that should be triggered
            self.remote.evt_scalars.callback = scalars_callback
            await self.remote.cmd_setScalars.start(
                cmd_scalars_data, timeout=STD_TIMEOUT
            )
            # give the callback time to be called
            await asyncio.sleep(EVENT_DELAY)
            self.csc.assert_scalars_equal(callback_data, cmd_scalars_data)

    async def test_synchronous_event_callback(self) -> None:
        """Like test_asynchronous_event_callback but the callback function
        is synchronous.
        """
        async with self.make_csc(initial_state=salobj.State.ENABLED):
            cmd_scalars_data = self.csc.make_random_cmd_scalars()
            callback_data = None

            def scalars_callback(scalars: salobj.BaseDdsDataType) -> None:
                nonlocal callback_data
                callback_data = scalars

            # send the setScalars command with random data
            # but first set a callback for event that should be triggered
            self.remote.evt_scalars.callback = scalars_callback
            await self.remote.cmd_setScalars.start(
                cmd_scalars_data, timeout=STD_TIMEOUT
            )
            # give the callback time to be called
            await asyncio.sleep(EVENT_DELAY)
            self.csc.assert_scalars_equal(callback_data, cmd_scalars_data)

    async def test_command_next_ack(self) -> None:
        async with self.make_csc(initial_state=salobj.State.ENABLED):
            duration = 0.1  # Arbitrary short value so the test runs quickly
            ackcmd1 = await self.remote.cmd_wait.set_start(
                duration=duration, wait_done=False, timeout=STD_TIMEOUT
            )
            self.assertEqual(ackcmd1.ack, salobj.SalRetCode.CMD_ACK)
            ackcmd2 = await self.remote.cmd_wait.next_ackcmd(
                ackcmd1, wait_done=False, timeout=STD_TIMEOUT
            )
            self.assertEqual(ackcmd2.ack, salobj.SalRetCode.CMD_INPROGRESS)
            self.assertAlmostEqual(ackcmd2.timeout, duration)
            ackcmd3 = await self.remote.cmd_wait.next_ackcmd(
                ackcmd2, wait_done=True, timeout=STD_TIMEOUT
            )
            self.assertEqual(ackcmd3.ack, salobj.SalRetCode.CMD_COMPLETE)

            # Now try a timeout. Specify a negative duration to avoid the
            # CMD_INPROGRESS command ack that extends the timeout.
            ackcmd1 = await self.remote.cmd_wait.set_start(
                duration=-5, wait_done=False, timeout=STD_TIMEOUT
            )
            self.assertEqual(ackcmd1.ack, salobj.SalRetCode.CMD_ACK)
            with salobj.assertRaisesAckTimeoutError(ack=salobj.SalRetCode.CMD_ACK):
                await self.remote.cmd_wait.next_ackcmd(
                    ackcmd1, wait_done=True, timeout=NODATA_TIMEOUT
                )

    async def test_command_seq_num(self) -> None:
        async with self.make_csc(initial_state=salobj.State.ENABLED):
            prev_max_seq_num = None
            for cmd_name in self.remote.salinfo.command_names:
                cmd = getattr(self.remote, f"cmd_{cmd_name}")
                cmd.put()
                seq_num = cmd.data.private_seqNum
                cmd.put()
                seq_num2 = cmd.data.private_seqNum
                if seq_num < cmd.max_seq_num:
                    self.assertEqual(seq_num2, seq_num + 1)
                if prev_max_seq_num is None:
                    self.assertEqual(cmd.min_seq_num, 1)
                else:
                    self.assertEqual(cmd.min_seq_num, prev_max_seq_num + 1)
                prev_max_seq_num = cmd.max_seq_num

    async def test_partitions(self) -> None:
        """Test specifying a DDS partition with $LSST_DDS_PARTITION_PREFIX."""
        async with salobj.Domain() as domain:
            salinfo1 = salobj.SalInfo(domain=domain, name="Test", index=0)
            salobj.set_random_lsst_dds_partition_prefix()
            salinfo2 = salobj.SalInfo(domain=domain, name="Test", index=0)
            writer1 = salobj.topics.ControllerEvent(salinfo=salinfo1, name="errorCode")
            writer2 = salobj.topics.ControllerEvent(salinfo=salinfo2, name="errorCode")

            # write late joiner data (before we have readers);
            # only the last value should be seen
            for i in (3, 4, 5):
                writer1.set_put(errorCode=10 + i)
                writer2.set_put(errorCode=20 + i)

            # create readers and set callbacks for them
            reader1 = salobj.topics.RemoteEvent(salinfo=salinfo1, name="errorCode")
            reader2 = salobj.topics.RemoteEvent(salinfo=salinfo2, name="errorCode")
            await salinfo1.start()
            await salinfo2.start()

            # write more data now that we have readers;
            # they should see all of it
            for i in (6, 7, 8):
                writer1.set_put(errorCode=10 + i)
                writer2.set_put(errorCode=20 + i)

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

    async def test_sal_index(self) -> None:
        """Test separation of data using SAL index.

        Readers with index=0 should see data from all writers of that topic,
        regardless of index.
        Readers with a non-zero SAL index should only see data
        from a writer with the same index.
        """
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
                await asyncio.sleep(0.01)
                writer1.set_put(errorCode=10 + i)
                await asyncio.sleep(0.01)
                writer2.set_put(errorCode=20 + i)
                await asyncio.sleep(0.01)

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
                await asyncio.sleep(0.01)
                writer1.set_put(errorCode=10 + i)
                await asyncio.sleep(0.01)
                writer2.set_put(errorCode=20 + i)
                await asyncio.sleep(0.01)

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

    async def test_topic_repr(self) -> None:
        async with self.make_csc(initial_state=salobj.State.ENABLED):
            salinfo = self.remote.salinfo

            for obj, classSuffix in ((self.csc, "Controller"), (self.remote, "Remote")):
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

    async def test_write_topic_set(self) -> None:
        """Test that WriteTopic.set uses existing data for defaults."""
        async with salobj.Domain() as domain:
            salinfo = salobj.SalInfo(domain=domain, name="Test", index=1)
            write_topic = salobj.topics.WriteTopic(
                salinfo=salinfo, name="scalars", sal_prefix="logevent_"
            )
            await salinfo.start()

            predicted_data_dict = write_topic.DataType().get_vars()
            kwargs_list: typing.Iterable[typing.Dict[str, typing.Any]] = (
                dict(int0=1),
                dict(float0=1.3),
                dict(int0=-3, long0=47),
            )
            fields: typing.Set[str] = set()
            for kwargs in kwargs_list:
                fields.update(kwargs.keys())

            for kwargs in kwargs_list:
                write_topic.set(**kwargs)
                predicted_data_dict.update(kwargs)
                for field in fields:
                    self.assertAlmostEqual(
                        getattr(write_topic.data, field), predicted_data_dict[field]
                    )


if __name__ == "__main__":
    unittest.main()
