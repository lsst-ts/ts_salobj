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

__all__ = ["Remote"]

from . import utils
from .topics import RemoteEvent, RemoteTelemetry, RemoteCommand


class Remote:
    """A class that issues commands to a SAL component
    and receives telemetry and events from that component.

    If a SAL conponent listens to or commands other SAL components
    then it will have one Remote for each such component.

    Parameters
    ----------
    sallib : `module`
        salpy component library generated by SAL
    index : `int` or `None`
        SAL component index, or 0 or None if the component is not indexed.
    include : `iterable` of `str` (optional)
        Names of topics (telemetry or events) to support,
        for example ["FilterChangeInPosition", "TrackingTarget"]
        If `None` then all are included except those in `exclude`.
    exclude : `iterable` of `str` (optional)
        Names of topics (telemetry or events) to not support.
        If `None` or empty then no topics are excluded.

    If ``include`` and ``exclude`` are both `None` then all topics
    are supported.

    Raises
    ------
    ValueError
        If ``include`` and ``exclude`` are both iterables
        (one or both must be None).

    Notes
    -----
    Each `Remote will` have the following attributes:

    - ``cmd_<command_name>``, a `salobj.topics.RemoteCommand`,
      for each command supported by the component.
    - ``evt_<event_name>``, a `salobj.topics.RemoteEvent`
      for each log event topic supported by the component
      and specified by ``include`` and the ``exclude`` arguments.
    - ``tel_<telemetry_name>``, a `salobj.topics.RemoteTelemetry`
      for each telemetry topic supported by the component
      and specified by the ``include`` and ``exclude`` arguments.

    Here is an example with the expected attributes::

        include SALPY_Test
        include salobj
        # the index is arbitrary, but a remote must use the same index
        # to talk to this particular controller
        index = 5
        test_remote = salobj.Remote(SALPY_Test, index)

    ``test_remote`` will have the following attributes:

    * Commands, each an instance of `salobj.topics.RemoteCommand`:

        * ``cmd_standby``
        * ``cmd_start``
        * ... and so on for all other standard CSC commands
        * ``cmd_setArrays``
        * ``cmd_setScalars``

    * Events, each an instance of `salobj.topics.RemoteEvent`:

        * ``evt_appliedSettingsMatchStart``
        * ``evt_errorCode``
        * ... and so on for all other standard CSC log events
        * ``evt_arrays``
        * ``evt_scalars``

    * Telemetry, each an instance of `salobj.topics.RemoteTelemetry`:

        * ``tel_arrays``
        * ``tel_scalars``
    """
    def __init__(self, sallib, index=None, include=None, exclude=None):
        self.salinfo = None
        if include is not None and exclude is not None:
            raise ValueError("Cannot specify both include and exclude")
        include_set = set(include) if include is not None else None
        exclude_set = set(exclude) if exclude is not None else None

        salinfo = utils.SalInfo(sallib, index)
        self.salinfo = salinfo

        for cmd_name in salinfo.manager.getCommandNames():
            cmd = RemoteCommand(salinfo, cmd_name)
            setattr(self, "cmd_" + cmd_name, cmd)

        for evt_name in salinfo.manager.getEventNames():
            if include_set and evt_name not in include_set:
                continue
            elif exclude_set and evt_name in exclude_set:
                continue
            evt = RemoteEvent(salinfo, evt_name)
            setattr(self, "evt_" + evt_name, evt)

        for tel_name in salinfo.manager.getTelemetryNames():
            if include_set and tel_name not in include_set:
                continue
            elif exclude_set and tel_name in exclude_set:
                continue
            tel = RemoteTelemetry(salinfo, tel_name)
            setattr(self, "tel_" + tel_name, tel)

    def __del__(self):
        if self.salinfo is not None:
            self.salinfo.manager.salShutdown()
