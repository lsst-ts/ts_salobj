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

__all__ = ["AckCmdWriter", "ControllerCommand"]

import inspect

from .. import sal_enums
from .. import base
from . import read_topic
from . import write_topic


class AckCmdWriter(write_topic.WriteTopic):
    """Command Acknowledgement writer."""
    def __init__(self, salinfo):
        super().__init__(salinfo=salinfo, name="ackcmd", sal_prefix="", min_seq_num=None)


class ControllerCommand(read_topic.ReadTopic):
    """Read a specified command topic.

    Each command must be acknowledged. If you use a callback function
    to process the command then this happens automatically (including
    acknowledging as a failure if the callback raises an exception).
    Otherwise you must the `ack` method to do this yourself.

    Parameters
    ----------
    salinfo : `SalInfo`
        SAL component information
    name : `str`
        Command name
    """
    def __init__(self, salinfo, name, max_history=0, queue_len=100):
        super().__init__(salinfo=salinfo, name=name, sal_prefix="command_",
                         max_history=max_history, queue_len=queue_len)
        self.cmdtype = salinfo.sal_topic_names.index(self.sal_name)
        self._ack_writer = AckCmdWriter(salinfo=salinfo)

    def ack(self, data, ackcmd):
        """Acknowledge a command by writing a new state.

        Parameters
        ----------
        data : `DataType`
            Command data.
        ackcmd : `salobj.AckCmdType`
            Command acknowledgement.
        """
        self._ack_writer.set(private_seqNum=data.private_seqNum,
                             host=data.private_host,
                             origin=data.private_origin,
                             cmdtype=self.cmdtype,
                             ack=ackcmd.ack,
                             error=ackcmd.error,
                             result=ackcmd.result)
        self._ack_writer.put()

    def ackInProgress(self, data, result=""):
        """Ackowledge this command as "in progress".
        """
        ackcmd = self.salinfo.makeAckCmd(private_seqNum=data.private_seqNum,
                                         ack=sal_enums.SalRetCode.CMD_INPROGRESS, result=result)
        self.ack(data, ackcmd)

    async def next(self, *, timeout=None):
        """Wait for data, returning old data if found.

        Unlike `RemoteEvent.next` and `RemoteTelemetry.next`,
        the flush argument is not allowed; the only way to flush
        old commands is to call `flush`.

        Parameters
        ----------
        timeout : `float` (optional)
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

    def _queue_one_item(self, data):
        if data.private_seqNum <= 0:
            raise ValueError(f"private_seqNum={data.private_seqNum} must be positive")
        ack = self.salinfo.makeAckCmd(private_seqNum=data.private_seqNum, ack=sal_enums.SalRetCode.CMD_ACK)
        self.ack(data, ack)
        super()._queue_one_item(data)

    async def _run_callback(self, data):
        """Run the callback function, acknowledge the command,
        and start another wait.

        Parameters
        ----------
        data : `DataType`
            Command data.
        """
        try:
            result = self._callback(data)
            if inspect.isawaitable(result):
                self.ackInProgress(data)
                ack = await result
            else:
                ack = result
            if ack is None:
                ack = self.salinfo.makeAckCmd(private_seqNum=data.private_seqNum,
                                              ack=sal_enums.SalRetCode.CMD_COMPLETE, result="Done")
            self.ack(data, ack)
        except Exception as e:
            ack = self.salinfo.makeAckCmd(private_seqNum=data.private_seqNum,
                                          ack=sal_enums.SalRetCode.CMD_FAILED, error=1,
                                          result=f"Failed: {e}", truncate_result=True)
            self.ack(data, ack)
            if not isinstance(e, base.ExpectedError):
                self.log.exception(f"Callback {self.callback} failed with data={data}")
