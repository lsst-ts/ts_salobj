# This file is part of ts_salobj.
#
# Developed for the LSST Telescope and Site Systems.
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

import unittest

import asynctest

from lsst.ts import salobj


class SalInfoTestCase(asynctest.TestCase):
    def setUp(self):
        salobj.set_random_lsst_dds_domain()

    async def test_salinfo_constructor(self):
        with self.assertRaises(TypeError):
            salobj.SalInfo(domain=None, name="Test")

        async with salobj.Domain() as domain:
            with self.assertRaises(RuntimeError):
                salobj.SalInfo(domain=domain, name="invalid_component_name")

            salinfo = salobj.SalInfo(domain=domain, name="Test")
            self.assertEqual(salinfo.name, "Test")

    async def test_salinfo_attributes(self):
        async with salobj.Domain() as domain:
            salinfo = salobj.SalInfo(domain=domain, name="Test")

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

    async def test_salinfo_metadata(self):
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

    async def test_make_ack_cmd(self):
        async with salobj.Domain() as domain:
            salinfo = salobj.SalInfo(domain=domain, name="Test")

            # Use all defaults
            seqNum = 55
            ack = salobj.SalRetCode.CMD_COMPLETE
            ackcmd = salinfo.makeAckCmd(private_seqNum=seqNum, ack=ack)
            self.assertEqual(ackcmd.private_seqNum, seqNum)
            self.assertEqual(ackcmd.ack, ack)
            self.assertEqual(ackcmd.error, 0)
            self.assertEqual(ackcmd.result, "")

            # Specify an error code and result
            for truncate_result in (False, True):
                with self.subTest(truncate_result=truncate_result):
                    seqNum = 27
                    ack = salobj.SalRetCode.CMD_FAILED
                    error = 127
                    result = "why not?"
                    ackcmd = salinfo.makeAckCmd(
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

            # Test behavior with too-long result strings
            seqNum = 27
            ack = salobj.SalRetCode.CMD_FAILED
            error = 127
            result = "a" * (salobj.MAX_RESULT_LEN + 5)
            with self.assertRaises(ValueError):
                salinfo.makeAckCmd(
                    private_seqNum=seqNum,
                    ack=ack,
                    error=error,
                    result=result,
                    truncate_result=False,
                )
            ackcmd = salinfo.makeAckCmd(
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

    async def test_no_commands(self):
        """Test a SAL component with no commands.
        """
        async with salobj.Domain() as domain:
            salinfo = salobj.SalInfo(domain=domain, name="LOVE")
            self.assertEqual(salinfo.command_names, ())
            with self.assertRaises(RuntimeError):
                salinfo.AckCmdType
            with self.assertRaises(RuntimeError):
                salinfo.makeAckCmd(
                    private_seqNum=1, ack=salobj.SalRetCode.CMD_COMPLETE, result="Done"
                )


if __name__ == "__main__":
    unittest.main()
