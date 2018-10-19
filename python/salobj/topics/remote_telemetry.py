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

__all__ = ["RemoteTelemetry"]

import asyncio
import inspect
import time


class RemoteTelemetry:
    """An object that reads a specific telemetry topic
    from a SAL component.

    Parameters
    ----------
    salinfo : `salobj.SalInfo`
        SAL component information
    name : `str`
        Telemetry topic name

    Notes
    -----
    Please try to avoid excessive use of callbacks. However, they have
    their place. In particular, if you have data that is computed
    based on one one or more events or telemetry topics, you can easily
    keep that data current by creating a method to compute it and
    subscribing that method to the appropriate topics.
    """
    def __init__(self, salinfo, name):
        self.salinfo = salinfo
        self.name = str(name)
        self._callback_func = None  # callback function, if any
        self._callback_task = None  # task waiting to run callback, if any
        self._allow_multiple_callbacks = True
        self._cached_data = None
        self._setup()

    @property
    def DataType(self):
        """The class of data for this topic."""
        return self._DataType

    def get(self):
        """Read the most recent data.

        If data has never been seen, then return None.

        If there is no callback function (which is typical)
        then this also flushes the queue.

        If there is a callback function then get will always
        return the most recently cached data. If the callback function
        is working its way through queued data then this may not be
        the most recent data.
        """
        if self.has_callback:
            return self._cached_data

        new_data = self.DataType()
        retcode = self._get_newest_func(new_data)
        if retcode == self.salinfo.lib.SAL__OK:
            self._cached_data = new_data
            return self._cached_data
        elif retcode == self.salinfo.lib.SAL__NO_UPDATES:
            return self._cached_data
        else:
            raise RuntimeError(f"get failed with retcode={retcode} from {self._get_newest_func_name}")

    def get_oldest(self):
        """Pop and return the oldest data from the queue.

        If there is no more data, then return None

        Raises
        ------
        RuntimeError
            If a callback function is present.
        """
        if self.has_callback:
            raise RuntimeError("`get_oldest` not supported while there is a callback function")

        data = self.DataType()
        retcode = self._get_oldest_func(data)
        if retcode == self.salinfo.lib.SAL__OK:
            return data
        elif retcode == self.salinfo.lib.SAL__NO_UPDATES:
            return None
        else:
            raise RuntimeError(f"get failed with retcode={retcode} from {self._get_oldest_func_name}")

    @property
    def has_data(self):
        """Has data ever been read, e.g. by `get`?"""
        return self._cached_data is not None

    def next(self, flush=True, timeout=None):
        """Get the next data.

        Parameters
        ----------
        flush : `bool`
            If True then flush the queue before starting a read.
            If False then pop and return the oldest item from the queue,
            if any, else wait for new data.
        timeout : `float` (optional)
            Time limit, in seconds. If None then no time limit.

        Returns
        -------
        coro : `coroutine`
            A coroutine that waits for the next data to be seen
            and returns that data.

        Raises
        ------
        RuntimeError
            If a callback function is present.
        """
        if self.has_callback:
            raise RuntimeError("`next` not supported while there is a callback function")

        if flush:
            self.flush()
        return self._next(timeout=timeout)

    def flush(self):
        """Flush the queue.

        This affects the value returned by `next`,
        but not affect the value returned by `get`.

        Raises
        ------
        RuntimeError
            If a callback function is present.
        """
        if self.has_callback:
            raise RuntimeError("`flush` not supported while there is a callback function")
        # the SAL flush function needs data, but doesn't do anything with it
        null_data = self.DataType()
        self._flush_func(null_data)

    @property
    def allow_multiple_callbacks(self):
        """Can mutiple callbacks run simultaneously?

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

    @property
    def callback(self):
        """Callback function, or None if there is not one.

        The callback function is called when new data is received;
        it receives one argument: the data.

        Raises
        ------
        TypeError
            When setting a new callback if the callback is not None
            and is not callable.

        Notes
        -----
        The callback function can be synchronous or asynchronous
        (e.g. defined with ``async def``).
        If it is asynchronous then you should set the command property
        `allow_multiple_callbacks` False if you wish to prohibit
        more than one instance of the callback to be run at a time.

        ``flush``, ``get_oldest`` and ``next`` are prohibited
        while there is a callback function.
        """
        return self._callback_func

    @callback.setter
    def callback(self, func):
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
        """Return True if there is a callback function."""
        return self._callback_func is not None

    def __str__(self):
        return f"{type(self).__name__}({self.salinfo}, {self.name})"

    def _run_callback(self, task):
        """Run the callback function and start another wait."""
        if not self.callback:
            return

        try:
            is_awaitable = False
            data = task.result()
            result = self._callback_func(data)

            if inspect.isawaitable(result):
                is_awaitable = True
                asyncio.ensure_future(self._finish_awaitable_callback(result))
        finally:
            if not is_awaitable or self.allow_multiple_callbacks:
                self._queue_callback()

    async def _finish_awaitable_callback(self, coro):
        """Wait for the callback to finish.

        Parameters
        ----------
        coro : `asyncio.coroutine`
            Awaitable returned by the callback function.
        """
        try:
            await coro
        finally:
            if not self.allow_multiple_callbacks:
                self._queue_callback()

    def _queue_callback(self):
        self._callback_task = asyncio.ensure_future(self._next(timeout=None))
        self._callback_task.add_done_callback(self._run_callback)

    def _next(self, timeout):
        """Implement next.

        Unlike `next`, this can be called while using a callback function.
        """
        return self._wait_next(timeout=timeout)

    async def _wait_next(self, timeout):
        """Wait for the next data.

        Parameters
        ----------
        timeout : `float` (optional)
            Time limit, in seconds. If None then no time limit.

        Returns
        -------
        coro : `coroutine`
            A coroutine that waits for the next data to be seen
            and returns that data.
        """
        end_time = time.time() + timeout if timeout else None
        while True:
            new_data = self.DataType()
            retcode = self._get_oldest_func(new_data)
            if retcode == self.salinfo.lib.SAL__OK:
                self._cached_data = new_data
                return self._cached_data
            elif retcode == self.salinfo.lib.SAL__NO_UPDATES:
                if end_time and time.time() > end_time:
                    raise asyncio.TimeoutError()
                else:
                    await asyncio.sleep(0.05)
            else:
                raise RuntimeError(f"bad return code {retcode} from {self._get_oldest_func_name}")

    def _setup(self):
        """Get functions from salinfo and subscribe to the topic."""
        # also save function names for error reporting
        self._get_newest_func_name = "getSample_" + self.name
        self._get_newest_func = getattr(self.salinfo.manager, self._get_newest_func_name)
        self._get_oldest_func_name = "getNextSample_" + self.name
        self._get_oldest_func = getattr(self.salinfo.manager, self._get_oldest_func_name)
        self._flush_func_name = "flushSamples_" + self.name
        self._flush_func = getattr(self.salinfo.manager, self._flush_func_name)
        self._DataType_name = self.salinfo.name + "_" + self.name + "C"
        self._DataType = getattr(self.salinfo.lib, self._DataType_name)

        topic_name = self.salinfo.name + "_" + self.name
        retcode = self.salinfo.manager.salTelemetrySub(topic_name)
        if retcode != self.salinfo.lib.SAL__OK:
            raise RuntimeError(f"salTelemetrySub({topic_name}) failed with return code {retcode}")
