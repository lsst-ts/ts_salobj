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

__all__ = ["AckCmdWriter", "ControllerCommand"]

import asyncio
import inspect
import typing

from .. import sal_enums
from .. import base
from .. import type_hints
from . import read_topic
from . import write_topic

if typing.TYPE_CHECKING:
    from ..sal_info import SalInfo


class AckCmdWriter(write_topic.WriteTopic):
    """ackcmd (command acknowledgement) topic writer.

    Parameters
    ----------
    salinfo : `SalInfo`
        SAL component information
    """

    def __init__(self, salinfo: SalInfo) -> None:
        super().__init__(salinfo=salinfo, attr_name="ack_ackcmd", min_seq_num=None)


class ControllerCommand(read_topic.ReadTopic):
    """Read a specified command topic.

    Parameters
    ----------
    salinfo : `SalInfo`
        SAL component information.
    name : `str`
        Command name, with no prefix, e.g. "start".
    queue_len : `int`, optional
        Number of elements that can be queued for `get_oldest`.

    Notes
    -----
    Each command must be acknowledged by writing an appropriate ``ackcmd``
    message. If you use a callback function to process the command
    then this happens automatically, as follows:

    * If the callback function returns `None` then send a final
      acknowledgement with ``ack=SalRetCode.CMD_COMPLETE``.
    * If the callback function returns an acknowledgement
      (instance of `SalInfo.AckCmdType`) instead of `None`, then send that
      as the final acknowledgement. This is very unusual, but might
      be useful if the callback wants to exit early and leave some
      background task or thread processing the rest of the command.
    * If the callback function raises `asyncio.TimeoutError` then send a
      final acknowledgement with ``ack=SalRetCode.CMD_TIMEOUT``.
    * If the callback function raises `asyncio.CancelledError` then send
      a final acknowledgement with ``ack=SalRetCode.CMD_ABORTED``.
    * If the callback function raises `ExpectedError` then send a final
      acknowledgement with ``ack=SalRetCode.CMD_FAILED`` and
      ``result=f"Failed: {exception}"``.
    * If the callback function raises any other `Exception`
      then do the same as `ExpectedError` and also log a traceback.
    """

    def __init__(
        self, salinfo: SalInfo, name: str, queue_len: int = read_topic.DEFAULT_QUEUE_LEN
    ) -> None:
        super().__init__(
            salinfo=salinfo,
            attr_name="cmd_" + name,
            max_history=0,
            queue_len=queue_len,
        )
        # TODO DM-32379: replace salinfo.default_authorize with True
        self.authorize = salinfo.default_authorize
        self.cmdtype = salinfo.sal_topic_names.index(self.sal_name)
        if salinfo._ackcmd_writer is None:
            self.salinfo._ackcmd_writer = AckCmdWriter(salinfo=salinfo)

    async def ack(
        self, data: type_hints.BaseMsgType, ackcmd: type_hints.AckCmdDataType
    ) -> None:
        """Acknowledge a command by writing a new state.

        Parameters
        ----------
        data : `DataType`
            Data for the command being acknowledged.
        ackcmd : `salobj.AckCmdType`
            Command acknowledgement data.

        Raises
        ------
        RuntimeError
            If self.salinfo is not running. This may occur at shutdown.
            (It is much less likely if the SalInfo as not started,
            because the SalInfo will not have received any commands.)
        """
        # mypy thinks salinfo._ackcmd_writer can be None, but it can't.
        # Testing is expensive, so hide the warnings.
        await self.salinfo._ackcmd_writer.set_write(  # type: ignore
            private_seqNum=data.private_seqNum,
            origin=data.private_origin,
            identity=data.private_identity,
            cmdtype=self.cmdtype,
            ack=ackcmd.ack,
            error=ackcmd.error,
            result=ackcmd.result,
            timeout=ackcmd.timeout,
        )

    async def ack_in_progress(
        self, data: type_hints.BaseMsgType, timeout: float, result: str = ""
    ) -> None:
        """Ackowledge this command as "in progress".

        Parameters
        ----------
        data : `DataType`
            Data for the command being acknowledged.
        timeout : `float`
            Estimated command duration (sec).
        result : `str`, optional
            Reason for acknowledgement. Typically left "".

        Raises
        ------
        RuntimeError
            If self.salinfo is not running. This may occur at shutdown.
            (It is much less likely if the SalInfo as not started,
            because the SalInfo will not have received any commands.)
        """
        ackcmd = self.salinfo.make_ackcmd(
            private_seqNum=data.private_seqNum,
            ack=sal_enums.SalRetCode.CMD_INPROGRESS,
            result=result,
            timeout=timeout,
        )
        await self.ack(data=data, ackcmd=ackcmd)

    async def next(  # type: ignore[override]  # noqa
        self, *, timeout: float | None = None
    ) -> type_hints.BaseMsgType:
        """Wait for data, returning old data if found.

        Unlike `RemoteEvent.next` and `RemoteTelemetry.next`,
        the flush argument is not allowed; the only way to flush
        old commands is to call `flush`.

        Parameters
        ----------
        timeout : `float`, optional
            Time limit, in seconds. If None then no time limit.

        Returns
        -------
        data : `DataType`
            Command data.

        Raises
        ------
        RuntimeError
            If a callback function is present.

        Notes
        -----
        Do not modify the data or assume that it will be static.
        If you need a private copy, then copy it yourself.
        """
        return await super().next(flush=False, timeout=timeout)

    async def _ack_if_running(
        self, data: type_hints.BaseMsgType, ackcmd: type_hints.AckCmdDataType
    ) -> None:
        """Wrapper around self.ack that logs a warning if not salinfo.running.

        This allows methods of this class to safely acknowledge commands,
        without having to test if the SalInfo is still running.
        The ack will succeed if it can, and log a warning if it can't.
        There isn't much else that a ControllerCommand instance can do
        if a command finishes or fails while the SalInfo is shutting down.

        Parameters
        ----------
        data : `DataType`
            Data for the command being acknowledged.
        ackcmd : `salobj.AckCmdType`
            Command acknowledgement data.
        """
        if not self.salinfo.running:
            self.log.warning(f"Cannot issue {ackcmd=}; SalInfo is not running")
            return
        await self.ack(data=data, ackcmd=ackcmd)

    def _queue_one_item(self, data: type_hints.BaseMsgType) -> None:
        """Queue the message if it has a valid sequence number.

        This override checks for a positive private_seqNum
        and raises ValueError if not.
        """
        if data.private_seqNum <= 0:
            raise ValueError(f"private_seqNum={data.private_seqNum} must be positive")
        super()._queue_one_item(data)

    async def _run_callback(self, data: type_hints.BaseMsgType) -> None:
        """Run the callback function, acknowledge the command,
        and start another wait.

        Parameters
        ----------
        data : `DataType`
            Command data.
        """
        if self.authorize:
            try:
                identity = data.private_identity
                auth_error = None
                if "@" in identity:
                    # A user
                    if (
                        identity != self.salinfo.domain.user_host
                        and identity not in self.salinfo.authorized_users
                    ):
                        auth_error = (
                            f"User identity {identity!r} "
                            f"not self ({self.salinfo.domain.user_host}) "
                            f"and not in {self.salinfo.authorized_users}"
                        )
                elif identity in self.salinfo.non_authorized_cscs:
                    auth_error = f"CSC identity {identity!r} in {self.salinfo.non_authorized_cscs}"
                if auth_error is not None:
                    ack = self.salinfo.make_ackcmd(
                        private_seqNum=data.private_seqNum,
                        ack=sal_enums.SalRetCode.CMD_NOPERM,
                        error=1,
                        result=f"Not authorized: {auth_error}",
                    )
                    await self.ack(data, ack)
                    return
            except Exception:
                self.log.exception("Error checking identity")

        try:
            result = self._callback(data)  # type: ignore
            if inspect.isawaitable(result):
                ack = await result  # type: ignore
            else:
                ack = result  # type: ignore
            if ack is None:
                ack = self.salinfo.make_ackcmd(
                    private_seqNum=data.private_seqNum,
                    ack=sal_enums.SalRetCode.CMD_COMPLETE,
                    result="Done",
                )
            await self._ack_if_running(data, ack)
        except asyncio.CancelledError:
            ack = self.salinfo.make_ackcmd(
                private_seqNum=data.private_seqNum,
                ack=sal_enums.SalRetCode.CMD_ABORTED,
                error=1,
                result="Aborted",
            )
            await self._ack_if_running(data, ack)
        except asyncio.TimeoutError:
            ack = self.salinfo.make_ackcmd(
                private_seqNum=data.private_seqNum,
                ack=sal_enums.SalRetCode.CMD_TIMEOUT,
                error=1,
                result="Timeout",
            )
            await self._ack_if_running(data, ack)
        except Exception as e:
            ack = self.salinfo.make_ackcmd(
                private_seqNum=data.private_seqNum,
                ack=sal_enums.SalRetCode.CMD_FAILED,
                error=1,
                result=f"Failed: {e}",
            )
            await self._ack_if_running(data, ack)
            if not isinstance(e, base.ExpectedError):
                self.log.exception(f"Callback {self.callback} failed with data={data}")
