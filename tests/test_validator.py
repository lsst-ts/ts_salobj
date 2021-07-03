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

import pathlib
import unittest
import typing

import yaml
import jsonschema

from lsst.ts import salobj


class ValidatorTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.validator = salobj.DefaultingValidator(schema=salobj.CONFIG_SCHEMA)

    def test_no_config_specified(self) -> None:
        data_dict: typing.Dict[str, typing.Any] = {}
        result = self.validator.validate(data_dict)
        # the defaults are hard-coded in schema/Test.yaml
        expected_result = dict(
            string0="default value for string0",
            bool0=True,
            int0=5,
            float0=3.14,
            intarr0=[-1, 1],
            multi_type=None,
        )
        self.assertEqual(data_dict, {})  # input not changed
        self.assertEqual(result, expected_result)

        result = self.validator.validate(None)
        self.assertEqual(result, expected_result)

    def test_all_fields(self) -> None:
        """Test a config with all fields set to a non-default value."""
        data_dict: typing.Dict[str, typing.Any] = dict(
            string0="an arbitrary string",
            bool0=False,
            int0=-47,
            float0=1.234,
            intarr0=[0, 2, -3, -5, 4],
            multi_type="another string",
        )
        original_data = data_dict.copy()
        result = self.validator.validate(data_dict)
        self.assertEqual(result, original_data)  # input not changed
        # all values were provided so none should be altered
        self.assertEqual(data_dict, original_data)

    def test_some_fields(self) -> None:
        """Test a config with some fields set to a non-default value."""
        default_values = dict(
            string0="default value for string0",
            bool0=True,
            int0=5,
            float0=3.14,
            intarr0=[-1, 1],
            multi_type=None,
        )
        non_default_values = dict(
            string0="an arbitrary string",
            bool0=False,
            int0=-47,
            float0=1.234,
            intarr0=[0, 2, -3, -5, 4],
            multi_type=5,
        )
        for name, value in non_default_values.items():
            expected_values = default_values.copy()
            expected_values[name] = value
            one_item_data_dict: typing.Dict[str, typing.Any] = {name: value}
        result = self.validator.validate(one_item_data_dict)
        self.assertEqual(result, expected_values)

    def test_invalid_data(self) -> None:
        good_data = dict(
            string0="an arbitrary string",
            bool0=False,
            int0=-47,
            float0=1.234,
            intarr0=[0, 2, -3, -5, 4],
            multi_type=5,
        )
        bad_data = dict(
            string0=45, bool0=35, int0=1.234, float0="hello", intarr0=45, multi_type=3.5
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


class DefaultingTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.schemadir = pathlib.Path(__file__).resolve().parents[0] / "data"

    def test_contained_object(self) -> None:
        schemapath = self.schemadir / "contained_object_schema.yaml"
        with open(schemapath, "r") as f:
            rawschema = f.read()
        self.schema = yaml.safe_load(rawschema)
        self.validator = salobj.DefaultingValidator(schema=self.schema)
        default_values = self.validator.validate({})
        print(f"default_values={default_values}")
        self.assertEqual(default_values["number1"], 1)
        self.assertEqual(default_values["subobject"]["subnumber1"], 2)
        import types

        print(types.SimpleNamespace(**default_values))


if __name__ == "__main__":
    unittest.main()
