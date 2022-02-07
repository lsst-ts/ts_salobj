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

import getpass
import os
import random
import re
import socket
import unittest

import pytest

from lsst.ts import salobj


class BasicsTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        salobj.set_random_lsst_dds_partition_prefix()

    async def test_assert_raises_ack_error(self) -> None:
        """Test the assertRaisesAckError function."""
        async with salobj.Domain() as domain:
            salinfo = salobj.SalInfo(domain, "Test", index=1)
            private_seqNum = 5
            ack = 23
            error = -6
            result = "a result"
            err = salobj.AckError(
                "a message",
                ackcmd=salinfo.make_ackcmd(
                    private_seqNum=private_seqNum, ack=ack, error=error, result=result
                ),
            )
            assert err.ackcmd.private_seqNum == private_seqNum
            assert err.ackcmd.ack == ack
            assert err.ackcmd.error == error
            assert err.ackcmd.result == result

            for ExceptionClass in (
                Exception,
                TypeError,
                KeyError,
                RuntimeError,
                AssertionError,
            ):
                with pytest.raises(ExceptionClass):
                    with salobj.assertRaisesAckError():
                        raise ExceptionClass(
                            "assertRaisesAckError should ignore other exception types"
                        )

            with pytest.raises(AssertionError):
                with salobj.assertRaisesAckError(ack=5):
                    raise salobj.AckError(
                        "mismatched ack",
                        ackcmd=salinfo.make_ackcmd(private_seqNum=1, ack=1),
                    )

            with pytest.raises(AssertionError):
                with salobj.assertRaisesAckError(error=47):
                    raise salobj.AckError(
                        "mismatched error",
                        ackcmd=salinfo.make_ackcmd(private_seqNum=2, ack=25, error=2),
                    )

            with salobj.assertRaisesAckError():
                raise salobj.AckError(
                    "no ack or error specified",
                    ackcmd=salinfo.make_ackcmd(private_seqNum=3, ack=1, error=2),
                )

            result = "result for this exception"
            # test result_contains with the full result string
            with salobj.assertRaisesAckError(ack=1, error=2, result_contains=result):
                raise salobj.AckError(
                    "match ack, error and full result",
                    ackcmd=salinfo.make_ackcmd(
                        private_seqNum=4, ack=1, error=2, result=result
                    ),
                )
            # test result_contains with a substring of the result string
            with salobj.assertRaisesAckError(
                ack=1, error=2, result_contains=result[2:-2]
            ):
                raise salobj.AckError(
                    "match ack, error and a substring of result",
                    ackcmd=salinfo.make_ackcmd(
                        private_seqNum=4, ack=1, error=2, result=result
                    ),
                )

    async def test_ack_error_repr(self) -> None:
        """Test AckError.__str__ and AckError.__repr__"""
        async with salobj.Domain() as domain:
            salinfo = salobj.SalInfo(domain, "Test", index=1)
            msg = "a message"
            private_seqNum = 5
            ack = 23
            error = -6
            result = "a result"
            err = salobj.AckError(
                msg,
                ackcmd=salinfo.make_ackcmd(
                    private_seqNum=private_seqNum, ack=ack, error=error, result=result
                ),
            )
            str_err = str(err)
            for item in (msg, private_seqNum, ack, error, result):
                assert str(item) in str_err
            assert "AckError" not in str_err
            repr_err = repr(err)
            for item in ("AckError", msg, private_seqNum, ack, error, result):
                assert str(item) in repr_err

    async def test_get_opensplice_version(self) -> None:
        ospl_version = salobj.get_opensplice_version()
        assert re.search(r"^\d+\.\d+\.\d+", ospl_version) is not None

    async def test_get_user_host(self) -> None:
        expected_user_host = getpass.getuser() + "@" + socket.getfqdn()
        user_host = salobj.get_user_host()
        assert expected_user_host == user_host

    def test_set_random_lsst_dds_partition_prefix(self) -> None:
        random.seed(42)
        NumToTest = 1000
        names = set()
        for i in range(NumToTest):
            salobj.set_random_lsst_dds_partition_prefix()
            name = os.environ.get("LSST_DDS_PARTITION_PREFIX")
            assert name
            names.add(name)
            assert "." not in name  # type: ignore
        # any duplicate names will reduce the size of names
        assert len(names) == NumToTest

    async def test_domain_attr(self) -> None:
        async with salobj.Domain() as domain:
            assert domain.origin == os.getpid()

            assert domain.user_host == salobj.get_user_host()
            assert domain.default_identity == domain.user_host
            assert domain.ackcmd_qos_set.profile_name == "AckcmdProfile"
            assert domain.command_qos_set.profile_name == "CommandProfile"
            assert domain.event_qos_set.profile_name == "EventProfile"
            assert domain.telemetry_qos_set.profile_name == "TelemetryProfile"
            assert domain.ackcmd_qos_set.volatile
            assert domain.command_qos_set.volatile
            assert not domain.event_qos_set.volatile
            assert domain.telemetry_qos_set.volatile

    def test_name_to_name_index(self) -> None:
        for name, expected_result in (
            ("Script", ("Script", 0)),
            ("Script:0", ("Script", 0)),
            ("Script:15", ("Script", 15)),
            ("MTM1M3", ("MTM1M3", 0)),
            ("MTM1M3:47", ("MTM1M3", 47)),
        ):
            with self.subTest(name=name):
                result = salobj.name_to_name_index(name)
                assert result == expected_result

        for bad_name in (
            (" Script:15"),  # leading space
            ("Script:15 "),  # trailing space
            ("Script:"),  # colon with no index
            ("Script:zero"),  # index is not an integer
        ):
            with self.subTest(bad_name=bad_name):
                with pytest.raises(ValueError):
                    salobj.name_to_name_index(bad_name)
