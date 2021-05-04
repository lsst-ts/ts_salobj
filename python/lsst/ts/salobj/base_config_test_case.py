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
import os
import pathlib
import unittest
import yaml

import jsonschema

from . import validator


class BaseConfigTestCase(metaclass=abc.ABCMeta):
    """Base class for testing configuration files.

    Subclasses must:

    * Inherit both from this and `unittest.TestCase`.

    Also we suggest:

    * Add a method ``test_<foo>`` which calls
      `check_config_files`.
    """

    def get_module_dir(self, module_name):
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

    def get_schema(self, csc_package_root, sal_name=None, schema_subpath=None):
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
        self.assertTrue(
            csc_package_root.is_dir(),
            f"csc_package_root={csc_package_root} is not a file",
        )

        if schema_subpath is None:
            if sal_name is None:
                raise RuntimeError("Must specify sal_name or schema_subpath")
            schema_path = csc_package_root / "schema" / f"{sal_name}.yaml"
        else:
            schema_path = csc_package_root / schema_subpath
        self.assertTrue(
            schema_path.is_file(), f"schema_path={schema_path} is not a file"
        )
        with open(schema_path, "r") as schema_file:
            schema_yaml = schema_file.read()
        schema = yaml.safe_load(schema_yaml)
        self.assertIsInstance(schema, dict)
        return schema

    def get_config_dir(self, config_package_root, sal_name, schema):
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
        self.assertTrue(
            config_package_root.is_dir(),
            f"config_package_root={config_package_root} is not a dir",
        )

        version = schema["title"].split()[-1]
        self.assertTrue(
            version.startswith("v"),
            f"version={version} from schema title {schema['title']} does not start with 'v'",
        )

        config_dir = pathlib.Path(config_package_root) / sal_name / version
        self.assertTrue(config_dir.is_dir(), f"config_dir={config_dir} is not a dir")
        return config_dir

    def check_config_files(self, config_dir, schema):
        """Check all configuration files for a given package.

        Parameters
        ----------
        config_dir : `str` or `pathlib.Path`
            Directory containing config files and ``_labels.yaml``.
        schema : `dict`
            Configuration schema.
        """
        config_dir = pathlib.Path(config_dir)
        self.assertTrue(config_dir.is_dir(), f"config_dir={config_dir} is not a dir")
        self.assertIsInstance(schema, dict)

        config_validator = validator.DefaultingValidator(schema)
        version = schema["title"].split()[-1]
        self.assertTrue(
            version.startswith("v"),
            f"version={version} from schema title {schema['title']} does not start with 'v'",
        )

        config_files = config_dir.glob("*.yaml")

        # Check that all config files are valid.
        # Avoid using self.subTest because that somehow prevents
        # the following from working with known bad config files:
        #     with self.assertRaises(AssertionError): # or Exception
        #         self.check_config_files(...)
        bad_config_files = []
        for config_file in config_files:
            if config_file.name == "_labels.yaml":
                continue
            with open(config_file, "r") as f:
                config_yaml = f.read()
            try:
                config_dict = yaml.safe_load(config_yaml)
                # Delete metadata, if present
                if config_dict:
                    config_dict.pop("metadata", None)
                config_validator.validate(config_dict)
            except jsonschema.exceptions.ValidationError as e:
                print(f"config file {config_file} failed validation: {e}")
                bad_config_files.append(str(config_file))
        if bad_config_files:
            raise AssertionError(
                f"{len(bad_config_files)} config file(s) failed validation: {bad_config_files}"
            )

        # Check that all entries in the label dict are valid
        # and point to existing files.
        labels_path = config_dir / "_labels.yaml"
        self.assertTrue(
            labels_path.is_file(), f"labels file={labels_path} is not a file"
        )
        with open(labels_path, "r") as f:
            labels_yaml = f.read()
        if labels_yaml:
            input_dict = yaml.safe_load(labels_yaml)
            if input_dict is None:
                input_dict = {}
            else:
                self.assertIsInstance(input_dict, dict)
        else:
            input_dict = {}

        invalid_labels = []
        invalid_files = []
        missing_files = []
        for label, config_name in input_dict.items():
            if not label.isidentifier() or label.startswith("_"):
                invalid_labels.append(label)
            if config_name.strip().startswith("/") or not config_name.endswith(".yaml"):
                invalid_files.append(config_name)
            if not (config_dir / config_name).is_file():
                missing_files.append(config_name)
        if invalid_labels:
            self.fail(f"Invalid labels {invalid_labels} in {labels_path}")
        if invalid_files:
            self.fail(f"Labels to invalid file {invalid_files} in {labels_path}")
        if missing_files:
            self.fail(f"Labels to missing files {missing_files} in {labels_path}")

    def check_standard_config_files(
        self,
        sal_name=None,
        module_name=None,
        package_name=None,
        schema_name=None,
        schema_subpath=None,
        config_package_root=None,
        config_dir=None,
    ):
        """A wrapper around `check_config_files` that handles the most common
        case.

        Assumptions:

        * The module can be imported, if ``module_name`` specified,
          else environment variable ``f"{package_name.upper()}_DIR"`` exists.
          If not, skip the test, because the package is not available.
        * The schema is a module constant named ``schema_name``,
          if provided, else the schema is a file found as follows:

            * If ``module_name`` is provided,
              the module root is n+1 levels above the package,
              where n is the number of "." in ``module_name``
            * The schema is in ``module root / "schema" / f"{sal_name}.yaml"``
              unless you override this with ``schema_subpath``.

        Parameters
        ----------
        sal_name : `str`
            SAL component name, e.g. "Watcher".
        module_name : `str` or `None`, optional
            Module name, e.g. "lsst.ts.salobj".
            If not None then get the CSC package root by importing
            the module and ignore ``package_name``.
        package_name : `str`, optional
            If ``module_name`` is None then specify this argument
            and get the CSC package root using environment variable
            ``f"{package_name.upper()}_DIR"``.
            This is useful for non-python packages or packages that
            need a special environment to be imported.
        schema_name : `str` or None, optional
            Name of schema constant in the module, typically "CONFIG_SCHEMA".
            If None then look for a schema file instead of a schema constant.
        schema_subpath : `str` or `None`
            Schema path relative to csc_package_root.
            If `None` then use ``f"schema/{sal_name}.yaml"``.
            Ignored if ``schema_name`` is specified.
        config_package_root : `str` or `pathlib.Path` or `None`
            Root directory of configuration package.
            Within the unit test this will work:

                config_package_root = pathlib.Path(__file__).parents[1]

            Ignored if ``schema_name`` or ``config_dir`` is specified.

        config_dir : `str` or `pathlib.Path` or `None`
            Directory containing config files and ``_labels.yaml``.
            If `None` then a reasonable value is computed;
            this is primarily intended to support unit testing in ts_salobj.
        """
        if module_name is not None and schema_name is not None:
            try:
                module = importlib.import_module(module_name)
            except ImportError:
                raise unittest.SkipTest(f"Cannot import {module_name}")
            schema = getattr(module, schema_name)
        else:
            if module_name is None:
                if package_name is None:
                    raise RuntimeError("Must specify module_name or package_name")
                else:
                    env_var = package_name.upper() + "_DIR"
                    csc_package_root = os.environ.get(env_var)
                    if csc_package_root is None:
                        raise unittest.SkipTest(
                            f"Cannot find package {package_name}; "
                            f"environment variable {env_var} not defined"
                        )
            else:
                num_dots = len(module_name.split("."))
                try:
                    csc_package_root = self.get_module_dir(module_name).parents[
                        num_dots
                    ]
                except ImportError:
                    raise unittest.SkipTest(f"Cannot import {module_name}")
            schema = self.get_schema(
                csc_package_root=csc_package_root,
                sal_name=sal_name,
                schema_subpath=schema_subpath,
            )
        if config_dir is None:
            if config_package_root is None:
                raise RuntimeError(
                    "config_package_root or config_dir must be specified."
                )
            config_dir = self.get_config_dir(
                config_package_root=config_package_root,
                sal_name=sal_name,
                schema=schema,
            )
        self.check_config_files(config_dir=config_dir, schema=schema)
