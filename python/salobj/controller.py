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

from . import utils
from .topics import ControllerEvent, ControllerTelemetry, ControllerCommand


class Controller:
    """A class that receives commands for a SAL component
    and sends telemetry and events from that component.

    Each SAL component will have one Controller.

    Parameters
    ----------
    sallib : ``module``
        salpy component library generatedby SAL
    component_name : `str`
        Component name and optional index, separated by a colon, e.g.
        "scheduler" or "Test:2".

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
        test_controller = salobj.Controller(SALPY_Test, f"Test:{index}")

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
    def __init__(self, sallib, component_name):
        self.salinfo = None
        self.salinfo = utils.SalInfo(sallib, component_name)

        for cmd_name in self.salinfo.manager.getCommandNames():
            cmd = ControllerCommand(self.salinfo, cmd_name)
            setattr(self, "cmd_" + cmd_name, cmd)

        for evt_name in self.salinfo.manager.getEventNames():
            evt = ControllerEvent(self.salinfo, evt_name)
            setattr(self, "evt_" + evt_name, evt)

        for tel_name in self.salinfo.manager.getTelemetryNames():
            tel = ControllerTelemetry(self.salinfo, tel_name)
            setattr(self, "tel_" + tel_name, tel)

    def __del__(self):
        if self.salinfo is not None:
            self.salinfo.manager.salShutdown()
