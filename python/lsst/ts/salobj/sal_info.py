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

__all__ = ["SalInfo", "MAX_RESULT_LEN"]

import asyncio
import atexit
import concurrent
import logging
import os
import time
import types
import typing
import warnings

import dds
import ddsutil

from . import base
from . import idl_metadata
from . import sal_enums
from . import topics
from . import type_hints
from .domain import Domain

# Maximum length of the ``result`` field in an ``ackcmd`` topic.
MAX_RESULT_LEN = 256

# We want SAL logMessage messages for at least INFO level messages,
# so if the current level is less verbose, set it to INFO.
# Do not change the level if it is already more verbose,
# because somebody has intentionally increased verbosity
# (a common thing to do in unit tests).
MAX_LOG_LEVEL = logging.INFO

# The maximum number of historical samples to read for each topic.
# This can be any value larger than the length of the longest DDS write queue.
# If it is too short then you risk mixing historical data
# with new data samples, which can produce very confusing behavior.
MAX_HISTORY_READ = 10000

# Default time to wait for historical data (sec);
# override by setting env var $LSST_DDS_HISTORYSYNC.
DEFAULT_LSST_DDS_HISTORYSYNC = 60


class SalInfo:
    r"""DDS information for one SAL component and its DDS partition

    Parameters
    ----------
    domain : `Domain`
        DDS domain participant and quality of service information.
    name : `str`
        SAL component name.
    index : `int`, optional
        Component index; 0 or None if this component is not indexed.

    Raises
    ------
    RuntimeError
        If environment variable ``LSST_DDS_PARTITION_PREFIX`` is not defined.
    RuntimeError
        If the IDL file cannot be found for the specified ``name``.
    TypeError
        If ``domain`` is not a `Domain`.
    ValueError
        If ``index`` is nonzero and the component is not indexed.

    Attributes
    ----------
    domain : `Domain`
        The ``domain`` constructor argument.
    name : `str`
        The ``name`` constructor argument.
    index : `int`
        The ``index`` constructor argument.
    indexed : `bool`
        `True` if this SAL component is indexed (meaning a non-zero index
        is allowed), `False` if not.
    identity : `str`
        Value used for the private_identity field of DDS messages.
        Defaults to username@host, but CSCs should use the CSC name:
        * SAL_component_name for a non-indexed SAL component
        * SAL_component_name:index for an indexed SAL component.
    isopen : `bool`
        Is this read topic open? `True` until `close` is called.
    log : `logging.Logger`
        A logger.
    partition_prefix : `str`
        The DDS partition name prefix, from environment variable
        ``LSST_DDS_PARTITION_PREFIX``.
    publisher : ``dds.Publisher``
        A DDS publisher, used to create DDS writers.
    subscriber : ``dds.Subscriber``
        A DDS subscriber, used to create DDS readers.
    start_task : `asyncio.Task`
        A task which is finished when `start` is done,
        or to an exception if `start` fails.
    done_task : `asyncio.Task`
        A task which is finished when `close` is done.
    command_names : `List` [`str`]
        A tuple of command names without the ``"command_"`` prefix.
    event_names : `List` [`str`]
        A tuple of event names, without the ``"logevent_"`` prefix
    telemetry_names : `List` [`str`]
        A tuple of telemetry topic names.
    sal_topic_names : `List` [`str`]
        A tuple of SAL topic names, e.g. "logevent_summaryState",
        in alphabetical order.
    revnames : `dict` [`str`, `str`]
        A dict of topic name: name_revision.
    topic_info : `dict` [`str`, `TopicMetadata`]
        A dict of SAL topic name: topic metadata.
    authorized_users : `List` [`str`]
        Set of users authorized to command this component.
    non_authorized_cscs : `List` [`str`]
        Set of CSCs that are not authorized to command this component.

    Notes
    -----
    Reads the following `Environment Variables
    <https://ts-salobj.lsst.io/configuration.html#environment_variables>`_;
    follow the link for details:

    * ``LSST_DDS_PARTITION_PREFIX`` (required): the DDS partition name.
    * ``LSST_DDS_HISTORYSYNC``, optional: time limit (sec)
      for waiting for historical (late-joiner) data.

    **Usage**

    Call `start` after constructing this `SalInfo` and all `Remote` objects.
    Until `start` is called no data will be read.

    Each `SalInfo` automatically registers itself with the specified ``domain``
    for cleanup using a weak reference to avoid circular dependencies.
    You may safely close a `SalInfo` before closing its domain,
    and this is recommended if you create and destroy many remotes.

    **DDS Partition Names**

    The DDS partition name for each topic is {prefix}.{name}.{suffix}, where:

    * ``prefix`` = $LSST_DDS_PARTITION_PREFIX
      (fall back to $LSST_DDS_DOMAIN if necessary).
    * ``name`` = the ``name`` constructor argument.
    * ``suffix`` = "cmd" for command topics, and "data" for all other topics,
      including ``ackcmd``.

    The idea is that each `Remote` and `Controller` should have just one
    subscriber and one publisher, and that the durability service for
    a `Controller` will not read topics that a controller writes:
    events, telemetry, and the ``ackcmd`` topic.
    """

    def __init__(
        self, domain: Domain, name: str, index: typing.Optional[int] = 0
    ) -> None:
        if not isinstance(domain, Domain):
            raise TypeError(f"domain {domain!r} must be an lsst.ts.salobj.Domain")
        self.isopen = False
        self.domain = domain
        self.name = name
        self.index = 0 if index is None else int(index)
        self.identity = domain.default_identity
        self.start_called = False

        # Dict of SAL topic name: wait_for_historical_data succeeded
        # for each topic for which wait_for_historical_data was called.
        # This is primarily intended for unit tests.
        self.wait_history_isok: typing.Dict[str, bool] = dict()

        partition_prefix = os.environ.get("LSST_DDS_PARTITION_PREFIX")
        if partition_prefix is None:
            partition_prefix = os.environ.get("LSST_DDS_DOMAIN")
            if partition_prefix is None:
                raise RuntimeError(
                    "Environment variable $LSST_DDS_PARTITION_PREFIX not defined, "
                    "nor is the deprecated fallback $LSST_DDS_DOMAIN"
                )
            warnings.warn(
                "Environment variable $LSST_DDS_PARTITION_PREFIX not defined; "
                "using deprecated fallback $LSST_DDS_DOMAIN instead",
                DeprecationWarning,
            )
        elif os.environ.get("LSST_DDS_DOMAIN") is not None:
            warnings.warn(
                "Using environment variable $LSST_DDS_PARTITION_PREFIX "
                "instead of deprecated $LSST_DDS_DOMAIN",
                DeprecationWarning,
            )
        self.partition_prefix = partition_prefix

        self.start_task: asyncio.Future = asyncio.Future()
        self.done_task: asyncio.Future = asyncio.Future()

        self.log = logging.getLogger(self.name)
        if self.log.getEffectiveLevel() > MAX_LOG_LEVEL:
            self.log.setLevel(MAX_LOG_LEVEL)

        self.authorized_users: typing.Set[str] = set()
        self.non_authorized_cscs: typing.Set[str] = set()

        # Publishers and subscribers.
        # Create at need to avoid unnecessary instances.
        # Controller needs a _cmd_publisher and _data_subscriber.
        # Remote needs a _cmd_subscriber and _data_publisher.
        self._cmd_publisher = None
        self._cmd_subscriber = None
        self._data_publisher = None
        self._data_subscriber = None

        # dict of private_seqNum: salobj.topics.CommandInfo
        self._running_cmds: typing.Dict[int, topics.CommandInfo] = dict()
        # dict of dds.ReadCondition: salobj topics.ReadTopic
        # This is needed because read conditions don't store the associated
        # data reader. When a wait on a dds.WaitSet returns a read condition
        # we use this dict to figure out which topic to read.
        self._reader_dict: typing.Dict[dds.ReadCondition, topics.ReadTopic] = dict()
        # list of salobj topics.WriteTopic
        self._writer_list: typing.List[topics.WriteTopic] = list()
        # the first RemoteCommand created should set this to
        # an lsst.ts.salobj.topics.AckCmdReader
        # and set its callback to self._ackcmd_callback
        self._ackcmd_reader: typing.Optional[topics.AckCmdReader] = None
        # the first ControllerCommand created should set this to
        # an lsst.ts.salobj.topics.AckCmdWriter
        self._ackcmd_writer: typing.Optional[topics.AckCmdWriter] = None
        # wait_timeout is a failsafe for shutdown; normally all you have to do
        # is call `close` to trigger the guard condition and stop the wait
        self._wait_timeout = dds.DDSDuration(sec=10)
        self._guardcond = dds.GuardCondition()
        self._waitset = dds.WaitSet()
        self._waitset.attach(self._guardcond)
        self._read_loop_task = base.make_done_future()

        idl_path = domain.idl_dir / f"sal_revCoded_{self.name}.idl"
        if not idl_path.is_file():
            raise RuntimeError(
                f"Cannot find IDL file {idl_path} for name={self.name!r}"
            )
        self.metadata = idl_metadata.parse_idl(name=self.name, idl_path=idl_path)
        self.parse_metadata()  # Adds self.indexed, self.revnames, etc.
        if self.index != 0 and not self.indexed:
            raise ValueError(
                f"Index={index!r} must be 0 or None; {name} is not an indexed SAL component"
            )
        if len(self.command_names) > 0:
            ackcmd_revname = self.revnames.get("ackcmd")
            if ackcmd_revname is None:
                raise RuntimeError(f"Could not find {self.name} topic 'ackcmd'")
            self._ackcmd_type: type_hints.AckCmdDataType = ddsutil.get_dds_classes_from_idl(  # type: ignore
                idl_path, ackcmd_revname
            )

        domain.add_salinfo(self)

        # Make sure the background thread terminates.
        atexit.register(self.basic_close)
        self.isopen = True

    def _ackcmd_callback(self, data: type_hints.AckCmdDataType) -> None:
        if not self._running_cmds:
            return
        # Note: ReadTopic's reader filters out ackcmd samples
        # for commands issued by other remotes.
        if data.identity and data.identity != self.identity:
            # This ackcmd is for a command issued by a different Remote,
            # so ignore it.
            return
        cmd_info = self._running_cmds.get(data.private_seqNum, None)
        if cmd_info is None:
            return
        isdone = cmd_info.add_ackcmd(data)
        if isdone:
            del self._running_cmds[data.private_seqNum]

    @property
    def AckCmdType(self) -> typing.Type[type_hints.AckCmdDataType]:
        """The class of command acknowledgement.

        It includes these fields, as well as the usual other
        private fields.

        private_seqNum : `int`
            Sequence number of command.
        ack : `int`
            Acknowledgement code; one of the `SalRetCode` ``CMD_``
            constants, such as `SalRetCode.CMD_COMPLETE`.
        error : `int`
            Error code; 0 for no error.
        result : `str`
            Explanatory message, or "" for no message.

        Raises
        ------
        RuntimeError
            If the SAL component has no commands (because if there
            are no commands then there is no ackcmd topic).
        """
        if len(self.command_names) == 0:
            raise RuntimeError("This component has no commands, so no ackcmd topic")
        return self._ackcmd_type.topic_data_class  # type: ignore

    @property
    def cmd_partition_name(self) -> str:
        """Partition name for command topics."""
        return f"{self.partition_prefix}.{self.name}.cmd"

    @property
    def data_partition_name(self) -> str:
        """Partition name for non-command topics."""
        return f"{self.partition_prefix}.{self.name}.data"

    @property
    def cmd_publisher(self) -> dds.Publisher:
        """Publisher for command topics, but not ackcmd.

        This has a different partition name than a data_publisher.
        """
        if self._cmd_publisher is None:
            self._cmd_publisher = self.domain.make_publisher([self.cmd_partition_name])

        return self._cmd_publisher

    @property
    def cmd_subscriber(self) -> dds.Subscriber:
        """Subscriber for command topics, but not ackcmd.

        This has a different partition name than a data_subscriber.
        """
        if self._cmd_subscriber is None:
            self._cmd_subscriber = self.domain.make_subscriber(
                [self.cmd_partition_name]
            )

        return self._cmd_subscriber

    @property
    def data_publisher(self) -> dds.Publisher:
        """Publisher for ackcmd, events and telemetry topics.

        This has a different partition name than a cmd_publisher.
        """
        if self._data_publisher is None:
            self._data_publisher = self.domain.make_publisher(
                [self.data_partition_name]
            )

        return self._data_publisher

    @property
    def data_subscriber(self) -> dds.Subscriber:
        """Subscriber for ackcmd, events and telemetry topics.

        This has a different partition name than a cmd_subscriber.
        """
        if self._data_subscriber is None:
            self._data_subscriber = self.domain.make_subscriber(
                [self.data_partition_name]
            )

        return self._data_subscriber

    @property
    def name_index(self) -> str:
        """Get name[:index].

        The suffix is only present if the component is indexed.
        """
        if self.indexed:
            return f"{self.name}:{self.index}"
        else:
            return self.name

    @property
    def started(self) -> bool:
        """Return True if successfully started, False otherwise."""
        return (
            self.start_task.done()
            and not self.start_task.cancelled()
            and self.start_task.exception() is None
        )

    def assert_started(self) -> None:
        """Raise RuntimeError if not successfully started.

        Notes
        -----
        Does not raise after this is closed.
        That avoids race conditions at shutdown.
        """
        if not self.started:
            raise RuntimeError("Not started")

    def make_ackcmd(
        self,
        private_seqNum: int,
        ack: sal_enums.SalRetCode,
        error: int = 0,
        result: str = "",
        timeout: float = 0,
        truncate_result: bool = False,
    ) -> type_hints.AckCmdDataType:
        """Make an AckCmdType object from keyword arguments.

        Parameters
        ----------
        private_seqNum : `int`
            Sequence number of command.
        ack : `int`
            Acknowledgement code; one of the ``salobj.SalRetCode.CMD_``
            constants, such as ``salobj.SalRetCode.CMD_COMPLETE``.
        error : `int`
            Error code. Should be 0 unless ``ack`` is
            ``salobj.SalRetCode.CMD_FAILED``
        result : `str`
            More information. This is arbitrary, but limited to
            `MAX_RESULT_LEN` characters.
        timeout : `float`
            Esimated command duration. This should be specified
            if ``ack`` is ``salobj.SalRetCode.CMD_INPROGRESS``.
        truncate_result : `bool`
            What to do if ``result`` is longer than  `MAX_RESULT_LEN`
            characters:

            * If True then silently truncate ``result`` to `MAX_RESULT_LEN`
              characters.
            * If False then raise `ValueError`

        Raises
        ------
        ValueError
            If ``len(result) > `MAX_RESULT_LEN`` and ``truncate_result``
            is false.
        RuntimeError
            If the SAL component has no commands (because if there
            are no commands then there is no ackcmd topic).
        """
        if len(result) > MAX_RESULT_LEN:
            if truncate_result:
                result = result[0:MAX_RESULT_LEN]
            else:
                raise ValueError(
                    f"len(result) > MAX_RESULT_LEN={MAX_RESULT_LEN}; result={result}"
                )
        return self.AckCmdType(
            private_seqNum=private_seqNum,
            ack=ack,
            error=error,
            result=result,
            timeout=timeout,
        )

    def makeAckCmd(
        self, *args: typing.Any, **kwargs: typing.Any
    ) -> type_hints.AckCmdDataType:
        """Deprecated version of make_ackcmd."""
        # TODO DM-26518: remove this method
        warnings.warn(
            "makeAckCmd is deprecated; use make_ackcmd instead.", DeprecationWarning
        )
        return self.make_ackcmd(*args, **kwargs)

    def parse_metadata(self) -> None:
        """Parse the IDL metadata to generate some attributes.

        Set the following attributes (see the class doc string for details):

        * indexed
        * command_names
        * event_names
        * telemetry_names
        * sal_topic_names
        * revnames
        """
        command_names = []
        event_names = []
        telemetry_names = []
        revnames = {}
        for topic_metadata in self.metadata.topic_info.values():
            sal_topic_name = topic_metadata.sal_name
            if sal_topic_name.startswith("command_"):
                command_names.append(sal_topic_name[8:])
            elif sal_topic_name.startswith("logevent_"):
                event_names.append(sal_topic_name[9:])
            elif sal_topic_name != "ackcmd":
                telemetry_names.append(sal_topic_name)
            revnames[
                sal_topic_name
            ] = f"{self.name}::{sal_topic_name}_{topic_metadata.version_hash}"

        # Examine last topic (or any topic) to see if component is indexed.
        indexed_field_name = f"{self.name}ID"
        self.indexed = indexed_field_name in topic_metadata.field_info

        self.command_names = tuple(command_names)
        self.event_names = tuple(event_names)
        self.telemetry_names = tuple(telemetry_names)
        self.sal_topic_names = tuple(sorted(self.metadata.topic_info.keys()))
        self.revnames = revnames

    def basic_close(self) -> None:
        """A synchronous and less thorough version of `close`.

        Intended for exit handlers and constructor error handlers.
        """
        if not self.isopen:
            return
        self.isopen = False
        self._guardcond.trigger()
        self._read_loop_task.cancel()
        try:
            self._detach_read_conditions()
        except Exception as e:
            print(
                f"{self}.basic_close: failed to detach one or more conditions "
                f"from the wait set; continuing: {e!r}"
            )
        for reader in self._reader_dict.values():
            reader.basic_close()
        for writer in self._writer_list:
            writer.basic_close()

    async def close(self) -> None:
        """Shut down and clean up resources.

        May be called multiple times. The first call closes the SalInfo;
        subsequent calls wait until the SalInfo is closed.
        """
        if not self.isopen:
            await self.done_task
            return
        self.isopen = False
        try:
            self._guardcond.trigger()
            # Give the read loop time to exit.
            await asyncio.sleep(0.01)
            self._read_loop_task.cancel()
            try:
                self._detach_read_conditions()
            except Exception as e:
                print(
                    f"{self}.close: failed to detach one or more conditions "
                    f"from the wait set; continuing: {e!r}"
                )
            for reader in self._reader_dict.values():
                await reader.close()
            for writer in self._writer_list:
                await writer.close()
            while self._running_cmds:
                private_seqNum, cmd_info = self._running_cmds.popitem()
                try:
                    cmd_info.abort("shutting down")
                except Exception:
                    pass
            self.domain.remove_salinfo(self)
        except Exception:
            self.log.exception("close failed")
        finally:
            if not self.done_task.done():
                self.done_task.set_result(None)

    def add_reader(self, topic: topics.ReadTopic) -> None:
        """Add a ReadTopic, so it can be read by the read loop and closed
        by `close`.

        Parameters
        ----------
        topic : `topics.ReadTopic`
            Topic to read and (eventually) close.

        Raises
        ------
        RuntimeError
            If called after `start` has been called.
        """
        if self.start_called:
            raise RuntimeError("Cannot add topics after the start called")
        if topic._read_condition in self._reader_dict:
            raise RuntimeError(f"{topic} already added")
        self._reader_dict[topic._read_condition] = topic
        self._waitset.attach(topic._read_condition)

    def add_writer(self, topic: topics.WriteTopic) -> None:
        """Add a WriteTopic, so it can be closed by `close`.

        Parameters
        ----------
        topic : `topics.WriteTopic`
            Write topic to (eventually) close.
        """
        self._writer_list.append(topic)

    async def start(self) -> None:
        """Start the read loop.

        Call this after all topics have been added.

        Raises
        ------
        RuntimeError
            If `start` has already been called.
        """
        if self.start_called:
            raise RuntimeError("Start already called")
        self.start_called = True
        try:
            loop = asyncio.get_running_loop()
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                t0 = time.monotonic()
                isok = await loop.run_in_executor(pool, self._wait_history)
                dt = time.monotonic() - t0
                if not self.isopen:  # shutting down
                    return
                if isok:
                    self.log.info(f"Read historical data in {dt:0.2f} sec")
                else:
                    self.log.warning(f"Could not read historical data in {dt:0.2f} sec")

                # read historical (late-joiner) data
                for read_cond, reader in self._reader_dict.items():
                    if not self.isopen:  # shutting down
                        return
                    if (
                        reader.volatile
                        or not reader.isopen
                        or not read_cond.triggered()
                    ):
                        # reader gets no historical data, is closed,
                        # or has no data to be read
                        continue
                    try:
                        data_list = reader._reader.take_cond(
                            read_cond, MAX_HISTORY_READ
                        )
                    except dds.DDSException as e:
                        self.log.warning(
                            f"dds error while reading late joiner data for {reader}; "
                            f"trying again: {e}"
                        )
                        time.sleep(0.001)
                        try:
                            data_list = reader._reader.take_cond(
                                read_cond, MAX_HISTORY_READ
                            )
                        except dds.DDSException as e:
                            raise RuntimeError(
                                f"dds error while reading late joiner data for {reader}; "
                                "giving up"
                            ) from e
                    self.log.debug(f"Read {len(data_list)} history items for {reader}")
                    sd_list = [
                        self._sample_to_data(sd, si)
                        for sd, si in data_list
                        if si.valid_data
                    ]
                    if len(sd_list) < len(data_list):
                        ninvalid = len(data_list) - len(sd_list)
                        self.log.warning(
                            f"Read {ninvalid} invalid late-joiner items from {reader}. "
                            "The invalid items were safely skipped, but please examine "
                            "the code in SalInfo.start to see if it needs an update "
                            "for changes to OpenSplice dds."
                        )
                    if reader.max_history > 0:
                        sd_list = sd_list[-reader.max_history :]
                        if sd_list:
                            reader._queue_data(sd_list, loop=None)
            self._read_loop_task = asyncio.create_task(self._read_loop(loop=loop))
            self.start_task.set_result(None)
        except Exception as e:
            self.start_task.set_exception(e)
            raise

    def _detach_read_conditions(self) -> None:
        """Try to detach all read conditions from the wait set.

        ADLink suggests doing this at shutdown to work around a bug
        in their software that produces spurious error messages
        in the ospl log.
        """
        self._waitset.detach(self._guardcond)
        for read_cond in self._reader_dict:
            self._waitset.detach(read_cond)

    async def _read_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """Read and process data.

        Parameters
        ----------
        loop : `asyncio.AbstractEventLoop`
            The main thread's event loop (which must be running).
        """
        self.domain.num_read_loops += 1
        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                await loop.run_in_executor(pool, self._read_loop_thread, loop)
        except asyncio.CancelledError:
            raise
        except Exception:
            self.log.exception("_read_loop failed")
        finally:
            self.domain.num_read_loops -= 1

    def _read_loop_thread(self, loop: asyncio.AbstractEventLoop) -> None:
        """Read and process DDS data in a background thread.

        Parameters
        ----------
        loop : `asyncio.AbstractEventLoop`
            The main asyncio event loop.
        """
        while self.isopen:
            conditions = self._waitset.wait(self._wait_timeout)
            if not self.isopen:
                # shutting down; clean everything up
                return
            for condition in conditions:
                reader = self._reader_dict.get(condition)
                if reader is None or not reader.isopen:
                    continue
                # odds are we will only get one value per read,
                # but read more so we can tell if we are falling behind
                data_list = reader._reader.take_cond(
                    condition, reader._data_queue.maxlen
                )
                reader.dds_queue_length_checker.check_nitems(len(data_list))
                sd_list = [
                    self._sample_to_data(sd, si)
                    for sd, si in data_list
                    if si.valid_data
                ]
                if sd_list:
                    reader._queue_data(sd_list, loop=loop)

    def _sample_to_data(self, sd: dds._Sample, si: dds.SampleInfo) -> dds._Sample:
        """Process one sample data, sample info pair.

        Set sd.private_rcvStamp based on si.reception_timestamp
        and return the updated sd.
        """
        rcv_utc = si.reception_timestamp * 1e-9
        rcv_tai = base.tai_from_utc_unix(rcv_utc)
        sd.private_rcvStamp = rcv_tai
        return sd

    def _wait_history(self) -> bool:
        """Wait for historical data to be available for all topics.

        Blocks, so intended to be run in a background thread.

        Returns
        -------
        iosk : `bool`
            True if we got historical data or none was wanted
        """
        time_limit_str = os.environ.get("LSST_DDS_HISTORYSYNC")
        if time_limit_str is None:
            time_limit: float = DEFAULT_LSST_DDS_HISTORYSYNC
        else:
            time_limit = float(time_limit_str)
        if time_limit < 0:
            self.log.info(
                f"Time limit {time_limit} < 0; not waiting for historical data"
            )
            return True
        wait_timeout = dds.DDSDuration(sec=time_limit)
        num_ok = 0
        num_checked = 0
        t0 = time.monotonic()
        for reader in self._reader_dict.values():
            if not self.isopen:  # shutting down
                return False
            if reader.volatile or not reader.isopen:
                continue
            num_checked += 1
            isok = reader._reader.wait_for_historical_data(wait_timeout)
            self.wait_history_isok[reader.sal_name] = isok
            if isok:
                num_ok += 1
            elapsed_time = time.monotonic() - t0
            rem_time = max(0.01, time_limit - elapsed_time)
            wait_timeout = dds.DDSDuration(sec=rem_time)
        return num_ok > 0 or num_checked == 0

    async def __aenter__(self) -> SalInfo:
        if self.start_called:
            await self.start_task
        return self

    async def __aexit__(
        self,
        type: typing.Optional[typing.Type[BaseException]],
        value: typing.Optional[BaseException],
        traceback: typing.Optional[types.TracebackType],
    ) -> None:
        await self.close()

    def __repr__(self) -> str:
        return f"SalInfo({self.name}, {self.index})"
