import os
import random
import unittest

try:
    import SALPY_Test
except ImportError:
    SALPY_Test = None
import salobj


class SplitComponentNameTestCase(unittest.TestCase):
    def test_split_component_name(self):
        for name, expected in (
            ("foo", ("foo", None)),
            ("foo:0", ("foo", 0)),
            ("foo: 0", ("foo", 0)),
            ("foo:-1", ("foo", -1)),
            ("foo: -1", ("foo", -1)),
            ("foo: 999", ("foo", 999)),
        ):
            with self.subTest(name=name, expected=expected):
                result = salobj.utils.split_component_name(name)
                self.assertEqual(expected, result)

        for bad_name in (
            "foo:"
            "foo:-",
            "foo:bar",
            "foo: bar",
        ):
            with self.subTest(bad_name=bad_name):
                with self.assertRaises(ValueError):
                    salobj.utils.split_component_name(bad_name)


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
