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
import datetime
import getpass
import os
import random
import re
import socket
import unittest

import astropy.time
from astropy.coordinates import Angle
import astropy.units as u
import numpy as np
import pytest

from lsst.ts import utils
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

    def test_astropy_time_from_tai_unix(self) -> None:
        # Check the function at a leap second transition,
        # since that is likely to cause problems
        unix_time0 = datetime.datetime.fromisoformat("2017-01-01").timestamp()
        for dt in (-1, -0.5, -0.1, 0, 0.1, 1):
            with self.subTest(dt=dt):
                utc_unix = unix_time0 + dt
                tai_unix = utils.tai_from_utc(utc_unix)
                with pytest.warns(DeprecationWarning):
                    astropy_time1 = salobj.astropy_time_from_tai_unix(tai_unix)
                astropy_time2 = utils.astropy_time_from_tai_unix(tai_unix)
                assert astropy_time1 == astropy_time2

    async def test_get_opensplice_version(self) -> None:
        ospl_version = salobj.get_opensplice_version()
        assert re.search(r"^\d+\.\d+\.\d+", ospl_version) is not None

    async def test_get_user_host(self) -> None:
        expected_user_host = getpass.getuser() + "@" + socket.getfqdn()
        user_host = salobj.get_user_host()
        assert expected_user_host == user_host

    async def test_long_ack_result(self) -> None:
        async with salobj.Domain() as domain:
            salinfo = salobj.SalInfo(domain, "Test", index=1)
            ack = salobj.SalRetCode.CMD_FAILED
            error = 15
            long_result = (
                "this string is longer than MAX_RESULT_LEN characters "
                "this string is longer than MAX_RESULT_LEN characters "
                "this string is longer than MAX_RESULT_LEN characters "
                "this string is longer than MAX_RESULT_LEN characters "
                "this string is longer than MAX_RESULT_LEN characters "
            )
            assert len(long_result) > salobj.MAX_RESULT_LEN
            with pytest.raises(ValueError):
                salinfo.make_ackcmd(
                    private_seqNum=1,
                    ack=ack,
                    error=error,
                    result=long_result,
                    truncate_result=False,
                )
            ackcmd = salinfo.make_ackcmd(
                private_seqNum=2,
                ack=ack,
                error=error,
                result=long_result,
                truncate_result=True,
            )
            assert ackcmd.result == long_result[0 : salobj.MAX_RESULT_LEN]
            assert ackcmd.ack == ack
            assert ackcmd.error == error

    def test_set_random_lsst_dds_domain(self) -> None:
        """Test that set_random_lsst_dds_domain is a deprecated
        alias for set_random_lsst_dds_partition_prefix.
        """
        old_prefix = os.environ["LSST_DDS_PARTITION_PREFIX"]
        with pytest.warns(
            DeprecationWarning, match="Use set_random_lsst_dds_partition_prefix"
        ):
            salobj.set_random_lsst_dds_domain()
        new_prefix = os.environ["LSST_DDS_PARTITION_PREFIX"]
        assert old_prefix != new_prefix

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

    def test_modify_environ(self) -> None:
        rng = np.random.default_rng(seed=45)
        original_environ = os.environ.copy()
        n_to_delete = 3
        assert len(original_environ) > n_to_delete
        new_key0 = "_a_long_key_name_" + astropy.time.Time.now().isot
        new_key1 = "_another_long_key_name_" + astropy.time.Time.now().isot
        assert new_key0 not in os.environ
        assert new_key1 not in os.environ
        some_keys = rng.choice(list(original_environ.keys()), 3)
        kwargs = {
            some_keys[0]: None,
            some_keys[1]: None,
            some_keys[2]: "foo",
            new_key0: "bar",
            new_key1: None,
        }
        with pytest.warns(DeprecationWarning), salobj.modify_environ(**kwargs):
            for name, value in kwargs.items():
                if value is None:
                    assert name not in os.environ
                else:
                    assert os.environ[name] == value
            for name, value in os.environ.items():
                if name in kwargs:
                    assert value == kwargs[name]
                else:
                    assert value == original_environ[name]
        assert os.environ == original_environ

        # Values that are neither None nor a string should raise RuntimeError
        for bad_value in (3, 1.23, True, False):
            with pytest.raises(RuntimeError):
                bad_kwargs = kwargs.copy()
                bad_kwargs[new_key1] = bad_value  # type: ignore
                with pytest.warns(DeprecationWarning), salobj.modify_environ(
                    **bad_kwargs
                ):
                    pass
            assert os.environ == original_environ

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

    def test_index_generator(self) -> None:
        with pytest.raises(ValueError):
            salobj.index_generator(1, 1)  # imin >= imax
        with pytest.raises(ValueError):
            salobj.index_generator(1, 0)  # imin >= imax
        with pytest.raises(ValueError):
            salobj.index_generator(0, 5, -1)  # i0 < imin
        with pytest.raises(ValueError):
            salobj.index_generator(0, 5, 6)  # i0 > imax

        imin = -2
        imax = 5
        gen = salobj.index_generator(imin=imin, imax=imax)
        expected_values = [-2, -1, 0, 1, 2, 3, 4, 5, -2, -1, 0, 1, 2, 3, 4, 5, -2]
        values = [next(gen) for i in range(len(expected_values))]
        assert values == expected_values

        imin = -2
        imax = 5
        i0 = 5
        expected_values = [5, -2, -1, 0, 1, 2, 3, 4, 5, -2]
        gen = salobj.index_generator(imin=imin, imax=imax, i0=i0)
        values = [next(gen) for i in range(len(expected_values))]
        assert values == expected_values

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

    # TODO DM-31660: Remove this test of deprecated code
    def check_tai_from_utc(self, utc_ap: astropy.time.Time) -> None:
        """Check tai_from_utc at a specific UTC date.

        Parameters
        ----------
        utc_ap : `astropy.time.Time`
            UTC date as an astropy time.
        """
        tai = utils.tai_from_utc_unix(utc_ap.utc.unix)
        with pytest.warns(DeprecationWarning):
            tai0 = salobj.tai_from_utc_unix(utc_ap.utc.unix)
        assert tai == tai0

        with pytest.warns(DeprecationWarning):
            tai1 = salobj.tai_from_utc(utc_ap.utc.unix)
        assert tai == pytest.approx(tai1, abs=1e-6)

        with pytest.warns(DeprecationWarning):
            tai2 = salobj.tai_from_utc(utc_ap.utc.iso, format="iso")
        assert tai == pytest.approx(tai2, abs=1e-6)

        with pytest.warns(DeprecationWarning):
            tai3 = salobj.tai_from_utc(utc_ap.utc.iso, format=None)
        assert tai == pytest.approx(tai3, abs=1e-6)

        with pytest.warns(DeprecationWarning):
            tai4 = salobj.tai_from_utc(utc_ap.utc.mjd, format="mjd")
        assert tai == pytest.approx(tai4, abs=1e-6)

        tai_mjd = (tai + salobj.MJD_MINUS_UNIX_SECONDS) / salobj.SECONDS_PER_DAY
        tai_mjd_ap = astropy.time.Time(tai_mjd, scale="tai", format="mjd")
        with pytest.warns(DeprecationWarning):
            tai5 = salobj.tai_from_utc(tai_mjd_ap)
        assert tai == pytest.approx(tai5, abs=1e-6)

        tai_iso_ap = astropy.time.Time(utc_ap.tai.iso, scale="tai", format="iso")
        with pytest.warns(DeprecationWarning):
            tai6 = salobj.tai_from_utc(tai_iso_ap)
        assert tai == pytest.approx(tai6, abs=1e-6)

        with pytest.warns(DeprecationWarning):
            tai7 = salobj.tai_from_utc(utc_ap)
        assert tai == pytest.approx(tai7, abs=1e-6)

    # TODO DM-31660: Remove this test of deprecated code
    def test_tai_from_utc(self) -> None:
        """Test tai_from_utc."""
        # Check tai_from_utc near leap second transition at UTC = 2017-01-01
        # when leap seconds went from 36 to 37.
        utc0_ap = astropy.time.Time("2017-01-01", scale="utc", format="iso")
        for utc_ap in (
            (utc0_ap - 0.5 * u.day),
            (utc0_ap - 1 * u.second),
            (utc0_ap - 0.1 * u.second),
            (utc0_ap),
            (utc0_ap + 0.1 * u.second),
            (utc0_ap + 1 * u.second),
        ):
            with self.subTest(utc_ap=utc_ap):
                tai1 = utils.tai_from_utc(utc_ap)
                with pytest.warns(DeprecationWarning):
                    tai2 = salobj.tai_from_utc(utc_ap)
                assert tai1 == tai2

    # TODO DM-31660: Remove this test of deprecated code
    def test_utc_from_tai_unix(self) -> None:
        # Check utc_from_tai_unix near leap second transition at
        # UTC = 2017-01-01 when leap seconds went from 36 to 37.
        utc0 = astropy.time.Time("2017-01-01", scale="utc", format="iso").unix
        tai_minus_utc_after = 37
        tai0 = utc0 + tai_minus_utc_after
        # Don't test right at tai0 because roundoff error could cause failure;
        # utc_from_tai_unix is discontinuous at a leap second tranition.
        for tai in (
            tai0 - 0.5 * utils.SECONDS_PER_DAY,
            tai0 - 1,
            tai0 - 0.001,
            tai0 + 0.001,
            tai0 + 1,
            tai0 + 0.5 * utils.SECONDS_PER_DAY,
        ):
            with pytest.warns(DeprecationWarning):
                utc1 = salobj.utc_from_tai_unix(tai)
            utc2 = utils.utc_from_tai_unix(tai)
            assert utc1 == utc2

    # TODO DM-31660: Remove this test of deprecated code
    def test_current_tai(self) -> None:
        with pytest.warns(DeprecationWarning):
            tai0 = salobj.current_tai()
        tai1 = utils.current_tai()
        # Leave plenty of slop because time has jitter on macOS Docker.
        assert tai0 == pytest.approx(tai1, abs=0.2)

    # TODO DM-31660: Remove this test of deprecated code
    def test_angle_diff(self) -> None:
        for angle1, angle2 in (
            (5.15, 0),
            (5.21, 359.20),
            (270, -90),
        ):
            for swap in (False, True):
                if swap:
                    angle1, angle2 = angle2, angle1
                with self.subTest(angle1=angle1, angle2=angle2):
                    diff1 = utils.angle_diff(angle1, angle2)
                    with pytest.warns(DeprecationWarning):
                        diff2 = salobj.angle_diff(angle1, angle2)
                    assert diff1 == diff2

    # TODO DM-31660: Remove this test of deprecated code
    def test_angle_wrap_center(self) -> None:
        for base_angle in (-180, -180, 0, 179, 180):
            for nwraps in (-2, -1, 0, 1, 2):
                with self.subTest(base_angle=base_angle, nwraps=nwraps):
                    angle = base_angle + 360 * nwraps
                    with pytest.warns(DeprecationWarning):
                        wrapped1 = salobj.angle_wrap_center(angle)
                    wrapped2 = utils.angle_wrap_center(angle)
                    assert wrapped1 == wrapped2

    # TODO DM-31660: Remove this test of deprecated code
    def test_angle_wrap_nonnegative(self) -> None:
        for base_angle in (-0, 0, 180, 359, 360):
            for nwraps in (-2, -1, 0, 1, 2):
                with self.subTest(base_angle=base_angle, nwraps=nwraps):
                    angle = base_angle + 360 * nwraps
                    with pytest.warns(DeprecationWarning):
                        wrapped1 = salobj.angle_wrap_nonnegative(angle)
                    wrapped2 = utils.angle_wrap_nonnegative(angle)
                    assert wrapped1 == wrapped2

    # TODO DM-31660: Remove this test of deprecated code
    def test_make_done_future(self) -> None:
        with pytest.warns(DeprecationWarning):
            done_future = salobj.make_done_future()
            assert isinstance(done_future, asyncio.Future)
            assert done_future.done()
            assert done_future.result() is None
            assert not done_future.cancelled()
            assert done_future.exception() is None

    # TODO DM-31660: Remove this test of deprecated code
    def test_assertAnglesAlmostEqual(self) -> None:
        for angle1, angle2 in ((5.15, 5.14), (-0.20, 359.81), (270, -90.1)):
            epsilon = Angle(1e-15, u.deg)
            with self.subTest(angle1=angle1, angle2=angle2):
                diff = abs(utils.angle_diff(angle1, angle2))
                bad_diff = diff - epsilon
                assert bad_diff.deg > 0

                for arg1, arg2 in (
                    (angle1, angle2),
                    (angle2, angle1),
                    (Angle(angle1, u.deg), angle2),
                    (Angle(angle1, u.deg), Angle(angle2, u.deg)),
                ):
                    with self.subTest(arg1=arg1, arg2=arg2):
                        # Test too-large differences
                        with pytest.raises(AssertionError):
                            utils.assert_angles_almost_equal(
                                angle1=arg1, angle2=arg2, max_diff=bad_diff
                            )
                        with pytest.raises(AssertionError), pytest.warns(
                            DeprecationWarning
                        ):
                            salobj.assertAnglesAlmostEqual(
                                arg1, arg2, max_diff=bad_diff
                            )
                        with pytest.raises(AssertionError), pytest.warns(
                            DeprecationWarning
                        ):
                            salobj.assertAnglesAlmostEqual(
                                arg1, arg2, max_diff=bad_diff.deg
                            )

                        # Test acceptable differences
                        good_diff = diff + epsilon
                        utils.assert_angles_almost_equal(
                            angle1=arg1, angle2=arg2, max_diff=good_diff
                        )
                        with pytest.warns(DeprecationWarning):
                            salobj.assertAnglesAlmostEqual(
                                arg1, arg2, max_diff=good_diff
                            )
                        with pytest.warns(DeprecationWarning):
                            salobj.assertAnglesAlmostEqual(
                                arg1, arg2, max_diff=good_diff.deg
                            )
