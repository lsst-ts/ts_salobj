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
import unittest

import pytest
from lsst.ts import salobj, utils

# Long enough to perform any reasonable operation
# including starting a CSC or loading a script (seconds)
STD_TIMEOUT = 60

index_gen = utils.index_generator()


class SalInfoTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        salobj.set_random_lsst_dds_partition_prefix()

    async def test_salinfo_constructor(self) -> None:
        with pytest.raises(TypeError):
            salobj.SalInfo(domain=None, name="Test")

        async with salobj.Domain() as domain:
            with pytest.raises(RuntimeError):
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
                with pytest.raises(RuntimeError):
                    salinfo.assert_started()

                asyncio.create_task(salinfo.start())
                # Use a short time limit because there are no topics to read
                await asyncio.wait_for(salinfo.start_task, timeout=STD_TIMEOUT)
                assert salinfo.start_task.done()
                assert not salinfo.done_task.done()
                assert salinfo.started
                salinfo.assert_started()

                with pytest.raises(RuntimeError):
                    await salinfo.start()

                await asyncio.wait_for(salinfo.close(), timeout=STD_TIMEOUT)
                assert salinfo.start_task.done()
                assert salinfo.done_task.done()
                assert salinfo.started
                salinfo.assert_started()

                # Test enum index
                class SalIndex(enum.IntEnum):
                    ONE = 1
                    TWO = 2

            async with salobj.SalInfo(
                domain=domain, name="Script", index=SalIndex.ONE
            ) as salinfo:
                assert isinstance(salinfo.index, SalIndex)
                assert salinfo.index == SalIndex.ONE

    async def test_salinfo_attributes(self) -> None:
        index = next(index_gen)
        async with salobj.Domain() as domain, salobj.SalInfo(
            domain=domain, name="Test", index=index
        ) as salinfo:
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
            salinfo.indexed = False
            assert salinfo.name_index == "Test"

            assert salinfo.partition_prefix == os.environ["LSST_DDS_PARTITION_PREFIX"]

    async def test_salinfo_metadata(self) -> None:
        """Test some of the metadata in SalInfo.

        The main tests of the IDL parser are elsewhere.
        """
        index = next(index_gen)
        async with salobj.Domain() as domain, salobj.SalInfo(
            domain=domain, name="Test", index=index
        ) as salinfo:
            # Check some topic and field metadata
            for topic_name, topic_metadata in salinfo.metadata.topic_info.items():
                assert topic_name == topic_metadata.sal_name
                for field_name, field_metadata in topic_metadata.field_info.items():
                    assert field_name == field_metadata.name

            some_expected_topic_names = (
                "command_enable",
                "command_setArrays",
                "command_setScalars",
                "logevent_arrays",
                "logevent_scalars",
                "arrays",
                "scalars",
            )
            assert set(some_expected_topic_names).issubset(
                set(salinfo.metadata.topic_info.keys())
            )

    async def test_lsst_dds_partition_prefix_required(self) -> None:
        # Delete LSST_DDS_PARTITION_PREFIX. This should prevent
        # constructing a Domain
        with utils.modify_environ(LSST_DDS_PARTITION_PREFIX=None):
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
        async with salobj.Domain() as domain, salobj.SalInfo(
            domain=domain, name="Test", index=index
        ) as salinfo:
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
        async with salobj.Domain() as domain, salobj.SalInfo(
            domain=domain, name="Test", index=index, write_only=True
        ) as salinfo:
            # Cannot add a read topic to a write-only SalInfo
            with pytest.raises(RuntimeError):
                salobj.topics.ReadTopic(
                    salinfo=salinfo, attr_name="evt_summaryState", max_history=0
                )

            # Check that starting the SalInfo does not start the read loop
            await salinfo.start()
            assert salinfo._read_loop_task.done()
