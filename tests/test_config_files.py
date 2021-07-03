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

import os
import pathlib
import unittest

from lsst.ts import salobj


class ConfigTestCase(salobj.BaseConfigTestCase, unittest.TestCase):
    def setUp(self) -> None:
        self.schema = salobj.CONFIG_SCHEMA

    def test_get_schema(self) -> None:
        csc_package_root = pathlib.Path(__file__).parents[1]
        schema = self.get_schema(csc_package_root=csc_package_root, sal_name="Test")
        self.assertIsInstance(schema, dict)

        schema2 = self.get_schema(
            csc_package_root=csc_package_root, schema_subpath="schema/Test.yaml"
        )
        self.assertEqual(schema, schema2)

        with self.assertRaises(AssertionError):
            # Invalid sal_name
            self.get_schema(
                csc_package_root=csc_package_root, sal_name="NoSuchSalComponent"
            )
        with self.assertRaises(AssertionError):
            # Invalid schema_subpath
            self.get_schema(
                csc_package_root=csc_package_root,
                schema_subpath="schema/no_such_file.yaml",
            )
        with self.assertRaises(AssertionError):
            # Invalid csc_package_root
            self.get_schema(csc_package_root="not/a/directory", sal_name="Test")
        with self.assertRaises(RuntimeError):
            # Must specify sal_name or schema_subpath
            self.get_schema(csc_package_root=csc_package_root)

    def test_get_module_dir(self) -> None:
        module_dir = self.get_module_dir("lsst.ts.salobj")
        self.assertTrue(str(module_dir).endswith("lsst/ts/salobj"))

        with self.assertRaises(ModuleNotFoundError):
            self.get_module_dir("lsst.lsst.lsst.no_such_module")

    @unittest.skipIf("TS_CONFIG_OCS_DIR" not in os.environ, "ts_config_ocs not found")
    def test_standard_configs(self) -> None:
        """Test the config files in ts_config_ocs/Test/..."""
        config_package_root = os.environ["TS_CONFIG_OCS_DIR"]
        config_dir = self.get_config_dir(
            config_package_root=config_package_root, sal_name="Test", schema=self.schema
        )
        self.check_config_files(config_dir=config_dir, schema=self.schema)

        # Test check_standard_config_files using module import and schema_name
        self.check_standard_config_files(
            module_name="lsst.ts.salobj",
            schema_name="CONFIG_SCHEMA",
            config_dir=config_dir,
        )

        # Test check_standard_config_files using module import
        self.check_standard_config_files(
            sal_name="Test", module_name="lsst.ts.salobj", config_dir=config_dir
        )

        # Test check_standard_config_files using env var TS_SALOBJ_DIR
        self.check_standard_config_files(
            sal_name="Test", package_name="ts_salobj", config_dir=config_dir
        )

        # Test check_standard_config_files using env var TS_SALOBJ_DIR
        # and schema_subpath
        self.check_standard_config_files(
            sal_name="Test",
            package_name="ts_salobj",
            config_dir=config_dir,
            schema_subpath="schema/Test.yaml",
        )

        with self.assertRaises(AssertionError):
            self.check_standard_config_files(
                sal_name="Test",
                package_name="ts_salobj",
                config_dir=config_dir,
                schema_subpath="schema/no_such_file.yaml",
            )

    def test_local_configs(self) -> None:
        """Test the various local config directories."""
        data_root = pathlib.Path(__file__).parent / "data"

        self.check_config_files(
            config_dir=data_root / "config_good", schema=self.schema
        )

        for config_dir in data_root.glob("config_bad*"):
            with self.subTest(config_dir=str(config_dir)):
                with self.assertRaises(AssertionError):
                    self.check_config_files(config_dir=config_dir, schema=self.schema)


if __name__ == "__main__":
    unittest.main()
