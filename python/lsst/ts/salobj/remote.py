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

__all__ = ["Remote"]

import asyncio
import types
import typing
from collections.abc import Iterable

from .domain import Domain
from .sal_info import SalInfo
from .topics import RemoteCommand, RemoteEvent, RemoteTelemetry


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
    index : `int` or `None`, optional
        SAL component index, or 0 or None if the component is not indexed.
        A value is required if the component is indexed.
    readonly : `bool`
        If True then do not provide commands.
    include : ``iterable`` of `str`, optional
        Names of topics (telemetry or events) to support,
        for example ["FilterChangeInPosition", "TrackingTarget"]
        If `None` then all are included except those in `exclude`.
    exclude : ``iterable`` of `str`, optional
        Names of topics (telemetry or events) to not support.
        Topic names must not have a ``tel_`` or ``evt_`` prefix.
        If `None` or empty then no topics are excluded.
    evt_max_history : `int`, optional
        Maximum number of historical items to read for events.
        Set to 0 if your remote is not interested in "late joiner" data.
    start : `bool`, optional
        Automatically start the read loop when constructed?
        Normally this should be `True`, but if you are adding topics
        piecemeal after constructing the remote then specify `False`
        and call `start` manually after you have added all topics.
        Warning: if `False` then `self.start_task` will not exist
        and the remote cannot be used as an async context manager.
    num_messages : `int`
        Number of messages to consume in the read loop.
    consume_messages_timeout : `float`
        Timeout to wait for new messages to arrive in the read loop.

    Raises
    ------
    ValueError
        If ``include`` and ``exclude`` are both iterables
        (one or both must be `None`).

    Attributes
    ----------
    start_called : `bool`
        Has the start method been called?
        The instance is fully started when start_task is done.
    cmd_<command_name> : `topics.RemoteCommand`
        Remote command topic for each command supported by the component.
        Omitted if ``readonly`` true.
    evt_<event_name> : `topics.RemoteEvent`
        Remote event for each event supported by the component,
        as specified by ``include`` and the ``exclude`` arguments.
    tel_<telemetry_name> : `topics.RemoteTelemetry`
        Remote telemetry topic for each telemetry topic supported by the
        component, as specified by the ``include`` and ``exclude`` arguments.

    Notes
    -----

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

        * ``evt_configurationApplied``
        * ... and so on for all other standard CSC log events
        * ``evt_arrays``
        * ``evt_scalars``

    * Telemetry, each an instance of `topics.RemoteTelemetry`:

        * ``tel_arrays``
        * ``tel_scalars``
    """

    def __init__(
        self,
        domain: Domain,
        name: str,
        index: int | None = None,
        *,
        readonly: bool = False,
        include: Iterable[str] | None = None,
        exclude: Iterable[str] | None = None,
        evt_max_history: int = 1,
        start: bool = True,
        num_messages: int = 1,
        consume_messages_timeout: float = 0.1,
    ) -> None:
        if include is not None and exclude is not None:
            raise ValueError("Cannot specify both include and exclude")
        include_set = set(include) if include is not None else None
        exclude_set = set(exclude) if exclude is not None else None

        if not isinstance(domain, Domain):
            raise TypeError(f"domain {domain!r} must be an lsst.ts.salobj.Domain")

        self.salinfo = SalInfo(
            domain=domain,
            name=name,
            index=index,
            num_messages=num_messages,
            consume_messages_timeout=consume_messages_timeout,
        )
        try:
            if not readonly:
                for cmd_name in self.salinfo.command_names:
                    cmd = RemoteCommand(self.salinfo, cmd_name)
                    setattr(self, cmd.attr_name, cmd)

            for evt_name in self.salinfo.event_names:
                if include_set is not None and evt_name not in include_set:
                    continue
                elif exclude_set and evt_name in exclude_set:
                    continue
                evt = RemoteEvent(self.salinfo, evt_name, max_history=evt_max_history)
                setattr(self, evt.attr_name, evt)

            for tel_name in self.salinfo.telemetry_names:
                if include_set is not None and tel_name not in include_set:
                    continue
                elif exclude_set and tel_name in exclude_set:
                    continue
                tel = RemoteTelemetry(self.salinfo, tel_name)
                setattr(self, tel.attr_name, tel)

            if start:
                self.start_called = True
                self.start_task = asyncio.create_task(self.start())
            else:
                self.start_called = False
        except Exception:
            self.salinfo.basic_close()
            raise

    async def start(self) -> None:
        """Start the read loop by starting the contained SalInfo.

        Raises
        ------
        RuntimeError
            If the SalInfo is already started, closing or closed.
        """
        await self.salinfo.start()

    async def close(self) -> None:
        """Shut down and clean up resources.

        Close the contained `SalInfo`, but not the `Domain`,
        because that may be used by other objects.

        May be called multiple times. The first call closes the SalInfo;
        subsequent calls wait until the Remote is closed.
        """
        await self.salinfo.close()

    def __repr__(self) -> str:
        return f"Remote(name={self.salinfo.name}, index={self.salinfo.index})"

    async def __aenter__(self) -> Remote:
        if self.start_called:
            # The Remote was constructed with start=True (the default)
            await self.start_task
        return self

    async def __aexit__(
        self,
        type: typing.Type[BaseException] | None,
        value: BaseException | None,
        traceback: types.TracebackType | None,
    ) -> None:
        await self.close()
