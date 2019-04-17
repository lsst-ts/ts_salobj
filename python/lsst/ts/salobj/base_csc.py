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

__all__ = ["BaseCsc", "State"]

import argparse
import asyncio
import enum
import sys

from . import base
from .controller import Controller

HEARTBEAT_INTERVAL = 1  # seconds


class State(enum.IntEnum):
    """CSC summaryState constants.
    """
    # This does not use SALPY enum values because that would require a SALPY
    # library. Using hard-coded values makes State available to all packages
    # without having to know which SALPY library the package uses.
    OFFLINE = 4
    STANDBY = 5
    DISABLED = 1
    ENABLED = 2
    FAULT = 3


class BaseCsc(Controller):
    """Base class for a Commandable SAL Component (CSC)

    To implement a CSC in Python define a subclass of this class.

    Parameters
    ----------
    sallib : ``module``
        salpy component library generatedby SAL
    index : `int` or `None`
        SAL component index, or 0 or None if the component is not indexed.
    initial_state : `State` or `int` (optional)
        The initial state of the CSC. This is provided for unit testing,
        as real CSCs should start up in `State.STANDBY`, the default.
    initial_simulation_mode : `int` (optional)
        Initial simulation mode. This is provided for unit testing,
        as real CSCs should start up not simulating, the default.

    Raises
    ------
    salobj.ExpectedError
        If initial_state or initial_simulation_mode is invalid.

    Notes
    -----
    The constructor does the following:

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
        * Call `report_summary_state` to report the new summary state.
          If this fails then leave the summary state updated
          (since the new value *may* have been reported),
          but acknowledge the command as failed.
        * Acknowledge the command as complete.

    * Set the summary state.
    * Run `start` asynchronously.
    """
    def __init__(self, sallib, index=None, initial_state=State.STANDBY, initial_simulation_mode=0):
        # cast initial_state from an int or State to a State,
        # and reject invalid int values with ValueError
        initial_state = State(initial_state)
        super().__init__(sallib, index, do_callbacks=True)
        self._summary_state = State(initial_state)
        self._heartbeat_task = asyncio.ensure_future(self._heartbeat_loop())
        self.heartbeat_interval = HEARTBEAT_INTERVAL
        """Interval between heartbeat events (sec)."""
        self.start_task = asyncio.Future()
        """This task is set done when the CSC is fully started.

        If `start` fails then the task has an exception set
        and the CSC is not usable.
        """
        self.done_task = asyncio.Future()
        """This task is set done when the CSC is done, which is when
        the ``exitControl`` command is received.
        """
        asyncio.ensure_future(self.start(initial_simulation_mode))

    async def start(self, initial_simulation_mode):
        """Finish constructing the CSC.

        * Call `set_simulation_mode`. If this fails, set ``self.start_task``
          to the exception, call `stop`, making the CSC unusable, and return.
        * Call `report_summary_state`
        * Set ``self.start_task`` done.

        Parameters
        ----------
        initial_simulation_mode : `int` (optional)
            Initial simulation mode.
        """
        try:
            await self.set_simulation_mode(initial_simulation_mode)
        except Exception as e:
            self.start_task.set_exception(e)
            await self.stop(exception=e)
            return

        self.report_summary_state()
        self.start_task.set_result(None)

    async def stop(self, exception=None):
        """Stop the CSC.

        Stop all background tasks and set ``self.done_task`` done.
        `main` and other code that runs CSCs should exit when
        ``self.done_task`` is done.

        Parameters
        ----------
        exception : `Exception` (optional)
            The exception that caused stopping, if any, in which case
            the ``self.done_task`` exception is set to this value.
            Specify `None` for a normal exit, in which case
            the ``self.done_task`` result is set to `None`.
        """
        await asyncio.sleep(0.1)
        self._heartbeat_task.cancel()
        if exception:
            self.done_task.set_exception(exception)
        else:
            self.done_task.set_result(None)

    @classmethod
    def main(cls, index, run_loop=True, **kwargs):
        """Start the CSC from the command line.

        Parameters
        ----------
        index : `int`, `True`, `False` or `None`
            If the CSC is indexed: specify `True` make index a required
            command line argument, or specify a non-zero `int` to use
            that index.
            If the CSC is not indexed: specify `None` or `False`.
        run_loop : `bool` (optional)
            Start an event loop? Set True for normal CSC operation.
            False is convenient for some kinds of testing.
        **kwargs : `dict` (optional)
            Additional keyword arguments for your CSC's constructor.
            If any arguments match those from the command line
            the command line values will be used.

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
            parser.add_argument("index", type=int,
                                help="Script SAL Component index.")
        cls.add_arguments(parser)

        args = parser.parse_args()
        if index is True:
            kwargs["index"] = args.index
        elif index in (None, False):
            pass
        else:
            kwargs["index"] = int(index)
        cls.add_kwargs_from_args(args=args, kwargs=kwargs)

        csc = cls(**kwargs)
        if run_loop:
            asyncio.get_event_loop().run_until_complete(csc.done_task)
        return csc

    @classmethod
    def add_arguments(cls, parser):
        """Add arguments to the argument parser created by `main`.

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
    def add_kwargs_from_args(cls, args, kwargs):
        """Add constructor keyword arguments based on parsed arguments.

        Parameters
        ----------
        args : `argparse.namespace`
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

    async def do_disable(self, id_data):
        """Transition to from `State.ENABLED` to `State.DISABLED`.

        Parameters
        ----------
        id_data : `CommandIdData`
            Command ID and data
        """
        await self._do_change_state(id_data, "disable", [State.ENABLED], State.DISABLED)

    async def do_enable(self, id_data):
        """Transition from `State.DISABLED` to `State.ENABLED`.

        Parameters
        ----------
        id_data : `CommandIdData`
            Command ID and data
        """
        await self._do_change_state(id_data, "enable", [State.DISABLED], State.ENABLED)

    async def do_exitControl(self, id_data):
        """Transition from `State.STANDBY` to `State.OFFLINE` and quit.

        Parameters
        ----------
        id_data : `CommandIdData`
            Command ID and data
        """
        await self._do_change_state(id_data, "exitControl", [State.STANDBY], State.OFFLINE)

        asyncio.ensure_future(self.stop())

    async def do_standby(self, id_data):
        """Transition from `State.DISABLED` or `State.FAULT` to
        `State.STANDBY`.

        Parameters
        ----------
        id_data : `CommandIdData`
            Command ID and data
        """
        await self._do_change_state(id_data, "standby", [State.DISABLED, State.FAULT], State.STANDBY)

    async def do_start(self, id_data):
        """Transition to from `State.STANDBY` to `State.DISABLED`.

        Parameters
        ----------
        id_data : `CommandIdData`
            Command ID and data
        """
        await self._do_change_state(id_data, "start", [State.STANDBY], State.DISABLED)

    async def do_setSimulationMode(self, id_data):
        """Enter or leave simulation mode.

        The CSC must be in `State.STANDBY` or `State.DISABLED` state.

        Parameters
        ----------
        id_data : `CommandIdData`
            Command ID and data

        Notes
        -----
        To implement simulation mode: override `implement_simulation_mode`.
        """
        if self.summary_state not in (State.STANDBY, State.DISABLED):
            raise base.ExpectedError(f"Cannot set simulation_mode in state {self.summary_state!r}")
        await self.set_simulation_mode(id_data.data.mode)

    @property
    def simulation_mode(self):
        """Get or set the current simulation mode.

        0 means normal operation (no simulation).

        Raises
        ------
        ExpectedError
            If the new simulation mode is not a supported value.

        """
        return self.evt_simulationMode.data.mode

    async def set_simulation_mode(self, simulation_mode):
        """Set the simulation mode.

        Await implement_simulation_mode, update the simulation mode
        property and report the new value.

        Parameters
        ----------
        simulation_mode : `int`
            Requested simulation mode; 0 for normal operation.
        """
        await self.implement_simulation_mode(simulation_mode)

        self.evt_simulationMode.set_put(mode=simulation_mode, force_output=True)

    async def implement_simulation_mode(self, simulation_mode):
        """Implement going into or out of simulation mode.

        Parameters
        ----------
        simulation_mode : `int`
            Requested simulation mode; 0 for normal operation.

        Raises
        ------
        ExpectedError
            If ``simulation_mode`` is not a supported value.

        Notes
        -----
        Subclasses should override this method to implement simulation
        mode. The implementation should:

        * Check the value of ``simulation_mode`` and raise
          `ExpectedError` if not supported.
        * If ``simulation_mode`` is 0 then go out of simulation mode.
        * If ``simulation_mode`` is nonzero then enter the requested
          simulation mode.

        Do not check the current summary state, nor set the
        ``simulation_mode`` property nor report the new mode.
        All of that is handled `do_setSimulationMode`.
        """
        if simulation_mode != 0:
            raise base.ExpectedError(
                f"This CSC does not support simulation; simulation_mode={simulation_mode} but must be 0")

    async def begin_disable(self, id_data):
        """Begin do_disable; called before state changes.

        Parameters
        ----------
        id_data : `CommandIdData`
            Command ID and data
        """
        pass

    async def begin_enable(self, id_data):
        """Begin do_enable; called before state changes.

        Parameters
        ----------
        id_data : `CommandIdData`
            Command ID and data
        """
        pass

    async def begin_exitControl(self, id_data):
        """Begin do_exitControl; called before state changes.

        Parameters
        ----------
        id_data : `CommandIdData`
            Command ID and data
        """
        pass

    async def begin_standby(self, id_data):
        """Begin do_standby; called before the state changes.

        Parameters
        ----------
        id_data : `CommandIdData`
            Command ID and data
        """
        pass

    async def begin_start(self, id_data):
        """Begin do_start; called before state changes.

        Parameters
        ----------
        id_data : `CommandIdData`
            Command ID and data
        """
        pass

    async def end_disable(self, id_data):
        """End do_disable; called after state changes
        but before command acknowledged.

        Parameters
        ----------
        id_data : `CommandIdData`
            Command ID and data
        """
        pass

    async def end_enable(self, id_data):
        """End do_enable; called after state changes
        but before command acknowledged.

        Parameters
        ----------
        id_data : `CommandIdData`
            Command ID and data
        """
        pass

    async def end_exitControl(self, id_data):
        """End do_exitControl; called after state changes
        but before command acknowledged.

        Parameters
        ----------
        id_data : `CommandIdData`
            Command ID and data
        """
        pass

    async def end_standby(self, id_data):
        """End do_standby; called after state changes
        but before command acknowledged.

        Parameters
        ----------
        id_data : `CommandIdData`
            Command ID and data
        """
        pass

    async def end_start(self, id_data):
        """End do_start; called after state changes
        but before command acknowledged.

        Parameters
        ----------
        id_data : `CommandIdData`
            Command ID and data
        """
        pass

    def fault(self, code=None, report=""):
        """Enter the fault state.

        Parameters
        ----------
        code : `int` (optional)
            Error code for the ``errorCode`` event; if None then ``errorCode``
            is not output and you should output it yourself.
        report : `str` (optional)
            Text description of the error.
        """
        if code is not None:
            self.evt_errorCode.set_put(errorCode=code, errorReport=report, force_output=True)
        self.summary_state = State.FAULT

    def assert_enabled(self, action):
        """Assert that an action that requires ENABLED state can be run.
        """
        if self.summary_state != State.ENABLED:
            raise base.ExpectedError(f"{action} not allowed in state {self.summary_state!r}")

    @property
    def summary_state(self):
        """Set or get the summary state as a `State` enum.

        If you set the state then it is reported as a summaryState event.
        You can set summary_state to a `State` constant or to
        the integer equivalent.

        Raises
        ------
        ValueError
            If the new summary state is an invalid integer.
        """
        return self._summary_state

    @summary_state.setter
    def summary_state(self, summary_state):
        # cast summary_state from an int or State to a State,
        # and reject invalid int values with ValueError
        self._summary_state = State(summary_state)
        self.report_summary_state()

    def report_summary_state(self):
        """Report a new value for summary_state, including current state.

        Subclasses may wish to override for code that depends on
        the current state (rather than the state transition command
        that got it into that state).
        """
        self.evt_summaryState.set_put(summaryState=self.summary_state)

    async def _do_change_state(self, id_data, cmd_name, allowed_curr_states, new_state):
        """Change to the desired state.

        Parameters
        ----------
        id_data : `CommandIdData`
            Command ID and data
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
            await getattr(self, f"begin_{cmd_name}")(id_data)
        except Exception:
            self.log.exception(f"beg_{cmd_name} failed; remaining in state {curr_state!r}")
            raise
        self._summary_state = new_state
        try:
            await getattr(self, f"end_{cmd_name}")(id_data)
        except Exception:
            self._summary_state = curr_state
            self.log.exception(f"end_{cmd_name} failed; reverting to state {curr_state!r}")
            raise
        self.report_summary_state()

    async def _heartbeat_loop(self):
        """Output heartbeat at regular intervals.
        """
        while True:
            try:
                await asyncio.sleep(self.heartbeat_interval)
                self.evt_heartbeat.put()
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"Heartbeat output failed: {e}", file=sys.stderr)
