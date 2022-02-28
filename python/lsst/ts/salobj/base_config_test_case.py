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

__all__ = ["BaseConfigTestCase"]

import abc
import importlib
import pathlib
import typing
import unittest
import yaml

from . import type_hints
from .configurable_csc import ConfigurableCsc
from .validator import StandardValidator


class BaseConfigTestCase(metaclass=abc.ABCMeta):
    """Base class for testing configuration files.

    Subclasses must:

    * Inherit both from this and `unittest.TestCase`.

    Also we suggest:

    * Add a method ``test_<foo>`` which calls
      `check_config_files`.
    """

    def get_module_dir(self, module_name: str) -> pathlib.Path:
        """Get the directory of a python module, by importing the module.

        Parameters
        ----------
        module_name : `str`
            Module name, e.g. "lsst.ts.salobj".

        Returns
        -------
        module_dir : `pathlib.Path`
            Module directory, e.g. ``<package_root>/lsst/ts/salobj``

        Raises
        ------
        ModuleNotFoundError
            If the module is not found.
        """
        module = importlib.import_module(module_name)
        init_path = pathlib.Path(module.__file__)
        return init_path.parent

    def get_schema(
        self,
        csc_package_root: type_hints.PathType,
        sal_name: typing.Optional[str] = None,
        schema_subpath: typing.Optional[str] = None,
    ) -> typing.Dict[str, str]:
        """Get the config schema for a package, as a dict.

        The schema is expected to be:

            csc_package_root / "schema" / f"{sal_name}.yaml"

        Parameters
        ----------
        csc_package_root : `str` or `pathlib.Path`
            Root directory of CSC package.
        sal_name : `str`
            SAL component name, e.g. "Watcher".
            Ignored if ``schema_subpath`` is specified.
        schema_subpath : `str` or `None`
            Schema path relative to csc_package_root.
            If `None` then use ``f"schema/{sal_name}.yaml"``

        Raises
        ------
        AssertionError
            If csc_package_root is not an existing directory.
            If the schema file is not an existing file.
        jsonschema.exceptions.SchemaError
            If the file cannot be interpreted as a `dict`.
        """
        csc_package_root = pathlib.Path(csc_package_root)
        assert csc_package_root.is_dir()

        if schema_subpath is None:
            if sal_name is None:
                raise RuntimeError("Must specify sal_name or schema_subpath")
            schema_path = csc_package_root / "schema" / f"{sal_name}.yaml"
        else:
            schema_path = csc_package_root / schema_subpath
        assert schema_path.is_file()
        with open(schema_path, "r") as schema_file:
            schema_yaml = schema_file.read()
        schema = yaml.safe_load(schema_yaml)
        assert isinstance(schema, dict)
        return schema

    def get_config_dir(
        self,
        config_package_root: type_hints.PathType,
        sal_name: str,
        schema: typing.Dict[str, typing.Any],
    ) -> pathlib.Path:
        """Get the directory of config files, assuming the standard
        ts_config_x package layout.

        The config dir is assumed to be as follows, where ``version``
        comes from the title field of the schema:

            config_package_root / sal_name / version

        Parameters
        ----------
        config_package_root : `str` or `pathlib.Path`
            Root directory of configuration package.
            For unit tests in a config package, this will work:

                config_package_root = pathlib.Path(__file__).parents[1]
        sal_name : `str`
            SAL component name, e.g. "Watcher".
        schema : `dict`
            Configuration schema.
            Used to determine the version.

        Returns
        -------
        config_dir : `pathlib.Path`
            Directory containing configuration files.
        """
        config_package_root = pathlib.Path(config_package_root)
        assert config_package_root.is_dir()

        version = schema["title"].split()[-1]
        assert version.startswith(
            "v"
        ), f"version={version} from schema title {schema['title']} does not start with 'v'"

        config_dir = pathlib.Path(config_package_root) / sal_name / version
        assert config_dir.is_dir()
        return config_dir

    def check_config_files(
        self,
        config_dir: type_hints.PathType,
        schema: typing.Dict[str, typing.Any],
        exclude_glob: typing.Optional[str] = None,
    ) -> None:
        """Check all configuration files for a given package.

        Parameters
        ----------
        config_dir : `str` or `pathlib.Path`
            Directory containing config files.
        schema : `dict`
            Configuration schema.
        exclude_override_glob : `dict`
            Glob expression for files to exclude.

        Raises
        ------
        AssertionError
            If the files do not produce a valid schema.
        """
        try:
            config_dir = pathlib.Path(config_dir)
            assert config_dir.is_dir()
            assert isinstance(schema, dict)

            config_validator = StandardValidator(schema)
            schema_version = schema["title"].split()[-1]
            assert schema_version.startswith(
                "v"
            ), f"version={schema_version} from schema title {schema['title']} does not start with 'v'"

            config_files = list(config_dir.glob("*.yaml"))
            if exclude_glob:
                files_to_exclude = set(config_dir.glob(exclude_glob))
                config_files = [
                    filename
                    for filename in config_files
                    if filename not in files_to_exclude
                ]
            found_init = False
            site_files = []
            override_files = [""]
            for filepath in config_files:
                filename = filepath.name
                if filename == "_init.yaml":
                    found_init = True
                elif filename.startswith("_"):
                    site_files.append(filepath.name)
                else:
                    override_files.append(filepath.name)
            if not found_init:
                raise RuntimeError("Failed: no _init.yaml file found")
            if not site_files:
                site_files = [""]

            # Check each site and each site with each override file
            for site_file in site_files:
                for override_file in override_files:
                    ConfigurableCsc.read_config_files(
                        config_validator=config_validator,
                        config_dir=config_dir,
                        files_to_read=["_init.yaml", site_file, override_file],
                    )
        except Exception as e:
            raise AssertionError(repr(e)) from e

    def check_standard_config_files(
        self,
        module_name: str,
        schema_name: str = "CONFIG_SCHEMA",
        sal_name: typing.Optional[str] = None,
        config_package_root: typing.Union[str, pathlib.Path, None] = None,
        config_dir: typing.Union[str, pathlib.Path, None] = None,
    ) -> None:
        """A wrapper around `check_config_files` to test salobj packages.

        Parameters
        ----------
        module_name : `str`
            Module name, e.g. "lsst.ts.salobj".
        schema_name : `str`
            Name of schema constant in the module, typically "CONFIG_SCHEMA".
        sal_name : `str` or `None`
            SAL component name, e.g. "Watcher".
            Ignored if ``config_dir`` is not None.
            Used to determine config dir if ``config_dir`` is None.
        config_package_root : `str` or `pathlib.Path` or `None`
            Root directory of configuration package.
            Used to determine config dir if ``config_dir`` is None.
            Within the unit test for a config package, this will work::

                config_package_root = pathlib.Path(__file__).parents[1]

            Ignored if ``config_dir`` is specified.

        config_dir : `str` or `pathlib.Path` or `None`
            Directory containing config files.
            If `None` then a reasonable value is computed;
            this is primarily intended to support unit testing in ts_salobj.
        exclude_glob : str
            Glob expression of override files to exclude.
            For use by salobj unit tests.
        """
        try:
            module = importlib.import_module(module_name)
        except ImportError:
            raise unittest.SkipTest(f"Cannot import {module_name}")
        schema = getattr(module, schema_name)

        if config_dir is None:
            if config_package_root is None:
                raise RuntimeError(
                    "config_package_root must be specified if config_dir is None."
                )
            if sal_name is None:
                raise ValueError("sal_name must be specified if config_dir is None")
            config_dir = self.get_config_dir(
                config_package_root=config_package_root,
                sal_name=sal_name,
                schema=schema,
            )
        self.check_config_files(config_dir=config_dir, schema=schema)
