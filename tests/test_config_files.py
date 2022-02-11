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

import pytest

from lsst.ts import salobj


class ConfigTestCase(salobj.BaseConfigTestCase, unittest.TestCase):
    def setUp(self) -> None:
        self.schema = salobj.CONFIG_SCHEMA

    def test_get_schema(self) -> None:
        csc_package_root = pathlib.Path(__file__).parents[1]
        schema = self.get_schema(csc_package_root=csc_package_root, sal_name="Test")
        assert isinstance(schema, dict)

        schema2 = self.get_schema(
            csc_package_root=csc_package_root, schema_subpath="schema/Test.yaml"
        )
        assert schema == schema2

        with pytest.raises(AssertionError):
            # Invalid sal_name
            self.get_schema(
                csc_package_root=csc_package_root, sal_name="NoSuchSalComponent"
            )
        with pytest.raises(AssertionError):
            # Invalid schema_subpath
            self.get_schema(
                csc_package_root=csc_package_root,
                schema_subpath="schema/no_such_file.yaml",
            )
        with pytest.raises(AssertionError):
            # Invalid csc_package_root
            self.get_schema(csc_package_root="not/a/directory", sal_name="Test")
        with pytest.raises(RuntimeError):
            # Must specify sal_name or schema_subpath
            self.get_schema(csc_package_root=csc_package_root)

    def test_get_module_dir(self) -> None:
        module_dir = self.get_module_dir("lsst.ts.salobj")
        assert str(module_dir).endswith("lsst/ts/salobj")

        with pytest.raises(ModuleNotFoundError):
            self.get_module_dir("lsst.lsst.lsst.no_such_module")

    @unittest.skipIf("TS_CONFIG_OCS_DIR" not in os.environ, "ts_config_ocs not found")
    def test_standard_configs(self) -> None:
        """Test the config files in ts_config_ocs/Test/..."""
        config_package_root = pathlib.Path(os.environ["TS_CONFIG_OCS_DIR"])
        assert config_package_root.is_dir()
        config_dir = self.get_config_dir(
            config_package_root=config_package_root, sal_name="Test", schema=self.schema
        )
        self.check_config_files(config_dir=config_dir, schema=self.schema)

        minimal_kwargs = dict(
            module_name="lsst.ts.salobj",
            config_dir=config_dir,
        )

        # Check with minimal arguments
        self.check_standard_config_files(**minimal_kwargs)

        # Omit required arguments
        for key in minimal_kwargs:
            bad_kwargs = minimal_kwargs.copy()
            expected_exception = dict(
                module_name=TypeError,
                config_dir=RuntimeError,
            )[key]
            del bad_kwargs[key]
            with pytest.raises(expected_exception):
                self.check_standard_config_files(**bad_kwargs)

        # Specify schema_name
        self.check_standard_config_files(
            module_name="lsst.ts.salobj",
            schema_name="CONFIG_SCHEMA",
            config_dir=config_dir,
        )

        # Specify invalid schema_name
        with pytest.raises(AttributeError):
            self.check_standard_config_files(
                module_name="lsst.ts.salobj",
                schema_name="invalid_name",
                config_dir=config_dir,
            )

        # specify sal_name and config_package_root
        self.check_standard_config_files(
            module_name="lsst.ts.salobj",
            schema_name="CONFIG_SCHEMA",
            sal_name="Test",
            config_package_root=config_package_root,
        )

        # check that sal_name and config_package_root are ignored
        # if config_dir specified
        self.check_standard_config_files(
            module_name="lsst.ts.salobj",
            schema_name="CONFIG_SCHEMA",
            sal_name="NoSuchSALComponent",
            config_package_root=config_package_root / "no such dir",
            config_dir=config_dir,
        )

        # Specify invalid sal_name
        with pytest.raises(AssertionError):
            self.check_standard_config_files(
                module_name="lsst.ts.salobj",
                schema_name="CONFIG_SCHEMA",
                sal_name="NoSuchSALComponent",
                config_package_root=config_package_root,
            )

        # Specify invalid config_package_root
        with pytest.raises(AssertionError):
            self.check_standard_config_files(
                module_name="lsst.ts.salobj",
                schema_name="CONFIG_SCHEMA",
                sal_name="Test",
                config_package_root=config_package_root / "no_such_dir",
            )

    def test_local_configs(self) -> None:
        """Test the various local config directories."""
        configs_root = pathlib.Path(__file__).parent / "data" / "configs"

        for config_dir in configs_root.glob("good_*"):
            self.check_config_files(
                config_dir=config_dir, schema=self.schema, exclude_glob="bad_*"
            )

        for config_dir in configs_root.glob("bad_*"):
            with self.subTest(config_dir=str(config_dir)):
                with pytest.raises(AssertionError):
                    self.check_config_files(
                        config_dir=config_dir, schema=self.schema, exclude_glob="bad_*"
                    )
