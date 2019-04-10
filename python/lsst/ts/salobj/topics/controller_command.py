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

__all__ = ["ControllerCommand"]

import asyncio
import inspect
import time

from .base_topic import BaseTopic, SAL_SLEEP
from ..base import CommandIdData, ExpectedError


class ControllerCommand(BaseTopic):
    """An object that receives a specific command for a SAL component

    Parameters
    ----------
    salinfo : `lsst.ts.salobj.SalInfo`
        SAL component information
    name : `str`
        Command name
    log : `logging.Logger`
        Logger to which to log messages, including exceptions
        in callback functions.
    """
    def __init__(self, salinfo, name, log):
        super().__init__(salinfo=salinfo, name=name)
        self.log = log
        self._callback_func = None  # callback function, if any
        self._callback_task = None  # task waiting to run callback, if any
        self._allow_multiple_callbacks = False

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
        time.sleep(SAL_SLEEP)

    def ackInProgress(self, id_data, result=""):
        """Ackowledge this command as "in progress".
        """
        ack = self.salinfo.makeAck(self.salinfo.lib.SAL__CMD_INPROGRESS, result=result)
        self.ack(id_data, ack)

    @property
    def allow_multiple_callbacks(self):
        """Can mutiple callbacks run simultaneously?

        False by default.

        Notes
        -----
        This is handled automatically for the following cases:

        * Awaitable callbacks that do all the work themselves
          (meaning that they do not start additional tasks that
          they don't wait for).
        * Synchronous callbacks that do all the work themselves.
          In this case the attribute is ignored, since only
          one instance of the callback can ever run at one time.

        If the callback function starts a task that it does not wait for,
        you will have to handle prohibition of multiple callbacks manually,
        e.g. by overriding `_run_callback`.
        """
        return self._allow_multiple_callbacks

    @allow_multiple_callbacks.setter
    def allow_multiple_callbacks(self, allow):
        self._allow_multiple_callbacks = bool(allow)

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
        time.sleep(SAL_SLEEP)
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

        Raises
        ------
        TypeError
            When setting a new value if the value is not None
            and is not callable.

        Notes
        -----
        The callback function can be synchronous or asynchronous
        (e.g. defined with ``async def``).
        If it is asynchronous then you should set the command property
        `allow_multiple_callbacks` False if you wish to prohibit
        more than one instance of the callback to be run at a time.

        Acknowledgement of the command is automatic:

        * If the callback is asynchronous then the command is
          acknowledged as InProgress before the callback begins.
        * If the callback raises an exception then the command
          is acknowledged as failed.
        * If the callback returns None then the command is
          acknowledged as completed.
        * If the callback returns an instance of `salobj.AckType`,
          then the command is acknowledged with that.
          If that ack is not final, then you must issue the final ack
          yourself, by calling `ack`.
          This feature is deprecated and should not be used in new code.

        `next` is prohibited while there is a callback function.

        If a callback must perform slow synchronous operations,
        such as CPU-heavy tasks, make the method asynchronous
        and call the synchronous operation in a thread using
        the ``run_in_executor`` method of the event loop.
        """
        return self._callback_func

    @callback.setter
    def callback(self, func):
        if func is None:
            self._callback_func = None
            if self._callback_task:
                self._callback_task.cancel()
            return

        if not callable(func):
            raise TypeError(f"func={func} not callable")
        self._callback_func = func
        self._queue_callback()

    @property
    def has_callback(self):
        """Return True if there is a callback function.

        This property is read-only.
        """
        return self._callback_func is not None

    def __del__(self):
        callback_task = getattr(self, "_callback_task", None)
        if callback_task is not None and not self._callback_task.done():
            self._callback_task.cancel()

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
            is_awaitable = False
            id_data = task.result()
            assert id_data.cmd_id > 0
            assert isinstance(id_data.data, self.DataType)

            result = self._callback_func(id_data)
            if inspect.isawaitable(result):
                is_awaitable = True
                self.ackInProgress(id_data)
                asyncio.ensure_future(self._finish_awaitable_callback(id_data, result))
            else:
                if result is None:
                    ack = self.salinfo.makeAck(self.salinfo.lib.SAL__CMD_COMPLETE, result="Done")
                else:
                    ack = result
                self.ack(id_data, ack)
        except Exception as e:
            ack = self.salinfo.makeAck(self.salinfo.lib.SAL__CMD_FAILED, error=1, result=f"Failed: {e}")
            self.ack(id_data, ack)
            if not isinstance(e, ExpectedError):
                self.log.exception(f"cmd_{self.name} callback failed")
        finally:
            if not is_awaitable or self.allow_multiple_callbacks:
                self._queue_callback()

    async def _finish_awaitable_callback(self, id_data, coro):
        """Wait for the callback to finish and acknowledge the command.

        Parameters
        ----------
        id_data : `salobj.CommandIdData`
            Command ID and data.
        coro : `asyncio.coroutine`
            Awaitable returned by the callback function.
        """
        try:
            ack = await coro
            if ack is None:
                ack = self.salinfo.makeAck(self.salinfo.lib.SAL__CMD_COMPLETE, result="Done")
            self.ack(id_data, ack)
        except Exception as e:
            ack = self.salinfo.makeAck(self.salinfo.lib.SAL__CMD_FAILED, error=1, result=f"Failed: {e}")
            self.ack(id_data, ack)
            if not isinstance(e, ExpectedError):
                self.log.exception(f"coro cmd_{self.name} callback failed")
        finally:
            if not self.allow_multiple_callbacks:
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
                time.sleep(SAL_SLEEP)
                return CommandIdData(cmd_id, data)

            await asyncio.sleep(0.05)

    def _setup(self):
        """Get SAL functions and tell SAL that I want to receive this command.
        """
        self._accept_func = getattr(self.salinfo.manager, 'acceptCommand_' + self.name)
        self._ack_func = getattr(self.salinfo.manager, 'ackCommand_' + self.name)
        self._DataType = getattr(self.salinfo.lib, self.salinfo.name + "_command_" + self.name + "C")

        topic_name = self.salinfo.name + "_command_" + self.name
        try:  # work around lack of topic name in SAL's exception message
            self.salinfo.manager.salProcessor(topic_name)
        except Exception as e:
            raise RuntimeError(f"Could not subscribe to command {self.name}") from e
        time.sleep(SAL_SLEEP)
