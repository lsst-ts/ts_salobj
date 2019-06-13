# This file is part of ts_salobj.
#
# Developed for the LSST Telescope and Site Systems.
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

__all__ = ["ConfigurableCsc"]

import abc
import os
import pathlib
import subprocess
import types

import yaml

from . import base
from .base_csc import BaseCsc, State
from .validator import DefaultingValidator

# maximum length of settingsVersion.recommendedSettingsVersion field
MAX_LABELS_LEN = 256


class ConfigurableCsc(BaseCsc, abc.ABC):
    """Base class for a configurable Commandable SAL Component (CSC)

    Parameters
    ----------
    name : `str`
        Name of SAL component.
    index : `int` or `None`
        SAL component index, or 0 or None if the component is not indexed.
    schema_path : `str`
        Path to a schema file used to validate configuration files.
    config_dir : `str` (optional)
        Directory of configuration files, or None for the standard
        configuration directory (obtained from `get_default_config_dir`).
        This is provided for unit testing.
    initial_state : `State` or `int` (optional)
        The initial state of the CSC. This is provided for unit testing,
        as real CSCs should start up in `State.STANDBY`, the default.
    initial_simulation_mode : `int` (optional)
        Initial simulation mode. This is provided for unit testing,
        as real CSCs should start up not simulating, the default.

    Raises
    ------
    ValueError
        If ``config_dir`` is not a directory.
    salobj.ExpectedError
        If ``initial_state`` or ``initial_simulation_mode`` is invalid.

    Notes
    -----
    Configuration is handled by the ``start`` command, as follows:

    * The ``settingsToApply`` field specifies a path to a configuration file
      found in the package specified by ``config_pkg`` in a subdirectory
      with the name of this SAL component (e.g. Test or ATDomeTrajectory).
    * The configuration file is validated against the schema specified
      by specified ``schema_path``.
      This includes setting default values from the schema and validating
      the result again (in case the default values are invalid).
    * The validated configuration is converted to a struct-like object
      using `types.SimpleNamespace`.
    * The configuration is passed to the ``configure`` method,
      which subclasses must override. Note that ``configure`` is called just
      before summary state changes from `State.STANDBY` to `State.DISABLED`.

    The constructor does the following:

    * Set summary state, then run the `ConfigurableCsc.start` asynchronously,
      which does the following:
    * If ``initial_summary_state`` is `State.DISABLED` or `State.ENABLED`
      then call `ConfigurableCsc.configure`.
    * Call `BaseCsc.set_simulation_mode`
    * Call `BaseCsc.report_summary_state`
    * Set ``start_task`` done
    """
    def __init__(self, name, index, schema_path, config_dir=None,
                 initial_state=State.STANDBY, initial_simulation_mode=0):

        if not pathlib.Path(schema_path).is_file():
            raise ValueError(f"schema_path={schema_path} is not a file")
        with open(schema_path, "r") as f:
            schema_data = f.read()
        try:
            schema = yaml.safe_load(schema_data)
            self.config_validator = DefaultingValidator(schema=schema)
            title = schema["title"]
            name_version = title.rsplit(" ", 1)
            if len(name_version) != 2 or not name_version[1].startswith("v"):
                raise ValueError(f"Schema title {title!r} must end with ' v<version>'")
            self.schema_version = name_version[1]
        except Exception as e:
            raise ValueError(f"Schema {schema_path} invalid") from e

        super().__init__(name=name, index=index, initial_state=initial_state,
                         initial_simulation_mode=initial_simulation_mode)

        if config_dir is None:
            config_dir = self.get_default_config_dir()
        else:
            config_dir = pathlib.Path(config_dir)
            if not config_dir.is_dir():
                raise ValueError(f"config_dir={config_dir} does not exists or is not a directory")
        self.config_dir = config_dir

    @property
    def config_dir(self):
        """Get or set the configuration directory.

        Parameters
        ----------
        config_dir : `str`, `bytes`, or `pathlib.Path`
            New configuration directory.

        Returns
        -------
        config_dir : `pathlib.Path`
            Absolute path to the configuration directory.

        Raises
        ------
        ValueError
            If the new configuration dir is not a directory.
        """
        return self._config_dir

    @config_dir.setter
    def config_dir(self, config_dir):
        config_dir = pathlib.Path(config_dir).resolve()
        if not config_dir.is_dir():
            raise ValueError(f"config_dir={config_dir} does not exist or is not a directory")
        self._config_dir = config_dir

    def read_config_dir(self):
        """Set ``self.config_label_dict`` and output ``evt_settingVersions``.

        Set ``self.config_label_dict`` from ``self.config_dir/_labels.yaml``.
        Output the ``settingVersions`` event as follows:

        * ``recommendedSettingsLabels`` is a comma-separated list of
          labels in ``self.config_label_dict``, truncated by omitting labels
          if necessary.
        * ``recommendedSettingsVersion`` is derived from git information for
          ``self.config_dir``, if it is a git repository, else "".
        """
        self.config_label_dict = self._make_config_label_dict()

        labels = list(self.config_label_dict.keys())
        labels_str = ",".join(labels)
        if len(labels_str) > MAX_LABELS_LEN:
            nitems = len(labels)
            nitems_to_drop = len(labels_str[MAX_LABELS_LEN:].split(","))
            self.log.warning(f"Config labels do not all fit into {MAX_LABELS_LEN} characters; "
                             f"dropping {nitems_to_drop} of {nitems} items")
            # use max just in case; nitems_to_drop should always be <= nitems
            labels_str = ",".join(labels[0:max(0, nitems - nitems_to_drop)])

        settings_version = self._get_settings_version()

        self.evt_settingVersions.set_put(recommendedSettingsLabels=",".join(labels),
                                         recommendedSettingsVersion=settings_version,
                                         settingsUrl=f"{self.config_dir.as_uri()}",
                                         force_output=True)

    async def start(self):
        """Finish constructing the CSC.

        * If ``initial_summary_state`` is `State.DISABLED` or `State.ENABLED`
          then call `configure`.
        * Run `BaseCsc.start`
        """
        # If starting up in Enabled or Disabled state then the CSC must be
        # configured now, because it won't be configured by
        # the start command (do_start method).
        if self.summary_state in (State.DISABLED, State.ENABLED):
            default_config_dict = self.config_validator.validate(None)
            default_config = types.SimpleNamespace(**default_config_dict)
            await self.configure(config=default_config)
        await super().start()

    def _get_settings_version(self):
        """Get data for evt_settingsVersions.recommendedSettingsVersion.

        If config_dir is a git repository (as it should be)
        then return detailed git information. Otherwise return "".
        """
        try:
            git_info = subprocess.check_output(["git", "describe", "--all", "--long", "--always",
                                                "--dirty"], stderr=subprocess.STDOUT)
        except subprocess.CalledProcessError:
            self.log.warning(f"Could not get git info for config_dir={self.config_dir}")
            return ""
        return git_info.decode(errors="replace").strip()

    def _make_config_label_dict(self):
        """Parse ``self.config_dir/_labels.yaml`` and return the dict.

        where the path is relative to ``self.config_dir`` directory.

        Parsing is on a best-effort basis. Invalid labels are listed in
        one or more ``logMessage`` events and valid labels are used.

        The result should be put in self.config_label_dict
        """
        labels_path = self.config_dir / "_labels.yaml"
        if not labels_path.is_file():
            self.log.warning(f"{labels_path} not found")
            return {}
        with open(labels_path, "r") as f:
            labels_raw = f.read()
        if not labels_raw:
            self.log.debug(f"{labels_path} is empty")
            return {}
        input_dict = yaml.safe_load(labels_raw)
        if input_dict is None:
            return {}
        if not isinstance(input_dict, dict):
            self.log.warning(f"{labels_path} does not describe a dict")
            return {}
        missing_files = []
        invalid_labels = []
        output_dict = dict()
        # iterate over a copy so the dict can be modified
        for label, config_name in input_dict.items():
            valid = True
            if not label.isidentifier() or label.startswith("_"):
                valid = False
                invalid_labels.append(label)
            if config_name.strip().startswith("/"):
                valid = False
                missing_files.append(config_name)
            if not (self.config_dir / config_name).is_file():
                valid = False
                missing_files.append(config_name)
            if valid:
                output_dict[label] = config_name
        if invalid_labels:
            self.log.warning(f"Ignoring invalid labels {invalid_labels}")
        if missing_files:
            self.log.warning(f"Labeled config files {missing_files} not found in {self.config_dir}")
        return output_dict

    def report_summary_state(self):
        super().report_summary_state()
        if self.summary_state == State.STANDBY:
            try:
                self.read_config_dir()
            except Exception as e:
                self.log.exception(e)

    async def begin_start(self, data):
        """Begin do_start; configure the CSC before changing state.

        Parameters
        ----------
        data : ``cmd_start.DataType``
            Command data

        Notes
        -----
        The ``settingsToApply`` field must be one of:

        * The name of a config label or config file
        * The name and version of a config file, formatted as
          ``<file_name>:<version>``, where the version is a git reference,
          such as a git tag or commit hash. This form does not support labels.
        """
        config_name = data.settingsToApply
        if config_name:
            name_version = config_name.split(":")
            if len(name_version) == 2:
                config_file_name, githash = name_version
                config_file_path = self.config_dir / config_file_name
                try:
                    config_yaml = subprocess.check_output(["git", "cat-file", "--textconv",
                                                          f"{githash}:{config_file_path}"],
                                                          stderr=subprocess.STDOUT)
                except subprocess.CalledProcessError as e:
                    raise base.ExpectedError(f"Could not read config {config_name}: {e.output}")
            elif len(name_version) == 1:
                config_file_name = self.config_label_dict.get(config_name, config_name)
                config_file_path = self.config_dir / config_file_name
                if not config_file_path.is_file():
                    raise base.ExpectedError(f"Cannot find config file {config_file_name} "
                                             f"in {self.config_dir}")
                with open(config_file_path, "r") as f:
                    config_yaml = f.read()
            else:
                raise base.ExpectedError(f"Could not parse {config_name} as name or name:version")

            user_config_dict = yaml.safe_load(config_yaml)
        else:
            user_config_dict = {}
        try:
            full_config_dict = self.config_validator.validate(user_config_dict)
        except Exception as e:
            raise base.ExpectedError(f"schema {config_file_path} failed validation: {e}")
        config = types.SimpleNamespace(**full_config_dict)
        await self.configure(config)
        self.evt_appliedSettingsMatchStart.set_put(appliedSettingsMatchStartIsTrue=True, force_output=True)

    @abc.abstractmethod
    async def configure(self, config):
        """Configure the CSC.

        Parameters
        ----------
        config : `object`
            The configuration as described by the schema at ``schema_path``,
            as a struct-like object.

        Notes
        -----
        Called when running the ``start`` command, just before changing
        summary state from `State.STANDBY` to `State.DISABLED`.
        """
        raise NotImplementedError("Subclasses must override")

    @staticmethod
    @abc.abstractmethod
    def get_config_pkg():
        """Get the name of the configuration package, e.g. "ts_config_ocs".
        """
        raise NotImplementedError()

    def get_default_config_dir(self):
        """Compute the default directory for configuration files.

        Returns
        -------
        config_dir : `pathlib.Path`
            Default configuration directory.

        Raises
        ------
        RuntimeError
            If environment variable "{config_pkg}_DIR" is not defined
            or does not point to a directory, or points to a directory
            that does not contain a subdirectory with the name of this
            SAL component.

        Notes
        -----
        The base directory is environment variable "{config_pkg}_DIR",
        where `config_pkg = self.get_config_pkg()` changed to uppercase.
        Configuration files are found in the subdirectory whose name is:

            <SAL component name>/<schema version>

        For example

            Test/v1
        """
        config_pkg = self.get_config_pkg()
        config_env_var_name = f"{config_pkg.upper()}_DIR"
        try:
            config_pkg_dir = os.environ[config_env_var_name]
        except KeyError:
            raise RuntimeError(f"Environment variable {config_env_var_name} not defined")
        config_pkg_dir = pathlib.Path(config_pkg_dir).resolve()
        if not config_pkg_dir.is_dir():
            raise RuntimeError(f"{config_pkg_dir!r} = ${config_env_var_name} "
                               "does not exists or is not a directory")

        config_dir = config_pkg_dir / self.salinfo.name / self.schema_version
        if not config_dir.is_dir():
            raise RuntimeError(f"{config_dir} = ${config_env_var_name}/SAL_component_name/schema_version "
                               "does not exist or is not a directory")
        return config_dir

    @classmethod
    def add_arguments(cls, parser):
        parser.add_argument(f"--configdir",
                            help="Directory containing configuration files for the start command.")

    @classmethod
    def add_kwargs_from_args(cls, args, kwargs):
        kwargs["config_dir"] = args.configdir