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

__all__ = ["ReadTopic"]

import asyncio
import collections
import inspect

import dds

from .base_topic import BaseTopic
from .. import base


class QueueLengthChecker:
    """Check queue length with a set of graded warnings.

    Parameters
    ----------
    queue_len : `int`
        Length of queue
    """
    def __init__(self, queue_len):
        # 2-3 warnings:
        # * 5-10
        # * 1/2 queue_len if >= 10
        # * 9/10 queue_len
        if queue_len < 10:
            raise ValueError(f"queue_len {queue_len} must be >= 10")
        warn_lengths = [min(10, max(5, queue_len // 10))]
        if queue_len >= 20:
            warn_lengths.append(queue_len // 2)
        warn_lengths.append(queue_len*9 // 10)
        self._warn_lengths = tuple(warn_lengths)
        self._warn_level = self._warn_lengths[0]
        self._warn_index = 0
        self._reset_level = None

    def length_ok(self, length):
        if self._warn_level is not None and length >= self._warn_level:
            self._reset_level = self._warn_level // 2
            self._warn_index += 1
            if self._warn_index < len(self._warn_lengths):
                self._warn_level = self._warn_lengths[self._warn_index]
            else:
                self._warn_level = None
            return False
        elif self._reset_level is not None and length <= self._reset_level:
            self._warn_index -= 1
            self._warn_level = self._warn_lengths[self._warn_index]
            if self._warn_index > 0:
                self._reset_level = self._warn_lengths[self._warn_index-1] // 2
            else:
                self._reset_level = None
        return True


class ReadTopic(BaseTopic):
    r"""Base class for reading a topic.

    Parameters
    ----------
    salinfo : `SalInfo`
        SAL component information
    name : `str`
        Topic name, without a "command\_" or "logevent\_" prefix.
    sal_prefix : `str`
        SAL topic prefix: one of "command\_", "logevent\_" or ""
    max_history : `int`
        Maximum number of historical items to read:

        * 0 is strongly recommended for commands and the ackcmd reader
        * 1 is recommended for events and telemetry
    queue_len : `int` (optional)
        The maximum number of items that can be read and not dealt with
        by a callback function or `next` before older data will be dropped.

    Notes
    -----
    There are actually two queues: an internal queue whose length
    is set by ``queue_len`` and a dds queue whose length is set by
    low level configuration. Data can be lost in two ways:
    - If this class cannot read data from the dds queue fast enough
    then older data will be dropped from the dds queue. You will get a warning
    log message if the reader starts to fall behind.
    - As data is read it is put on the internal queue. if a callback
    function or `next` does not process data quickly enough then
    older data is dropped from the internal queue. If you have a callback
    function you will get several warning log messages as this internal queue
    fills up. You get no warning otherwise because this class has no way
    of knowing if you intend to read all data using `next`.
    """
    def __init__(self, *, salinfo, name, sal_prefix, max_history, queue_len=100):
        super().__init__(salinfo=salinfo, name=name, sal_prefix=sal_prefix)
        self.isopen = True
        self._allow_multiple_callbacks = False
        if max_history < 0:
            raise ValueError(f"max_history={max_history} must be >= 0")
        if queue_len <= 0:
            raise ValueError(f"queue_len={queue_len} must be positive")
        if max_history > queue_len:
            raise ValueError(f"max_history={max_history} must be <= queue_len={queue_len}")
        self._max_history = int(max_history)
        self._data_queue = collections.deque(maxlen=queue_len)
        self._current_data = None
        # task that `next` waits on
        self._next_task = base.make_done_future()
        self._callback = None
        self._callback_tasks = set()
        self._callback_loop_task = base.make_done_future()
        self._length_checker = QueueLengthChecker(queue_len)
        self._warned_readloop = False
        self._reader = salinfo.subscriber.create_datareader(self._topic, salinfo.domain.reader_qos)
        if name == "ackcmd" or sal_prefix == "command_":
            # TODO DM-20313: remove this workaround for DM-20312:
            # SALPY 3.10 disposes of ackcmd and command samples
            # immediately after writing them, so don't require ALIVE
            read_mask = [dds.DDSStateKind.NOT_READ_SAMPLE_STATE]
        else:
            read_mask = [dds.DDSStateKind.NOT_READ_SAMPLE_STATE,
                         dds.DDSStateKind.ALIVE_INSTANCE_STATE]
        if salinfo.index > 0:
            query = f"{salinfo.name}ID = {salinfo.index}"
            read_condition = dds.QueryCondition(self._reader, read_mask, query)
        else:
            read_condition = self._reader.create_readcondition(read_mask)
        self._read_condition = read_condition

        salinfo.add_reader(self)

    @property
    def allow_multiple_callbacks(self):
        """Can callbacks can run simultaneously?

        Notes
        -----
        Ignored for synchronous callbacks because those block
        while running. In particular, if the callback is
        synchronous but launches one or more background jobs
        then the number of those jobs cannot be limited by
        this class.
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

        Setting a callback flushes the queue, and it will remain empty
        as long as there is a callback.

        `get_oldest` and `next` are prohibited if there is a callback function.
        Technically they could both work, but `get_oldest` would always return
        `None` and `next` would miss data if it arrived while waiting
        for something else. It seemed safer to just raise an exception.
        """
        return self._callback

    @callback.setter
    def callback(self, func):
        # cancel the callback loop and clear out existing callbacks
        self._callback_loop_task.cancel()
        for task in self._callback_tasks:
            task.cancel()
            self._callback_tasks = set()

        if func is None:
            # clear the existing callback
            self._callback = None
            return

        # flush the queue, set a new callback and restart the callback loop
        if not callable(func):
            raise TypeError(f"func={func} not callable")
        self._data_queue.clear()
        self._callback = func
        self._callback_loop_task = asyncio.ensure_future(self._callback_loop())

    @property
    def has_callback(self):
        """Return True if there is a callback function."""
        return self._callback is not None

    @property
    def has_data(self):
        """Has `data` ever been read?"""
        return self._current_data is not None

    @property
    def max_history(self):
        return self._max_history

    async def close(self):
        """Shut down and release resources.

        Intended to be called by SalInfo.close(),
        since that frees all DDS resources.
        """
        if not self.isopen:
            return
        self.isopen = False
        self._callback = None
        self._callback_loop_task.cancel()
        self._next_task.cancel()
        while self._callback_tasks:
            task = self._callback_tasks.pop()
            task.cancel()
        self._data_queue.clear()

    def flush(self):
        """Flush the queue of unread messages.

        Raises
        ------
        RuntimeError
            If a callback function is present.
        """
        if self.has_callback:
            raise RuntimeError("Not allowed because there is a callback function")
        self._data_queue.clear()

    def get(self, flush=True):
        """Get the most recently seen value, or `None` if no data ever seen.

        Parameters
        ----------
        flush : `bool` (optional)
            Flush the queue? Defaults to `True` for backwards compatibility.
            This only affects the next value returned by `next`
            and is ignored if there is a callback function.

        Returns
        -------
        data : ``self.DataType`` or `None`
            Return ``self.data`` if data has been read, else `None`.
        """
        if flush and not self.has_callback:
            self.flush()
        return self._current_data

    def get_oldest(self):
        """Pop and return the oldest data from the queue, or `None`
        if all data has been read.

        Returns
        -------
        data : ``self.DataType`` or `None`
            Return ``self.data`` if unread data was found on the queue,
            else ``None``.

        Raises
        ------
        RuntimeError
            If a callback function is present.

        Notes
        -----
        Use with caution when mixing with `next`, since that also
        consumes data from the queue.
        """
        if self.has_callback:
            raise RuntimeError("Not allowed because there is a callback function")
        if self._data_queue:
            return self._data_queue.popleft()
        return None

    async def next(self, *, flush, timeout=None):
        """Wait for data, returning old data if found.

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
        data : `DataType`
            The data.

        Raises
        ------
        RuntimeError
            If a callback function is present.

        Notes
        -----
        Do not modify the data or assume that it will be static.
        If you need a private copy, then copy it yourself.
        """
        if self.has_callback:
            raise RuntimeError("Not allowed because there is a callback function")
        if flush:
            self.flush()
        return await self._next(timeout=timeout)

    async def _next(self, *, timeout=None):
        """Implement next.

        Unlike `next`, this can be called while using a callback function.
        """
        if not self._length_checker.length_ok(len(self._data_queue)):
            self.log.warning(f"falling behind; queue contains {len(self._data_queue)} elements")
        if self._data_queue:
            return self._data_queue.popleft()
        if self._next_task.done():
            self._next_task = asyncio.Future()
        await asyncio.wait_for(self._next_task, timeout=timeout)
        return self._data_queue.popleft()

    async def _callback_loop(self):
        while True:
            if not self.has_callback:
                return
            data = await self._next()
            result = self._run_callback(data)
            if self.allow_multiple_callbacks:
                self._callback_tasks = {task for task in self._callback_tasks if not task.done()}
                self._callback_tasks.add(asyncio.ensure_future(result))
            else:
                await result

    async def _run_callback(self, data):
        try:
            result = self._callback(data)
            if inspect.isawaitable(result):
                await result
        except asyncio.CancelledError:
            raise
        except Exception as e:
            if not isinstance(e, base.ExpectedError):
                self.log.exception(f"Callback {self.callback} failed with data={data}")

    def _queue_data(self, data_list):
        """Convert items of data and add them to the internal queue.

        Also update self._current_data and fire self._next_task if waiting.
        """
        if not data_list:
            return
        for data in data_list:
            self._queue_one_item(data)
        self._current_data = data
        if not self._next_task.done():
            self._next_task.set_result(None)

    def _queue_one_item(self, data):
        self._data_queue.append(data)
