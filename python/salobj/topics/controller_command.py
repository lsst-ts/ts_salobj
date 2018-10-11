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

__all__ = ["ControllerCommand"]

import asyncio
from ..base import CommandIdData


class ControllerCommand:
    """An object that receives a specific command for a SAL component

    Parameters
    ----------
    salinfo : `salobj.SalInfo`
        SAL component information
    name : `str`
        Command name
    """
    def __init__(self, salinfo, name):
        self.name = str(name)
        self.salinfo = salinfo
        self._setup()

    @property
    def DataType(self):
        """The class of data for this command."""
        return self._DataType

    def ack(self, id_data, ack):
        """Acknowledge a command by writing a new state.

        Parameters
        ----------
        id_data : `salobj.CommandIdData`
            Command ID and data.
        ack : `salobj.AckType`
            Command acknowledgement.
        """
        self._ack_func(id_data.cmd_id, ack.ack, ack.error, ack.result)

    def get(self):
        """Pop the oldest command from the queue and return it.

        Returns
        -------
        cmd_info : `salobj.CommandIdData`
            Command info, or None of no command is available.
        """
        if self._callback_func is not None:
            raise RuntimeError("`get` prohibited while there is a callback function.")

        data = self.DataType()
        cmd_id = self._accept_func(data)
        if cmd_id > 0:
            return CommandIdData(cmd_id, data)
        return None

    def next(self):
        """Like `get` but if no command is on the queue then wait for one.
        """
        if self._callback_func is not None:
            raise RuntimeError("`start` prohibited while there is a callback function.")
        return self._next()

    @property
    def callback(self):
        """Callback function, or None if there is not one.

        The callback function is called when new data is received;
        it receives one argument: a `salobj.CommandIdData` containing
        the command ID and the command data.

        Acknowledgement of the command is automatic:

        * If the callback raises an exception then the command
          is acknowledged as failed.
        * If the callback returns None then the command is
          acknowledged as completed.
        * If the callback returns an instance of `salobj.AckType`,
          then the command is acknowledged with that.
          If that ack is not final, then you must issue the final ack
          yourself, by calling `ack`.

        Raises
        ------
        TypeError
            When setting a new value if the value is not None
            and is not callable.

        Notes
        -----
        `next` is prohibited while there is a callback function.
        """
        return self._callback_func

    @callback.setter
    def callback(self, func):
        self._callback_func = func

        if func is None:
            if self._callback_task:
                self._callback_task.cancel()
            self._callback_func = None
            return

        if not callable(func):
            raise TypeError(f"func={func} not callable")
        self._callback_func = func
        self._queue_callback()

    @property
    def has_callback(self):
        """Return True if there is a callback function"""
        return self._callback_func is not None

    def __str__(self):
        return f"ControllerCommand({self.salinfo}, {self.name})"

    def _run_callback(self, task):
        """Run the callback function, acknowledge the command,
        and start another wait.

        Parameters
        ----------
        task : `asyncio.Task`
            The task that completed. Its result must be an instance
            of `salobj.CommandIdData`.
        """
        if not self.callback:
            return
        try:
            id_data = task.result()
            # sanity check the return value,
            # to save the callback from getting garbage
            assert id_data.cmd_id > 0
            assert isinstance(id_data.data, self.DataType)
            ack = self._callback_func(id_data)
            if ack is None:
                ack = self.salinfo.makeAck(self.salinfo.lib.SAL__CMD_COMPLETE, result="Done")
            self.ack(id_data, ack)
        except Exception as e:
            ack = self.salinfo.makeAck(self.salinfo.lib.SAL__CMD_FAILED, error=1, result=f"Failed: {e}")
            self.ack(id_data, ack)
        finally:
            self._queue_callback()

    def _queue_callback(self):
        self._callback_task = asyncio.ensure_future(self._next())
        self._callback_task.add_done_callback(self._run_callback)

    def _next(self):
        """Implement next.

        Unlike `next`, this can be called while using a callback function.
        """
        return self._wait_next()

    async def _wait_next(self):
        """Wait for the next command."""
        data = self.DataType()
        while True:
            cmd_id = self._accept_func(data)
            if cmd_id > 0:
                return CommandIdData(cmd_id, data)

            await asyncio.sleep(0.05)

    def _setup(self):
        """Get SAL functions and tell SAL that I want to receive this command."""
        self._callback_func = None  # callback function, if any
        self._callback_task = None  # task waiting to run callback, if any
        self._accept_func = getattr(self.salinfo.manager, 'acceptCommand_' + self.name)
        self._ack_func = getattr(self.salinfo.manager, 'ackCommand_' + self.name)
        self._DataType = getattr(self.salinfo.lib, self.salinfo.name + "_command_" + self.name + "C")

        topic_name = self.salinfo.name + "_command_" + self.name
        retcode = self.salinfo.manager.salProcessor(topic_name)
        if retcode != self.salinfo.lib.SAL__OK:
            raise RuntimeError(f"salProcessor({topic_name}) failed with return code {retcode}")
