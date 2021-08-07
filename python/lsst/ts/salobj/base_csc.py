from __future__ import annotations

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

__all__ = ["BaseCsc"]

import argparse
import asyncio
import enum
import sys
import typing
import warnings

from . import base
from . import dds_utils
from . import type_hints
from .sal_enums import State
from .controller import Controller
from .csc_utils import make_state_transition_dict

HEARTBEAT_INTERVAL = 1  # seconds


class BaseCsc(Controller):
    """Base class for a Commandable SAL Component (CSC)

    To implement a CSC in Python define a subclass of this class.

    Parameters
    ----------
    name : `str`
        Name of SAL component.
    index : `int` or `None`
        SAL component index, or 0 or None if the component is not indexed.
    initial_state : `State` or `int`, optional
        Initial state for this CSC.
        Typically `State.STANDBY` (or `State.OFFLINE` for an
        externally commandable CSC) but can also be
        `State.DISABLED`, or `State.ENABLED`,
        in which case you may also want to specify
        ``settings_to_apply`` for a configurable CSC.
    settings_to_apply : `str`, optional
        Settings to apply if ``initial_state`` is `State.DISABLED`
        or `State.ENABLED`. Ignored if the CSC is not configurable.
    simulation_mode : `int`, optional
        Simulation mode. The default is 0: do not simulate.

    Raises
    ------
    ValueError
        If ``initial_state`` is invalid.
    salobj.ExpectedError
        If ``simulation_mode`` is invalid.
        Note: you will only see this error if you await `start_task`.

    Attributes
    ----------
    default_initial_state : `State`
        A *class* attribute.
        Default initial state. Leave at `State.STANDBY` for most CSCs;
        set to `State.OFFLINE` for externally commandable CSCs.
    enable_cmdline_state : `State`
        A *class* attribute.
        If `True` then add ``--state`` and (if a subclass of `ConfigurableCsc`)
        ``--settings`` command-line arguments.
        The default is `False` because CSCs should start in
        ``default_initial_state`` unless we have good reason to do otherwise.
    require_settings : `bool`
        A *class* attribute.
        Controls whether the ``--settings`` command-line argument
        is required if ``--state`` is specified.
        Ignored unless ``enable_cmdline_state`` is True
        and the CSC is a subclass of `ConfigurableCsc`.
    simulation_help : `str`
        A *class* attribute.
        Help for the --simulate command, or None for the default help
        (which is fine for the usual case of 0/1).
        Ignored if simulation is not supported.
    valid_simulation_modes : `list` [`int`] or `None`
        A *class* attribute. A value of `None` is deprecated
        (though it is the default, for backwards compatibility;
        once `None` is prohibited there will be no default).
        If not `None` has the following effect:

        * ``simulation_mode`` will be checked in the constructor
        * `implement_simulation_mode` will be a no-op.
        * The `amain` command parser will have a ``--simulate`` argument.
          The default value will be 0 if that is a valid simulation mode
          (and it certainly should be).
          Otherwise the default value will be the first entry.
    version : `str`
        A *class* attribute. Used to set the ``cscVersion`` attribute of the
        ``softwareVersions`` event. You should almost always set this to
        your package's ``__version__`` attribute.
    heartbeat_interval : `float`
        Interval between heartbeat events, in seconds;

    Notes
    -----
    **Constructor**

    The constructor does the following, beyond the parent class constructor:

    * For each command defined for the component, find a ``do_<name>`` method
      (which must be present) and add it as a callback to the
      ``cmd_<name>`` attribute.
    * The base class provides asynchronous ``do_<name>`` methods for the
      standard CSC commands. The default implementation is as follows
      (if any step fails then the remaining steps are not performed):

        * Check for validity of the requested state change;
          if the change is valid then:
        * Call ``begin_<name>``. This is a no-op in the base class,
          and is available for the subclass to override. If this fails,
          then log an error and acknowledge the command as failed.
        * Change self.summary_state.
        * Call ``end_<name>``. Again, this is a no-op in the base class,
          and is available for the subclass to override.
          If this fails then revert ``self.summary_state``, log an error,
          and acknowledge the command as failed.
        * Call `handle_summary_state` and `report_summary_state`
          to handle report the new summary state.
          If this fails then leave the summary state updated
          (since the new value *may* have been reported),
          but acknowledge the command as failed.
        * Acknowledge the command as complete.

    * Set the summary state.
    * Run `start` asynchronously.
    """

    # See Attributes in the doc string.
    default_initial_state: State = State.STANDBY
    enable_cmdline_state = False
    require_settings: bool = False
    valid_simulation_modes: typing.Optional[typing.Sequence[int]] = None
    simulation_help: typing.Optional[str] = None

    def __init__(
        self,
        name: str,
        index: typing.Optional[int] = None,
        initial_state: State = State.STANDBY,
        settings_to_apply: str = "",
        simulation_mode: int = 0,
    ) -> None:
        # Check for consistent require_settings and enable_cmdline_state.
        # Do that here, instead of in make_from_cmd_line, to  make sure
        # the developer sees the problem.
        if self.require_settings and not self.enable_cmdline_state:
            raise RuntimeError(
                "Class variable require_settings=True "
                "requires class variable enable_cmdline_state=True"
            )

        # cast initial_state from an int or State to a State,
        # and reject invalid int values with ValueError
        initial_state = State(initial_state)
        if initial_state == State.FAULT:
            raise ValueError("initial_state cannot be FAULT")

        if self.valid_simulation_modes is None:
            warnings.warn(
                "valid_simulation_modes=None is deprecated", DeprecationWarning
            )
        else:
            if simulation_mode not in self.valid_simulation_modes:
                raise ValueError(
                    f"simulation_mode={simulation_mode} "
                    f"not in valid_simulation_modes={self.valid_simulation_modes}"
                )

        self._settings_to_apply = settings_to_apply
        self._summary_state = State(self.default_initial_state)
        self._initial_state = initial_state
        self._faulting = False
        self._heartbeat_task = base.make_done_future()
        # Interval between heartbeat events (sec)
        self.heartbeat_interval = HEARTBEAT_INTERVAL

        if not hasattr(self, "version"):
            warnings.warn(
                "Please set class attribute `version`. It is needed to set "
                "the `cscVersion` field of the `softwareVersions` event.",
                DeprecationWarning,
            )

        # Postpone assigning command callbacks until `start` is done (but call
        # assert_do_methods_present to fail early if there is a problem).
        super().__init__(name=name, index=index, do_callbacks=True)

        # Set evt_simulationMode, now that it is available.
        self.evt_simulationMode.set(mode=int(simulation_mode))  # type: ignore

        def format_version(version: typing.Optional[str]) -> str:
            return "?" if version is None else version

        self.evt_softwareVersions.set(  # type: ignore
            salVersion=format_version(self.salinfo.metadata.sal_version),
            xmlVersion=format_version(self.salinfo.metadata.xml_version),
            openSpliceVersion=dds_utils.get_dds_version(),
            cscVersion=getattr(self, "version", "?"),
        )

    async def start(self) -> None:
        """Finish constructing the CSC.

        * Call `set_simulation_mode`. If this fails, set ``self.start_task``
          to the exception, call `stop`, making the CSC unusable, and return.
        * Call `handle_summary_state` and `report_summary_state`.
        * Set ``self.start_task`` done.
        """
        await super().start()
        self._heartbeat_task.cancel()  # Paranoia
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
        await self.set_simulation_mode(self.simulation_mode)

        # Handle initial state, then transition to the desired state.
        # If this fails then log the exception and continue,
        # in hopes that the CSC can still be used. For instance
        # if the settings were invalid, the user can specify others.
        await self.handle_summary_state()
        self.report_summary_state()
        command = None
        if self._initial_state != self.default_initial_state:
            state_transition_dict = make_state_transition_dict()
            # List of commands to transition from
            # current state to initial_state.
            # Use the current state instead of default_initial_state
            # because of Hexapod and Rotator, which do not know their
            # current state until they connect to the low-level controller.
            command_state_list = state_transition_dict[
                (self.summary_state, self._initial_state)
            ]
            state_transition_commands = [item[0] for item in command_state_list]
            try:
                for command in state_transition_commands:
                    method = getattr(self, f"do_{command}")
                    data = getattr(self, f"cmd_{command}").DataType()
                    if command == "start":
                        data.settingsToApply = self._settings_to_apply
                    self.log.info(f"Executing {command} command during startup")
                    await method(data)
            except Exception:
                self.log.exception(
                    f"Failed in start on state transition command {command}; continuing."
                )

        self.evt_softwareVersions.put()  # type: ignore

    async def close_tasks(self) -> None:
        """Shut down pending tasks. Called by `close`."""
        self._heartbeat_task.cancel()

    @classmethod
    def make_from_cmd_line(
        cls, index: typing.Union[int, enum.IntEnum, bool, None], **kwargs: typing.Any
    ) -> BaseCsc:
        """Construct a CSC from command line arguments.

        Parameters
        ----------
        index : `int`, `enum.IntEnum`, `True`, or `None`
            If the CSC is indexed, do one of the following:

            * Specify `True` to make ``index`` a required
              command-line argument that accepts any nonzero index.
            * Specify an `enum.IntEnum` *class* to make ``index`` a required
              command-line argument that only accepts the enum values.
            * Specify a non-zero integer to use that index.
              This is rare; if the CSC is indexed then the user
              should usually be allowed to specify the index.

            If the CSC is not indexed, specify `None` or 0.
        **kwargs : `dict`, optional
            Additional keyword arguments for your CSC's constructor.

        Returns
        -------
        csc : ``cls``
            The CSC.

        Notes
        -----
        To add additional command-line arguments, override `add_arguments`
        and `add_kwargs_from_args`.
        """
        parser = argparse.ArgumentParser(f"Run {cls.__name__}")
        if index is True:
            parser.add_argument("index", type=int, help="SAL index.")
        elif isinstance(index, type) and issubclass(index, enum.IntEnum):
            # The isinstance check just above prevents errors
            # when index is an int or bool.
            choices = [int(item.value) for item in index]  # type: ignore
            names_str = ", ".join(
                f"{item.value}: {item.name.lower()}" for item in index  # type: ignore
            )
            help_text = f"SAL index, one of: {names_str}"
            parser.add_argument("index", type=int, help=help_text, choices=choices)
        parser.add_argument(
            "--loglevel",
            type=int,
            help="log level: error=40, warning=30, info=20, debug=10",
        )
        if cls.enable_cmdline_state:
            parser.add_argument(
                "--state",
                choices=["offline", "standby", "disabled", "enabled"],
                dest="initial_state",
                help="initial state",
            )
        add_simulate_arg = (
            cls.valid_simulation_modes is not None
            and len(cls.valid_simulation_modes) > 1
        )
        if add_simulate_arg:
            assert cls.valid_simulation_modes is not None  # make mypy happy
            if 0 in cls.valid_simulation_modes:
                default_simulation_mode: int = 0
            else:
                default_simulation_mode = cls.valid_simulation_modes[0]
            if default_simulation_mode == 0 and len(cls.valid_simulation_modes) == 2:
                # There are only two simulation modes, one of which is 0.
                # Make --simulate a flag that takes no value and stores
                # the other value, if specified.
                simulation_help = (
                    "Run in simulation mode?"
                    if cls.simulation_help is None
                    else cls.simulation_help
                )
                nonzero_value = (set(cls.valid_simulation_modes) - set([0])).pop()
                parser.add_argument(
                    "--simulate",
                    help=simulation_help,
                    default=0,
                    action="store_const",
                    const=nonzero_value,
                )
            else:
                # There are more than 2 simulation modes or none of them is 0.
                # Make --simulate an argument that requires a value.
                simulation_help = (
                    "Simulation mode"
                    if cls.simulation_help is None
                    else cls.simulation_help
                )
                parser.add_argument(
                    "--simulate",
                    type=int,
                    help=simulation_help,
                    default=default_simulation_mode,
                    choices=cls.valid_simulation_modes,
                )

        try:
            version = getattr(cls, "version", None)
            if version is not None:
                parser.add_argument("--version", action="version", version=version)
        except ImportError:
            warnings.warn(
                "No --version command-line argument because __version__ is unavailable.",
                RuntimeWarning,
            )
        cls.add_arguments(parser)

        args = parser.parse_args()
        if hasattr(args, "index"):
            kwargs["index"] = args.index
        elif not index:
            pass
        else:
            kwargs["index"] = int(index)
        if add_simulate_arg:
            kwargs["simulation_mode"] = args.simulate
        state_arg = getattr(args, "initial_state", None)
        if state_arg is not None:
            initial_state_name = state_arg.upper()
            initial_state = getattr(State, initial_state_name)
            kwargs["initial_state"] = initial_state
        if hasattr(args, "settings_to_apply"):
            # A configurable CSC with constructor arg ``settings_to_apply``
            if args.settings_to_apply is not None:
                kwargs["settings_to_apply"] = args.settings_to_apply
            elif cls.require_settings and args.initial_state in ("disabled", "enabled"):
                parser.error(
                    "You must specify --settings if you specify --state disabled or enabled"
                )
        cls.add_kwargs_from_args(args=args, kwargs=kwargs)

        csc = cls(**kwargs)
        if args.loglevel is not None:
            csc.log.setLevel(args.loglevel)
        return csc

    @classmethod
    async def amain(
        cls, index: typing.Union[int, enum.IntEnum, bool, None], **kwargs: typing.Any
    ) -> None:
        """Make a CSC from command-line arguments and run it.

        Parameters
        ----------
        index : `int`, `enum.IntEnum`, `True`, or `None`
            If the CSC is indexed, do one of the following:

            * Specify `True` to make ``index`` a required
              command-line argument that accepts any nonzero index.
            * Specify an `enum.IntEnum` *class* to make ``index`` a required
              command-line argument that only accepts the enum values.
            * Specify a non-zero integer to use that index.
              This is rare; if the CSC is indexed then the user
              should usually be allowed to specify the index.

            If the CSC is not indexed, specify `None` or 0.
        **kwargs : `dict`, optional
            Additional keyword arguments for your CSC's constructor.
        """
        csc = cls.make_from_cmd_line(index=index, **kwargs)
        await csc.done_task

    @classmethod
    def add_arguments(cls, parser: argparse.ArgumentParser) -> None:
        """Add arguments to the parser created by `make_from_cmd_line`.

        Parameters
        ----------
        parser : `argparse.ArgumentParser`
            The argument parser.

        Notes
        -----
        If you override this method then you should almost certainly override
        `add_kwargs_from_args` as well.
        """
        pass

    @classmethod
    def add_kwargs_from_args(
        cls, args: argparse.Namespace, kwargs: typing.Dict[str, typing.Any]
    ) -> None:
        """Add constructor keyword arguments based on parsed arguments.

        Parameters
        ----------
        args : `argparse.Namespace`
            Parsed command.
        kwargs : `dict`
            Keyword argument dict for the constructor.
            Update this based on ``args``.
            The index argument will already be present if relevant.

        Notes
        -----
        If you override this method then you should almost certainly override
        `add_arguments` as well.
        """
        pass

    async def do_disable(self, data: type_hints.BaseDdsDataType) -> None:
        """Transition from `State.ENABLED` to `State.DISABLED`.

        Parameters
        ----------
        data : ``cmd_disable.DataType``
            Command data
        """
        await self._do_change_state(data, "disable", [State.ENABLED], State.DISABLED)

    async def do_enable(self, data: type_hints.BaseDdsDataType) -> None:
        """Transition from `State.DISABLED` to `State.ENABLED`.

        Parameters
        ----------
        data : ``cmd_enable.DataType``
            Command data
        """
        await self._do_change_state(data, "enable", [State.DISABLED], State.ENABLED)

    async def do_exitControl(self, data: type_hints.BaseDdsDataType) -> None:
        """Transition from `State.STANDBY` to `State.OFFLINE` and quit.

        Parameters
        ----------
        data : ``cmd_exitControl.DataType``
            Command data
        """
        await self._do_change_state(data, "exitControl", [State.STANDBY], State.OFFLINE)

        asyncio.create_task(self.close())

    async def do_standby(self, data: type_hints.BaseDdsDataType) -> None:
        """Transition from `State.DISABLED` or `State.FAULT` to
        `State.STANDBY`.

        Parameters
        ----------
        data : ``cmd_standby.DataType``
            Command data
        """
        await self._do_change_state(
            data, "standby", [State.DISABLED, State.FAULT], State.STANDBY
        )

    async def do_start(self, data: type_hints.BaseDdsDataType) -> None:
        """Transition from `State.STANDBY` to `State.DISABLED`.

        Parameters
        ----------
        data : ``cmd_start.DataType``
            Command data
        """
        await self._do_change_state(data, "start", [State.STANDBY], State.DISABLED)

    @property
    def simulation_mode(self) -> int:
        """Get the current simulation mode.

        0 means normal operation (no simulation).

        Raises
        ------
        ExpectedError
            If the new simulation mode is not a supported value.

        """
        return self.evt_simulationMode.data.mode  # type: ignore

    async def set_simulation_mode(self, simulation_mode: int) -> None:
        """Set the simulation mode.

        Await implement_simulation_mode, update the simulation mode
        property and report the new value.

        Parameters
        ----------
        simulation_mode : `int`
            Requested simulation mode; 0 for normal operation.
        """
        await self.implement_simulation_mode(simulation_mode)

        self.evt_simulationMode.set_put(mode=simulation_mode, force_output=True)  # type: ignore

    async def implement_simulation_mode(self, simulation_mode: int) -> None:
        """Implement going into or out of simulation mode.

        Deprecated. See :ref:`simulation mode<lsst.ts.salobj-simulation_mode>`
        for details.

        Parameters
        ----------
        simulation_mode : `int`
            Requested simulation mode; 0 for normal operation.

        Raises
        ------
        ExpectedError
            If ``simulation_mode`` is not a supported value.
        """
        if self.valid_simulation_modes is not None:
            return

        # Handle the deprecated case.
        if simulation_mode != 0:
            raise base.ExpectedError(
                f"This CSC does not support simulation; simulation_mode={simulation_mode} but must be 0"
            )

    async def begin_disable(self, data: type_hints.BaseDdsDataType) -> None:
        """Begin do_disable; called before state changes.

        Parameters
        ----------
        data : `DataType`
            Command data
        """
        pass

    async def begin_enable(self, data: type_hints.BaseDdsDataType) -> None:
        """Begin do_enable; called before state changes.

        Parameters
        ----------
        data : `DataType`
            Command data
        """
        pass

    async def begin_exitControl(self, data: type_hints.BaseDdsDataType) -> None:
        """Begin do_exitControl; called before state changes.

        Parameters
        ----------
        data : `DataType`
            Command data
        """
        pass

    async def begin_standby(self, data: type_hints.BaseDdsDataType) -> None:
        """Begin do_standby; called before the state changes.

        Parameters
        ----------
        data : `DataType`
            Command data
        """
        pass

    async def begin_start(self, data: type_hints.BaseDdsDataType) -> None:
        """Begin do_start; called before state changes.

        Parameters
        ----------
        data : `DataType`
            Command data
        """
        pass

    async def end_disable(self, data: type_hints.BaseDdsDataType) -> None:
        """End do_disable; called after state changes
        but before command acknowledged.

        Parameters
        ----------
        data : `DataType`
            Command data
        """
        pass

    async def end_enable(self, data: type_hints.BaseDdsDataType) -> None:
        """End do_enable; called after state changes
        but before command acknowledged.

        Parameters
        ----------
        data : `DataType`
            Command data
        """
        pass

    async def end_exitControl(self, data: type_hints.BaseDdsDataType) -> None:
        """End do_exitControl; called after state changes
        but before command acknowledged.

        Parameters
        ----------
        data : `DataType`
            Command data
        """
        pass

    async def end_standby(self, data: type_hints.BaseDdsDataType) -> None:
        """End do_standby; called after state changes
        but before command acknowledged.

        Parameters
        ----------
        data : `DataType`
            Command data
        """
        pass

    async def end_start(self, data: type_hints.BaseDdsDataType) -> None:
        """End do_start; called after state changes
        but before command acknowledged.

        Parameters
        ----------
        data : `DataType`
            Command data
        """
        pass

    def fault(
        self, code: typing.Optional[int], report: str, traceback: str = ""
    ) -> None:
        """Enter the fault state and output the ``errorCode`` event.

        Parameters
        ----------
        code : `int`
            Error code for the ``errorCode`` event.
            If `None` then ``errorCode`` is not output and you should
            output it yourself. Specifying `None` is deprecated;
            please always specify an integer error code.
        report : `str`
            Description of the error.
        traceback : `str`, optional
            Description of the traceback, if any.
        """
        if self._faulting:
            return

        try:
            self._faulting = True
            self._summary_state = State.FAULT
            if code is not None:
                try:
                    self.evt_errorCode.set_put(  # type: ignore
                        errorCode=code,
                        errorReport=report,
                        traceback=traceback,
                        force_output=True,
                    )
                except Exception:
                    self.log.exception(
                        f"Failed to output errorCode: code={code!r}; report={report!r}"
                    )
            try:
                self.report_summary_state()
            except Exception:
                self.log.exception(
                    "report_summary_state failed while going to FAULT; "
                    "some code may not have run."
                )
                self.evt_summaryState.set_put(  # type: ignore
                    summaryState=self._summary_state,
                )  # type: ignore
            asyncio.create_task(self.handle_summary_state())
        finally:
            self._faulting = False

    def assert_enabled(self, action: str = "") -> None:
        """Assert that an action that requires ENABLED state can be run.

        Parameters
        ----------
        action : `str`, optional
            Action attempted. Not needed if this is called at the beginning
            of a ``do_...`` method, since the user will know what command
            was called.
        """
        if self.summary_state != State.ENABLED:
            what = f"{action} not allowed" if action else "Not allowed"
            errorCode = self.evt_errorCode.data.errorCode  # type: ignore
            errorReport = self.evt_errorCode.data.errorReport  # type: ignore
            if self.summary_state == State.FAULT:
                why = (
                    "in Fault state: "
                    f"errorCode={errorCode}, "  # type:ignore
                    f"errorReport={errorReport!r}"  # type: ignore
                )
            else:
                why = f"in state={self.summary_state!r}"
            raise base.ExpectedError(f"{what} {why}")

    @property
    def disabled_or_enabled(self) -> bool:
        """Return True if the summary state is `State.DISABLED` or
        `State.ENABLED`.

        This is useful in `handle_summary_state` to determine if
        you should start or stop a telemetry loop,
        and connect to or disconnect from an external controller
        """
        return self.summary_state in (State.DISABLED, State.ENABLED)

    @property
    def summary_state(self) -> State:
        """Get the summary state as a `State` enum."""
        return self._summary_state

    async def handle_summary_state(self) -> None:
        """Called when the summary state has changed.

        Override to perform tasks such as starting and stopping telemetry
        (`example <https://ts-salobj.lsst.io/salobj_cscs.html
        #telemetry-loop-example>`_).

        Notes
        -----
        The versions in `BaseCsc` and `ConfigurableCsc` do nothing,
        so if you subclass one of those you do not need to call
        ``await super().handle_summary_state()``.
        """
        pass

    def report_summary_state(self) -> None:
        """Report a new value for summary_state, including current state.

        Subclasses may wish to override for code that depends on
        the current state (rather than the state transition command
        that got it into that state).
        """
        self.evt_summaryState.set_put(summaryState=self.summary_state)  # type: ignore

    async def _do_change_state(
        self,
        data: typing.Any,
        cmd_name: str,
        allowed_curr_states: typing.Sequence[State],
        new_state: State,
    ) -> None:
        """Change to the desired state.

        Parameters
        ----------
        data : `DataType`
            Command data
        cmd_name : `str`
            Name of command, e.g. "disable" or "exitControl".
        allowed_curr_states : `list` of `State`
            Allowed current states
        new_state : `State`
            Desired new state.
        """
        curr_state = self.summary_state
        if curr_state not in allowed_curr_states:
            raise base.ExpectedError(f"{cmd_name} not allowed in state {curr_state!r}")
        try:
            await getattr(self, f"begin_{cmd_name}")(data)
        except base.ExpectedError as e:
            self.log.error(
                f"beg_{cmd_name} failed; remaining in state {curr_state!r}: {e}"
            )
            raise
        except Exception:
            self.log.exception(
                f"beg_{cmd_name} failed; remaining in state {curr_state!r}"
            )
            raise
        self._summary_state = new_state
        try:
            await getattr(self, f"end_{cmd_name}")(data)
        except base.ExpectedError as e:
            self.log.error(
                f"beg_{cmd_name} failed; reverting to state {curr_state!r}: {e}"
            )
            raise
        except Exception:
            self._summary_state = curr_state
            self.log.exception(
                f"end_{cmd_name} failed; reverting to state {curr_state!r}"
            )
            raise
        await self.handle_summary_state()
        self.report_summary_state()

    async def _heartbeat_loop(self) -> None:
        """Output heartbeat at regular intervals."""
        while True:
            try:
                await asyncio.sleep(self.heartbeat_interval)
                self.evt_heartbeat.put()  # type: ignore
            except asyncio.CancelledError:
                break
            except Exception as e:
                # don't use the log because it also uses DDS messaging
                print(f"Heartbeat output failed: {e!r}", file=sys.stderr)
