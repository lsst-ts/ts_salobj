import pathlib
import unittest

import yaml
import jsonschema

from lsst.ts import salobj


class ValidatorTestCase(unittest.TestCase):
    def setUp(self):
        schemapath = pathlib.Path(__file__).resolve().parents[1].joinpath("schema", "Test.yaml")
        with open(schemapath, "r") as f:
            rawschema = f.read()
        self.schema = yaml.safe_load(rawschema)
        self.validator = salobj.DefaultingValidator(schema=self.schema)

    def test_no_config_specified(self):
        data_dict = {}
        result = self.validator.validate(data_dict)
        # the defaults are hard-coded in schema/Test.yaml
        expected_result = dict(string0="default value for string0",
                               bool0=True,
                               int0=5,
                               float0=3.14,
                               intarr0=[-1, 1],
                               )
        self.assertEqual(data_dict, {})  # input not changed
        self.assertEqual(result, expected_result)

        result = self.validator.validate(None)
        self.assertEqual(result, expected_result)

    def test_all_fields(self):
        """Test a config with all fields set to a non-default value."""
        data_dict = dict(string0="an arbitrary string",
                         bool0=False,
                         int0=-47,
                         float0=1.234,
                         intarr0=[0, 2, -3, -5, 4],
                         )
        original_data = data_dict.copy()
        result = self.validator.validate(data_dict)
        self.assertEqual(result, original_data)  # input not changed
        # all values were provided so none should be altered
        self.assertEqual(data_dict, original_data)

    def test_some_fields(self):
        """Test a config with some fields set to a non-default value."""
        data_dict = dict(string0="an arbitrary string",
                         bool0=False,
                         int0=-47,
                         float0=1.234,
                         intarr0=[0, 2, -3, -5, 4],
                         )
        original_data = data_dict.copy()
        result = self.validator.validate(data_dict)
        self.assertEqual(result, original_data)  # input not changed
        # all values were provided so none should be altered
        self.assertEqual(data_dict, original_data)

    def test_invalid_data(self):
        good_data = dict(string0="an arbitrary string",
                         bool0=False,
                         int0=-47,
                         float0=1.234,
                         intarr0=[0, 2, -3, -5, 4],
                         )

        bad_data = dict(string0=45,
                        bool0=35,
                        int0=1.234,
                        float0="hello",
                        intarr0=45,
                        )
        # set one field at a time to bad data
        for field in good_data:
            data = good_data.copy()
            data[field] = bad_data[field]
            with self.assertRaises(jsonschema.exceptions.ValidationError):
                self.validator.validate(data)

        # all fields are invalid
        with self.assertRaises(jsonschema.exceptions.ValidationError):
            self.validator.validate(bad_data)

        # extra field
        bad_data = good_data.copy()
        bad_data["unwanted"] = 0
        with self.assertRaises(jsonschema.exceptions.ValidationError):
            self.validator.validate(bad_data)

        # invalid types
        for bad_type_data in (True, False, 1, 1.34, "hello", (1, 2), ["a", "b"]):
            with self.subTest(bad_type_data=bad_type_data):
                with self.assertRaises(jsonschema.exceptions.ValidationError):
                    self.validator.validate(bad_type_data)


if __name__ == "__main__":
    unittest.main()
