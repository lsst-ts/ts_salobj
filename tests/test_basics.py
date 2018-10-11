import os
import random
import unittest

try:
    import SALPY_Test
except ImportError:
    SALPY_Test = None
import salobj


class SetRandomLsstDdsDomainTestCase(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
