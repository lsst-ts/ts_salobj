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

__all__ = ["Remote"]

import asyncio

from .topics import RemoteEvent, RemoteTelemetry, RemoteCommand
from .domain import Domain
from .sal_info import SalInfo


class Remote:
    """A class that issues commands to a SAL component
    and receives telemetry and events from that component.

    If a SAL component listens to or commands other SAL components
    then it will have one Remote for each such component.

    Parameters
    ----------
    domain : `Domain`
        DDS Domain. If you have a `Controller` then use its ``domain``
        attribute. Otherwise create your own `Domain` and close it
        when you are done, for example::

            async with Domain() as domain:
                dome = Remote(domain=domain, name="ATDome", index=0)
    name : `str`
        Name of SAL component.
    index : `int` or `None` (optional)
        SAL component index, or 0 or None if the component is not indexed.
        A value is required if the component is indexed.
    readonly : `bool`
        If True then do not provide commands.
    include : ``iterable`` of `str` (optional)
        Names of topics (telemetry or events) to support,
        for example ["FilterChangeInPosition", "TrackingTarget"]
        If `None` then all are included except those in `exclude`.
    exclude : ``iterable`` of `str` (optional)
        Names of topics (telemetry or events) to not support.
        If `None` or empty then no topics are excluded.
    evt_max_history : `int` (optional)
        Maximum number of historical items to read for events.
        Set to 0 if your remote is not interested in "late joiner" data.
    tel_max_history : `int` (optional)
        Maximum number of historical items to read for telemetry.
        Set to 0 if your remote is not interested in "late joiner" data.

    Raises
    ------
    ValueError
        If ``include`` and ``exclude`` are both iterables
        (one or both must be `None`).

    Notes
    -----
    Each `Remote` will have the following attributes:

    - ``cmd_<command_name>``, a `topics.RemoteCommand`,
      for each command supported by the component.
      Omitted if ``readonly`` true.
    - ``evt_<event_name>``, a `topics.RemoteEvent`
      for each log event topic supported by the component
      and specified by ``include`` and the ``exclude`` arguments.
    - ``tel_<telemetry_name>``, a `topics.RemoteTelemetry`
      for each telemetry topic supported by the component
      and specified by the ``include`` and ``exclude`` arguments.

    Here is an example that makes a Test remote and displays
    the topic-related attributes::

        include salobj
        # the index is arbitrary, but a remote must use the same index
        # as the controller or CSC in order to communicate
        index = 5
        test_remote = salobj.Remote("Test", index)

        print(dir(test_remote))

    You should see the following topic-related attributes:

    * Commands, each an instance of `topics.RemoteCommand`:

        * ``cmd_standby``
        * ``cmd_start``
        * ... and so on for all other standard CSC commands
        * ``cmd_setArrays``
        * ``cmd_setScalars``

    * Events, each an instance of `topics.RemoteEvent`:

        * ``evt_appliedSettingsMatchStart``
        * ``evt_errorCode``
        * ... and so on for all other standard CSC log events
        * ``evt_arrays``
        * ``evt_scalars``

    * Telemetry, each an instance of `topics.RemoteTelemetry`:

        * ``tel_arrays``
        * ``tel_scalars``
    """
    def __init__(self, domain, name, index=None, *, readonly=False,
                 include=None, exclude=None, evt_max_history=1, tel_max_history=1):
        if include is not None and exclude is not None:
            raise ValueError("Cannot specify both include and exclude")
        include_set = set(include) if include is not None else None
        exclude_set = set(exclude) if exclude is not None else None

        if not isinstance(domain, Domain):
            raise TypeError(f"domain {domain!r} must be an lsst.ts.salobj.Domain")

        salinfo = SalInfo(domain=domain, name=name, index=index)
        self.salinfo = salinfo

        try:
            if not readonly:
                for cmd_name in salinfo.command_names:
                    cmd = RemoteCommand(salinfo, cmd_name)
                    setattr(self, "cmd_" + cmd_name, cmd)

            for evt_name in salinfo.event_names:
                if include_set and evt_name not in include_set:
                    continue
                elif exclude_set and evt_name in exclude_set:
                    continue
                evt = RemoteEvent(salinfo, evt_name, max_history=evt_max_history)
                setattr(self, "evt_" + evt_name, evt)

            for tel_name in salinfo.telemetry_names:
                if include_set and tel_name not in include_set:
                    continue
                elif exclude_set and tel_name in exclude_set:
                    continue
                tel = RemoteTelemetry(salinfo, tel_name, max_history=tel_max_history)
                setattr(self, "tel_" + tel_name, tel)

            self.start_task = asyncio.ensure_future(self.start())
        except Exception:
            asyncio.ensure_future(self.salinfo.close())
            raise

    async def start(self):
        await self.salinfo.start()

    async def close(self):
        """Shut down and clean up resources.

        Close the contained `SalInfo`, but not the `Domain`,
        because that may be used by other objects.
        """
        await self.salinfo.close()

    async def __aenter__(self):
        await self.start_task
        return self

    async def __aexit__(self, type, value, traceback):
        await self.close()
