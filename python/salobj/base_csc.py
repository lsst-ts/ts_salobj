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

from . import base
from .controller import Controller


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
      or asynchronous (``async def do_<name>...``).
    * Your CSC will report the command as failed if the ``do_<name>``
      method raises an exception. The ``result`` field of that
      acknowledgement will be the data in the exception.
      Eventually the CSC may log a traceback, as well,
      but never for ``salobj.ExpectedException``.
    * By default your CSC will report the command as completed
      when ``do_<name>`` finishes, but you can return a different
      acknowledgement (instance of `SalInfo.AckType`) instead,
      and that will be reportd as the final command state.
    * If ``do<name>`` will take awhile, you should call
      ``cmd_<name>.ackInProgress`` as the callback starts, after you have
      validated the data and are pretty sure you can run the command.
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
        super().__init__(sallib, index)
        self.state = State.STANDBY
        self.summary_state = self.evt_summaryState.DataType()
        command_names = self.salinfo.manager.getCommandNames()
        self._assert_do_methods_present(command_names)
        for name in command_names:
            cmd = getattr(self, f"cmd_{name}")
            cmd.callback = getattr(self, f"do_{name}")

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
        self.state = State.FAULT
        self.report_summary_state()

    def set_summary_state(self):
        """Set an updated value for summary_state."""
        self.summary_state.summaryState = self.state

    def report_summary_state(self):
        """Report a new value for summary_state, including current state.

        Subclasses must override if summaryState is not the standard type.
        """
        self.set_summary_state()
        self.evt_summaryState.put(self.summary_state, 1)

    def _assert_do_methods_present(self, command_names):
        """Assert that all needed do_<name> methods are present,
        and no extra such methods are present.

        Parameters
        ----------
        command_names : `list` of `str`
            List of command names, e.g. as provided by
            `salinfo.manager.getCommandNames`
        """
        do_names = [name for name in dir(self) if name.startswith("do_")]
        supported_command_names = [name[3:] for name in do_names]
        if set(command_names) != set(supported_command_names):
            err_msgs = []
            unsupported_commands = set(command_names) - set(supported_command_names)
            if unsupported_commands:
                needed_do_str = ", ".join(f"do_{name}" for name in sorted(unsupported_commands))
                err_msgs.append(f"must add {needed_do_str} methods")
            extra_commands = sorted(set(supported_command_names) - set(command_names))
            if extra_commands:
                extra_do_str = ", ".join(f"do_{name}" for name in sorted(extra_commands))
                err_msgs.append(f"must remove {extra_do_str} methods")
            err_msg = " and ".join(err_msgs)
            raise TypeError(f"This class {err_msg}")

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
        curr_state = self.state
        if self.state not in allowed_curr_states:
            raise base.ExpectedError(f"{cmd_name} not allowed in {self.state} state")
        getattr(self, f"begin_{cmd_name}")(id_data)
        self.state = new_state
        try:
            getattr(self, f"end_{cmd_name}")(id_data)
        except Exception:
            self.state = curr_state
            raise
        self.report_summary_state()
