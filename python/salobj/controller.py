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

__all__ = ["Controller"]

from . import base
from .topics import ControllerEvent, ControllerTelemetry, ControllerCommand


class Controller:
    """A class that receives commands for a SAL component
    and sends telemetry and events from that component.

    Each SAL component will have one Controller.

    Parameters
    ----------
    sallib : ``module``
        salpy component library generatedby SAL
    index : `int` or `None` (optional)
        SAL component index, or 0 or None if the component is not indexed.
        A value is required if the component is indexed.
    do_callbacks : `bool`
        Set ``do_<name>`` methods as callbacks for commands?
        If True then there must be exactly one ``do_<name>`` method
        for each command.

    Notes
    -----
    Each `Controller` will have the following attributes:

    - ``cmd_<command_name>``, a `salobj.topics.ControllerCommand`,
      for each command supported by the component.
    - ``evt_<event_name>``, a `salobj.topics.ControllerEvent`
      for each log event topic supported by the component.
    - ``tel_<telemetry_name>``, a `salobj.topics.ControllerTelemetry`
      for each telemetry topic supported by the component.

    Here is an example with the expected attributes::

        include SALPY_Test
        include salobj
        # the index is arbitrary, but a remote must use the same index
        # to talk to this particular controller
        index = 5
        test_controller = salobj.Controller(SALPY_Test, index)

    ``test_controller`` will have the following attributes:

    * Commands, each an instance of `salobj.topics.ControllerCommand`:

        * ``cmd_standby``
        * ``cmd_start``
        * ... and so on for all other standard CSC commands
        * ``cmd_setArrays``
        * ``cmd_setScalars``

    * Events, each an instance of `salobj.topics.ControllerEvent`:

        * ``evt_appliedSettingsMatchStart``
        * ``evt_errorCode``
        * ... and so on for all other standard CSC log events
        * ``evt_arrays``
        * ``evt_scalars``

    * Telemetry, each an instance of `salobj.topics.ControllerTelemetry`:

        * ``tel_arrays``
        * ``tel_scalars``

    """
    def __init__(self, sallib, index=None, *, do_callbacks=False):
        self.salinfo = None
        self.salinfo = base.SalInfo(sallib, index)

        command_names = self.salinfo.manager.getCommandNames()
        if do_callbacks:
            self._assert_do_methods_present(command_names)
        for cmd_name in command_names:
            cmd = ControllerCommand(self.salinfo, cmd_name)
            setattr(self, "cmd_" + cmd_name, cmd)
            if do_callbacks:
                cmd.callback = getattr(self, f"do_{cmd_name}")

        for evt_name in self.salinfo.manager.getEventNames():
            evt = ControllerEvent(self.salinfo, evt_name)
            setattr(self, "evt_" + evt_name, evt)

        for tel_name in self.salinfo.manager.getTelemetryNames():
            tel = ControllerTelemetry(self.salinfo, tel_name)
            setattr(self, "tel_" + tel_name, tel)

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

    def __del__(self):
        if self.salinfo is not None:
            self.salinfo.manager.salShutdown()
