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
import collections
import copy
import itertools
import math
import pathlib
import time
import typing
import unittest
from collections.abc import Iterable, Sequence

import numpy as np
import pytest
from lsst.ts import salobj, utils

# Long enough to perform any reasonable operation
# including starting a CSC or loading a script (seconds)
STD_TIMEOUT = 10
# Time for events to be output as a result of a command (seconds).
EVENT_DELAY = 0.1
# Timeout for when we expect no new data (seconds)
NO_DATA_TIMEOUT = 1

np.random.seed(47)


class TopicsTestCase(salobj.BaseCscTestCase, unittest.IsolatedAsyncioTestCase):
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

    def check_topic_info(self, topic: salobj.topics.BaseTopic) -> None:
        assert topic.topic_info.sal_name == topic.sal_name
        assert topic.topic_info.attr_name == topic.attr_name
        assert topic.topic_info is topic.salinfo.component_info.topics[topic.attr_name]

    async def test_attributes(self) -> None:
        async with self.make_csc(initial_state=salobj.State.ENABLED):
            for obj in (self.remote, self.csc):
                is_remote = isinstance(obj, salobj.Remote)
                for cmd_name in obj.salinfo.command_names:
                    cmd = getattr(obj, f"cmd_{cmd_name}")
                    assert cmd.attr_name == "cmd_" + cmd_name
                    assert cmd.sal_name == "command_" + cmd_name
                    self.check_topic_info(cmd)

                for evt_name in obj.salinfo.event_names:
                    evt = getattr(obj, f"evt_{evt_name}")
                    assert evt.attr_name == "evt_" + evt_name
                    assert evt.sal_name == "logevent_" + evt_name
                    self.check_topic_info(evt)
                    if is_remote:
                        assert isinstance(evt, salobj.topics.RemoteEvent)
                    else:
                        assert isinstance(evt, salobj.topics.ControllerEvent)

                for tel_name in obj.salinfo.telemetry_names:
                    tel = getattr(obj, f"tel_{tel_name}")
                    assert tel.attr_name == "tel_" + tel_name
                    assert tel.sal_name == tel_name
                    self.check_topic_info(tel)
                    if is_remote:
                        assert isinstance(tel, salobj.topics.RemoteTelemetry)
                    else:
                        assert isinstance(tel, salobj.topics.ControllerTelemetry)

            # Create a new SalInfo, because we cannot add new topics
            # to an existing SalInfo once its read loop has started.
            async with salobj.SalInfo(
                domain=self.csc.salinfo.domain,
                name=self.csc.salinfo.name,
                index=self.csc.salinfo.index,
            ) as salinfo:
                for ackcmd in (
                    salobj.topics.AckCmdReader(salinfo=salinfo),
                    salobj.topics.AckCmdWriter(salinfo=salinfo),
                ):
                    assert ackcmd.attr_name == "ack_ackcmd"
                    assert ackcmd.sal_name == "ackcmd"

    async def test_base_topic_constructor_good(self) -> None:
        async with salobj.Domain() as domain:
            salinfo = salobj.SalInfo(domain=domain, name="Test", index=1)

            for cmd_name in salinfo.command_names:
                cmd = salobj.topics.BaseTopic(
                    salinfo=salinfo, attr_name="cmd_" + cmd_name
                )
                assert cmd.attr_name == f"cmd_{cmd_name}"

            for evt_name in salinfo.event_names:
                evt = salobj.topics.BaseTopic(
                    salinfo=salinfo, attr_name="evt_" + evt_name
                )
                assert evt.attr_name == f"evt_{evt_name}"

            for tel_name in salinfo.telemetry_names:
                tel = salobj.topics.BaseTopic(
                    salinfo=salinfo, attr_name="tel_" + tel_name
                )
                assert tel.attr_name == f"tel_{tel_name}"

    async def test_base_topic_constructor_errors(self) -> None:
        async with salobj.Domain() as domain:
            salinfo = salobj.SalInfo(domain=domain, name="Test", index=1)

            for good_name in ("setScalars", "scalars"):
                for bad_prefix in (
                    "_",
                    "invalid_",
                    "ack",  # no trailing underscore
                    "cmd",  # no trailing underscore
                    "evt",  # no trailing underscore
                    "tel",  # no trailing underscore
                ):
                    with pytest.raises(RuntimeError):
                        salobj.topics.BaseTopic(
                            salinfo=salinfo, attr_name=bad_prefix + good_name
                        )

            for good_prefix in ("ack_", "cmd_", "evt_", "tel_"):
                for bad_name in ("", "no_such_topic"):
                    with pytest.raises(RuntimeError):
                        salobj.topics.BaseTopic(
                            salinfo=salinfo, attr_name=good_prefix + bad_name
                        )

            for cmd_name in salinfo.command_names:
                for non_cmd_prefix in ("ack_", "evt_", "tel_"):
                    with pytest.raises(RuntimeError):
                        salobj.topics.BaseTopic(
                            salinfo=salinfo, attr_name=non_cmd_prefix + cmd_name
                        )

            # there is overlap between event and telemetry names
            # so just use the command_ prefix as the invalid prefix
            non_evt_prefix = "cmd_"
            for evt_name in salinfo.event_names:
                with pytest.raises(RuntimeError):
                    salobj.topics.BaseTopic(
                        salinfo=salinfo, attr_name=non_evt_prefix + evt_name
                    )

            # there is overlap between event and telemetry names
            # so just use the command_ prefix as the invalid prefix
            non_tel_prefix = "cmd__"
            for tel_name in salinfo.telemetry_names:
                with pytest.raises(RuntimeError):
                    salobj.topics.BaseTopic(
                        salinfo=salinfo, attr_name=non_tel_prefix + tel_name
                    )

    async def test_command_isolation(self) -> None:
        """Test that multiple RemoteCommands for one command only see
        ackcmd replies to their own samples.
        """
        async with salobj.Domain() as domain, salobj.SalInfo(
            domain=domain, name="Test", index=1
        ) as salinfo, salobj.SalInfo(domain=domain, name="Test", index=0) as salinfo0:
            cmdreader = salobj.topics.ReadTopic(
                salinfo=salinfo, attr_name="cmd_wait", max_history=0
            )
            cmdwriter = salobj.topics.RemoteCommand(salinfo=salinfo, name="wait")
            cmdtype = salinfo.sal_topic_names.index(cmdwriter.sal_name)
            ackcmdwriter = salobj.topics.AckCmdWriter(salinfo=salinfo)

            # Also make an ackcmd reader that sees all ackcmd messages
            # (including those triggered by other users).
            unfiltered_ackcmd_reader = salobj.topics.ReadTopic(
                salinfo=salinfo0, attr_name="ack_ackcmd", max_history=0
            )
            await asyncio.wait_for(
                asyncio.gather(salinfo.start(), salinfo0.start()), timeout=STD_TIMEOUT
            )

            # Send and acknowledge 4 commands:
            # * The first is acknowledged with a different origin.
            # * The second is acknowledged with a different identity.
            # * The third is acknowledged with identity=""
            # * The last is acknowledged normally
            # The first three will not complete, the last will.
            nread = 0
            cmd_callback_event = asyncio.Event()

            async def cmd_reader_callback(data: salobj.BaseMsgType) -> None:
                nonlocal nread, cmd_callback_event
                # Write final ackcmd, after tweaking data if appropriate.
                ackcmdwriter.set(
                    private_seqNum=data.private_seqNum,
                    origin=data.private_origin,
                    identity=data.private_identity,
                    cmdtype=cmdtype,
                    ack=salobj.SalRetCode.CMD_COMPLETE,
                )
                if nread == 0:
                    # Mismatched origin.
                    ackcmdwriter.set(origin=data.private_origin + 1)
                elif nread == 1:
                    # Mismatched identity.
                    ackcmdwriter.set(identity=data.private_identity + "extra")
                elif nread == 2:
                    # No identity.
                    ackcmdwriter.set(identity="")
                await ackcmdwriter.write()
                nread += 1
                cmd_callback_event.set()

            unfiltered_nread = 0
            unfiltered_future: asyncio.Future = asyncio.Future()

            async def unfiltered_ackcmd_reader_callback(
                data: salobj.BaseMsgType,
            ) -> None:
                nonlocal unfiltered_nread
                unfiltered_nread += 1
                if unfiltered_nread == 4:
                    unfiltered_future.set_result(None)

            cmdreader.callback = cmd_reader_callback
            unfiltered_ackcmd_reader.callback = unfiltered_ackcmd_reader_callback

            tasks = []
            try:
                for i in range(4):
                    cmd_callback_event.clear()
                    tasks.append(asyncio.create_task(cmdwriter.start(timeout=2)))
                    await asyncio.wait_for(
                        cmd_callback_event.wait(), timeout=STD_TIMEOUT
                    )
                    assert nread == i + 1
                await tasks[3]
                assert not tasks[0].done()  # Origin did not match.
                assert not tasks[1].done()  # Identity did not match.
                assert not tasks[2].done()  # No identity.
            finally:
                for task in tasks:
                    task.cancel()
            await asyncio.wait_for(unfiltered_future, timeout=STD_TIMEOUT)
            assert nread == 4
            assert unfiltered_nread == 4

    async def test_controller_telemetry_write(self) -> None:
        """Test ControllerTelemetry.set, write, and set_write."""
        async with self.make_csc(initial_state=salobj.State.ENABLED):
            # until put is called nothing has been sent
            assert not self.csc.tel_scalars.has_data
            assert not self.remote.tel_scalars.has_data
            assert self.remote.tel_scalars.get() is None

            # put random telemetry data using write
            scalars_dict1 = self.csc.make_random_scalars_dict()
            self.csc.tel_scalars.set(**scalars_dict1)
            assert self.csc.tel_scalars.has_data
            self.csc.assert_scalars_equal(scalars_dict1, self.csc.tel_scalars.data)
            await self.csc.tel_scalars.write()
            data = await self.remote.tel_scalars.next(flush=False, timeout=STD_TIMEOUT)
            with pytest.raises(asyncio.TimeoutError):
                await self.remote.tel_scalars.next(flush=False, timeout=NO_DATA_TIMEOUT)
            self.csc.assert_scalars_equal(data, self.csc.tel_scalars.data)

            # put random telemetry data using set_write
            scalars_dict2 = self.csc.make_random_scalars_dict()
            await self.csc.tel_scalars.set_write(**scalars_dict2)
            self.csc.assert_scalars_equal(scalars_dict2, self.csc.tel_scalars.data)
            data = await self.remote.tel_scalars.next(flush=False, timeout=STD_TIMEOUT)
            self.csc.assert_scalars_equal(data, self.csc.tel_scalars.data)
            with pytest.raises(asyncio.TimeoutError):
                await self.remote.tel_scalars.next(flush=False, timeout=NO_DATA_TIMEOUT)

    async def test_controller_event_write(self) -> None:
        """Test ControllerEvent.set, write, and set_write.

        Also test setting fields private_origin,
        private_sndStamp and private_rcvStamp
        """
        async with self.make_csc(initial_state=salobj.State.ENABLED):
            # until put is called nothing has been sent
            assert not self.csc.evt_scalars.has_data
            assert not self.remote.evt_scalars.has_data
            assert self.remote.evt_scalars.get() is None

            # Write random event data using set and write
            scalars_dict1 = self.csc.make_random_scalars_dict()
            self.csc.evt_scalars.set(**scalars_dict1)
            assert self.csc.evt_scalars.has_data
            self.csc.assert_scalars_equal(self.csc.evt_scalars.data, scalars_dict1)
            send_tai0 = utils.current_tai()
            written_data = await self.csc.evt_scalars.write()
            self.csc.assert_scalars_equal(written_data, scalars_dict1)
            self.csc.assert_scalars_equal(self.csc.evt_scalars.data, scalars_dict1)
            read_data = await self.remote.evt_scalars.next(
                flush=False, timeout=STD_TIMEOUT
            )
            self.csc.assert_scalars_equal(read_data, scalars_dict1)
            rcv_tai0 = utils.current_tai()
            with pytest.raises(asyncio.TimeoutError):
                await self.remote.evt_scalars.next(flush=False, timeout=NO_DATA_TIMEOUT)
            for data in (read_data, self.csc.evt_scalars.data):
                assert data.private_origin == self.csc.domain.origin
                assert data.private_sndStamp == pytest.approx(send_tai0, abs=0.5)
            assert read_data.private_rcvStamp == pytest.approx(rcv_tai0, abs=0.5)

            # Write random event data using set_write
            scalars_dict2 = self.csc.make_random_scalars_dict()
            with pytest.raises(AssertionError):
                self.csc.assert_scalars_equal(scalars_dict1, scalars_dict2)
            write_result = await self.csc.evt_scalars.set_write(**scalars_dict2)
            self.csc.assert_scalars_equal(self.csc.evt_scalars.data, scalars_dict2)
            self.csc.assert_scalars_equal(write_result.data, scalars_dict2)
            read_data = await self.remote.evt_scalars.next(
                flush=False, timeout=STD_TIMEOUT
            )
            self.csc.assert_scalars_equal(read_data, scalars_dict2)
            with pytest.raises(asyncio.TimeoutError):
                await self.remote.evt_scalars.next(flush=False, timeout=NO_DATA_TIMEOUT)

    async def test_controller_set_and_write(self) -> None:
        """Test set and write methods of ControllerTelemetry
        and ControllerEvent.
        """
        async with self.make_csc(initial_state=salobj.State.ENABLED):
            for do_telemetry, do_arrays in itertools.product(
                (False, True), (False, True)
            ):
                with self.subTest(do_telmetry=do_telemetry, do_arrrays=do_arrays):
                    await self.check_controller_set_and_write(
                        do_telemetry=do_telemetry, do_arrays=do_arrays
                    )

    async def set_scalars(
        self, num_commands: int, assert_none: bool = True
    ) -> list[salobj.BaseMsgType]:
        """Send the setScalars command repeatedly and return the data sent.

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
            assert self.remote.evt_scalars.get() is None
            assert self.remote.tel_scalars.get() is None

        # send the setScalars command with random data
        sent_data_list = []
        for _ in range(num_commands):
            scalars_dict = self.csc.make_random_scalars_dict()
            await self.remote.cmd_setScalars.set_start(
                **scalars_dict, timeout=STD_TIMEOUT
            )
            sent_data_list.append(self.remote.cmd_setScalars.data)
        return sent_data_list

    async def test_aget(self) -> None:
        async with self.make_csc(initial_state=salobj.State.ENABLED):
            with pytest.raises(asyncio.TimeoutError):
                await self.remote.evt_scalars.aget(timeout=NO_DATA_TIMEOUT)
            with pytest.raises(asyncio.TimeoutError):
                await self.remote.tel_scalars.aget(timeout=NO_DATA_TIMEOUT)

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

            # the aget should not interfere with next
            for i in range(num_commands):
                print(f"test {i}")
                evt_data = await self.remote.evt_scalars.next(
                    flush=False, timeout=STD_TIMEOUT
                )
                tel_data = await self.remote.tel_scalars.next(
                    flush=False, timeout=STD_TIMEOUT
                )
                self.csc.assert_scalars_equal(cmd_data_list[i], evt_data)
                self.csc.assert_scalars_equal(cmd_data_list[i], tel_data)

            # aget should return the last value seen,
            # no matter now many times it is called
            evt_data_list = [await self.remote.evt_scalars.aget() for _ in range(5)]
            for evt_data in evt_data_list:
                assert evt_data is not None
                self.csc.assert_scalars_equal(cmd_data_list[-1], evt_data)

            # aget should return the last value seen,
            # no matter now many times it is called
            tel_data_list = [await self.remote.tel_scalars.aget() for _ in range(5)]
            for tel_data in tel_data_list:
                assert tel_data is not None
                self.csc.assert_scalars_equal(cmd_data_list[-1], tel_data)

    async def test_plain_get(self) -> None:
        """Test RemoteEvent.get and RemoteTelemetry.get."""
        async with self.make_csc(initial_state=salobj.State.ENABLED):
            for read_topic in (self.remote.evt_scalars, self.remote.tel_scalars):
                # Clear out data from previous iteration, if any
                read_topic.flush()

                num_commands = 3

                for _ in range(num_commands):
                    cmd_data_list = await self.set_scalars(
                        num_commands=1, assert_none=False
                    )

                    next_data = await read_topic.next(flush=False, timeout=STD_TIMEOUT)
                    get_data = read_topic.get()
                    self.csc.assert_scalars_equal(cmd_data_list[0], next_data)
                    self.csc.assert_scalars_equal(cmd_data_list[0], get_data)

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
            assert len(evt_data_list) == num_commands
            for cmd_data, evt_data in zip(cmd_data_list, evt_data_list):
                self.csc.assert_scalars_equal(cmd_data, evt_data)

            tel_data_list = []
            while True:
                data = self.remote.tel_scalars.get_oldest()
                if data is None:
                    break
                tel_data_list.append(data)
            assert len(tel_data_list) == num_commands
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
                        flush=False, timeout=NO_DATA_TIMEOUT
                    )
                    assert evt_data is not None
                    evt_data_list.append(evt_data)
                except asyncio.TimeoutError:
                    break
            assert len(evt_data_list) == num_commands
            for cmd_data, evt_data in zip(cmd_data_list, evt_data_list):
                self.csc.assert_scalars_equal(cmd_data, evt_data)

            tel_data_list = []
            while True:
                try:
                    tel_data = await self.remote.tel_scalars.next(
                        flush=False, timeout=NO_DATA_TIMEOUT
                    )
                    assert tel_data is not None
                    tel_data_list.append(tel_data)
                except asyncio.TimeoutError:
                    break
            assert len(tel_data_list) == num_commands
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
                self.data: list[salobj.BaseMsgType] = []
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
                await self.csc.tel_scalars.set_write(int0=item)
            await asyncio.wait_for(
                asyncio.gather(*[reader.read_loop_task for reader in readers]),
                timeout=STD_TIMEOUT,
            )
            for reader in readers:
                read_data = [item.int0 for item in reader.data]
                assert data == read_data

    async def test_callbacks(self) -> None:
        num_commands = 3

        evt_data_list: list[salobj.BaseMsgType] = []
        evt_future: asyncio.Future = asyncio.Future()

        async def evt_callback(data: salobj.BaseMsgType) -> None:
            evt_data_list.append(data)
            if len(evt_data_list) == num_commands:
                evt_future.set_result(None)

        tel_data_list: list[salobj.BaseMsgType] = []
        tel_future: asyncio.Future = asyncio.Future()

        async def tel_callback(data: salobj.BaseMsgType) -> None:
            tel_data_list.append(data)
            if len(tel_data_list) == num_commands:
                tel_future.set_result(None)

        async with self.make_csc(initial_state=salobj.State.ENABLED):
            self.remote.evt_scalars.callback = evt_callback
            self.remote.tel_scalars.callback = tel_callback

            # Check methods that are not allowed
            # when there is a callback function
            with pytest.raises(RuntimeError):
                self.remote.evt_scalars.get_oldest()
            with pytest.raises(RuntimeError):
                self.remote.tel_scalars.get_oldest()
            with pytest.raises(RuntimeError):
                self.remote.evt_scalars.flush()
            with pytest.raises(RuntimeError):
                self.remote.tel_scalars.flush()
            with pytest.raises(RuntimeError):
                await self.remote.evt_scalars.next(flush=False)
            with pytest.raises(RuntimeError):
                await self.remote.tel_scalars.next(flush=False)

            cmd_data_list = await self.set_scalars(num_commands=num_commands)
            await asyncio.wait_for(
                asyncio.gather(evt_future, tel_future), timeout=STD_TIMEOUT
            )

            assert len(evt_data_list) == num_commands
            for cmd_data, evt_data in zip(cmd_data_list, evt_data_list):
                self.csc.assert_scalars_equal(cmd_data, evt_data)

            assert len(tel_data_list) == num_commands
            for cmd_data, tel_data in zip(cmd_data_list, tel_data_list):
                self.csc.assert_scalars_equal(cmd_data, tel_data)

    # TODO DM-37502: modify this to expect construction to raise,
    # once we drop support for synchronous callback functions.
    # Possibly combine it with test_callbacks?
    async def test_synchronous_callbacks(self) -> None:
        num_commands = 3

        evt_data_list: typing.List[salobj.BaseMsgType] = []
        evt_future: asyncio.Future = asyncio.Future()

        def evt_callback(data: salobj.BaseMsgType) -> None:
            evt_data_list.append(data)
            if len(evt_data_list) == num_commands:
                evt_future.set_result(None)

        tel_data_list: typing.List[salobj.BaseMsgType] = []
        tel_future: asyncio.Future = asyncio.Future()

        def tel_callback(data: salobj.BaseMsgType) -> None:
            tel_data_list.append(data)
            if len(tel_data_list) == num_commands:
                tel_future.set_result(None)

        async with self.make_csc(initial_state=salobj.State.ENABLED):
            with pytest.warns(DeprecationWarning):
                self.remote.evt_scalars.callback = evt_callback
            with pytest.warns(DeprecationWarning):
                self.remote.tel_scalars.callback = tel_callback

            cmd_data_list = await self.set_scalars(num_commands=num_commands)
            await asyncio.wait_for(
                asyncio.gather(evt_future, tel_future), timeout=STD_TIMEOUT
            )

            assert len(evt_data_list) == num_commands
            for cmd_data, evt_data in zip(cmd_data_list, evt_data_list):
                self.csc.assert_scalars_equal(cmd_data, evt_data)

            assert len(tel_data_list) == num_commands
            for cmd_data, tel_data in zip(cmd_data_list, tel_data_list):
                self.csc.assert_scalars_equal(cmd_data, tel_data)

    async def test_bad_put(self) -> None:
        """Try to put invalid data types."""
        async with self.make_csc(initial_state=salobj.State.ENABLED):
            with pytest.raises(TypeError):
                await self.remote.cmd_wait.start(self.csc.cmd_setScalars.DataType())

    async def test_put_id(self) -> None:
        """Test that one can set the salIndex field of a write topic
        if index=0 and not otherwise.
        """
        async with salobj.Controller(name="Test", index=0) as controller0:
            async with salobj.Controller(name="Test", index=1) as controller1:
                for ind in (0, 1, 2, 3):
                    # for a controller with zero index
                    # salIndex will be whatever you set it to
                    await controller0.evt_scalars.set_write(salIndex=ind)
                    assert controller0.evt_scalars.data.salIndex == ind
                    # for a controller with non-zero index
                    # salIndex always matches that index
                    await controller1.evt_scalars.set_write(salIndex=ind)
                    assert controller1.evt_scalars.data.salIndex == 1

    async def test_command_timeout(self) -> None:
        async with self.make_csc(initial_state=salobj.State.ENABLED):
            # Test that a CMD_INPROGRESS command acknowledgement
            # extends the timeout.
            await self.remote.cmd_wait.set_start(duration=2, timeout=0.5)
            # Specify a negative duration in order to avoid the
            # CMD_INPROGRESS command ack that extends the timeout.
            # This should time out.
            with salobj.assertRaisesAckTimeoutError():
                await self.remote.cmd_wait.set_start(duration=-2, timeout=0.5)

    async def test_controller_command_get_next(self) -> None:
        """Test ControllerCommand get and next methods.

        This requires unsetting the callback function for a command
        and thus not awaiting the start command.
        """
        async with self.make_csc(initial_state=salobj.State.ENABLED):
            # next fails if there is a callback
            with pytest.raises(RuntimeError):
                await self.csc.cmd_wait.next()

            self.csc.cmd_wait.callback = None

            duration = 1
            task1 = asyncio.create_task(
                self.remote.cmd_wait.set_start(duration=duration)
            )
            next_data = await self.csc.cmd_wait.next(timeout=STD_TIMEOUT)
            get_data = self.csc.cmd_wait.get()
            assert get_data is not None
            assert get_data.duration == duration
            assert next_data.duration == duration

            # show that get() flushes the queue
            with pytest.raises(asyncio.TimeoutError):
                await self.csc.cmd_wait.next(timeout=NO_DATA_TIMEOUT)

            duration = 2
            task2 = asyncio.create_task(
                self.remote.cmd_wait.set_start(duration=duration)
            )
            await asyncio.sleep(0.5)
            get_data = self.csc.cmd_wait.get()
            next_data = await self.csc.cmd_wait.next(timeout=STD_TIMEOUT)
            assert get_data is not None
            assert get_data.duration == duration
            assert next_data.duration == duration

            task1.cancel()
            task2.cancel()

    async def test_controller_command_get_set_callback(self) -> None:
        """Test getting and setting a callback for a ControllerCommand."""
        async with self.make_csc(initial_state=salobj.State.ENABLED):
            assert self.csc.cmd_wait.has_callback
            assert self.csc.cmd_wait.callback == self.csc.do_wait

            # Set callback to non-callable should fail,
            # leaving the original callback.
            with pytest.raises(TypeError):
                self.csc.cmd_wait.callback = "not callable"
            assert self.csc.cmd_wait.callback == self.csc.do_wait

            # Set callback to a callable should succeed
            # (even if it has the wrong number of arguments).

            async def foo() -> None:
                """A simple callable."""
                pass

            self.csc.cmd_wait.callback = foo
            assert self.csc.cmd_wait.callback == foo

            # Set callback to None should clear it.
            self.csc.cmd_wait.callback = None
            assert not self.csc.cmd_wait.has_callback

    async def test_controller_command_success(self) -> None:
        """Test ack when a controller command succeeds."""
        async with self.make_csc(initial_state=salobj.State.ENABLED):
            ackcmd = await self.remote.cmd_wait.set_start(
                duration=0, timeout=STD_TIMEOUT
            )
            assert ackcmd.ack == salobj.SalRetCode.CMD_COMPLETE

    async def test_controller_command_callback_return_failed_ackcmd(self) -> None:
        """Test exception raised by remote command when controller command
        callback returns an explicit failed ackcmd.
        """
        async with self.make_csc(initial_state=salobj.State.ENABLED):
            failed_ack = salobj.SalRetCode.CMD_NOPERM
            result = "return failed ackcmd"

            async def return_ack(data: salobj.BaseMsgType) -> salobj.AckCmdDataType:
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

            async def fail_expected_exception(data: salobj.BaseMsgType) -> None:
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

            async def fail_exception(data: salobj.BaseMsgType) -> None:
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

            async def fail_timeout(data: salobj.BaseMsgType) -> None:
                raise asyncio.TimeoutError()

            await self.check_controller_command_callback_failure(
                callback=fail_timeout, ack=salobj.SalRetCode.CMD_TIMEOUT
            )

    async def test_controller_command_callback_canceled(self) -> None:
        """Test exception raised by remote command when controller command
        callback is cancelled (raises asyncio.CancelledError).
        """
        async with self.make_csc(initial_state=salobj.State.ENABLED):

            async def fail_cancel(data: salobj.BaseMsgType) -> None:
                raise asyncio.CancelledError()

            await self.check_controller_command_callback_failure(
                callback=fail_cancel, ack=salobj.SalRetCode.CMD_ABORTED
            )

    async def check_controller_command_callback_failure(
        self,
        callback: typing.Callable,
        ack: salobj.SalRetCode,
        result_contains: str | None = None,
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

    async def check_controller_set_and_write(
        self, do_telemetry: bool = False, do_arrays: bool = False
    ) -> None:
        """Check set and write methods for `ControllerTelemetry`
        or `ControllerEvent`.
        """
        if do_arrays:
            assert_data_equal = self.csc.assert_arrays_equal
            make_random_data_dict = self.csc.make_random_arrays_dict
            if do_telemetry:
                read_topic = self.remote.tel_arrays
                write_topic = self.csc.tel_arrays
            else:
                read_topic = self.remote.evt_arrays
                write_topic = self.csc.evt_arrays
        else:
            assert_data_equal = self.csc.assert_scalars_equal
            make_random_data_dict = self.csc.make_random_scalars_dict
            if do_telemetry:
                read_topic = self.remote.tel_scalars
                write_topic = self.csc.tel_scalars
            else:
                read_topic = self.remote.evt_scalars
                write_topic = self.csc.evt_scalars

        assert not write_topic.has_data
        assert not read_topic.has_data
        assert read_topic.get() is None

        input_dict = make_random_data_dict()
        did_change = write_topic.set(**input_dict)
        assert did_change
        assert write_topic.has_data
        data_written = await write_topic.write()
        assert write_topic.has_data
        assert_data_equal(input_dict, write_topic.data)
        assert_data_equal(data_written, write_topic.data)
        data = await read_topic.next(flush=False, timeout=STD_TIMEOUT)
        assert_data_equal(data, input_dict)
        with pytest.raises(asyncio.TimeoutError):
            await read_topic.next(flush=False, timeout=NO_DATA_TIMEOUT)

        # Write the same data using `write` with kwargs
        # (the above already tested write without kwargs)
        # and all values of force_output.
        for force_output in (False, True, None):
            with self.subTest(force_output=force_output):
                write_result = await write_topic.set_write(
                    **input_dict, force_output=force_output
                )
                assert not write_result.did_change
                if force_output is True:
                    assert write_result.was_written
                elif force_output is False:
                    assert not write_result.was_written
                elif do_telemetry:
                    assert write_result.was_written
                else:
                    assert not write_result.was_written
                assert write_topic.has_data
                assert_data_equal(input_dict, write_topic.data)
                assert_data_equal(input_dict, write_result.data)
                if write_result.was_written:
                    data = await read_topic.next(flush=False, timeout=STD_TIMEOUT)
                    assert_data_equal(data, input_dict)

        # Use None for values to write; this just checks
        # that the fields exist without changing them
        none_dict = dict((key, None) for key in input_dict)
        write_result = await write_topic.set_write(**none_dict)
        assert not write_result.did_change
        assert write_topic.has_data
        assert_data_equal(input_dict, write_topic.data)
        if do_telemetry:
            data = await read_topic.next(flush=False, timeout=STD_TIMEOUT)
            assert_data_equal(data, input_dict)

        # Check that setting a NaN field to NaN again is not a change
        for field_name in ("float0", "double0"):
            if do_arrays:
                original_value = input_dict[field_name][:]
                nan_value = copy.copy(original_value)
                assert len(nan_value) >= 4
                nan_value[1] = math.nan
                nan_value[3] = math.nan
            else:
                original_value = input_dict[field_name]
                nan_value = math.nan
            nan_kwarg = {field_name: nan_value}
            original_kwarg = {field_name: original_value}
            try:
                for i in range(2):
                    input_dict[field_name] = nan_value
                    write_result = await write_topic.set_write(**nan_kwarg)
                    if i == 0:
                        assert write_result.did_change
                    else:
                        assert not write_result.did_change
                    assert write_topic.has_data
                    assert_data_equal(input_dict, write_topic.data)
                    if do_telemetry or write_result.did_change:
                        assert write_result.was_written
                        data = await read_topic.next(flush=False, timeout=STD_TIMEOUT)
                        assert_data_equal(data, input_dict)

                input_dict[field_name] = original_value
                did_change = write_topic.set(**original_kwarg)
                assert did_change
            finally:
                input_dict[field_name] = original_value

        # try an invalid key
        with pytest.raises(AttributeError):
            await write_topic.set_write(no_such_attribute=None)

        # try an invalid value
        if do_arrays:
            bad_int0_value = ["not an int"] * len(input_dict["int0"])  # type: ignore
        else:
            bad_int0_value = "not an int"  # type: ignore
        with pytest.raises(TypeError):
            await write_topic.set_write(int0=bad_int0_value)

        if do_arrays:
            # Try an array that is too short
            # (note: arrays that are too long are silently truncated)
            short_int0_value = np.arange(len(input_dict["int0"]) - 1, dtype=int)
            # This became a warning instead of an error.
            with pytest.warns(UserWarning):
                await write_topic.set_write(int0=short_int0_value)

            # Make sure data can be read successfully.
            data = await read_topic.next(flush=False, timeout=NO_DATA_TIMEOUT)
            assert len(data.int0) == len(short_int0_value)
            assert (data.int0 == short_int0_value).all()

        # Make sure data can be read successfully.
        with pytest.raises(asyncio.TimeoutError):
            await read_topic.next(flush=False, timeout=NO_DATA_TIMEOUT)

    async def test_multiple_commands(self) -> None:
        """Test that we can have multiple instances of the same command
        running at the same time.
        """
        async with self.make_csc(initial_state=salobj.State.ENABLED):
            await self.assert_next_sample(
                self.remote.evt_heartbeat, flush=True, timeout=STD_TIMEOUT
            )
            assert self.csc.cmd_wait.has_callback
            assert self.csc.cmd_wait.allow_multiple_callbacks

            durations = (4, 2)  # seconds
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
            t0 = time.monotonic()
            ackcmds = await asyncio.gather(*tasks)
            measured_duration = time.monotonic() - t0
            for ackcmd in ackcmds:
                assert ackcmd.ack == salobj.SalRetCode.CMD_COMPLETE

            expected_duration = max(*durations)
            assert abs(measured_duration - expected_duration) < 1

    async def test_multiple_sequential_commands(self) -> None:
        """Test that commands prohibiting multiple callbacks are executed
        one after the other.
        """
        async with self.make_csc(initial_state=salobj.State.ENABLED):
            assert self.csc.cmd_wait.has_callback
            self.csc.cmd_wait.allow_multiple_callbacks = False
            assert not self.csc.cmd_wait.allow_multiple_callbacks

            durations = (STD_TIMEOUT, STD_TIMEOUT / 2.0)  # seconds

            tasks = []
            for duration in durations:
                task = self.remote.cmd_wait.set_start(
                    duration=duration,
                    timeout=STD_TIMEOUT + duration,
                )
                tasks.append(task)
            # stop to give time for the system to stabilize before
            await asyncio.sleep(NO_DATA_TIMEOUT)
            t0 = time.monotonic()
            ackcmds = await asyncio.gather(*tasks)
            measured_duration = time.monotonic() - t0
            for ackcmd in ackcmds:
                assert ackcmd.ack == salobj.SalRetCode.CMD_COMPLETE

            expected_duration = np.sum(durations)
            assert measured_duration == pytest.approx(expected_duration, rel=1e-1)

    async def test_remote_command_not_ready(self) -> None:
        """Test RemoteCommand methods that should raise an exception when the
        read loop isn't running."""
        async with salobj.Domain() as domain, salobj.SalInfo(
            domain=domain, name="Test", index=self.next_index()
        ) as salinfo:
            cmdwriter = salobj.topics.RemoteCommand(salinfo=salinfo, name="setScalars")
            with pytest.raises(RuntimeError):
                await cmdwriter.start(timeout=NO_DATA_TIMEOUT)
            with pytest.raises(RuntimeError):
                await cmdwriter.set_start(timeout=NO_DATA_TIMEOUT)
            await salinfo.close()

    async def test_remote_command_set(self) -> None:
        """Test that RemoteCommand.set and set_start use new data.

        Test that RemoteCommand.set and set_start both begin with a new sample
        for each call, rather than remembering anything from the previous
        command. This is different than WriteTopic.set.
        """
        async with salobj.Domain() as domain, salobj.SalInfo(
            domain=domain, name="Test", index=1
        ) as salinfo:
            cmdreader = salobj.topics.ControllerCommand(
                salinfo=salinfo, name="setScalars"
            )
            cmdwriter = salobj.topics.RemoteCommand(salinfo=salinfo, name="setScalars")
            await salinfo.start()

            read_data_list = []

            async def cmd_reader_callback(data: salobj.BaseMsgType) -> None:
                read_data_list.append(data)
                ackcmd = cmdreader.salinfo.AckCmdType(
                    private_seqNum=data.private_seqNum,
                    ack=salobj.SalRetCode.CMD_COMPLETE,
                )
                await cmdreader.ack(data=data, ackcmd=ackcmd)

            cmdreader.callback = cmd_reader_callback
            kwargs_list: Sequence[dict[str, typing.Any]] = (
                dict(int0=1),
                dict(float0=1.3),
                dict(short0=-3, long0=47),
            )
            fields: set[str] = set()
            for kwargs in kwargs_list:
                fields.update(kwargs.keys())

            # RemoteCommand.set resets data
            for kwargs in kwargs_list:
                cmdwriter.set(**kwargs)
                for field in fields:
                    assert getattr(cmdwriter.data, field) == pytest.approx(
                        kwargs.get(field, 0)
                    )

            # RemoteCommand.start with no data does not reset data,
            # so that it can be used with set.
            last_kwargs = kwargs_list[-1]
            await cmdwriter.start(timeout=STD_TIMEOUT)
            for field in fields:
                assert getattr(cmdwriter.data, field) == pytest.approx(
                    last_kwargs.get(field, 0)
                )
            assert len(read_data_list) == 1

            # RemoteCommand.set with no kwargs resets all data
            # (test this *after* start so start has non-zero data).
            cmdwriter.set()
            for field in fields:
                assert getattr(cmdwriter.data, field) == pytest.approx(0)

            # RemoteCommand.set_start resets data.
            start_ind = 1 + len(read_data_list)
            for i, kwargs in enumerate(kwargs_list):
                await cmdwriter.set_start(**kwargs, timeout=STD_TIMEOUT)
                assert len(read_data_list) == i + start_ind
                read_data = read_data_list[-1]
                for field in fields:
                    assert getattr(read_data, field) == pytest.approx(
                        kwargs.get(field, 0)
                    )

            # Make sure set_write and write are prohibited.
            with pytest.raises(NotImplementedError):
                await cmdwriter.set_write()
            with pytest.raises(NotImplementedError):
                await cmdwriter.write()

    async def test_read_topic_not_ready(self) -> None:
        """Test ReadTopic for exceptions when the read loop isn't running."""
        async with salobj.Domain() as domain, salobj.SalInfo(
            domain=domain, name="Test", index=self.next_index()
        ) as salinfo:
            # Use a logevent topic because it is not volatile
            # (which might cause the read loop to start too quickly).
            topic = salobj.topics.ReadTopic(
                salinfo=salinfo, attr_name="evt_scalars", max_history=100
            )
            with pytest.raises(RuntimeError):
                topic.has_data
            with pytest.raises(RuntimeError):
                topic.get()
            with pytest.raises(RuntimeError):
                topic.get_oldest()
            with pytest.raises(RuntimeError):
                # Use a timeout of 0 because the exception
                # should occur before the timeout is used
                # and we cannot afford to wait -- the read loop might start.
                await topic.aget(timeout=0)
            with pytest.raises(RuntimeError):
                await topic.next(flush=False, timeout=0)

    async def test_read_topic_constructor_errors_and_warnings(self) -> None:
        MIN_QUEUE_LEN = salobj.topics.MIN_QUEUE_LEN
        async with salobj.Domain() as domain, salobj.SalInfo(
            domain=domain, name="Test", index=self.next_index()
        ) as salinfo:
            # max_history must not be negative
            for bad_max_history in (-1, -10):
                for attr_name in (
                    "ack_ackcmd",
                    "cmd_setScalars",
                    "evt_scalars",
                    "tel_scalars",
                ):
                    with pytest.raises(ValueError):
                        salobj.topics.ReadTopic(
                            salinfo=salinfo,
                            attr_name=attr_name,
                            max_history=bad_max_history,
                        )
            # queue_len must be be >= MIN_QUEUE_LEN
            for bad_queue_len in (-1, 0, MIN_QUEUE_LEN - 1):
                for attr_name in (
                    "ack_ackcmd",
                    "cmd_setScalars",
                    "evt_scalars",
                    "tel_scalars",
                ):
                    with pytest.raises(ValueError):
                        salobj.topics.ReadTopic(
                            salinfo=salinfo,
                            attr_name=attr_name,
                            max_history=0,
                            queue_len=bad_queue_len,
                        )

            # max_history must be <= queue_len
            for queue_len, delta, attr_name in itertools.product(
                (1, 10),
                (1, 5),
                ("ack_ackcmd", "cmd_setScalars", "evt_scalars", "tel_scalars"),
            ):
                bad_max_history = queue_len + delta
                with pytest.raises(ValueError):
                    salobj.topics.ReadTopic(
                        salinfo=salinfo,
                        attr_name=attr_name,
                        max_history=bad_max_history,
                        queue_len=queue_len,
                    )

            # max_history can only be 0 or 1 with index=0
            # for an indexed component
            async with salobj.SalInfo(domain=domain, name="Test", index=0) as salinfo0:
                for bad_max_history in (-1, 2, 3, 10):
                    with pytest.raises(ValueError):
                        salobj.topics.ReadTopic(
                            salinfo=salinfo0,
                            attr_name="evt_scalars",
                            max_history=bad_max_history,
                        )

    async def test_command_next_ack(self) -> None:
        async with self.make_csc(initial_state=salobj.State.ENABLED):
            duration = 0.1  # Arbitrary short value so the test runs quickly
            ackcmd1 = await self.remote.cmd_wait.set_start(
                duration=duration, wait_done=False, timeout=STD_TIMEOUT
            )
            assert ackcmd1.ack == salobj.SalRetCode.CMD_INPROGRESS
            assert ackcmd1.timeout == pytest.approx(duration)
            ackcmd2 = await self.remote.cmd_wait.next_ackcmd(
                ackcmd1, wait_done=True, timeout=STD_TIMEOUT
            )
            assert ackcmd2.ack == salobj.SalRetCode.CMD_COMPLETE

            # Now try a timeout. Specify a negative duration to avoid the
            # CMD_INPROGRESS command ack that extends the timeout.
            with salobj.assertRaisesAckTimeoutError():
                await self.remote.cmd_wait.set_start(
                    duration=-5, wait_done=False, timeout=NO_DATA_TIMEOUT
                )

    async def test_command_seq_num(self) -> None:
        async with self.make_csc(initial_state=salobj.State.ENABLED):
            prev_max_seq_num = None
            for cmd_name in self.remote.salinfo.command_names:
                cmd = getattr(self.remote, f"cmd_{cmd_name}")
                if prev_max_seq_num is None:
                    assert cmd.min_seq_num == 1
                else:
                    assert cmd.min_seq_num == prev_max_seq_num + 1
                    assert cmd.max_seq_num > cmd.min_seq_num
                    assert cmd.max_seq_num <= salobj.topics.MAX_SEQ_NUM
                prev_max_seq_num = cmd.max_seq_num

            # Execute non-state-transition commands
            # (since state-transition commands cannot be repeated)
            for cmd in (
                self.remote.cmd_setArrays,
                self.remote.cmd_setScalars,
                self.remote.cmd_wait,
            ):
                data = await cmd.start()
                seq_num = data.private_seqNum
                data = await cmd.start()
                seq_num2 = data.private_seqNum
                if seq_num < cmd.max_seq_num:
                    assert seq_num2 == seq_num + 1

    async def test_mock_write_topic(self) -> None:
        async with salobj.make_mock_write_topics(
            name="Test", attr_names=["cmd_wait", "evt_summaryState", "tel_arrays"]
        ) as topics:
            # Create the test_data first, then iterate over it,
            # to make mypy happier.
            test_data: list[tuple[str, list[dict[str, typing.Any]]]] = [
                ("cmd_wait", [dict(duration=val) for val in (1, 2, 3)]),
                ("evt_summaryState", [dict(summaryState=val) for val in (2, 3, 4)]),
                ("tel_arrays", [dict(int0=[val] * 5) for val in range(5)]),
            ]
            for attr_name, data_list in test_data:
                topic = getattr(topics, attr_name)
                assert (
                    topic.default_force_output is False
                    if attr_name.startswith("evt")
                    else True
                )
                assert len(topic.data_list) == 0
                for i, data in enumerate(data_list):
                    await topic.set_write(**data)
                    assert len(topic.data_list) == i + 1
                    for key, value in data.items():
                        assert getattr(topic.data_list[-1], key) == value

                # Write the last data again. This should only write and add
                # data if not an event.
                result = await topic.set_write(**data)
                assert not result.did_change
                assert result.was_written == topic.default_force_output
                if result.was_written:
                    assert len(topic.data_list) == len(data_list) + 1
                else:
                    assert len(topic.data_list) == len(data_list)

    async def test_topic_subname(self) -> None:
        """Test specifying topic subname with $LSST_TOPIC_SUBNAME."""

        salobj.set_test_topic_subname(randomize=True)
        async with salobj.Domain() as domain, salobj.SalInfo(
            domain=domain, name="Test", index=0
        ) as salinfo_r1, salobj.SalInfo(
            domain=domain, name="Test", index=0
        ) as salinfo_w1:
            salobj.set_test_topic_subname(randomize=True)
            async with salobj.SalInfo(
                domain=domain, name="Test", index=0
            ) as salinfo_r2, salobj.SalInfo(
                domain=domain, name="Test", index=0
            ) as salinfo_w2:
                assert (
                    salinfo_r1.component_info.topic_subname
                    == salinfo_w1.component_info.topic_subname
                )
                assert (
                    salinfo_r2.component_info.topic_subname
                    == salinfo_w2.component_info.topic_subname
                )
                assert (
                    salinfo_r1.component_info.topic_subname
                    != salinfo_r2.component_info.topic_subname
                )

                writer1 = salobj.topics.ControllerEvent(
                    salinfo=salinfo_w1, name="errorCode"
                )
                writer2 = salobj.topics.ControllerEvent(
                    salinfo=salinfo_w2, name="errorCode"
                )
                await asyncio.wait_for(
                    asyncio.gather(salinfo_w1.start(), salinfo_w2.start()),
                    timeout=STD_TIMEOUT,
                )

                # write late joiner data (before we have readers);
                # only the last value should be seen
                for i in (3, 4, 5):
                    await writer1.set_write(errorCode=10 + i)
                    await writer2.set_write(errorCode=20 + i)

                # create readers and set callbacks for them
                reader1 = salobj.topics.RemoteEvent(
                    salinfo=salinfo_r1, name="errorCode"
                )
                reader2 = salobj.topics.RemoteEvent(
                    salinfo=salinfo_r2, name="errorCode"
                )
                await asyncio.wait_for(
                    asyncio.gather(salinfo_r1.start(), salinfo_r2.start()),
                    timeout=STD_TIMEOUT,
                )

                # write more data now that we have readers;
                # they should see all of it
                for i in (6, 7, 8):
                    await writer1.set_write(errorCode=10 + i)
                    await writer2.set_write(errorCode=20 + i)

                read_codes1 = []
                read_codes2 = []
                expected_codes1 = [15, 16, 17, 18]
                expected_codes2 = [25, 26, 27, 28]
                try:
                    timeout = STD_TIMEOUT
                    for i in range(5):
                        data1 = await reader1.next(flush=False, timeout=timeout)
                        read_codes1.append(data1.errorCode)
                        if len(read_codes1) >= len(expected_codes1):
                            timeout = NO_DATA_TIMEOUT
                except asyncio.TimeoutError:
                    if len(read_codes1) < len(expected_codes1):
                        raise
                try:
                    timeout = STD_TIMEOUT
                    for i in range(5):
                        data2 = await reader2.next(flush=False, timeout=timeout)
                        read_codes2.append(data2.errorCode)
                        if len(read_codes2) >= len(expected_codes2):
                            timeout = NO_DATA_TIMEOUT
                except asyncio.TimeoutError:
                    if len(read_codes2) < len(expected_codes2):
                        raise
                assert read_codes1 == expected_codes1
                assert read_codes2 == expected_codes2

    async def test_sal_index(self) -> None:
        """Test separation of data using SAL index, including historical data.

        Readers with index=0 should see data from all writers of that topic,
        regardless of index.
        Readers with a non-zero SAL index should only see data
        from a writer with the same index.
        """
        sal_indices = (0, 1, 2)
        salobj.set_test_topic_subname(randomize=True)
        async with salobj.Domain() as domain:
            writers = [
                salobj.topics.ControllerEvent(
                    salinfo=salobj.SalInfo(domain=domain, name="Test", index=index),
                    name="errorCode",
                )
                for index in sal_indices
            ]
            await asyncio.wait_for(
                asyncio.gather(*[writer.salinfo.start() for writer in writers]),
                timeout=STD_TIMEOUT,
            )

            # Write historical data (before we have readers);
            # only the last value for each index should be seen.
            for base_value in (3, 4, 5):
                for writer in writers:
                    value = writer.salinfo.index * 10 + base_value
                    print(f"Pre data write: salindex={writer.salinfo.index} {value=}.")
                    await writer.set_write(errorCode=value)
                    await asyncio.sleep(0.2)

            # Create readers.
            # The index 0 reader should read data from all writers.
            # The index 1 and 2 readers should only see data from
            # the writer with the same index.
            readers = [
                salobj.topics.RemoteEvent(
                    salinfo=salobj.SalInfo(domain=domain, name="Test", index=index),
                    name="errorCode",
                )
                for index in sal_indices
            ]
            await asyncio.wait_for(
                asyncio.gather(*[reader.salinfo.start() for reader in readers]),
                timeout=STD_TIMEOUT,
            )

            # Write more data now that we have readers;
            # the readers should see all of it.
            for base_value in (6, 7, 8):
                for writer in writers:
                    value = base_value + writer.salinfo.index * 10
                    print(f"Post data write: salindex={writer.salinfo.index} {value=}.")
                    await writer.set_write(errorCode=value)
                    await asyncio.sleep(0.2)

            # Dict of salIndex: list of errorCodes read for that salIndex
            read_codes: dict[int, list[int]] = collections.defaultdict(list)
            expected_codes = {
                # 0 gets the last historical value written for each index
                # plus new data for all indices
                0: [5, 15, 25, 6, 16, 26, 7, 17, 27, 8, 18, 28],
                # the other two get the last historical value written
                # for those indices, plus new data for that index
                1: [15, 16, 17, 18],
                2: [25, 26, 27, 28],
            }
            for reader in readers:
                index = reader.salinfo.index
                for _ in range(len(expected_codes[index])):
                    data = await reader.next(flush=False, timeout=STD_TIMEOUT)
                    read_codes[index].append(data.errorCode)
            assert read_codes.keys() == set(sal_indices)
            for index in sal_indices:
                assert read_codes[index] == expected_codes[index]

    async def test_topic_repr(self) -> None:
        async with self.make_csc(initial_state=salobj.State.ENABLED):
            salinfo = self.remote.salinfo

            for obj, classSuffix in ((self.csc, "Controller"), (self.remote, "Remote")):
                with self.subTest(obj=obj, classSuffix=classSuffix):
                    for cmd_name in salinfo.command_names:
                        cmd = getattr(obj, "cmd_" + cmd_name)
                        cmd_repr = repr(cmd)
                        assert cmd_name in cmd_repr
                        assert "Test" in cmd_repr
                        assert classSuffix + "Command" in cmd_repr
                    for evt_name in salinfo.event_names:
                        evt = getattr(obj, "evt_" + evt_name)
                        evt_repr = repr(evt)
                        assert evt_name in evt_repr
                        assert "Test" in evt_repr
                        assert classSuffix + "Event" in evt_repr
                    for tel_name in salinfo.telemetry_names:
                        tel = getattr(obj, "tel_" + tel_name)
                        tel_repr = repr(tel)
                        assert tel_name in tel_repr
                        assert "Test" in tel_repr
                        assert classSuffix + "Telemetry" in tel_repr

    async def test_write_topic_set(self) -> None:
        """Test that WriteTopic.set uses existing data for defaults."""
        async with salobj.Domain() as domain, salobj.SalInfo(
            domain=domain, name="Test", index=1
        ) as salinfo:
            write_topic = salobj.topics.WriteTopic(
                salinfo=salinfo, attr_name="evt_scalars"
            )
            await asyncio.wait_for(salinfo.start(), timeout=STD_TIMEOUT)

            predicted_data_dict = vars(write_topic.DataType())
            kwargs_list: Iterable[dict[str, typing.Any]] = (
                dict(int0=1),
                dict(float0=1.3),
                dict(int0=-3, long0=47),
            )
            fields: set[str] = set()
            for kwargs in kwargs_list:
                fields.update(kwargs.keys())

            for kwargs in kwargs_list:
                write_topic.set(**kwargs)
                predicted_data_dict.update(kwargs)
                for field in fields:
                    assert getattr(write_topic.data, field) == pytest.approx(
                        predicted_data_dict[field]
                    )

    async def test_read_num_messages_read_timeout(self) -> None:
        """Test modifying the value of num_messages and message_read_timeout
        in SalInfo read loop."""
        num_messages = 100
        consume_messages_timeout = 2.5
        async with salobj.Domain() as domain, salobj.SalInfo(
            domain=domain,
            name="Test",
            index=3,
            num_messages=num_messages,
            consume_messages_timeout=consume_messages_timeout,
        ) as salinfo:
            tel_reader = salobj.topics.ReadTopic(
                salinfo=salinfo, attr_name="tel_scalars", max_history=0
            )
            tel_writter = salobj.topics.WriteTopic(
                salinfo=salinfo, attr_name="tel_scalars"
            )
            await asyncio.wait_for(salinfo.start(), timeout=STD_TIMEOUT)

            # Write 99 messages and try to read them with a short timeout.
            # This should timeout because the read loop has a timeout of 5s.
            for i in range(num_messages - 1):
                await tel_writter.write()

            with pytest.raises(asyncio.TimeoutError):
                await tel_reader.aget(timeout=consume_messages_timeout - 1)

            for i in range(num_messages - 1):
                await tel_reader.next(flush=False, timeout=consume_messages_timeout)

            # Write num_messages messages and try to read them with a
            # short timeout. This should not timeout because the read
            # loop only waits for num_messages.
            for i in range(num_messages):
                await tel_writter.write()

            for i in range(num_messages):
                await tel_reader.next(flush=False, timeout=NO_DATA_TIMEOUT)
