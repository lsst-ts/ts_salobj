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
    """State constants.

    The numeric values come from
    https://confluence.lsstcorp.org/display/SYSENG/SAL+constraints+and+recommendations
    """
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
    salobj.ExpectedException
        If initial_state or initial_simulation_mode is invalid.

    Notes
    -----
    The constructor does the following:

    * For each command defined for the component, find a ``do_<name>`` method
      (which must be present) and add it as a callback to the
      ``cmd_<name>`` attribute.
    * The base class provides synchronous ``do_<name>`` methods for the
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
    * Run the `start` method asynchronously. `start` sets the
      initial simulation mode, and, if that is successful,
      outputs the initial summaryState event and sets
      ``self.start_task`` done. At this point the CSC is running.
      If setting the initial simulation mode fails then `start`
      sets ``self.start_task`` to an exception and calls `stop`,
      making the CSC unusable.

    Standard CSC commands and their associated summary state changes:

    * ``start``: `State.STANDBY` to `State.DISABLED`
    * ``enable``: `State.DISABLED` to `State.ENABLED`

    * ``disable``: `State.ENABLED` to `State.DISABLED`
    * ``exitControl``: `State.STANDBY` to `State.OFFLINE` and then quit
    * ``standby``: `State.DISABLED` or `State.FAULT` to `State.STANDBY`

    .. _writing_a_csc:

    **Writing a CSC**

    * Make your CSC a subclass of `BaseCsc`.
    * Your subclass must provide a ``do_<name>`` method for every command
      that is not part of the standard CSC command set, as well as the
      following optional standard commands, if you want to support them:
      ``abort``, ``enterControl``, and ``setValue``.
      `BaseCsc` implements the standard state transition commands.
    * Each ``do_<name>`` method can be synchronous (``def do_<name>...``)
      or asynchronous (``async def do_<name>...``). If ``do_<name>``
      is asynchronous then the command is automatically acknowledged
      as in progress before the callback starts.
    * If a ``do_<name>`` method must perform slow synchronous operations,
      such as CPU-heavy tasks, make the method asynchronous
      and call the synchronous operation in a thread using
      the ``run_in_executor`` method of the event loop.
    * Your CSC will report the command as failed if the ``do_<name>``
      method raises an exception. The ``result`` field of that
      acknowledgement will be the data in the exception.
      Eventually the CSC may log a traceback, as well,
      but never for `ExpectedError`.
    * By default your CSC will report the command as completed
      when ``do_<name>`` finishes, but you can return a different
      acknowledgement (instance of `SalInfo.AckType`) instead,
      and that will be used as the final command acknowledgement.
    * If you want to allow more than one instance of the command running
      at a time, set ``self.cmd_<name>.allow_multiple_commands = True``
      in your CSC's constructor. See
      `topics.ControllerCommand`.allow_multiple_commands
      for details and limitations of this attribute.
    * Your subclass should construct a `Remote` for any
      remote SAL component it wishes to listen to or command. For example:
      ``self.electrometer1 = salobj.Remote(SALPY_Electrometer, index=1)``.
      You may wish to construct these when you go into the `State.DISABLED`
      state (e.g. order to output telemetry based on input from a remote)
      or `State.ENABLED` state (to command the remote).
    * Summary state:

        * `BaseCsc` provides a default implementation for all summary state
          transition commands that might suffice. However, it does not yet
          handle configuration. See ``ATDomeTrajectory`` for a CSC
          that handles configuration.
        * Most commands should only be allowed to run when the summary state
          is `State.ENABLED`. To check this, put the following as the first
          line of your ``do_<name>`` method: ``self.assert_enabled()``
        * Your subclass may override ``begin_<name>`` and/or ``end_<name>``
          for each state transition command, as appropriate. For complex state
          transitions your subclass may also override ``do_<name>``.
          If any of these methods fail then the state change operation
          is aborted, the summary state does not change, and the command
          is acknowledged as failed.
        * Your subclass may override `report_summary_state` if you wish to
          perform actions based the current summary state.
        * Output the ``errorCode`` event when your CSC goes into the
          `State.FAULT` summary state.

    * Detailed state (optional):

        * The ``detailedState`` event is unique to each CSC.
        * ``detailedState`` is optional, but strongly recommended for
          CSCs that are complex enough to have interesting internal state.
        * Report all information that seem relevant to detailed state
          and is not covered by summary state.
        * Detailed state should be *orthogonal* to summary state.
          You may provide an enum field in your detailedState event, but it
          is not required and, if present, should not include summary states.
    * ``do_`` is a reserved prefix: all ``do_<name>`` attributes must be
      must match a command name and must be callable.
    * Implement :ref:`simulation mode<simulation_mode>`, if practical.
      If your CSC talks to hardware then this is especially important.

    .. _running_a_csc:

    **Running a CSC**

    To run your CSC call the `main` method or equivalent code.
    For an example see ``bin.src/run_test_csc.py``. If you wish to
    provide additional command line arguments then it is probably simplest
    to copy the contents of `main` into your script and adapt it as required.

    In unit tests, wait for ``self.start_task`` to be done, or for the initial
    ``summaryState`` event, before expecting the CSC to be responsive.

    .. _simulation_mode:

    **Simulation Mode**

    CSCs should support a simulation mode if practical; this is especially
    important if the CSC talks to hardware.

    To implement a simulation mode, first pick one or more non-zero values
    for the ``simulation_mode`` property (0 is reserved for normal operation)
    and document what they mean. For example you might use a a bit mask
    to supporting independently simulating multiple different subsystems.

    Then override `implement_simulation_mode` to implement the specified
    simulation mode, if supported, or raise an exception if not.
    Note that this method is called during construction of the CSC.
    The default implementation of `implement_simulation_mode` is to reject
    all non-zero values for ``simulation_mode``.
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
        """Start the CSC.

        Set the initial simulation mode, report the initial summary state,
        and set ``self.start_task`` done.

        Parameters
        ----------
        initial_simulation_mode : `int` (optional)
            Initial simulation mode. If invalid then set an exception on
            ``self.start_task`` and call `stop` to stop the CSC.
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

        Stop background tasks and set ``self.done_task`` done.

        Parameters
        ----------
        exception : `Exception` (optional)
            The exception that caused stopping, if any, else `None`.
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

        Returns
        -------
        csc : ``cls``
            The CSC.

        Notes
        -----
        If you wish to allow additional command-line arguments
        then it is probably simplest to put a version of this code
        in your command-line executable.
        """
        if index is True:
            parser = argparse.ArgumentParser(f"Run {cls.__name__}")
            parser.add_argument("index", type=int,
                                help="Script SAL Component index; must be unique among running Scripts")
            args = parser.parse_args()
            kwargs["index"] = args.index
        elif index in (None, False):
            pass
        else:
            kwargs["index"] = index
        csc = cls(**kwargs)
        if run_loop:
            asyncio.get_event_loop().run_until_complete(csc.done_task)
        return csc

    def do_disable(self, id_data):
        """Transition to from `State.ENABLED` to `State.DISABLED`.

        Parameters
        ----------
        id_data : `CommandIdData`
            Command ID and data
        """
        self._do_change_state(id_data, "disable", [State.ENABLED], State.DISABLED)

    def do_enable(self, id_data):
        """Transition from `State.DISABLED` to `State.ENABLED`.

        Parameters
        ----------
        id_data : `CommandIdData`
            Command ID and data
        """
        self._do_change_state(id_data, "enable", [State.DISABLED], State.ENABLED)

    def do_exitControl(self, id_data):
        """Transition from `State.STANDBY` to `State.OFFLINE` and quit.

        Parameters
        ----------
        id_data : `CommandIdData`
            Command ID and data
        """
        self._do_change_state(id_data, "exitControl", [State.STANDBY], State.OFFLINE)

        asyncio.ensure_future(self.stop())

    def do_standby(self, id_data):
        """Transition from `State.DISABLED` or `State.FAULT` to `State.STANDBY`.

        Parameters
        ----------
        id_data : `CommandIdData`
            Command ID and data
        """
        self._do_change_state(id_data, "standby", [State.DISABLED, State.FAULT], State.STANDBY)

    def do_start(self, id_data):
        """Transition to from `State.STANDBY` to `State.DISABLED`.

        Parameters
        ----------
        id_data : `CommandIdData`
            Command ID and data
        """
        self._do_change_state(id_data, "start", [State.STANDBY], State.DISABLED)

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

    def begin_disable(self, id_data):
        """Begin do_disable; called before state changes.

        Parameters
        ----------
        id_data : `CommandIdData`
            Command ID and data
        """
        pass

    def begin_enable(self, id_data):
        """Begin do_enable; called before state changes.

        Parameters
        ----------
        id_data : `CommandIdData`
            Command ID and data
        """
        pass

    def begin_exitControl(self, id_data):
        """Begin do_exitControl; called before state changes.

        Parameters
        ----------
        id_data : `CommandIdData`
            Command ID and data
        """
        pass

    def begin_standby(self, id_data):
        """Begin do_standby; called before the state changes.

        Parameters
        ----------
        id_data : `CommandIdData`
            Command ID and data
        """
        pass

    def begin_start(self, id_data):
        """Begin do_start; called before state changes.

        Parameters
        ----------
        id_data : `CommandIdData`
            Command ID and data
        """
        pass

    def end_disable(self, id_data):
        """End do_disable; called after state changes
        but before command acknowledged.

        Parameters
        ----------
        id_data : `CommandIdData`
            Command ID and data
        """
        pass

    def end_enable(self, id_data):
        """End do_enable; called after state changes
        but before command acknowledged.

        Parameters
        ----------
        id_data : `CommandIdData`
            Command ID and data
        """
        pass

    def end_exitControl(self, id_data):
        """End do_exitControl; called after state changes
        but before command acknowledged.

        Parameters
        ----------
        id_data : `CommandIdData`
            Command ID and data
        """
        pass

    def end_standby(self, id_data):
        """End do_standby; called after state changes
        but before command acknowledged.

        Parameters
        ----------
        id_data : `CommandIdData`
            Command ID and data
        """
        pass

    def end_start(self, id_data):
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

    def _do_change_state(self, id_data, cmd_name, allowed_curr_states, new_state):
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
            getattr(self, f"begin_{cmd_name}")(id_data)
        except Exception:
            self.log.exception(f"beg_{cmd_name} failed; remaining in state {curr_state!r}")
            raise
        self._summary_state = new_state
        try:
            getattr(self, f"end_{cmd_name}")(id_data)
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
