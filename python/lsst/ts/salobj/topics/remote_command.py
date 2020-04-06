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

__all__ = ["AckCmdReader", "RemoteCommand"]

import asyncio
import collections
import logging
import random

from .. import base
from .. import sal_enums
from . import read_topic
from . import write_topic

DEFAULT_TIMEOUT = 60 * 60  # default timeout, in seconds


class AckCmdReader(read_topic.ReadTopic):
    """Read the ``ackcmd`` command acknowledgement topic.

    Parameters
    ----------
    salinfo : `.SalInfo`
        SAL component information
    queue_len : `int`
        Number of elements that can be queued for `get_oldest`.

    Notes
    -----
    The same ``ackcmd`` topic is used for all command topics from a given
    SAL component.
    """

    def __init__(self, salinfo, queue_len=100):
        super().__init__(
            salinfo=salinfo,
            name="ackcmd",
            sal_prefix="",
            max_history=0,
            queue_len=queue_len,
        )


class _CommandInfo:
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

    def __init__(self, remote_command, seq_num, wait_done):
        self.remote_command = remote_command
        self.seq_num = int(seq_num)
        self.wait_done = bool(wait_done)

        self._wait_task = asyncio.Future()
        self._next_ack_task = asyncio.Future()

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
        self._ack_queue = collections.deque(maxlen=4)
        self._last_ackcmd = None

    def abort(self, result=""):
        """Report command as aborted. Ignored if already done."""
        if not self._wait_task.done():
            self._wait_task.cancel()
        if not self._next_ack_task.done():
            self._next_ack_task.cancel()

    def add_ackcmd(self, ackcmd):
        """Add a command acknowledgement to the queue.

        Parameters
        ----------
        ackcmd : `SalInfo.AckCmdType`
            Command acknowledgement data.

        Returns
        -------
        isdone : `bool`
            True if this is a final acknowledgement.
        """
        # print(f"add_ackcmd; ackcmd.ack={ackcmd.ack}")
        isdone = ackcmd.ack in self.done_ack_codes
        self._ack_queue.append(ackcmd)
        if not self._next_ack_task.done():
            self._next_ack_task.set_result(None)
        return isdone

    async def next_ackcmd(self, timeout):
        """Get next command acknowledgement of interest.

        If ``wait_done`` true then return the final command acknowledgement,
        else return the next command acknowledgement.
        If the ackcmd is an error then raise `AckError`.
        If waiting times out then raise `AckTimeoutError`.

        Parameters
        ----------
        timeout : `float` (optional)
            Timeout in seconds. If the next command acknowledgement
            does not arrive in time then raise `AckTimeoutError`.

        Returns
        -------
        ackcmd : `SalInfo.AckCmdType`
            Command acknowledgement.

        Raises
        ------
        AckTimeoutError
            If the command acknowledgement does not arrive in time.
        AckError
            If the command fails.
        """
        if timeout is None:  # for backwards compatibility
            timeout = DEFAULT_TIMEOUT
        try:
            self._wait_task = asyncio.ensure_future(
                asyncio.wait_for(self._basic_next_ack(), timeout=timeout)
            )
            ackcmd = await self._wait_task
            # print(f"next_ackcmd got {ackcmd.ack} from _basic_next_ack")
            if ackcmd.ack in self.failed_ack_codes:
                raise base.AckError(msg="Command failed", ackcmd=ackcmd)
            return ackcmd
        except asyncio.TimeoutError:
            if self._last_ackcmd is None:
                last_ackcmd = self.remote_command.salinfo.makeAckCmd(
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

    async def _basic_next_ack(self):
        """Get the next command acknowledgment of interest.

        Implements `next_ackcmd` but does not interpret the result
        beyond ignoring acks that are not of interest.

        Returns
        -------
        ackcmd : `SalInfo.AckCmdType`
            Next command acknowledgement of interest.
        """
        # note: set self._last_ackcmd here instead of in add_ackcmd
        # because it reduces or eliminates a race condition where a new
        # command acknowledgement comes in as next_ackcmd is timing out.
        while True:
            while self._ack_queue:
                ackcmd = self._ack_queue.popleft()
                self._last_ackcmd = ackcmd
                if not self.wait_done or ackcmd.ack in self.done_ack_codes:
                    return ackcmd
            self._next_ack_task = asyncio.Future()
            await self._next_ack_task
            ackcmd = self._ack_queue.popleft()
            self._last_ackcmd = ackcmd
            if not self.wait_done or ackcmd.ack in self.done_ack_codes:
                return ackcmd

    def __del__(self):
        for task_name in ("_wait_task", "_next_ack_task"):
            task = getattr(self, task_name, None)
            if task is not None and not task.done():
                task.cancel()

    def __repr__(self):
        return (
            f"_CommandInfo(remote_command={self.remote_command}, seq_num={self.seq_num}, "
            f"wait_done={self.wait_done})"
        )


class RemoteCommand(write_topic.WriteTopic):
    """Issue a specific command topic and wait for acknowldgement.

    Parameters
    ----------
    salinfo : `.SalInfo`
        SAL component information
    name : `str`
        Command name
    """

    def __init__(self, salinfo, name):
        num_commands = len(salinfo.command_names)
        seq_num_increment = write_topic.MAX_SEQ_NUM // num_commands
        name_ind = salinfo.command_names.index(name)
        min_seq_num = name_ind * seq_num_increment + 1
        max_seq_num = min_seq_num + seq_num_increment - 1
        initial_seq_num = random.randint(min_seq_num, max_seq_num)
        super().__init__(
            salinfo=salinfo,
            name=name,
            sal_prefix="command_",
            min_seq_num=min_seq_num,
            max_seq_num=max_seq_num,
            initial_seq_num=initial_seq_num,
        )
        self.log = logging.getLogger(f"{salinfo}.RemoteCommand.{name}")
        # dict of seq_num: CommandInfo
        if salinfo._ackcmd_reader is None:
            salinfo._ackcmd_reader = AckCmdReader(salinfo)
            salinfo._ackcmd_reader.callback = salinfo._ackcmd_callback

    async def next_ackcmd(self, ackcmd, timeout=DEFAULT_TIMEOUT, wait_done=True):
        """Wait for the next acknowledement for the command

        Parameters
        ----------
        ackcmd : `SalInfo.AckCmdType`
            The command acknowledgement returned by
            the previous wait (e.g. from `start`).
        timeout : `float` (optional)
            Time limit, in seconds. If None then no time limit.
            This time limit is for the entire command if wait_done
            is true, else it is for the first acknowledgement
            after the initial "SAL__CMD_ACK".
        wait_done : `bool` (optional)
            If True then wait for final command acknowledgement.
            If False then wait until the next command acknowledgement;
            if that acknowledgement is not final (the ack code is not in
            ``done_ack_codes``), then you will almost certainly want to
            await `next_ackcmd` again.

        Returns
        -------
        ackcmd : `SalInfo.AckCmdType`
            Command acknowledgement.

        Raises
        ------
        salobj.AckError
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

    async def set_start(self, timeout=DEFAULT_TIMEOUT, wait_done=True, **kwargs):
        """Set zero or more command data fields and start a command.

        Parameters
        ----------
        timeout : `float` (optional)
            Time limit, in seconds. If None then no time limit.
            This time limit is for the entire command if wait_done
            is true, else it is for the first acknowledgement
            after the initial "SAL__CMD_ACK".
        wait_done : `bool` (optional)
            If True then wait for final command acknowledgement.
            If False then wait for the first acknowledgement after the
            initial "SAL__CMD_ACK"; if that acknowledgement is not final
            (the ack code is not in done_ack_codes), then you will almost
            certainly want to await `next_ackcmd`.
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
        salobj.AckError
            If the command fails.
        salobj.AckTimeoutError
            If the command times out.
        TypeError
            If ``data`` is not None and not an instance of `DataType`.
        """
        self.set(**kwargs)
        return await self.start(timeout=timeout, wait_done=wait_done)

    async def start(self, data=None, timeout=DEFAULT_TIMEOUT, wait_done=True):
        """Start a command.

        Parameters
        ----------
        data : ``self.DataType`` (optional)
            Command data. If None then send the current data.
        timeout : `float` (optional)
            Time limit, in seconds. If None then no time limit.
            This time limit is for the entire command if wait_done
            is true, else it is for the first acknowledgement
            after the initial "SAL__CMD_ACK".
        wait_done : `bool` (optional)
            If True then wait for final command acknowledgement.
            If False then wait for the first acknowledgement after the
            initial "SAL__CMD_ACK"; if that acknowledgement is not final
            (the ack code is not in done_ack_codes), then you will almost
            certainly want to await `next_ackcmd`.

        Returns
        -------
        ackcmd : `SalInfo.AckCmdType`
            Command acknowledgement.

        Raises
        ------
        salobj.AckError
            If the command fails.
        salobj.AckTimeoutError
            If the command times out.
        TypeError
            If ``data`` is not None and not an instance of `DataType`.
        """
        if data is not None:
            self.data = data
        self.put()
        seq_num = self.data.private_seqNum
        if seq_num in self.salinfo._running_cmds:
            raise RuntimeError(
                f"{self.name} bug: a command with seq_num={seq_num} is already running"
            )
        cmd_info = _CommandInfo(
            remote_command=self, seq_num=seq_num, wait_done=wait_done
        )
        self.salinfo._running_cmds[seq_num] = cmd_info
        return await cmd_info.next_ackcmd(timeout=timeout)
