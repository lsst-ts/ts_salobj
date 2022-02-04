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

__all__ = ["ConfigurableCsc"]

import abc
import argparse
import asyncio
import os
import pathlib
import subprocess
import types
import typing

import yaml

from lsst.ts import utils
from . import base
from . import type_hints
from .base_csc import BaseCsc, State
from .validator import StandardValidator


class ConfigurableCsc(BaseCsc, abc.ABC):
    """Base class for a configurable Commandable SAL Component (CSC)

    Parameters
    ----------
    name : `str`
        Name of SAL component.
    index : `int` or `None`
        SAL component index, or 0 or None if the component is not indexed.
    config_schema : `dict`
        Configuration schema, as a dict in jsonschema format.
    config_dir : `str`, optional
        Directory of configuration files, or None for the standard
        configuration directory (obtained from `_get_default_config_dir`).
        This is provided for unit testing.
    initial_state : `State` or `int`, optional
        The initial state of the CSC. This is provided for unit testing,
        as real CSCs should start up in `State.STANDBY`, the default.
    override : `str`, optional
        Configuration override file to use if ``initial_state`` is
        `State.DISABLED` or `State.ENABLED`.
    simulation_mode : `int`, optional
        Simulation mode. The default is 0: do not simulate.

    Raises
    ------
    ValueError
        If ``config_dir`` is not a directory or ``initial_state`` is invalid.
    salobj.ExpectedError
        If ``simulation_mode`` is invalid.
        Note: you will only see this error if you await `start_task`.
    RuntimeError
        If the environment variable ``LSST_SITE`` is not set.

    Attributes
    ----------
    config_dir : `pathlib.Path`
        Directory containing configuration files.
    config_validator : `DefaultingValidator`
        Validator for configuration files that also sets default values
        for omitted items.
    schema_version : `str`
        Configuration schema version, as specified in the schema as the
        final word of the ``title``. Used to find the ``config_dir``.
    site : `str`
        The value of the ``LSST_SITE`` environment variable, e.g. "summit".
        Used to select the correct configuration files.

    Notes
    -----

    **Configuration**

    Configuration is handled by the ``start`` command, as follows:

    * The ``override`` field specifies a path to a configuration file
      found in the package specified by ``config_pkg`` in a subdirectory
      with the name of this SAL component (e.g. Test or ATDomeTrajectory).
    * The configuration file is validated against the schema specified
      by specified ``config_schema``.
      This includes setting default values from the schema and validating
      the result again (in case the default values are invalid).
    * The validated configuration is converted to a struct-like object
      using `types.SimpleNamespace`.
    * The configuration is passed to the ``configure`` method,
      which subclasses must override. Note that ``configure`` is called just
      before summary state changes from `State.STANDBY` to `State.DISABLED`.

    **Constructor**

    The constructor does the following, beyond the parent class constructor:

    * Set summary state, then run the `ConfigurableCsc.start` asynchronously,
      which does the following:
    * If ``initial_summary_state`` is `State.DISABLED` or `State.ENABLED`
      then call `ConfigurableCsc.configure`.
    * Call `BaseCsc.set_simulation_mode`
    * Call `BaseCsc.handle_summary_state`
    * Call `BaseCsc.report_summary_state`
    * Set ``start_task`` done
    """

    def __init__(
        self,
        name: str,
        index: typing.Optional[int],
        config_schema: typing.Dict[str, typing.Any],
        config_dir: typing.Union[str, pathlib.Path, None] = None,
        initial_state: State = State.STANDBY,
        override: str = "",
        simulation_mode: int = 0,
    ) -> None:
        self.site = os.environ.get("LSST_SITE")
        if self.site is None:
            raise RuntimeError("Environment variable $LSST_SITE not defined.")

        try:
            assert config_schema is not None  # Make mypy happy
            self.config_validator = StandardValidator(schema=config_schema)
            title = config_schema["title"]
            name_version = title.rsplit(" ", 1)
            if len(name_version) != 2 or not name_version[1].startswith("v"):
                raise ValueError(f"Schema title {title!r} must end with ' v<version>'")
            self.schema_version = name_version[1]
        except Exception as e:
            raise ValueError(f"Schema {config_schema} invalid: {e!r}") from e

        if config_dir is None:
            config_dir = self._get_default_config_dir(name)
        else:
            config_dir = pathlib.Path(config_dir)

        if not config_dir.is_dir():
            raise ValueError(
                f"config_dir={config_dir} does not exist or is not a directory"
            )

        self.config_dir = config_dir
        # Interval between reading the config dir (seconds)
        self.read_config_dir_interval = 1
        self.read_config_dir_task = utils.make_done_future()

        super().__init__(
            name=name,
            index=index,
            initial_state=initial_state,
            override=override,
            simulation_mode=simulation_mode,
        )

        # Set static fields of the generic configuration events.
        # Neither event is complete, so don't put the information yet.
        for evt in (
            self.evt_configurationsAvailable,  # type: ignore
            self.evt_configurationApplied,  # type: ignore
        ):
            evt.set(  # type: ignore
                schemaVersion=self.schema_version, url=self.config_dir.as_uri()
            )

    @property
    def config_dir(self) -> pathlib.Path:
        """Get or set the configuration directory.

        Parameters
        ----------
        config_dir : `str`, `pathlib.Path`
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
    def config_dir(self, config_dir: typing.Union[str, pathlib.Path]) -> None:
        config_dir = pathlib.Path(config_dir).resolve()
        if not config_dir.is_dir():
            raise ValueError(
                f"config_dir={config_dir} does not exist or is not a directory"
            )
        self._config_dir = config_dir

    @classmethod
    def read_config_files(
        cls,
        config_validator: StandardValidator,
        config_dir: pathlib.Path,
        files_to_read: typing.List[str],
        git_hash: str = "",
    ) -> types.SimpleNamespace:
        """Read a set of configuration files and return the validated config.

        Parameters
        ----------
        config_validator : jsonschema validator
            Schema validator for configuration.
        config_dir : pathlib.Path
            Path to config files.
        files_to_read : List [str]
            Names of files to read, with .yaml suffix.
            Empty names are ignored (a useful feature for BaseConfigTestCase).
            The files are read in order, with each later file
            overriding values that have been accumulated so far.
        git_hash : str, optional
            Git hash to use for the files. "" if current.

        Returns
        -------
        types.SimpleNamespace
            The validated config as a simple namespace.

        Raises
        ------
        ExpectedError
            If the specified configuration files cannot be found,
            cannot be parsed as yaml dicts, or produce an invalid configuration
            (one that does not match the schema).
        """
        config_dict = {}
        for filename in files_to_read:
            if not filename:
                continue
            filepath = config_dir / filename
            if not filepath.is_file():
                raise base.ExpectedError(f"Config file '{filepath}' does not exist")
            if git_hash:
                try:
                    # git show must run in the target directory
                    config_raw_data: typing.Union[str, bytes] = subprocess.check_output(
                        args=["git", "show", f"{git_hash}:./{filename}"],
                        stderr=subprocess.STDOUT,
                        cwd=config_dir,
                    )
                except subprocess.CalledProcessError as e:
                    raise base.ExpectedError(
                        f"Could not read config file {filepath} with git hash {git_hash}: {e.output}"
                    )
            else:
                with open(filepath, "r") as f:
                    config_raw_data = f.read()
            try:
                config_data = yaml.safe_load(config_raw_data)
            except Exception as e:
                raise base.ExpectedError(
                    f"Could not parse data in {filepath} as a dict: {e!r}"
                )
            if config_data is not None:
                config_dict.update(config_data)

        # Delete metadata, if present (it is not part of the schema)
        if config_dict:
            config_dict.pop("metadata", None)

        try:
            config_validator.validate(config_dict)
        except Exception as e:
            raise base.ExpectedError(f"Configuration failed validation: {e!r}")

        return types.SimpleNamespace(**config_dict)

    async def read_config_dir(self) -> None:
        """Read the config dir and put configurationsAvailable if changed.

        Output the ``configurationsAvailable`` event (if changed),
        after updating the ``overrides`` and ``version`` fields.
        Also update the ``version`` field of ``evt_configurationApplied``,
        in preparation for the next time the event is output.
        """
        override_filenames = sorted(
            filepath.name
            for filepath in self.config_dir.glob("*")
            if filepath.name.endswith(".yaml") and not filepath.name.startswith("_")
        )

        configs_version = self._get_configs_version()
        self.evt_configurationsAvailable.set_put(  # type: ignore
            overrides=",".join(override_filenames),
            version=configs_version,
        )
        # Update the version field of configurationApplied, but don't put
        # the event, because we don't have all the info we need.
        self.evt_configurationApplied.set(  # type: ignore
            version=configs_version,
        )

    async def read_config_dir_loop(self) -> None:
        while self.summary_state == State.STANDBY:
            await self.read_config_dir()
            await asyncio.sleep(self.read_config_dir_interval)

    async def close_tasks(self) -> None:
        """Shut down pending tasks. Called by `close`."""
        self.read_config_dir_task.cancel()
        await super().close_tasks()

    def _get_configs_version(self) -> str:
        """Get data for evt_configurationsAvailable.version

        If config_dir is a git repository (as it should be)
        then return detailed git information. Otherwise return "".
        """
        try:
            git_info = subprocess.check_output(
                args=["git", "describe", "--all", "--long", "--always", "--dirty"],
                stderr=subprocess.STDOUT,
                cwd=self.config_dir,
            )
        except subprocess.CalledProcessError:
            self.log.warning(f"Could not get git info for config_dir={self.config_dir}")
            return ""
        return git_info.decode(errors="replace").strip()

    def _make_config_label_dict(self) -> typing.Dict[str, str]:
        """Parse ``self.config_dir/_labels.yaml`` and return the dict.

        where the path is relative to ``self.config_dir`` directory.

        Parsing is on a best-effort basis. Invalid labels are listed in
        one or more ``logMessage`` events and valid labels are used.

        The result should be put in self.config_label_dict
        """
        labels_path = self.config_dir / "_labels.yaml"
        try:
            with open(labels_path, "r") as f:
                labels_raw = f.read()
        except OSError as e:
            self.log.warning(f"Could not read labels {labels_path}: {e}")
            return {}
        if not labels_raw:
            self.log.debug(f"{labels_path} is empty")
            return {}
        input_dict = yaml.safe_load(labels_raw)
        if input_dict is None:
            return {}
        if not isinstance(input_dict, dict):
            self.log.warning(f"{labels_path} does not describe a dict")
            return {}
        invalid_labels = []
        invalid_files = []
        missing_files = []
        output_dict = dict()
        # iterate over a copy so the dict can be modified
        for label, config_name in input_dict.items():
            valid = True
            if not label.isidentifier() or label.startswith("_"):
                valid = False
                invalid_labels.append(label)
            if config_name.strip().startswith("/") or not config_name.endswith(".yaml"):
                valid = False
                invalid_files.append(config_name)
            if not (self.config_dir / config_name).is_file():
                valid = False
                missing_files.append(config_name)
            if valid:
                output_dict[label] = config_name
        if invalid_labels:
            self.log.warning(
                f"Ignoring invalid labels {invalid_labels} in {labels_path}"
            )
        if invalid_files:
            self.log.warning(
                f"Ignoring invalid config file names {invalid_files} in {labels_path}"
            )
        if missing_files:
            self.log.warning(
                f"Ignoring missing config files {missing_files} in {labels_path}"
            )
        return output_dict

    def report_summary_state(self) -> None:
        super().report_summary_state()
        self.read_config_dir_task.cancel()
        if self.summary_state == State.STANDBY:
            self.read_config_dir_task = asyncio.create_task(self.read_config_dir_loop())

    async def begin_start(self, data: type_hints.BaseDdsDataType) -> None:
        """Begin do_start; configure the CSC before changing state.

        Parameters
        ----------
        data : ``cmd_start.DataType``
            Command data

        Notes
        -----
        The ``override`` field must be one of:

        * The name of a config label or config file
        * The name and version of a config file, formatted as
          ``<file_name>:<version>``, where the version is a git reference,
          such as a git tag or commit hash. This form does not support labels.
        """
        self.read_config_dir_task.cancel()
        # Get the most current information
        await self.read_config_dir()

        # Get git hash, if relevant
        override: str = data.configurationOverride  # type: ignore
        (override_filename, _, git_hash) = override.partition(":")

        # List of (config filename, must exist)
        files_to_read = ["_init.yaml"]
        site_filename = f"_{self.site}.yaml"
        if (self.config_dir / site_filename).is_file():
            files_to_read.append(site_filename)
        if override_filename:
            if override_filename.startswith("_"):
                raise base.ExpectedError(
                    f"configurationOverride filename={override_filename!r} must not start with '_'"
                )

            files_to_read.append(override_filename)

        self.log.debug(
            f"Reading configuration from config_dir{self.config_dir}, "
            f"git_hash={git_hash!r}, "
            f"files={files_to_read}"
        )
        config = self.read_config_files(
            config_validator=self.config_validator,
            config_dir=self.config_dir,
            files_to_read=files_to_read,
            git_hash=git_hash,
        )
        await self.configure(config)
        self.evt_configurationApplied.set_put(  # type: ignore
            configurations=",".join(files_to_read)
        )

    @abc.abstractmethod
    async def configure(self, config: typing.Any) -> None:
        """Configure the CSC.

        Parameters
        ----------
        config : `object`
            The configuration, as described by the config schema,
            as a struct-like object.

        Notes
        -----
        Called when running the ``start`` command, just before changing
        summary state from `State.STANDBY` to `State.DISABLED`.
        """
        raise NotImplementedError("Subclasses must override")

    @staticmethod
    @abc.abstractmethod
    def get_config_pkg() -> str:
        """Get the name of the configuration package, e.g. "ts_config_ocs"."""
        raise NotImplementedError()

    def _get_default_config_dir(self, name: str) -> pathlib.Path:
        """Compute the default package directory for configuration files.

        Parameters
        ----------
        name : `str`
            SAL component name.

        Returns
        -------
        config_dir : `pathlib.Path`
            Default package directory for configuration files.

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

            Test/v2
        """
        config_pkg = self.get_config_pkg()
        config_env_var_name = f"{config_pkg.upper()}_DIR"
        try:
            config_pkg_dir: type_hints.PathType = os.environ[config_env_var_name]
        except KeyError:
            raise RuntimeError(
                f"Environment variable {config_env_var_name} not defined"
            )
        config_pkg_dir = pathlib.Path(config_pkg_dir).resolve()
        if not config_pkg_dir.is_dir():
            raise RuntimeError(
                f"{config_pkg_dir!r} = ${config_env_var_name} "
                "does not exists or is not a directory"
            )

        config_dir = config_pkg_dir / name / self.schema_version
        if not config_dir.is_dir():
            raise RuntimeError(
                f"{config_dir} = ${config_env_var_name}/SAL_component_name/schema_version "
                "does not exist or is not a directory"
            )
        return config_dir

    @classmethod
    def add_arguments(cls, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "--configdir",
            help="directory containing configuration files "
            "(only specify if you are sure the default will not suffice)",
        )
        if cls.enable_cmdline_state:
            parser.add_argument(
                "--override",
                help="override to apply if --state is disabled or enabled (ignored otherwise)",
                default="",
            )

    @classmethod
    def add_kwargs_from_args(
        cls, args: argparse.Namespace, kwargs: typing.Dict[str, typing.Any]
    ) -> None:
        kwargs["config_dir"] = args.configdir
        if hasattr(args, "override"):
            kwargs["override"] = args.override
