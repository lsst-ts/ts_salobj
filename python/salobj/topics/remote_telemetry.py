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
        self._setup()
        self._cached_data = self.DataType()
        self._cached_data_valid = False

    @property
    def DataType(self):
        """The class of data for this topic."""
        return self._DataType

    def get(self):
        """Read the most recent data.

        If data has never been seen, then return None.

        If there is a callback function then get_oldest will always
        return the most recently cached data. If the callback function
        is working its way through queued data then this may not be
        the most recent data.
        """
        if self.has_callback:
            return self._cached_data

        retcode = self._get_newest_func(self._cached_data)
        if retcode == self.salinfo.lib.SAL__OK:
            self._cached_data_valid = True
            return self._cached_data
        elif retcode == self.salinfo.lib.SAL__NO_UPDATES:
            return self._cached_data if self.has_data else None
        else:
            raise RuntimeError(f"get failed with retcode={retcode} from {self._get_newest_func_name}")

    @property
    def has_data(self):
        """Has data ever been read, e.g. by `get`?"""
        return self._cached_data_valid

    def next(self, flush=True, timeout=None):
        """Get the next data.

        Parameters
        ----------
        flush : `bool`
            If True then flush the queue before starting a read.
            If False then pop and return the oldest item from the queue,
            if any, else start reading new data.
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
        ``flush`` and ``next`` are prohibited while there is a callback
        function.
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
            self._callback_func(task.result())
        finally:
            self._queue_callback()

    def _queue_callback(self):
        self._callback_task = asyncio.ensure_future(self._next(timeout=None))
        self._callback_task.add_done_callback(self.self._run_callback)

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
            retcode = self._get_oldest_func(self._cached_data)
            if retcode == self.salinfo.lib.SAL__OK:
                self._cached_data_valid = True
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
