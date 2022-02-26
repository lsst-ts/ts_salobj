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

from lsst.ts import salobj
from lsst.ts import utils

# Long enough to perform any reasonable operation
# including starting a CSC or loading a script (seconds)
STD_TIMEOUT = 60

index_gen = utils.index_generator()


class SalInfoTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        salobj.set_random_topic_subname()

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
            salinfo = salobj.SalInfo(domain=domain, name="Test", index=index)
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

            salinfo = salobj.SalInfo(domain=domain, name="Script", index=SalIndex.ONE)
            assert isinstance(salinfo.index, SalIndex)
            assert salinfo.index == SalIndex.ONE

    async def test_salinfo_attributes(self) -> None:
        async with salobj.Domain() as domain:
            index = next(index_gen)
            salinfo = salobj.SalInfo(domain=domain, name="Test", index=index)

            assert salinfo.name_index == f"Test:{index}"

            # Expected commands; must be complete and sorted alphabetically.
            expected_commands = (
                "disable",
                "enable",
                "exitControl",
                "fault",
                "setArrays",
                "setAuthList",
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
                "authList",
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
        async with salobj.Domain() as domain:
            salinfo = salobj.SalInfo(domain=domain, name="Test")

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

    async def test_default_authorize(self) -> None:
        """Test that LSST_DDS_ENABLE_AUTHLIST correctly sets the
        default_authorize attribute.
        """
        async with salobj.Domain() as domain:
            for env_var_value in ("0", "1", None, "2", "", "00"):
                expected_default_authorize = True if env_var_value == "1" else False
                index = next(index_gen)
                with utils.modify_environ(LSST_DDS_ENABLE_AUTHLIST=env_var_value):
                    salinfo = salobj.SalInfo(domain=domain, name="Test", index=index)
                    assert salinfo.default_authorize == expected_default_authorize

    async def test_lsst_topic_subname_required(self) -> None:
        # Delete LSST_TOPIC_SUBNAME. This should prevent constructing
        # a SalInfo.
        with utils.modify_environ(LSST_TOPIC_SUBNAME=None):
            async with salobj.Domain() as domain:
                with pytest.raises(RuntimeError):
                    salobj.SalInfo(domain=domain, name="Test", index=1)

    async def test_log_level(self) -> None:
        """Test that log level is decreased (verbosity increased) to INFO."""
        log = logging.getLogger()
        log.setLevel(logging.WARNING)
        salinfos = []
        async with salobj.Domain() as domain:
            try:
                # Log level is WARNING; test that log level is decreased
                # (verbosity increased) to INFO.
                salinfo = salobj.SalInfo(domain=domain, name="Test")
                salinfos.append(salinfo)
                assert salinfo.log.getEffectiveLevel() == logging.INFO

                # Start with log level DEBUG and test that log level
                # is unchanged.
                salinfo.log.setLevel(logging.DEBUG)
                salinfo = salobj.SalInfo(domain=domain, name="Test")
                salinfos.append(salinfo)
                assert salinfo.log.getEffectiveLevel() == logging.DEBUG
            finally:
                for salinfo in salinfos:
                    await salinfo.close()

    async def test_make_ack_cmd(self) -> None:
        async with salobj.Domain() as domain:
            salinfo = salobj.SalInfo(domain=domain, name="Test")

            # Use all defaults
            seqNum = 55
            ack = salobj.SalRetCode.CMD_COMPLETE
            ackcmd = salinfo.make_ackcmd(private_seqNum=seqNum, ack=ack)
            assert ackcmd.private_seqNum == seqNum
            assert ackcmd.ack == ack
            assert ackcmd.error == 0
            assert ackcmd.result == ""

            # Specify an error code and result
            seqNum = 27
            ack = salobj.SalRetCode.CMD_FAILED
            error = 127
            result = "why not?"
            ackcmd = salinfo.make_ackcmd(
                private_seqNum=seqNum,
                ack=ack,
                error=error,
                result=result,
            )
            assert ackcmd.private_seqNum == seqNum
            assert ackcmd.ack == ack
            assert ackcmd.error == error
            assert ackcmd.result == result
