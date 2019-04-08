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

__all__ = ["RemoteCommand"]

import asyncio
import logging
import time
import warnings

from ..base import AckError, CommandIdAck
from .base_topic import BaseOutputTopic, SAL_SLEEP

DEFAULT_TIMEOUT = 60*60  # default timeout, in seconds


class _CommandInfo:
    """Struct to hold information about a command.

    Parameters
    ----------
    remote_command : `RemoteCommand`
        Remote command.
    cmd_id : `int`
        Command ID.
    ack : `salobj.AckType`
        Command acknowledgement.
    wait_done : `bool`
        Wait until the command is done to finish the task?
    """
    def __init__(self, remote_command, cmd_id, wait_done):
        self.remote_command = remote_command
        self.cmd_id = int(cmd_id)
        self.ack = remote_command.salinfo.AckType()
        self.wait_done = bool(wait_done)
        self.done_task = asyncio.Future()
        """A task that is set to the final CommandIdAck when the command
        is done, or raises salobj.AckError if the command fails.
        """
        self._timeout_task = None
        lib = self.remote_command.salinfo.lib
        self.good_ack_codes = (lib.SAL__CMD_ACK, lib.SAL__CMD_INPROGRESS, lib.SAL__CMD_COMPLETE)

    def start_timeout(self, timeout):
        """Start waiting for an ack."""
        # reset done_task in case we are starting a new wait with `next_ack`.
        self.done_task = asyncio.Future()
        self._timeout_task = asyncio.ensure_future(self._start_timeout(timeout))

    def set_final_ack(self, ack, cancel_timeout):
        """End waiting for an ack.

        Parameters
        ----------
        ack : `salobj.AckType`
            Command acknowledgement
        cancel_timeout : `bool`
            If True then cancel the timeout_task.
            If False then report timeout.
        """
        if self.done_task.done():
            return
        if cancel_timeout:
            if self._timeout_task is None or self._timeout_task.done():
                warnings.warn(f"{self}._timeout_task is already done")
            self._timeout_task.cancel()
        if ack.ack in self.good_ack_codes:
            self.done_task.set_result(CommandIdAck(cmd_id=self.cmd_id, ack=ack))
        else:
            self.done_task.set_exception(
                AckError(f"Command failed with ack code {ack.ack}", cmd_id=self.cmd_id, ack=ack))

    def __del__(self):
        timeout_task = getattr(self, "_timeout_task", None)
        if timeout_task is not None and not timeout_task.done():
            timeout_task.cancel()

    def __repr__(self):
        return f"_CommandInfo(remote_command={self.remote_command}, cmd_id={self.cmd_id}, " \
               f"wait_done={self.wait_done}, ack.ack={self.ack.ack})"

    async def _start_timeout(self, timeout):
        if timeout is None:
            timeout = DEFAULT_TIMEOUT
        await asyncio.sleep(timeout)

        # Set the final ack to NOACK, which is the correct code for the reader
        # timing out (TIMEOUT is for timing out at the controller).
        self.ack.ack = self.remote_command.salinfo.lib.SAL__CMD_NOACK
        if self.cmd_id in self.remote_command._running_cmds:
            self.remote_command._running_cmds.pop(self.cmd_id)
        self.set_final_ack(ack=self.ack, cancel_timeout=False)


class RemoteCommand(BaseOutputTopic):
    """An object that issues a specific command to a SAL component.

    Parameters
    ----------
    salinfo : `lsst.ts.salobj.SalInfo`
        SAL component information
    name : `str`
        Command name
    """
    def __init__(self, salinfo, name):
        super().__init__(salinfo=salinfo, name=name)
        self.log = logging.getLogger(f"{salinfo}.RemoteCommand.{name}")
        self._running_cmds = dict()
        self._next_ack_task = None

    def next_ack(self, cmd_id_ack, timeout=None, wait_done=True):
        """Wait for the next acknowledement for the command

        Parameters
        ----------
        cmd_id : `lsst.ts.salobj.CommandIdAck`
            The command ID and acknowledgement returned by
            the previous wait (e.g. from `start`).
        timeout : `float` (optional)
            Time limit, in seconds. If None then no time limit.
            This time limit is for the entire command if wait_done
            is true, else it is for the first acknowledgement
            after the initial "SAL__CMD_ACK".
        wait_done : `bool` (optional)
            If True then wait for final command acknowledgement,
            otherwise wait until the next ack; if that acknowledgement
            is not final (the ack code is not in done_ack_codes),
            then you will almost certainly want to await `next_ack` again.

        Returns
        -------
        coro : `coroutine`
            A coroutine that waits for command acknowledgement
            and returns a `lsst.ts.salobj.CommandIdAck` instance.

        Raises
        ------
        salobj.AckError
            If the command fails or times out.
        RuntimeError
            If the command specified by ``cmd_id`` is unknown
            or has already finished.
        """
        cmd_info = self._running_cmds.get(cmd_id_ack.cmd_id, None)
        if cmd_info is None:
            raise RuntimeError(f"Command cmd_id={cmd_id_ack.cmd_id} is unknown or finished")
        cmd_info.wait_done = wait_done
        self._start_wait_for_ack(cmd_info=cmd_info, timeout=timeout)
        return cmd_info.done_task

    async def start(self, data=None, timeout=None, wait_done=True):
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
            certainly want to await `next_ack`.

        Returns
        -------
        coro : `coroutine`
            A coroutine that waits for command acknowledgement
            and returns a `lsst.ts.salobj.CommandIdAck` instance.

        Raises
        ------
        salobj.AckError
            If the command fails or times out.
        TypeError
            If ``data`` is not None and not an instance of `DataType`.
        """
        if data is not None:
            self.data = data
        cmd_id = self._issue_func(self.data)
        await asyncio.sleep(SAL_SLEEP)
        if cmd_id <= 0:
            raise RuntimeError(f"{self.name} command with data={data} could not be started")
        if cmd_id in self._running_cmds:
            raise RuntimeError(f"{self.name} bug: a command with cmd_id={cmd_id} is already running")
        cmd_info = _CommandInfo(remote_command=self, cmd_id=cmd_id, wait_done=wait_done)
        self._running_cmds[cmd_id] = cmd_info
        self._start_wait_for_ack(cmd_info=cmd_info, timeout=timeout)
        return await cmd_info.done_task

    def _start_wait_for_ack(self, cmd_info, timeout):
        cmd_info.start_timeout(timeout)
        if self._next_ack_task is None or self._next_ack_task.done():
            self._next_ack_task = asyncio.ensure_future(self._next_ack_loop())

    async def _next_ack_loop(self):
        """Read command acks until self._running_cmds is empty.
        """
        ack = self.salinfo.AckType()
        while True:
            try:
                response_id = self._response_func(ack)
                await asyncio.sleep(SAL_SLEEP)
            except Exception as e:
                self.log.warning(f"{self._response_func_name} raised {e}")
                continue
            if response_id == self.salinfo.lib.SAL__CMD_NOACK:
                pass  # no new ack
            elif response_id < 0:
                self.log.warning(f"{self._response_func_name} returned {response_id}")
            elif response_id in self._running_cmds:
                cmd_info = self._running_cmds[response_id]
                cmd_info.ack = ack
                if cmd_info.done_task:
                    is_done = ack.ack in self.done_ack_codes
                    do_end_task = is_done if cmd_info.wait_done else True
                    if is_done:
                        del self._running_cmds[response_id]
                    if do_end_task:
                        cmd_info.set_final_ack(ack=ack, cancel_timeout=True)

            if self._running_cmds:
                await asyncio.sleep(0.05)
            else:
                return

    def _setup(self):
        """Get SAL functions."""
        self._issue_func_name = "issueCommand_" + self.name
        self._issue_func = getattr(self.salinfo.manager, self._issue_func_name)
        self._response_func_name = "getResponse_" + self.name
        self._response_func = getattr(self.salinfo.manager, self._response_func_name)
        self._AckType = getattr(self.salinfo.lib, self.salinfo.name + "_ackcmdC")
        self._DataType = getattr(self.salinfo.lib, self.salinfo.name + "_command_" + self.name + "C")
        self.done_ack_codes = frozenset((
            self.salinfo.lib.SAL__CMD_ABORTED,
            self.salinfo.lib.SAL__CMD_COMPLETE,
            self.salinfo.lib.SAL__CMD_FAILED,
            self.salinfo.lib.SAL__CMD_NOACK,
            self.salinfo.lib.SAL__CMD_NOPERM,
            self.salinfo.lib.SAL__CMD_STALLED,
            self.salinfo.lib.SAL__CMD_TIMEOUT,
        ))

        topic_name = self.salinfo.name + "_command_" + self.name
        try:  # work around lack of topic name in SAL's exception message
            self.salinfo.manager.salCommand(topic_name)
        except Exception as e:
            raise RuntimeError(f"Could not subscribe to command {self.name}") from e
        time.sleep(SAL_SLEEP)
