# This file is part of salobj.
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

    Notes
    -----
    The constructor does the following:

    * For each command defined for the component, find a ``do_<name>`` method
      (which must be present) and add it as a callback to the
      ``cmd_<name>`` attribute.
    * The base class provides synchronous ``do_<name>`` methods for the
      standard CSC commands. The default implementation:

        * Checks for validity of the requested state change;
            if the change is valid then:
        * Calls ``before_<name>``. This is a no-op in the base class,
            and is available for the subclass to override.
        * Changes the state and reports the new value.
        * Calls ``after_<name>``. Again, this is a no-op in the base class,
            and is available for the subclass to override.
        * Report the command as complete

    Standard CSC commands and their associated summary state changes:

    * ``start``: `State.STANDBY` to `State.DISABLED`
    * ``enable``: `State.DISABLED` to `State.ENABLED`

    * ``disable``: `State.ENABLED` to `State.DISABLED`
    * ``exitControl``: `State.STANDBY` to `State.OFFLINE` and then quit
    * ``standby``: `State.DISABLED` or `State.FAULT` to `State.STANDBY`

    Writing a CSC:

    * Make your CSC subclass of BaseCsc.
    * Your subclass must provide a ``do_<name>`` method for every command
      that is not part of the standard CSC command set.
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
      but never for ``salobj.ExpectedException``.
    * By default your CSC will report the command as completed
      when ``do_<name>`` finishes, but you can return a different
      acknowledgement (instance of `SalInfo.AckType`) instead,
      and that will be reportd as the final command state.
    * If you want only one instance of the command running at a time,
      set ``cmd_<name>.allow_multiple_commands = False`` in your
      CSC's constructor. See `ControllerCommand.allow_multiple_commands`
      for details and limitations of this attribute.
    * Your subclass should construct a `salobj.Remote` for any
      remote SAL component it wishes to listen to or command.
    * Your subclass may override ``before_<name>`` and/or ``after_<name>``
      for each state transition command, as appropriate. For complex state
      transitions your subclass may also override ``do_<name>``.
    * ``do_`` is a reserved prefix: all ``do_<name>`` attributes must be
      must match a command name and must be callable.
    """
    def __init__(self, sallib, index=None):
        super().__init__(sallib, index, do_callbacks=True)
        self._summary_state = State.STANDBY
        self._heartbeat_task = asyncio.ensure_future(self._heartbeat_loop())

    def do_disable(self, id_data):
        """Transition to from `State.ENABLED` to `State.DISABLED`.

        Parameters
        ----------
        id_data : `salobj.CommandIdData`
            Command ID and data
        """
        self._do_change_state(id_data, "disable", [State.ENABLED], State.DISABLED)

    def do_enable(self, id_data):
        """Transition from `State.DISABLED` to `State.ENABLED`.

        Parameters
        ----------
        id_data : `salobj.CommandIdData`
            Command ID and data
        """
        self._do_change_state(id_data, "enable", [State.DISABLED], State.ENABLED)

    def do_abort(self, id_data):
        """Subclasses may implement; otherwise this shouldn't be here
        but we're stuck with it.

        TODO TSS-3259: remove this if and when TSS-3257 is fixed
        """
        raise NotImplementedError()

    def do_enterControl(self, id_data):
        """Not relevant to this kind of CSC but we're stuck with it.

        TODO TSS-3259: remove this if and when TSS-3257 is fixed
        """
        raise NotImplementedError()

    def do_setValue(self, id_data):
        """Subclasses may implement; otherwise this shouldn't be here
        but we're stuck with it.

        TODO TSS-3259: remove this if and when TSS-3257 is fixed
        """
        raise NotImplementedError()

    def do_exitControl(self, id_data):
        """Transition from `State.STANDBY` to `State.OFFLINE` and quit.

        Parameters
        ----------
        id_data : `salobj.CommandIdData`
            Command ID and data
        """
        self._do_change_state(id_data, "exitControl", [State.STANDBY], State.OFFLINE)

        async def die():
            await asyncio.sleep(0.1)
            self._heartbeat_task.cancel()
            asyncio.get_event_loop().close()

        asyncio.ensure_future(die())

    def do_standby(self, id_data):
        """Transition from `State.ENABLED` or `State.FAULT` to `State.STANDBY`.

        Parameters
        ----------
        id_data : `salobj.CommandIdData`
            Command ID and data
        """
        self._do_change_state(id_data, "standby", [State.DISABLED, State.FAULT], State.STANDBY)

    def do_start(self, id_data):
        """Transition to from `State.STANDBY` to `State.DISABLED`.

        Parameters
        ----------
        id_data : `salobj.CommandIdData`
            Command ID and data
        """
        self._do_change_state(id_data, "start", [State.STANDBY], State.DISABLED)

    def begin_disable(self, id_data):
        """Begin do_disable; called before state changes.

        Parameters
        ----------
        id_data : `salobj.CommandIdData`
            Command ID and data
        """
        pass

    def begin_enable(self, id_data):
        """Begin do_enable; called before state changes.

        Parameters
        ----------
        id_data : `salobj.CommandIdData`
            Command ID and data
        """
        pass

    def begin_exitControl(self, id_data):
        """Begin do_exitControl; called before state changes.

        Parameters
        ----------
        id_data : `salobj.CommandIdData`
            Command ID and data
        """
        pass

    def begin_standby(self, id_data):
        """Begin do_standby; called before the state changes.

        Parameters
        ----------
        id_data : `salobj.CommandIdData`
            Command ID and data
        """
        pass

    def begin_start(self, id_data):
        """Begin do_start; called before state changes.

        Parameters
        ----------
        id_data : `salobj.CommandIdData`
            Command ID and data
        """
        pass

    def end_disable(self, id_data):
        """End do_disable; called after state changes
        but before command acknowledged.

        Parameters
        ----------
        id_data : `salobj.CommandIdData`
            Command ID and data
        """
        pass

    def end_enable(self, id_data):
        """End do_enable; called after state changes
        but before command acknowledged.

        Parameters
        ----------
        id_data : `salobj.CommandIdData`
            Command ID and data
        """
        pass

    def end_exitControl(self, id_data):
        """End do_exitControl; called after state changes
        but before command acknowledged.

        Parameters
        ----------
        id_data : `salobj.CommandIdData`
            Command ID and data
        """
        pass

    def end_standby(self, id_data):
        """End do_standby; called after state changes
        but before command acknowledged.

        Parameters
        ----------
        id_data : `salobj.CommandIdData`
            Command ID and data
        """
        pass

    def end_start(self, id_data):
        """End do_start; called after state changes
        but before command acknowledged.

        Parameters
        ----------
        id_data : `salobj.CommandIdData`
            Command ID and data
        """
        pass

    def fault(self):
        """Enter the fault state."""
        self.summary_state = State.FAULT

    def assert_enabled(self, action):
        """Assert that an action that requires ENABLED state can be run.
        """
        if self.summary_state != State.ENABLED:
            raise base.ExpectedError(f"{action} not allowed in state {self.summaryState}")

    @property
    def summary_state(self):
        """Set or get the summary state as a `State` enum.

        If you set the state then it is reported as a summaryState event.

        Raises
        ------
        ValueError
            If the new summary state is not a `State`.
        """
        return self._summary_state

    @summary_state.setter
    def summary_state(self, summary_state):
        if summary_state not in State:
            raise ValueError(f"New summary_state={summary_state} not a valid State")
        self._summary_state = summary_state
        self.report_summary_state()

    def report_summary_state(self):
        """Report a new value for summary_state, including current state.

        Subclasses must override if summaryState is not the standard type.
        """
        evt_data = self.evt_summaryState.DataType()
        evt_data.summaryState = self.summary_state
        self.evt_summaryState.put(evt_data)

    def _do_change_state(self, id_data, cmd_name, allowed_curr_states, new_state):
        """Change to the desired state.

        Parameters
        ----------
        id_data : `salobj.CommandIdData`
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
            raise base.ExpectedError(f"{cmd_name} not allowed in {curr_state} state")
        getattr(self, f"begin_{cmd_name}")(id_data)
        self._summary_state = new_state
        try:
            getattr(self, f"end_{cmd_name}")(id_data)
        except Exception:
            self._summary_state = curr_state
            raise
        self.report_summary_state()

    async def _heartbeat_loop(self):
        """Output heartbeat at regular intervals.
        """
        while True:
            try:
                await asyncio.sleep(HEARTBEAT_INTERVAL)
                self.evt_heartbeat.put(self.evt_heartbeat.DataType())
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"Heartbeat output failed: {e}", file=sys.stderr)
