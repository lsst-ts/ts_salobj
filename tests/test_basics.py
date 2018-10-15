import os
import random
import unittest

try:
    import SALPY_Test
except ImportError:
    SALPY_Test = None
import salobj


class BasicsTestCase(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
