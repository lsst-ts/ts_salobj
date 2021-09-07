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
import logging
import os
import unittest

from lsst.ts import utils
from lsst.ts import salobj

# Long enough to perform any reasonable operation
# including starting a CSC or loading a script (seconds)
STD_TIMEOUT = 60

index_gen = salobj.index_generator()


class SalInfoTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        salobj.set_random_lsst_dds_partition_prefix()

    async def test_salinfo_constructor(self) -> None:
        with self.assertRaises(TypeError):
            salobj.SalInfo(domain=None, name="Test")

        async with salobj.Domain() as domain:
            with self.assertRaises(RuntimeError):
                salobj.SalInfo(domain=domain, name="invalid_component_name")

            index = next(index_gen)
            salinfo = salobj.SalInfo(domain=domain, name="Test", index=index)
            self.assertEqual(salinfo.name, "Test")
            self.assertEqual(salinfo.index, index)
            self.assertFalse(salinfo.start_task.done())
            self.assertFalse(salinfo.done_task.done())
            self.assertFalse(salinfo.started)
            with self.assertRaises(RuntimeError):
                salinfo.assert_started()

            asyncio.create_task(salinfo.start())
            # Use a short time limit because there are no topics to read
            await asyncio.wait_for(salinfo.start_task, timeout=STD_TIMEOUT)
            self.assertTrue(salinfo.start_task.done())
            self.assertFalse(salinfo.done_task.done())
            self.assertTrue(salinfo.started)
            salinfo.assert_started()

            with self.assertRaises(RuntimeError):
                await salinfo.start()

            await asyncio.wait_for(salinfo.close(), timeout=STD_TIMEOUT)
            self.assertTrue(salinfo.start_task.done())
            self.assertTrue(salinfo.done_task.done())
            self.assertTrue(salinfo.started)
            salinfo.assert_started()

    async def test_salinfo_attributes(self) -> None:
        async with salobj.Domain() as domain:
            index = next(index_gen)
            salinfo = salobj.SalInfo(domain=domain, name="Test", index=index)

            self.assertEqual(salinfo.name_index, f"Test:{index}")

            # expected_commands omits a few commands that TestCsc
            # does not support, but that are in generics.
            expected_commands = [
                "disable",
                "enable",
                "exitControl",
                "standby",
                "start",
                "setArrays",
                "setLogLevel",
                "setScalars",
                "fault",
                "wait",
            ]
            self.assertTrue(set(expected_commands).issubset(set(salinfo.command_names)))

            # expected_events omits a few events that TestCsc
            # does not support, but that are in generics.
            expected_events = [
                "errorCode",
                "heartbeat",
                "logLevel",
                "logMessage",
                "settingVersions",
                "simulationMode",
                "summaryState",
                "scalars",
                "arrays",
            ]
            self.assertTrue(set(expected_events).issubset(set(salinfo.event_names)))

            # telemetry topic names should match; there are no generics
            expected_telemetry = ["arrays", "scalars"]
            self.assertEqual(set(expected_telemetry), set(salinfo.telemetry_names))

            expected_sal_topic_names = ["ackcmd"]
            expected_sal_topic_names += [
                f"command_{name}" for name in salinfo.command_names
            ]
            expected_sal_topic_names += [
                f"logevent_{name}" for name in salinfo.event_names
            ]
            expected_sal_topic_names += [name for name in salinfo.telemetry_names]
            self.assertEqual(
                sorted(expected_sal_topic_names), list(salinfo.sal_topic_names)
            )

            self.assertEqual(salinfo.identity, domain.user_host)

            # Check that the name_index for a non-indexed component
            # has no :index suffix.
            salinfo.indexed = False
            self.assertEqual(salinfo.name_index, "Test")

            self.assertEqual(
                salinfo.partition_prefix, os.environ["LSST_DDS_PARTITION_PREFIX"]
            )

    async def test_salinfo_metadata(self) -> None:
        """Test some of the metadata in SalInfo.

        The main tests of the IDL parser are elsewhere.
        """
        async with salobj.Domain() as domain:
            salinfo = salobj.SalInfo(domain=domain, name="Test")

            # Check some topic and field metadata
            for topic_name, topic_metadata in salinfo.metadata.topic_info.items():
                self.assertEqual(topic_name, topic_metadata.sal_name)
                for field_name, field_metadata in topic_metadata.field_info.items():
                    self.assertEqual(field_name, field_metadata.name)

            some_expected_topic_names = (
                "command_enable",
                "command_setArrays",
                "command_setScalars",
                "logevent_arrays",
                "logevent_scalars",
                "arrays",
                "scalars",
            )
            self.assertTrue(
                set(some_expected_topic_names).issubset(
                    set(salinfo.metadata.topic_info.keys())
                )
            )

    async def test_lsst_dds_domain_fallback(self) -> None:
        # Pick a value for LSST_DDS_DOMAIN that does not match
        # LSST_DDS_PARTITION_PREFIX.
        new_lsst_dds_domain = os.environ["LSST_DDS_PARTITION_PREFIX"] + "Extra text"

        # Test that LSST_DDS_DOMAIN is ignored, with a warning,
        # if both that and LSST_DDS_PARTITION_PREFIX are defined.
        with utils.modify_environ(LSST_DDS_DOMAIN=new_lsst_dds_domain):
            async with salobj.Domain() as domain:
                with self.assertWarnsRegex(
                    DeprecationWarning,
                    "LSST_DDS_PARTITION_PREFIX instead of deprecated",
                ):
                    salinfo = salobj.SalInfo(domain=domain, name="Test", index=1)
                self.assertEqual(
                    salinfo.partition_prefix, os.environ["LSST_DDS_PARTITION_PREFIX"]
                )

        # Test that LSST_DDS_DOMAIN is used, with a warning,
        # if LSST_DDS_PARTITION_PREFIX is not defined.
        with utils.modify_environ(
            LSST_DDS_PARTITION_PREFIX=None, LSST_DDS_DOMAIN=new_lsst_dds_domain
        ):
            async with salobj.Domain() as domain:
                with self.assertWarnsRegex(
                    DeprecationWarning,
                    "LSST_DDS_PARTITION_PREFIX not defined; using deprecated fallback",
                ):
                    salinfo = salobj.SalInfo(domain=domain, name="Test", index=1)
                self.assertEqual(salinfo.partition_prefix, new_lsst_dds_domain)

    async def test_lsst_dds_domain_required(self) -> None:
        # Delete LSST_DDS_PARTITION_PREFIX and (if defined) LSST_DDS_DOMAIN.
        # This should raise an error.
        with utils.modify_environ(LSST_DDS_PARTITION_PREFIX=None, LSST_DDS_DOMAIN=None):
            async with salobj.Domain() as domain:
                with self.assertRaises(RuntimeError):
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
                self.assertEqual(salinfo.log.getEffectiveLevel(), logging.INFO)

                # Start with log level DEBUG and test that log level
                # is unchanged.
                salinfo.log.setLevel(logging.DEBUG)
                salinfo = salobj.SalInfo(domain=domain, name="Test")
                salinfos.append(salinfo)
                self.assertEqual(salinfo.log.getEffectiveLevel(), logging.DEBUG)
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
            self.assertEqual(ackcmd.private_seqNum, seqNum)
            self.assertEqual(ackcmd.ack, ack)
            self.assertEqual(ackcmd.error, 0)
            self.assertEqual(ackcmd.result, "")

            warning_regex = "makeAckCmd is deprecated"
            with self.assertWarnsRegex(DeprecationWarning, warning_regex):
                ackcmd2 = salinfo.makeAckCmd(private_seqNum=seqNum, ack=ack)
            self.assertEqual(ackcmd.get_vars(), ackcmd2.get_vars())

            # Specify an error code and result
            for truncate_result in (False, True):
                with self.subTest(truncate_result=truncate_result):
                    seqNum = 27
                    ack = salobj.SalRetCode.CMD_FAILED
                    error = 127
                    result = "why not?"
                    ackcmd = salinfo.make_ackcmd(
                        private_seqNum=seqNum,
                        ack=ack,
                        error=error,
                        result=result,
                        truncate_result=truncate_result,
                    )
                    self.assertEqual(ackcmd.private_seqNum, seqNum)
                    self.assertEqual(ackcmd.ack, ack)
                    self.assertEqual(ackcmd.error, error)
                    self.assertEqual(ackcmd.result, result)

                    with self.assertWarnsRegex(DeprecationWarning, warning_regex):
                        ackcmd2 = salinfo.makeAckCmd(
                            private_seqNum=seqNum,
                            ack=ack,
                            error=error,
                            result=result,
                            truncate_result=truncate_result,
                        )
                    self.assertEqual(ackcmd.get_vars(), ackcmd2.get_vars())

            # Test behavior with too-long result strings
            seqNum = 27
            ack = salobj.SalRetCode.CMD_FAILED
            error = 127
            result = "a" * (salobj.MAX_RESULT_LEN + 5)
            with self.assertRaises(ValueError):
                salinfo.make_ackcmd(
                    private_seqNum=seqNum,
                    ack=ack,
                    error=error,
                    result=result,
                    truncate_result=False,
                )
            ackcmd = salinfo.make_ackcmd(
                private_seqNum=seqNum,
                ack=ack,
                error=error,
                result=result,
                truncate_result=True,
            )
            self.assertEqual(ackcmd.private_seqNum, seqNum)
            self.assertEqual(ackcmd.ack, ack)
            self.assertEqual(ackcmd.error, error)
            self.assertNotEqual(ackcmd.result, result)
            self.assertEqual(ackcmd.result, result[0 : salobj.MAX_RESULT_LEN])


if __name__ == "__main__":
    unittest.main()
