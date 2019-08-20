import asyncio
import os
import random
import unittest

from lsst.ts import salobj


class BasicsTestCase(unittest.TestCase):
    def setUp(self):
        salobj.set_random_lsst_dds_domain()

    def test_assert_ack_error(self):
        async def doit():
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

                with salobj.assertRaisesAckError(ack=1, error=2):
                    raise salobj.AckError("matching ack and error",
                                          ackcmd=salinfo.makeAckCmd(private_seqNum=4, ack=1, error=2))

        asyncio.get_event_loop().run_until_complete(doit())

    def test_ack_error_repr(self):
        """Test AckError.__str__ and AckError.__repr__"""
        async def doit():
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

        asyncio.get_event_loop().run_until_complete(doit())

    def test_long_ack_result(self):
        async def doit():
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

        asyncio.get_event_loop().run_until_complete(doit())

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

    def test_lsst_dds_domain_required(self):
        del os.environ["LSST_DDS_DOMAIN"]

        async def doit():
            async with salobj.Domain() as domain:
                with self.assertRaises(RuntimeError):
                    salobj.SalInfo(domain=domain, name="Test", index=1)

        asyncio.get_event_loop().run_until_complete(doit())

    def test_domain_host_origin(self):
        async def doit():
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

        asyncio.get_event_loop().run_until_complete(doit())

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

    def test_salinfo_constructor(self):
        async def doit():
            with self.assertRaises(TypeError):
                salobj.SalInfo(domain=None, name="Test")

            async with salobj.Domain() as domain:
                with self.assertRaises(RuntimeError):
                    salobj.SalInfo(domain=domain, name="invalid_component_name")

                salinfo = salobj.SalInfo(domain=domain, name="Test")
                self.assertEqual(salinfo.name, "Test")

        asyncio.get_event_loop().run_until_complete(doit())

    def test_salinfo_attributes(self):
        async def doit():
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

        asyncio.get_event_loop().run_until_complete(doit())


if __name__ == "__main__":
    unittest.main()
