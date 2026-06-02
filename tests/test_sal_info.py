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
import logging
import os
import pathlib
import tempfile
import unittest

import pytest
import yaml
from lsst.ts import salobj, utils
from lsst.ts.salobj.topics import ReadTopic, WriteTopic

# Long enough to perform any reasonable operation
# including starting a CSC or loading a script (seconds)
STD_TIMEOUT = 20

TOPIC_READ_TIMEOUT = 1

index_gen = utils.index_generator()


class SalInfoTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        salobj.set_test_topic_subname()

    async def asyncTearDown(self) -> None:
        """Runs after each test is completed."""
        await salobj.delete_kafka_topics()

    async def test_salinfo_constructor(self) -> None:
        with pytest.raises(TypeError):
            salobj.SalInfo(domain=None, name="Test")

        async with salobj.Domain() as domain:
            with pytest.raises(ValueError):
                salobj.SalInfo(domain=domain, name="invalid_component_name")

            for invalid_index in (1.1, "one"):
                with pytest.raises(TypeError):
                    salobj.SalInfo(domain=domain, name="Test", index=invalid_index)

            index = next(index_gen)
            async with salobj.SalInfo(
                domain=domain, name="Test", index=index
            ) as salinfo:
                assert salinfo.name == "Test"
                assert salinfo.index == index
                assert not salinfo.start_task.done()
                assert not salinfo.done_task.done()
                assert not salinfo.started
                assert not salinfo.running
                with pytest.raises(RuntimeError):
                    salinfo.assert_started()
                with pytest.raises(RuntimeError):
                    salinfo.assert_running()

                asyncio.create_task(salinfo.start())
                await asyncio.wait_for(salinfo.start_task, timeout=STD_TIMEOUT)
                assert salinfo.start_task.done()
                assert not salinfo.done_task.done()
                assert salinfo.started
                assert salinfo.running
                salinfo.assert_started()
                salinfo.assert_running()

                with pytest.raises(RuntimeError):
                    await salinfo.start()

                await asyncio.wait_for(salinfo.close(), timeout=STD_TIMEOUT)
                assert salinfo.start_task.done()
                assert salinfo.done_task.done()
                assert salinfo.started
                assert not salinfo.running
                salinfo.assert_started()
                with pytest.raises(RuntimeError):
                    salinfo.assert_running()

            # Test enum index
            class SalIndex(enum.IntEnum):
                ONE = 1
                TWO = 2

            async with salobj.SalInfo(
                domain=domain, name="Script", index=SalIndex.ONE
            ) as salinfo:
                assert isinstance(salinfo.index, SalIndex)
                assert salinfo.index == SalIndex.ONE

            async with salobj.SalInfo(
                domain=domain,
                name="Script",
                index=SalIndex.ONE,
                num_messages=100,
                consume_messages_timeout=0.01,
            ) as salinfo:

                assert salinfo.num_messages == 100
                assert salinfo.consume_messages_timeout == 0.01

    async def test_salinfo_attributes(self) -> None:
        index = next(index_gen)
        async with (
            salobj.Domain() as domain,
            salobj.SalInfo(domain=domain, name="Test", index=index) as salinfo,
        ):
            assert salinfo.name_index == f"Test:{index}"

            # Expected commands; must be complete and sorted alphabetically.
            expected_commands = (
                "disable",
                "enable",
                "exitControl",
                "fault",
                "setArrays",
                "setLogLevel",
                "setScalars",
                "standby",
                "start",
                "wait",
            )
            assert expected_commands == salinfo.command_names

            # Expected events; must be complete and sorted alphabetically.
            expected_events = (
                "arrays",
                "configurationApplied",
                "configurationsAvailable",
                "errorCode",
                "heartbeat",
                "logLevel",
                "logMessage",
                "scalars",
                "simulationMode",
                "softwareVersions",
                "summaryState",
            )
            assert expected_events == salinfo.event_names

            # telemetry topic names should match; there are no generics
            expected_telemetry = ("arrays", "scalars")
            assert expected_telemetry == salinfo.telemetry_names

            expected_sal_topic_names = ["ackcmd"]
            expected_sal_topic_names += [
                f"command_{name}" for name in salinfo.command_names
            ]
            expected_sal_topic_names += [
                f"logevent_{name}" for name in salinfo.event_names
            ]
            expected_sal_topic_names += [name for name in salinfo.telemetry_names]
            assert sorted(expected_sal_topic_names) == list(salinfo.sal_topic_names)

            assert salinfo.identity == domain.user_host

            # Check that the name_index for a non-indexed component
            # has no :index suffix.
            salinfo2 = salobj.SalInfo(domain=domain, name="MTRotator")
            assert not salinfo2.indexed
            assert salinfo2.name_index == "MTRotator"

            assert (
                salinfo.component_info.topic_subname == os.environ["LSST_TOPIC_SUBNAME"]
            )

    async def test_salinfo_component_info(self) -> None:
        """Test some of the component info in SalInfo.

        The main tests of ComponentInfo are elsewhere.
        """
        index = next(index_gen)
        async with (
            salobj.Domain() as domain,
            salobj.SalInfo(domain=domain, name="Test", index=index) as salinfo,
        ):
            # Check some topic and field metadata
            for attr_name, topic_info in salinfo.component_info.topics.items():
                assert attr_name == topic_info.attr_name
                for field_name, field_info in topic_info.fields.items():
                    assert field_name == field_info.name

            some_expected_attr_names = (
                "cmd_enable",
                "cmd_setArrays",
                "cmd_setScalars",
                "evt_arrays",
                "evt_scalars",
                "tel_arrays",
                "tel_scalars",
            )
            assert set(some_expected_attr_names).issubset(
                salinfo.component_info.topics.keys()
            )

    async def validate_max_history(
        self, domain: salobj.Domain, expected_max_history: int
    ) -> None:
        index = next(index_gen)
        async with salobj.SalInfo(domain=domain, name="Test", index=index) as salinfo:
            max_history = salinfo.get_max_history_for_indexed_component()
            assert max_history == expected_max_history

    async def test_get_max_history_for_indexed_component(self) -> None:
        async with salobj.Domain() as domain:
            with tempfile.TemporaryDirectory() as tmpdir:
                # Create a temporary directory and set the
                # LSST_HISTORY_READ_CONFIG env var. The file doesn't exist
                # yet and the code should handle that well.
                tmppath = pathlib.Path(tmpdir) / "sal_info_history_config.yaml"
                os.environ["LSST_HISTORY_READ_CONFIG"] = tmppath.as_posix()

                # This should load the hard coded default value.
                await self.validate_max_history(
                    domain=domain, expected_max_history=salobj.sal_info.MAX_HISTORY_READ
                )

                # This should load the value set in the env var.
                env_max_history = 750
                os.environ["LSST_MAX_HISTORY_READ"] = f"{env_max_history}"
                await self.validate_max_history(
                    domain=domain, expected_max_history=env_max_history
                )

                # Now the config file is created so the value in there should
                # be used.
                config_max_history = 1000
                with open(tmppath, "w") as fp:
                    yaml.safe_dump({"Test": config_max_history}, fp)
                await self.validate_max_history(
                    domain=domain, expected_max_history=config_max_history
                )

    async def test_lsst_topic_subname_required(self) -> None:
        # Delete LSST_TOPIC_SUBNAME. This should prevent constructing
        # a SalInfo.
        with utils.modify_environ(LSST_TOPIC_SUBNAME=None):
            async with salobj.Domain() as domain:
                with pytest.raises(RuntimeError):
                    salobj.SalInfo(domain=domain, name="Test", index=1)

    async def test_log_level(self) -> None:
        """Test that log level is decreased (verbosity increased) to INFO."""
        salinfos = []
        index = next(index_gen)
        async with salobj.Domain() as domain:
            try:
                # Start with log level WARNING, and test that creating
                # a SalInfo increases the verbosity to INFO.
                log = logging.getLogger()
                log.setLevel(logging.WARNING)
                salinfo = salobj.SalInfo(domain=domain, name="Test", index=index)
                salinfos.append(salinfo)
                assert salinfo.log.getEffectiveLevel() == logging.INFO

                # Start with log level DEBUG, and test that creating a SalInfo
                # does not decreaese the verbosity.
                salinfo.log.setLevel(logging.DEBUG)
                salinfo = salobj.SalInfo(domain=domain, name="Test", index=index)
                salinfos.append(salinfo)
                assert salinfo.log.getEffectiveLevel() == logging.DEBUG
            finally:
                for salinfo in salinfos:
                    await salinfo.close()

    async def test_make_ack_cmd(self) -> None:
        index = next(index_gen)
        async with (
            salobj.Domain() as domain,
            salobj.SalInfo(domain=domain, name="Test", index=index) as salinfo,
        ):
            # Use all defaults
            seq_num = 55
            ack = salobj.SalRetCode.CMD_COMPLETE
            ackcmd = salinfo.make_ackcmd(private_seqNum=seq_num, ack=ack)
            assert ackcmd.private_seqNum == seq_num
            assert ackcmd.ack == ack
            assert ackcmd.error == 0
            assert ackcmd.result == ""

            # Specify an error code and result
            seq_num = 27
            ack = salobj.SalRetCode.CMD_FAILED
            error = 127
            result = "why not?"
            ackcmd = salinfo.make_ackcmd(
                private_seqNum=seq_num,
                ack=ack,
                error=error,
                result=result,
            )
            assert ackcmd.private_seqNum == seq_num
            assert ackcmd.ack == ack
            assert ackcmd.error == error
            assert ackcmd.result == result

    async def test_write_only(self) -> None:
        index = next(index_gen)
        async with (
            salobj.Domain() as domain,
            salobj.SalInfo(
                domain=domain, name="Test", index=index, write_only=True
            ) as salinfo,
        ):
            # Cannot add a read topic to a write-only SalInfo
            with pytest.raises(RuntimeError):
                salobj.topics.ReadTopic(
                    salinfo=salinfo, attr_name="evt_summaryState", max_history=0
                )

            # Check that starting a write-only SalInfo
            # does not start the read loop
            await salinfo.start()
            assert salinfo._consumer is None
            assert salinfo._read_loop_task.done()

    async def test_reject_old_topic_data(self) -> None:
        index = next(index_gen)
        read_topics: dict[str, ReadTopic] = {}
        async with (
            salobj.Domain() as domain,
            salobj.SalInfo(domain=domain, name="Test", index=index) as salinfo,
        ):
            for topic in ["ack_ackcmd", "cmd_setScalars", "evt_scalars", "tel_scalars"]:
                WriteTopic(salinfo=salinfo, attr_name=topic)
                read_topics[topic] = ReadTopic(
                    salinfo=salinfo, attr_name=topic, max_history=10
                )

            await salinfo.start()

            for topic in read_topics:
                message_num = 0
                for value in 1000, 100:
                    message_num += 1
                    ackcmd = salinfo.make_ackcmd(
                        private_seqNum=value, ack=salobj.SalRetCode.CMD_COMPLETE
                    )
                    ackcmd.private_sndStamp = value
                    ackcmd.salIndex = index
                    topic_info = salinfo.component_info.topics[topic]
                    await salinfo.write_data(
                        topic_info=topic_info, data_dict=vars(ackcmd)
                    )

                    match message_num:
                        case 1:
                            # The first message should always be read.
                            await read_topics[topic].next(
                                flush=True, timeout=TOPIC_READ_TIMEOUT
                            )
                        case 2:
                            if topic in ["ack_ackcmd", "cmd_setScalars"]:
                                # Too old command messages should always be
                                # read.
                                await read_topics[topic].next(
                                    flush=True, timeout=TOPIC_READ_TIMEOUT
                                )
                            else:
                                # Too old event and telemetry data should be
                                # discarded.
                                with pytest.raises(TimeoutError):
                                    await read_topics[topic].next(
                                        flush=True, timeout=TOPIC_READ_TIMEOUT
                                    )

    async def test_no_discard_out_of_order_topics(self) -> None:
        index = next(index_gen)
        read_topics: dict[str, ReadTopic] = {}
        async with (
            salobj.Domain() as domain,
            salobj.SalInfo(
                domain=domain,
                name="Test",
                index=index,
                discard_out_of_order_events=False,
                discard_out_of_order_telemetry=False,
            ) as salinfo,
        ):
            for topic in ["ack_ackcmd", "cmd_setScalars", "evt_scalars", "tel_scalars"]:
                WriteTopic(salinfo=salinfo, attr_name=topic)
                read_topics[topic] = ReadTopic(
                    salinfo=salinfo, attr_name=topic, max_history=10
                )

            await salinfo.start()

            for topic in read_topics:
                for value in 1000, 100:
                    ackcmd = salinfo.make_ackcmd(
                        private_seqNum=value, ack=salobj.SalRetCode.CMD_COMPLETE
                    )
                    ackcmd.private_sndStamp = value
                    ackcmd.salIndex = index
                    topic_info = salinfo.component_info.topics[topic]
                    await salinfo.write_data(
                        topic_info=topic_info, data_dict=vars(ackcmd)
                    )
                    await read_topics[topic].next(
                        flush=True, timeout=TOPIC_READ_TIMEOUT
                    )
