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

__all__ = ["QueueCapacityChecker", "ReadTopic", "DEFAULT_QUEUE_LEN", "MIN_QUEUE_LEN"]

import asyncio
import bisect
import collections
import inspect
import logging
import typing
import warnings
from collections.abc import Awaitable, Callable, Collection

import dds
from lsst.ts import utils

from .. import base, type_hints
from .base_topic import BaseTopic

if typing.TYPE_CHECKING:
    from ..sal_info import SalInfo

# Default value for the ``queue_len`` constructor argument.
DEFAULT_QUEUE_LEN = 100

# Minimum value for the ``queue_len`` constructor argument.
MIN_QUEUE_LEN = 10


# TODO DM-37502: change "_BasicReturnType | Awaitable[_BasicReturnType]"
# to "Awaitable[_BasicReturnType]"
# once we drop support for synchronous callback functions.
_BasicReturnType = type_hints.AckCmdDataType | None
CallbackType = Callable[
    [type_hints.BaseMsgType],
    _BasicReturnType | Awaitable[_BasicReturnType],
]


class QueueCapacityChecker:
    """Log warnings for a fixed-length queue that should contain
    no more than one item.

    Call `check_nitems` to check the number of items in the queue.
    This will log a warning or error, if appropriate.

    Parameters
    ----------
    descr : `str`
        Brief description of queue, e.g. "python read queue"
        or "DDS read queue".
    log : `logging.Logger`
        Logger to which to write messages.
    queue_len : `int`
        Length of queue

    Attributes
    ----------
    warn_thresholds : `List` [`int`]
        Values for ``warn_threshold`` (see next item). Set to:

        * 5-10 elements, whichever is closest to ``queue_len/10``
        * 1/2 full, but only if ``queue_len >= 20``
        * 9/10 full
        * full

        The corresponding reset thresholds are 1/2 these values.

    warn_threshold : `int` or `None`
        A call to ``check_nitems(n)`` with ``n > warn_threshold``
        will produce a log message and update ``warn_threshold``
        and ``reset__threshold`` as follows:

        *  ``warn_threshold`` is set to the largest warn threshold <= n
           in ``warn_thresholds``, or `None` if the queue is full.
        * ``reset_threshold`` is set to the half of the next lower
          warning threshold.
    reset_threshold : `int` or `None`
        A call to ``check_nitems(n)`` with ``n < reset_threshold``
        will reduce ``warn_threshold`` and ``reset_threshold`` as follows:

        * ``reset_threshold`` is set to the largest reset threshold <= n,
          or `None` if the queue is empty.
        * ``warn_threshold`` is set to the warning threshold
          corresponding to one reset higher reset level.

    Notes
    -----
    Once a message has been logged for a particular threshold,
    no more messages are sent until either the queue fills enough
    to cross the next warning threshold or empties enough to reduce
    the warning threshold.

    Log messages are warnings unless the queue is full. A full queue
    produces an error because data is likely to have been lost.
    """

    def __init__(self, descr: str, log: logging.Logger, queue_len: int) -> None:
        if queue_len < MIN_QUEUE_LEN:
            raise ValueError(
                f"queue_len {queue_len} must be >= MIN_QUEUE_LEN={MIN_QUEUE_LEN}"
            )
        self.descr = descr
        self.log = log
        self.queue_len = queue_len
        warn_thresholds = [
            min(10, max(5, queue_len // 10)),
            queue_len * 9 // 10,
            queue_len,
        ]
        if queue_len >= 20:
            warn_thresholds.append(queue_len // 2)
        self.warn_thresholds = tuple(sorted(warn_thresholds))
        self._reset_thresholds = tuple(
            warn_thresh // 2 for warn_thresh in self.warn_thresholds
        )
        self.warn_threshold: int | None = self.warn_thresholds[0]
        self.reset_threshold: int | None = None

    def check_nitems(self, nitems: int) -> bool:
        """Check the number of items in the queue and log a message
        if appropriate.

        Parameters
        ----------
        nitems : `int`
            Number of elements in the queue.

        Returns
        -------
        did_log: `bool`
            True if a message was logged.
        """
        if self.warn_threshold is not None and nitems >= self.warn_threshold:
            # Issue a warning or error log message
            # and set new warning and reset thresholds.
            if nitems >= self.queue_len:
                self.warn_threshold = None
                self.reset_threshold = self._reset_thresholds[-1]
                self.log.error(
                    f"{self.descr} is full ({self.queue_len} elements); data may be lost"
                )
            else:
                index = bisect.bisect_right(self.warn_thresholds, nitems)
                self.warn_threshold = self.warn_thresholds[index]
                self.reset_threshold = self._reset_thresholds[index - 1]
                self.log.warning(
                    f"{self.descr} is filling: {nitems} of {self.queue_len} elements"
                )
            return True
        elif self.reset_threshold is not None and nitems <= self.reset_threshold:
            # Reset to lower warning and reset thresholds
            index = bisect.bisect_right(self._reset_thresholds, nitems - 1)
            self.warn_threshold = self.warn_thresholds[index]
            if index > 0:
                self.reset_threshold = self._reset_thresholds[index - 1]
            else:
                self.reset_threshold = None
        return False


class ReadTopic(BaseTopic):
    r"""Base class for reading a topic.

    Parameters
    ----------
    salinfo : `SalInfo`
        SAL component information
    attr_name : `str`
        Topic name with attribute prefix. The prefix must be one of:
        ``cmd_``, ``evt_``, ``tel_``, or (only for the ackcmd topic) ``ack_``.
    max_history : `int`
        Maximum number of historical items to read:

        * 0 is required for commands, events, and the ackcmd topic.
        * 1 is recommended for telemetry. For an indexed component
          it is possible for data from one index to push data for another
          index off the DDS queue, so historical data is not guaranteed.
        * For the special case of reading an indexed SAL component
          with index=0 (read all indices) the only allowed values are 0 or 1.
          If 1 then retrieve the most recent sample for each index
          that is still in the read queue, in the order received.
          max_history > 1 is forbidden, because it is difficult to implement.
    queue_len : `int`, optional
        The maximum number of messages that can be read and not dealt with
        by a callback function or `next` before older messages will be dropped.
    filter_ackcmd : `bool`, optional
        Filter out ackcmd topics so we only see responses to commands
        that we sent? This is normally what you want, but it is not wanted
        for SAL/Kafka producers.
        Ignored if ``name`` != "ackcmd".

    Raises
    ------
    ValueError
        If max_history < 0.
    ValueError
        If max_history > 0 and the topic is volatile (command or ackcmd).
    ValueError
        If queue_len < MIN_QUEUE_LEN.
    ValueError
        If max_history > queue_len.
    ValueError
        If for an indexed component if index=0 and max_history > 1.
        Reading more than one historical sample per index is more trouble
        than it is worth.
    UserWarning
        If max_history > DDS history queue depth or DDS durability service
        history depth for this topic.
        This is a warning rather than an exception, so that the DDS quality
        of service can be changed without breaking existing code.

    Attributes
    ----------
    isopen : `bool`
        Is this read topic open? `True` until `close` or `basic_close`
        is called.
    dds_queue_length_checker : `QueueCapacityChecker`
        Queue length checker for the DDS queue.
    python_queue_length_checker : `QueueCapacityChecker`:
        Queue length checker for the Python queue.

    Notes
    -----
    **Queues**

    There are two queues: a Python queue whose length is set by ``queue_len``
    and a dds queue whose length is set by the DDS Quality of Service file.
    (The Python queue is needed because of limitations in the API for
    the OpenSplice DDS queue, including no access to the most recent message,
    no ability to ask how many messages are on the queue, and no asyncio
    support). In the doc strings for the methods, below, any reference
    to the queue refers to the Python queue.

    Data can be lost from either queue:

    - If this class cannot read messages from the DDS queue fast enough,
      then older messages will be dropped from the DDS queue. You will get
      several warning log messages as the DDS queue fills.
    - As messages are read from the DDS queue they are put on the Python queue.
      If a callback function or `next` does not process data quickly enough
      then older messages are dropped from the Python queue.
      If you have a callback function then you will get several
      warning log messages as the Python queue fills up;
      you get no warning otherwise because `ReadTopic` has no way of knowing
      whether or not you intend to read all messages.

    **Reading**

    Reading is performed by the contained `SalInfo`, which has single
    read loop that reads messages for all topics. This is more efficient
    than having each `ReadTopic` read its own messages.

    **Modifying Messages**

    All functions that return messages return them from some form of internal
    cache. This presents a risk: if any reader modifies a message, then it
    will be modified for all readers of that message. To safely modify a
    returned message, make your own copy with ``copy.copy(data)``.
    """

    def __init__(
        self,
        *,
        salinfo: SalInfo,
        attr_name: str,
        max_history: int,
        queue_len: int = DEFAULT_QUEUE_LEN,
        filter_ackcmd: bool = True,
    ) -> None:
        super().__init__(salinfo=salinfo, attr_name=attr_name)
        self.isopen = True
        self._allow_multiple_callbacks = False
        if max_history < 0:
            raise ValueError(f"max_history={max_history} must be >= 0")
        if max_history > 0 and self.volatile:
            raise ValueError(f"max_history={max_history} must be 0 for volatile topics")
        if salinfo.indexed and salinfo.index == 0 and max_history > 1:
            raise ValueError(
                f"max_history={max_history} must be 0 or 1 "
                "for an indexed component read with index=0"
            )
        if queue_len <= MIN_QUEUE_LEN:
            raise ValueError(
                f"queue_len={queue_len} must be >= MIN_QUEUE_LEN={MIN_QUEUE_LEN}"
            )
        if max_history > queue_len:
            raise ValueError(
                f"max_history={max_history} must be <= queue_len={queue_len}"
            )
        if (
            max_history > self.qos_set.reader_qos.history.depth
            or max_history > self.qos_set.topic_qos.durability_service.history_depth
        ):
            warnings.warn(
                f"max_history={max_history} > history depth={self.qos_set.reader_qos.history.depth} "
                f"and/or {self.qos_set.topic_qos.durability_service.history_depth}; "
                "you will get less historical data than you asked for.",
                UserWarning,
            )
        self._max_history = int(max_history)
        self._data_queue: collections.deque[type_hints.BaseMsgType] = collections.deque(
            maxlen=queue_len
        )
        self._current_data: type_hints.BaseMsgType | None = None
        # Event that is set when new data arrives. Used by aget.
        self._new_data_event = asyncio.Event()
        # Task that `next` waits on.
        # Its result is set to the oldest message on the queue.
        # We do this instead of having `next` itself pop the oldest message
        # because it allows multiple callers of `next` to all get the same
        # message, and it avoids a potential race condition with `flush`.
        self._next_task = utils.make_done_future()
        self._callback: CallbackType | None = None
        self._callback_tasks: set[asyncio.Task] = set()
        self._callback_loop_task = utils.make_done_future()
        self.dds_queue_length_checker = QueueCapacityChecker(
            descr=f"{attr_name} DDS read queue",
            log=self.log,
            queue_len=self.qos_set.reader_qos.history.depth,
        )
        self.python_queue_length_checker = QueueCapacityChecker(
            descr=f"{attr_name} python read queue", log=self.log, queue_len=queue_len
        )
        # Command topics use a different a partition name than
        # all other topics, including ackcmd, and the partition name
        # is part of the publisher and subscriber.
        # This split allows us to create just one subscriber and one publisher
        # for each Controller or Remote:
        # `Controller` only needs a cmd_subscriber and data_publisher,
        # `Remote` only needs a cmd_publisher and data_subscriber.
        if attr_name.startswith("cmd_"):
            subscriber = salinfo.cmd_subscriber
        else:
            subscriber = salinfo.data_subscriber
        self._reader = subscriber.create_datareader(
            self._topic, self.qos_set.reader_qos
        )
        # TODO DM-26411: replace ANY_INSTANCE_STATE with ALIVE_INSTANCE_STATE
        # once the OpenSplice issue 00020647 is fixed.
        read_mask = [
            dds.DDSStateKind.NOT_READ_SAMPLE_STATE,
            dds.DDSStateKind.ANY_INSTANCE_STATE,
        ]
        queries = []
        if salinfo.index > 0:
            queries.append(f"salIndex = {salinfo.index}")
        if attr_name == "ack_ackcmd" and filter_ackcmd:
            queries += [
                f"origin = {salinfo.domain.origin}",
                f"identity = '{salinfo.identity}'",
            ]
        if queries:
            full_query = " AND ".join(queries)
            read_condition = dds.QueryCondition(self._reader, read_mask, full_query)
        else:
            read_condition = self._reader.create_readcondition(read_mask)
        self._read_condition = read_condition

        salinfo.add_reader(self)

    @property
    def allow_multiple_callbacks(self) -> bool:
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
    def allow_multiple_callbacks(self, allow: bool) -> None:
        self._allow_multiple_callbacks = bool(allow)

    @property
    def callback(
        self,
    ) -> CallbackType | None:
        """Asynchronous callback function, or None if there is not one.

        Synchronous callback functions are deprecated.

        The callback function is called when a new message is received;
        it receives one argument: the message (an object of type
        `topics.BaseTopic.DataType`).

        Raises
        ------
        TypeError
            When setting a new callback if the callback is not None
            and is not callable.

        Notes
        -----
        Setting a callback flushes the queue, and it will remain empty
        as long as there is a callback.

        `get_oldest` and `next` are prohibited if there is a callback function.
        Technically they could both work, but `get_oldest` would always return
        `None` and `next` would miss messages if they arrived while waiting
        for something else. It seems safer to raise an exception.
        """
        return self._callback

    @callback.setter
    def callback(self, func: CallbackType | None) -> None:
        if func is not None:
            if not callable(func):
                raise TypeError(f"callback {func} not callable")
            if not inspect.iscoroutinefunction(
                func
            ) and not asyncio.iscoroutinefunction(
                func.__call__  # type: ignore
            ):
                # TODO DM-37502: modify this to raise (and update doc string)
                # once we drop support for synchronous callback functions.
                warnings.warn(
                    f"callback {func} should be asynchronous",
                    category=DeprecationWarning,
                )

        self._cancel_callbacks()

        if func is None:
            # clear the existing callback
            self._callback = None
            return

        # flush the queue, set a new callback and restart the callback loop
        if not callable(func):
            raise TypeError(f"func={func} not callable")
        self._data_queue.clear()
        self._callback = func
        self._callback_loop_task = asyncio.create_task(self._callback_loop())

    @property
    def has_callback(self) -> bool:
        """Return True if there is a callback function."""
        return self._callback is not None

    @property
    def has_data(self) -> bool:
        """Has any data ever been seen for this topic?

        Raises
        ------
        RuntimeError
            If the ``salinfo`` has not started reading.
        """
        self.salinfo.assert_started()
        return self._current_data is not None

    @property
    def nqueued(self) -> int:
        """Return the number of messages in the Python queue."""
        return len(self._data_queue)

    @property
    def max_history(self) -> int:
        return self._max_history

    def basic_close(self) -> None:
        """A synchronous and possibly less thorough version of `close`.

        Intended for exit handlers and constructor error handlers.
        """
        if not self.isopen:
            return
        self.isopen = False
        self._callback = None
        try:
            # These raise RuntimeError if the asyncio loop is not running.
            self._cancel_callbacks()
            self._next_task.cancel()
        except RuntimeError:
            pass
        self._reader.close()
        self._data_queue.clear()

    async def close(self) -> None:
        """Shut down and release resources.

        Intended to be called by SalInfo.close(),
        since that tracks all topics.
        """
        self.basic_close()

    async def aget(self, timeout: float | None = None) -> type_hints.BaseMsgType:
        """Get the most recently seen message (with no delay), or wait for
        data if no data has ever been seen (`has_data` False).

        This is almost exactly like `get`. The only difference: if no data
        has ever been received by this topic it will wait for data.
        Once the topic has received *any* data, calling `aget` is identical
        to calling `get` (except for the need to use ``await``) and the call
        will return almost instantly.

        Please avoid `aget`, if possible, because it tends to confuse users.
        Use `get` to get the current data or `next` to wait for new data
        (you will almost never need both for the same topic).

        Parameters
        ----------
        timeout : `float`, optional
            Time limit, in seconds. If None then no time limit.

        Returns
        -------
        data : `DataType`
            The current or next message.

        Raises
        ------
        asyncio.TimeoutError
            If no message is available within the specified time limit.
        RuntimeError
            If a callback function is present,
            or if the ``salinfo`` has not started reading.

        Notes
        -----
        This method does not remove data from the queue, so it does not
        change which data is returned by `next`.
        In that respect it is not quite identical to this snippet,
        which otherwise does the same thing as `aget`::

            data = self.get()
            if data is None:
                data = await self.next(flush=False, timeout=timeout)
            return data

        Do not modify the returned data. To make a copy that you can
        safely modify, use ``copy.copy(data)``.
        """
        self.salinfo.assert_started()
        if self.has_callback:
            raise RuntimeError("Not allowed because there is a callback function")
        if self._current_data is None:
            self._new_data_event.clear()
            await asyncio.wait_for(self._new_data_event.wait(), timeout=timeout)
        assert self._current_data is not None  # make mypy happy
        return self._current_data

    def flush(self) -> None:
        """Flush the queue used by `get_oldest` and `next`.

        This makes `get_oldest` return `None` and `next` wait,
        until a new message arrives.
        It does not change which message will be returned by `aget` or `get`.

        Raises
        ------
        RuntimeError
            If a callback function is present.
        """
        if self.has_callback:
            raise RuntimeError("Not allowed because there is a callback function")
        self._data_queue.clear()

    def get(self) -> type_hints.BaseMsgType | None:
        """Get the most recent message, or `None` if no data has ever been seen
        (`has_data` False).

        This method does not change which message will be returned by `aget`,
        `get_oldest`, and `next`.

        Returns
        -------
        data : ``self.DataType`` or `None`
            Return ``self.data`` if data has been read, else `None`.

        Raises
        ------
        RuntimeError
            If the ``salinfo`` has not started reading.
        """
        self.salinfo.assert_started()

        return self._current_data

    def get_oldest(self) -> type_hints.BaseMsgType | None:
        """Pop and return the oldest message from the queue, or `None` if the
        queue is empty.

        This is a variant of `next` that does not wait for a new message.
        This method affects which message will be returned by `next`,
        but not which message will be returned by `aget` or `get`.

        Returns
        -------
        data : ``self.DataType`` or `None`
            The oldest message found on the queue, if any, else `None`.

        Raises
        ------
        RuntimeError
            If a callback function is present,
            or if the ``salinfo`` has not started reading.

        Notes
        -----
        Use with caution when mixing with `next`, since that also
        consumes data from the queue.
        """
        self.salinfo.assert_started()
        if self.has_callback:
            raise RuntimeError("Not allowed because there is a callback function")
        if self._data_queue:
            return self._data_queue.popleft()
        return None

    async def next(
        self, *, flush: bool, timeout: float | None = None
    ) -> type_hints.BaseMsgType:
        """Pop and return the oldest message from the queue, waiting for data
        if the queue is empty.

        This method affects the data returned by `get_oldest`,
        but not the data returned by `aget` or `get`.

        Parameters
        ----------
        flush : `bool`
            If `True` then flush the queue before starting a read.
            This guarantees that the method will wait for a new message.
            If `False` and there is data on the queue, then pop and return
            the oldest message from the queue, without waiting;
            if queue is empty then wait for a new message.
        timeout : `float`, optional
            Time limit, in seconds. If None then no time limit.

        Returns
        -------
        data : `DataType`
            The message data.

        Raises
        ------
        asyncio.TimeoutError
            If no message is available within the specified time limit.
        RuntimeError
            If a callback function is present,
            or if the ``salinfo`` has not started reading.

        Notes
        -----
        Do not modify the returned data. To make a copy that you can
        safely modify, use ``copy.copy(data)``.
        """
        self.salinfo.assert_started()
        if self.has_callback:
            raise RuntimeError("Not allowed because there is a callback function")
        if flush:
            self.flush()
        return await self._next(timeout=timeout)

    async def _next(self, *, timeout: float | None = None) -> type_hints.BaseMsgType:
        """Implement next.

        Unlike `next`, this can be called while using a callback function.
        """
        self.python_queue_length_checker.check_nitems(len(self._data_queue))
        if self._data_queue:
            return self._data_queue.popleft()
        if self._next_task.done():
            self._next_task = asyncio.Future()
        return await asyncio.wait_for(self._next_task, timeout=timeout)

    async def _callback_loop(self) -> None:
        while True:
            if not self.has_callback:
                return
            data = await self._next()
            result = self._run_callback(data)
            if self.allow_multiple_callbacks:
                # Purge done callback tasks and add a new one.
                self._callback_tasks = {
                    task for task in self._callback_tasks if not task.done()
                }
                self._callback_tasks.add(asyncio.create_task(result))
            else:
                await result

    def _cancel_callbacks(self) -> None:
        """Cancel the callback loop and all existing callback tasks."""
        self._callback_loop_task.cancel()
        while self._callback_tasks:
            task = self._callback_tasks.pop()
            task.cancel()

    async def _run_callback(self, data: type_hints.BaseMsgType) -> None:
        try:
            # mypy gets upset because self._callback may be None
            # but it's too expensive to check that
            result = self._callback(data)  # type: ignore
            if inspect.isawaitable(result):
                await result  # type: ignore
        except asyncio.CancelledError:
            raise
        except Exception as e:
            if not isinstance(e, base.ExpectedError):
                self.log.exception(f"Callback {self.callback} failed with data={data}")

    def _queue_data(self, data_list: Collection[type_hints.BaseMsgType]) -> None:
        """Queue messages.

        Parameters
        ----------
        data_list : Collection[type_hints.BaseMsgType]
            Messages to be queueued.

        Also update ``self._current_data`` and fire `self._next_task`
        (if pending).
        """
        if not data_list:
            return
        for data in data_list:
            self._queue_one_item(data)
        self._current_data = data
        self._new_data_event.set()
        self._report_next()

    def _queue_one_item(self, data: type_hints.BaseMsgType) -> None:
        """Add a single message to the Python queue.

        Subclasses may override this to modify the message before queuing.
        `ControllerCommand` does this.
        """
        self._data_queue.append(data)

    def _report_next(self) -> None:
        """Set self._next_task to the oldest message on the queue.

        A no-op if self._next_task is done or the queue is empty.
        """
        if not self._next_task.done() and self._data_queue:
            oldest_message = self._data_queue.popleft()
            self._next_task.set_result(oldest_message)
