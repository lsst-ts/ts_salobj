import os
import random
import time
import unittest

import asynctest

import astropy.time
from astropy.coordinates import Angle
import astropy.units as u

from lsst.ts import salobj


class BasicsTestCase(asynctest.TestCase):
    def setUp(self):
        salobj.set_random_lsst_dds_domain()

    async def test_assert_raises_ack_error(self):
        """Test the assertRaisesAckError function.
        """
        async with salobj.Domain() as domain:
            salinfo = salobj.SalInfo(domain, "Test", index=1)
            private_seqNum = 5
            ack = 23
            error = -6
            result = "a result"
            err = salobj.AckError("a message",
                                  ackcmd=salinfo.makeAckCmd(private_seqNum=private_seqNum, ack=ack,
                                                            error=error, result=result))
            self.assertEqual(err.ackcmd.private_seqNum, private_seqNum)
            self.assertEqual(err.ackcmd.ack, ack)
            self.assertEqual(err.ackcmd.error, error)
            self.assertEqual(err.ackcmd.result, result)

            for ExceptionClass in (Exception, TypeError, KeyError, RuntimeError, AssertionError):
                with self.assertRaises(ExceptionClass):
                    with salobj.assertRaisesAckError():
                        raise ExceptionClass("assertRaisesAckError should ignore other exception types")

            with self.assertRaises(AssertionError):
                with salobj.assertRaisesAckError(ack=5):
                    raise salobj.AckError("mismatched ack",
                                          ackcmd=salinfo.makeAckCmd(private_seqNum=1, ack=1))

            with self.assertRaises(AssertionError):
                with salobj.assertRaisesAckError(error=47):
                    raise salobj.AckError("mismatched error",
                                          ackcmd=salinfo.makeAckCmd(private_seqNum=2, ack=25, error=2))

            with salobj.assertRaisesAckError():
                raise salobj.AckError("no ack or error specified",
                                      ackcmd=salinfo.makeAckCmd(private_seqNum=3, ack=1, error=2))

            result = "result for this exception"
            # test result_contains with the full result string
            with salobj.assertRaisesAckError(ack=1, error=2, result_contains=result):
                raise salobj.AckError("match ack, error and full result",
                                      ackcmd=salinfo.makeAckCmd(private_seqNum=4, ack=1, error=2,
                                                                result=result))
            # test result_contains with a substring of the result string
            with salobj.assertRaisesAckError(ack=1, error=2, result_contains=result[2:-2]):
                raise salobj.AckError("match ack, error and a substring of result",
                                      ackcmd=salinfo.makeAckCmd(private_seqNum=4, ack=1, error=2,
                                                                result=result))

    async def test_ack_error_repr(self):
        """Test AckError.__str__ and AckError.__repr__"""
        async with salobj.Domain() as domain:
            salinfo = salobj.SalInfo(domain, "Test", index=1)
            msg = "a message"
            private_seqNum = 5
            ack = 23
            error = -6
            result = "a result"
            err = salobj.AckError(msg, ackcmd=salinfo.makeAckCmd(private_seqNum=private_seqNum,
                                                                 ack=ack, error=error, result=result))
            str_err = str(err)
            for item in (msg, private_seqNum, ack, error, result):
                self.assertIn(str(item), str_err)
            self.assertNotIn("AckError", str_err)
            repr_err = repr(err)
            for item in ("AckError", msg, private_seqNum, ack, error, result):
                self.assertIn(str(item), repr_err)

    async def test_long_ack_result(self):
        async with salobj.Domain() as domain:
            salinfo = salobj.SalInfo(domain, "Test", index=1)
            ack = salobj.SalRetCode.CMD_FAILED
            error = 15
            long_result = "this string is longer than MAX_RESULT_LEN characters " \
                "this string is longer than MAX_RESULT_LEN characters " \
                "this string is longer than MAX_RESULT_LEN characters " \
                "this string is longer than MAX_RESULT_LEN characters " \
                "this string is longer than MAX_RESULT_LEN characters "
            self.assertGreater(len(long_result), salobj.MAX_RESULT_LEN)
            with self.assertRaises(ValueError):
                salinfo.makeAckCmd(private_seqNum=1,
                                   ack=ack, error=error, result=long_result, truncate_result=False)
            ackcmd = salinfo.makeAckCmd(private_seqNum=2,
                                        ack=ack, error=error, result=long_result, truncate_result=True)
            self.assertEqual(ackcmd.result, long_result[0:salobj.MAX_RESULT_LEN])
            self.assertEqual(ackcmd.ack, ack)
            self.assertEqual(ackcmd.error, error)

    def test_set_random_lsst_dds_domain(self):
        random.seed(42)
        NumToTest = 1000
        names = set()
        for i in range(NumToTest):
            salobj.set_random_lsst_dds_domain()
            name = os.environ.get("LSST_DDS_DOMAIN")
            self.assertTrue(name)
            names.add(name)
        # any duplicate names will reduce the size of names
        self.assertEqual(len(names), NumToTest)

    async def test_lsst_dds_domain_required(self):
        del os.environ["LSST_DDS_DOMAIN"]

        async with salobj.Domain() as domain:
            with self.assertRaises(RuntimeError):
                salobj.SalInfo(domain=domain, name="Test", index=1)

    async def test_domain_host_origin(self):
        for bad_ip in ("57", "192.168", "192.168.0", "www.lsst.org"):
            os.environ["LSST_DDS_IP"] = bad_ip
            with self.assertRaises(ValueError):
                salobj.Domain()

        # a value from the ipaddress documentation
        os.environ["LSST_DDS_IP"] = "192.168.0.1"
        async with salobj.Domain() as domain:
            self.assertEqual(domain.host, 3232235521)
            self.assertEqual(domain.origin, os.getpid())

        del os.environ["LSST_DDS_IP"]
        async with salobj.Domain() as domain:
            self.assertGreater(domain.host, 0)

    def test_index_generator(self):
        with self.assertRaises(ValueError):
            salobj.index_generator(1, 1)  # imin >= imax
        with self.assertRaises(ValueError):
            salobj.index_generator(1, 0)  # imin >= imax
        with self.assertRaises(ValueError):
            salobj.index_generator(0, 5, -1)  # i0 < imin
        with self.assertRaises(ValueError):
            salobj.index_generator(0, 5, 6)  # i0 > imax

        imin = -2
        imax = 5
        gen = salobj.index_generator(imin=imin, imax=imax)
        expected_values = [-2, -1, 0, 1, 2, 3, 4, 5, -2, -1, 0, 1, 2, 3, 4, 5, -2]
        values = [next(gen) for i in range(len(expected_values))]
        self.assertEqual(values, expected_values)

        imin = -2
        imax = 5
        i0 = 5
        expected_values = [5, -2, -1, 0, 1, 2, 3, 4, 5, -2]
        gen = salobj.index_generator(imin=imin, imax=imax, i0=i0)
        values = [next(gen) for i in range(len(expected_values))]
        self.assertEqual(values, expected_values)

    def test_name_to_name_index(self):
        for name, expected_result in (
            ("Script", ("Script", 0)),
            ("Script:0", ("Script", 0)),
            ("Script:15", ("Script", 15)),
        ):
            with self.subTest(name=name):
                result = salobj.name_to_name_index(name)
                self.assertEqual(result, expected_result)

        for bad_name in (
            (" Script:15"),  # leading space
            ("Script:15 "),  # trailing space
            ("Script:"),   # colon with no index
            ("Script:zero"),  # index is not an integer
        ):
            with self.subTest(bad_name=bad_name):
                with self.assertRaises(ValueError):
                    salobj.name_to_name_index(bad_name)

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
            expected_commands = ["disable", "enable", "exitControl", "standby", "start",
                                 "setArrays", "setLogLevel", "setScalars", "setSimulationMode",
                                 "fault", "wait"]
            self.assertTrue(set(expected_commands).issubset(set(salinfo.command_names)))

            # expected_events omits a few events that TestCsc
            # does not support, but that are in generics.
            expected_events = ["errorCode", "heartbeat", "logLevel", "logMessage", "settingVersions",
                               "simulationMode", "summaryState",
                               "scalars", "arrays"]
            self.assertTrue(set(expected_events).issubset(set(salinfo.event_names)))

            # telemetry topic names should match; there are no generics
            expected_telemetry = ["arrays", "scalars"]
            self.assertEqual(set(expected_telemetry), set(salinfo.telemetry_names))

            expected_sal_topic_names = ["ackcmd"]
            expected_sal_topic_names += [f"command_{name}" for name in salinfo.command_names]
            expected_sal_topic_names += [f"logevent_{name}" for name in salinfo.event_names]
            expected_sal_topic_names += [name for name in salinfo.telemetry_names]
            self.assertEqual(sorted(expected_sal_topic_names), list(salinfo.sal_topic_names))

    def check_tai_from_utc(self, utc_ap, desired_tai_minus_utc):
        """Check tai_from_utc at a specific UTC date.

        Parameters
        ----------
        utc_ap : `astropy.time.Time`
            UTC date as an astropy time.
        desired_tai_minus_utc : `float`
            Desired TAI-UTC in seconds.
        """
        utc = utc_ap.utc.unix
        tai = salobj.tai_from_utc(utc)
        self.assertAlmostEqual(tai - utc, desired_tai_minus_utc)

        tai2 = salobj.tai_from_utc(utc_ap.utc.iso, format="iso")
        self.assertAlmostEqual(tai, tai2)

        tai3 = salobj.tai_from_utc(utc_ap.utc.iso, format=None)
        self.assertAlmostEqual(tai, tai3)

        tai4 = salobj.tai_from_utc(utc_ap.utc.mjd, format="mjd")
        self.assertAlmostEqual(tai, tai4, places=5)

    def test_tai_from_utc(self):
        """Test tai_from_utc.
        """
        # check tai_from_utc at leap second transition 2017-01-01
        # when leap seconds went from 36 to 37
        utc0_ap = astropy.time.Time("2017-01-01", scale="utc", format="iso")
        for desired_tai_minus_utc, utc_ap in (
            (36, utc0_ap - 1 * u.second),
            (36, utc0_ap - 0.1 * u.second),
            (37, utc0_ap),
            (37, utc0_ap + 0.1 * u.second),
            (37, utc0_ap + 1 * u.second),
        ):
            with self.subTest(utc_ap=utc_ap, desired_tai_minus_utc=desired_tai_minus_utc):
                self.check_tai_from_utc(utc_ap=utc_ap, desired_tai_minus_utc=desired_tai_minus_utc)

    def test_current_tai(self):
        utc0 = time.time()
        tai0 = salobj.tai_from_utc(utc0)
        tai1 = salobj.current_tai()
        print(f"tai1-tai0={tai1-tai0:0.4f}")
        # the difference should be much less than 0.1
        # but pytest can introduce unexpected delays
        self.assertLess(abs(tai1 - tai0), 0.1)
        self.assertGreaterEqual(tai1, tai0)

    def test_angle_diff(self):
        for angle1, angle2, expected_diff in (
            (5.15, 0, 5.15),
            (5.21, 359.20, 6.01),
            (270, -90, 0),
        ):
            with self.subTest(angle1=angle1, angle2=angle2, expected_diff=expected_diff):
                diff = salobj.angle_diff(angle1, angle2)
                self.assertAlmostEqual(diff.deg, expected_diff)
                diff = salobj.angle_diff(angle2, angle1)
                self.assertAlmostEqual(diff.deg, -expected_diff)
                diff = salobj.angle_diff(Angle(angle1, u.deg), angle2)
                self.assertAlmostEqual(diff.deg, expected_diff)
                diff = salobj.angle_diff(angle1, Angle(angle2, u.deg))
                self.assertAlmostEqual(diff.deg, expected_diff)
                diff = salobj.angle_diff(Angle(angle1, u.deg), Angle(angle2, u.deg))
                self.assertAlmostEqual(diff.deg, expected_diff)

    def test_assertAnglesAlmostEqual(self):
        for angle1, angle2 in (
            (5.15, 5.14),
            (-0.20, 359.81),
            (270, -90.1),
        ):
            epsilon = Angle(1e-15, u.deg)
            with self.subTest(angle1=angle1, angle2=angle2):
                diff = abs(salobj.angle_diff(angle1, angle2))
                bad_diff = diff - epsilon
                self.assertGreater(bad_diff.deg, 0)
                with self.assertRaises(AssertionError):
                    salobj.assertAnglesAlmostEqual(angle1, angle2, bad_diff)
                with self.assertRaises(AssertionError):
                    salobj.assertAnglesAlmostEqual(angle1, angle2, bad_diff.deg)
                with self.assertRaises(AssertionError):
                    salobj.assertAnglesAlmostEqual(angle2, angle1, bad_diff)
                with self.assertRaises(AssertionError):
                    salobj.assertAnglesAlmostEqual(Angle(angle1, u.deg), angle2, bad_diff)
                with self.assertRaises(AssertionError):
                    salobj.assertAnglesAlmostEqual(angle1, Angle(angle2, u.deg), bad_diff)
                with self.assertRaises(AssertionError):
                    salobj.assertAnglesAlmostEqual(Angle(angle1, u.deg), Angle(angle2, u.deg), bad_diff)

                good_diff = diff + epsilon
                salobj.assertAnglesAlmostEqual(angle1, angle2, good_diff)
                salobj.assertAnglesAlmostEqual(angle1, angle2, good_diff.deg)
                salobj.assertAnglesAlmostEqual(angle2, angle1, good_diff)
                salobj.assertAnglesAlmostEqual(Angle(angle1, u.deg), angle2, good_diff)
                salobj.assertAnglesAlmostEqual(angle1, Angle(angle2, u.deg), good_diff)
                salobj.assertAnglesAlmostEqual(Angle(angle1, u.deg), Angle(angle2, u.deg), good_diff)


if __name__ == "__main__":
    unittest.main()
