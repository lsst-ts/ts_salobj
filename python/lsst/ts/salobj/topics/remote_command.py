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

__all__ = ["AckCmdReader", "CommandInfo", "RemoteCommand"]

import asyncio
import collections
import logging
import random
import time
import typing

from lsst.ts.xml import sal_enums, type_hints

from .. import base
from . import read_topic, remote_command, write_topic

if typing.TYPE_CHECKING:
    from ..sal_info import SalInfo

DEFAULT_TIMEOUT = 60 * 60  # default timeout, in seconds


class AckCmdReader(read_topic.ReadTopic):
    """ackcmd (command acknowledgement) topic reader.

    Parameters
    ----------
    salinfo : `SalInfo`
        SAL component information.
    queue_len : `int`
        Number of elements that can be queued for `get_oldest`.

    Notes
    -----
    The same ``ackcmd`` topic is used for all command topics from a given
    SAL component.
    """

    def __init__(
        self, salinfo: SalInfo, queue_len: int = read_topic.DEFAULT_QUEUE_LEN
    ) -> None:
        super().__init__(
            salinfo=salinfo, attr_name="ack_ackcmd", max_history=0, queue_len=queue_len
        )

    def _queue_one_item(self, data: type_hints.BaseMsgType) -> None:
        """Queue an ackcmd message if its ``identity`` and ``origin`` match
        the values in self.salinfo.

        Ignore ackcmd messages that have a different ``identity`` or
        ``origin``, because those are in response to commands sent by
        a different user (or at least by a different process, or a different
        salinfo with a different identity).
        """
        if (
            data.identity == self.salinfo.identity  # type: ignore
            and data.origin == self.salinfo.domain.origin  # type: ignore
        ):
            self._data_queue.append(data)


class CommandInfo:
    """Struct to hold information about a command.

    Parameters
    ----------
    remote_command : `RemoteCommand`
        Remote command.
    seq_num : `int`
        Sequence number of command.
    wait_done : `bool`
        Wait until the command is done to finish the task?
        If false then wait for the next ack instead.
    """

    def __init__(
        self,
        remote_command: remote_command.RemoteCommand,
        seq_num: int,
        wait_done: bool,
    ) -> None:
        self.remote_command = remote_command
        self.seq_num = int(seq_num)
        self.wait_done = bool(wait_done)

        self._wait_task: asyncio.Future = asyncio.Future()
        self._next_ack_event = asyncio.Event()

        self.done_ack_codes = frozenset(
            (
                sal_enums.SalRetCode.CMD_ABORTED,
                sal_enums.SalRetCode.CMD_COMPLETE,
                sal_enums.SalRetCode.CMD_FAILED,
                sal_enums.SalRetCode.CMD_NOACK,
                sal_enums.SalRetCode.CMD_NOPERM,
                sal_enums.SalRetCode.CMD_STALLED,
                sal_enums.SalRetCode.CMD_TIMEOUT,
            )
        )
        self.failed_ack_codes = frozenset(
            (
                sal_enums.SalRetCode.CMD_ABORTED,
                sal_enums.SalRetCode.CMD_FAILED,
                sal_enums.SalRetCode.CMD_NOACK,
                sal_enums.SalRetCode.CMD_NOPERM,
                sal_enums.SalRetCode.CMD_STALLED,
                sal_enums.SalRetCode.CMD_TIMEOUT,
            )
        )
        self.good_ack_codes = frozenset(
            (
                sal_enums.SalRetCode.CMD_ACK,
                sal_enums.SalRetCode.CMD_INPROGRESS,
                sal_enums.SalRetCode.CMD_COMPLETE,
            )
        )

        # we should see at most 3 acks, but leave room for one more,
        # just in case
        self._ack_queue: collections.deque[type_hints.AckCmdDataType] = (
            collections.deque(maxlen=4)
        )
        self._last_ackcmd: type_hints.AckCmdDataType | None = None

    def add_ackcmd(self, ackcmd: type_hints.AckCmdDataType) -> bool:
        """Add a command acknowledgement to the queue.

        Parameters
        ----------
        ackcmd : `SalInfo.AckCmdType`
            Command acknowledgement message.

        Returns
        -------
        isdone : `bool`
            True if this is a final acknowledgement.
        """
        isdone = ackcmd.ack in self.done_ack_codes
        self._ack_queue.append(ackcmd)
        self._next_ack_event.set()
        return isdone

    def close(self) -> None:
        """Stop pending tasks."""
        self._wait_task.cancel()

    async def next_ackcmd(
        self, timeout: float = DEFAULT_TIMEOUT
    ) -> type_hints.AckCmdDataType:
        """Get next command acknowledgement of interest.

        If ``wait_done`` true then return the final command acknowledgement,
        else return the next command acknowledgement.
        If the ackcmd is an error then raise `AckError`.
        If waiting times out then raise `AckTimeoutError`.

        Parameters
        ----------
        timeout : `float`, optional
            Time limit, in seconds. If None then use ``DEFAULT_TIMEOUT``.
            This time limit is for the command to finish, if ``wait_done``
            is true, else it is for the next command acknowledgement.
            If the command is acknowledged with ``CMD_INPROGRESS`` then the
            timeout is extended by the timeout value in the acknowledgement.
            Thus a slow command will not need a long timeout, so long as
            the command issues a ``CMD_INPROGRESS`` acknowledgement
            with a reasonable ``timeout`` value.

        Returns
        -------
        ackcmd : `SalInfo.AckCmdType`
            Command acknowledgement.

        Raises
        ------
        AckError
            If the command fails.
        AckTimeoutError
            If the command acknowledgement does not arrive in time.
        """
        try:
            self._wait_task = asyncio.create_task(
                self._basic_next_ackcmd(timeout=timeout)
            )
            ackcmd = await self._wait_task
            if ackcmd.ack in self.failed_ack_codes:
                raise base.AckError(msg="Command failed", ackcmd=ackcmd)
            return ackcmd
        except asyncio.TimeoutError:
            if self._last_ackcmd is None:
                last_ackcmd = self.remote_command.salinfo.make_ackcmd(
                    private_seqNum=self.seq_num,
                    ack=sal_enums.SalRetCode.CMD_NOACK,
                    result="No command acknowledgement seen",
                )
            else:
                last_ackcmd = self._last_ackcmd

            if self.seq_num in self.remote_command.salinfo._running_cmds:
                self.remote_command.salinfo._running_cmds.pop(self.seq_num)
            raise base.AckTimeoutError(
                msg="Timed out waiting for command acknowledgement", ackcmd=last_ackcmd
            )

    async def _basic_next_ackcmd(self, timeout: float) -> type_hints.AckCmdDataType:
        """Basic implementation of next_ackcmd."""
        t0 = time.monotonic()
        elapsed_time: float = 0
        while True:
            ackcmd = await asyncio.wait_for(
                self._get_next_ackcmd(), timeout=timeout - elapsed_time
            )
            if not self.wait_done or ackcmd.ack in self.done_ack_codes:
                return ackcmd
            if ackcmd.ack == sal_enums.SalRetCode.CMD_INPROGRESS:
                timeout += ackcmd.timeout
            elapsed_time = time.monotonic() - t0

    async def _get_next_ackcmd(self) -> type_hints.AckCmdDataType:
        """Get the next ackcmd sample.

        Returns
        -------
        ackcmd : `SalInfo.AckCmdType`
            Next ackcmd sample.
        """
        # note: set self._last_ackcmd here instead of in add_ackcmd
        # because it reduces or eliminates a race condition where a new
        # command acknowledgement comes in as next_ackcmd is timing out.
        while True:
            if self._ack_queue:
                ackcmd = self._ack_queue.popleft()
                self._last_ackcmd = ackcmd
                return ackcmd
            await self._next_ack_event.wait()
            self._next_ack_event.clear()

    def __repr__(self) -> str:
        return (
            f"CommandInfo(remote_command={self.remote_command}, seq_num={self.seq_num}, "
            f"wait_done={self.wait_done})"
        )


class RemoteCommand(write_topic.WriteTopic):
    """Issue a specific command topic and wait for acknowldgement.

    Parameters
    ----------
    salinfo : `SalInfo`
        SAL component information.
    name : `str`
        Command name, with no prefix, e.g. "start".
    """

    def __init__(self, salinfo: SalInfo, name: str) -> None:
        num_commands = len(salinfo.command_names)
        seq_num_increment = write_topic.MAX_SEQ_NUM // num_commands
        name_ind = salinfo.command_names.index(name)
        min_seq_num = name_ind * seq_num_increment + 1
        max_seq_num = min_seq_num + seq_num_increment - 1
        initial_seq_num = random.randint(min_seq_num, max_seq_num)
        self._in_start = False
        super().__init__(
            salinfo=salinfo,
            attr_name="cmd_" + name,
            min_seq_num=min_seq_num,
            max_seq_num=max_seq_num,
            initial_seq_num=initial_seq_num,
        )
        self.log = logging.getLogger(f"{salinfo}.RemoteCommand.{name}")
        # dict of seq_num: CommandInfo
        if salinfo._ackcmd_reader is None:
            salinfo._ackcmd_reader = AckCmdReader(salinfo)
            salinfo._ackcmd_reader.callback = salinfo._ackcmd_callback  # type: ignore

    async def next_ackcmd(
        self,
        ackcmd: type_hints.AckCmdDataType,
        timeout: float = DEFAULT_TIMEOUT,
        wait_done: bool = True,
    ) -> type_hints.AckCmdDataType:
        """Wait for the next acknowledgement for the command.

        Parameters
        ----------
        ackcmd : `SalInfo.AckCmdType`
            Command acknowledgement returned by the previous call to
            `set_start`, `start` or `next_ackcmd`.
        timeout : `float`, optional
            Time limit, in seconds. If None then use ``DEFAULT_TIMEOUT``.
            This time limit is for the entire command if ``wait_done``
            is true, else it is for the next command acknowledgement.
            If ``wait_done`` is true and the command is acknowledged with
            ``CMD_INPROGRESS`` then the timeout is extended by
            the timeout value in the acknowledgement.
            Thus a slow command will not need a long timeout, so long as
            the command issues a ``CMD_INPROGRESS`` acknowledgement
            with a reasonable ``timeout`` value.
        wait_done : `bool`, optional
            If true then wait for final command acknowledgement.
            If false then wait only for the next command acknowledgement
            If that acknowledgement is not final
            (the ack code is not in ``self.done_ack_codes``),
            then you will almost certainly want to await `next_ackcmd` again.

        Returns
        -------
        ackcmd : `SalInfo.AckCmdType`
            Command acknowledgement.

        Raises
        ------
        lsst.ts.salobj.AckError
            If the command fails or times out.
        RuntimeError
            If the command specified by ``seq_num`` is unknown
            or has already finished.
        """
        cmd_info = self.salinfo._running_cmds.get(ackcmd.private_seqNum, None)
        if cmd_info is None:
            raise RuntimeError(
                f"Command private_seqNum={ackcmd.private_seqNum} is unknown or finished"
            )
        cmd_info.wait_done = wait_done
        return await cmd_info.next_ackcmd(timeout=timeout)

    def set(self, **kwargs: typing.Any) -> bool:
        """Create a new ``self.data`` and set one or more fields.

        Parameters
        ----------
        **kwargs : `dict` [`str`, ``any``]
            Dict of field name: new value for that field:

            * Any key whose value is `None` is checked for existence,
              but the value of the field is not changed.
            * If the field being set is an array then the value must either
              be an array of the same length or a scalar (which replaces
              every element of the array).

        Returns
        -------
        did_change : `bool`
            True if ``self.data`` was changed, or if this was the first call
            to `set`.

        Raises
        ------
        AttributeError
            If the topic does not have the specified field.
        ValueError
            If the field cannot be set to the specified value.

        Notes
        -----
        If one or more fields cannot be set, the data may be partially updated.
        """
        if not self._in_start:
            self.data = self.DataType()
        return super().set(**kwargs)

    async def set_start(
        self,
        timeout: float = DEFAULT_TIMEOUT,
        wait_done: bool = True,
        **kwargs: typing.Any,
    ) -> type_hints.AckCmdDataType:
        """Create a new ``self.data``, set zero or more fields,
        and start the command.

        Parameters
        ----------
        timeout : `float`, optional
            Time limit, in seconds. If None then use ``DEFAULT_TIMEOUT``.
            This time limit is for the entire command if ``wait_done``
            is true, else it is for the first command acknowledgement.
            If ``wait_done`` is true and the command is acknowledged with
            ``CMD_INPROGRESS`` then the timeout is extended by
            the timeout value in the acknowledgement.
            Thus a slow command will not need a long timeout, so long as
            the command issues a ``CMD_INPROGRESS`` acknowledgement
            with a reasonable ``timeout`` value.
        wait_done : `bool`, optional
            If True then wait for final command acknowledgement.
            If False then wait only for the first command acknowledgement
            If that acknowledgement is not final
            (the ack code is not in ``self.done_ack_codes``),
            then you will almost certainly want to await `next_ackcmd`.
        **kwargs : `dict` [`str`, ``any``]
            The remaining keyword arguments are
            field name = new value for that field.
            See `set` for more information about values.

        Returns
        -------
        ackcmd : `SalInfo.AckCmdType`
            Command acknowledgement.

        Raises
        ------
        lsst.ts.salobj.AckError
            If the command fails.
        lsst.ts.salobj.AckTimeoutError
            If the command times out.
        TypeError
            If ``data`` is not None and not an instance of `DataType`.
        """
        self.set(**kwargs)
        return await self.start(timeout=timeout, wait_done=wait_done)

    async def start(
        self,
        data: type_hints.BaseMsgType | None = None,
        timeout: float = DEFAULT_TIMEOUT,
        wait_done: bool = True,
    ) -> type_hints.AckCmdDataType:
        """Start a command.

        Parameters
        ----------
        data : ``self.DataType``, optional
            Command message. If `None` then send the current ``self.data``.
        timeout : `float`, optional
            Time limit, in seconds. If None then use ``DEFAULT_TIMEOUT``.
            This time limit is for the entire command if ``wait_done``
            is true, else it is for the first acknowledgement.
            If ``wait_done`` is true and the command is acknowledged with
            ``CMD_INPROGRESS`` then the timeout is extended by
            the timeout value in the acknowledgement.
            Thus a slow command will not need a long timeout, so long as
            the command issues a ``CMD_INPROGRESS`` acknowledgement
            with a reasonable ``timeout`` value.
        wait_done : `bool`, optional
            If True then wait for final command acknowledgement.
            If False then wait only for the first command acknowledgement.
            If that acknowledgement is not final
            (the ack code is not in ``self.done_ack_codes``),
            then you will almost certainly want to await `next_ackcmd`.

        Returns
        -------
        ackcmd : `SalInfo.AckCmdType`
            Command acknowledgement.

        Raises
        ------
        lsst.ts.salobj.AckError
            If the command fails.
        lsst.ts.salobj.AckTimeoutError
            If the command times out.
        RuntimeError
            If ``self.salinfo`` is not running.
        TypeError
            If ``data`` is not None and not an instance of `DataType`.
        """
        self.salinfo.assert_running()

        try:
            self._in_start = True
            if data is not None:
                self.data = data
            # else use the existing data, since it may have been set
            # via a call to "set"

            data = self._prepare_data_to_write()

            seq_num = data.private_seqNum
            if seq_num in self.salinfo._running_cmds:
                raise RuntimeError(
                    f"{self.attr_name} a command with seq_num={seq_num} is already running. "
                    "This may indicate a bug in ts_salobj SalInfo or RemoteCommand."
                )
            cmd_info = CommandInfo(
                remote_command=self, seq_num=seq_num, wait_done=wait_done
            )
            self.salinfo._running_cmds[seq_num] = cmd_info
            await self.salinfo.write_data(
                topic_info=self.topic_info, data_dict=vars(data)
            )
        finally:
            self._in_start = False

        return await cmd_info.next_ackcmd(timeout=timeout)

    async def set_write(
        self, *, force_output: bool | None = None, **kwargs: typing.Any
    ) -> write_topic.SetWriteResult:
        """An override of WriteTopic.set_write that is disabled."""
        raise NotImplementedError("Call set_start instead")

    async def write(self, **kwargs: typing.Any) -> type_hints.BaseMsgType:
        """An override of WriteTopic.write that is disabled."""
        raise NotImplementedError("Call start instead")
