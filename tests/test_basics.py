import os
import random
import unittest

try:
    import SALPY_Test
except ImportError:
    SALPY_Test = None
import salobj


class BasicsTestCase(unittest.TestCase):
    def test_assert_ack_error(self):

        def makeAck(ack, error=0, result=""):
            """Make an AckType object from keyword arguments.
            """
            data = SALPY_Test.Test_ackcmdC()
            data.ack = ack
            data.error = error
            data.result = result
            return data

        ackError = salobj.AckError("a message", cmd_id=5, ack=makeAck(ack=23, error=-6, result="a result"))
        self.assertEqual(ackError.cmd_id, 5)
        self.assertEqual(ackError.ack.ack, 23)
        self.assertEqual(ackError.ack.error, -6)
        self.assertEqual(ackError.ack.result, "a result")

        for ExceptionClass in (Exception, TypeError, KeyError, RuntimeError, AssertionError):
            with self.assertRaises(ExceptionClass):
                with salobj.test_utils.assertRaisesAckError():
                    raise ExceptionClass("assertRaisesAckError should ignore other exception types")

        with self.assertRaises(AssertionError):
            with salobj.test_utils.assertRaisesAckError(ack=5):
                raise salobj.AckError("mismatched ack", cmd_id=1, ack=makeAck(ack=1))

        with self.assertRaises(AssertionError):
            with salobj.test_utils.assertRaisesAckError(error=47):
                raise salobj.AckError("mismatched error", cmd_id=2, ack=makeAck(ack=25, error=2))

        with salobj.test_utils.assertRaisesAckError():
            raise salobj.AckError("no ack or error specified", cmd_id=3, ack=makeAck(ack=1, error=2))

        with salobj.test_utils.assertRaisesAckError(ack=1, error=2):
            raise salobj.AckError("matching ack and error", cmd_id=4, ack=makeAck(ack=1, error=2))

    def test_set_random_lsst_dds_domain(self):
        random.seed(42)
        NumToTest = 1000
        names = set()
        for i in range(NumToTest):
            salobj.test_utils.set_random_lsst_dds_domain()
            name = os.environ.get("LSST_DDS_DOMAIN")
            self.assertTrue(name)
            names.add(name)
        # any duplicate names will reduce the size of names
        self.assertEqual(len(names), NumToTest)

    def test_index_generator(self):
        with self.assertRaises(ValueError):
            salobj.index_generator(0, 0)
        with self.assertRaises(ValueError):
            salobj.index_generator(5, 4)

        imin = -2
        imax = 5
        nvalues = 14
        gen = salobj.index_generator(imin=imin, imax=imax)
        values = [next(gen) for i in range(nvalues)]
        expected_values = (list(range(imin, imax+1))*2)[0:nvalues]
        self.assertEqual(values, expected_values)

    def test_salinfo_constructor(self):
        with self.assertRaises(RuntimeError):
            salobj.SalInfo(SALPY_Test, index=None)

        with self.assertRaises(AttributeError):
            salobj.SalInfo(None)


if __name__ == "__main__":
    unittest.main()
