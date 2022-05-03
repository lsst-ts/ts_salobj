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

__all__ = ["SalInfo"]

import asyncio
import atexit
import collections
import enum
import itertools
import logging
import os
import time
import traceback
import types
import typing
import warnings

import aiohttp
from aiokafka import AIOKafkaConsumer, AIOKafkaProducer, TopicPartition
from confluent_kafka.admin import AdminClient, NewTopic
from confluent_kafka.error import KafkaError
from kafkit.registry.aiohttp import RegistryApi
from kafkit.registry import Deserializer, Serializer

from lsst.ts import utils
from .topic_info import TopicInfo
from .component_info import ComponentInfo
from . import sal_enums
from . import topics
from . import type_hints
from .domain import Domain

# We want SAL logMessage messages for at least INFO level messages,
# so if the current level is less verbose, set it to INFO.
# Do not change the level if it is already more verbose,
# because somebody has intentionally increased verbosity
# (a common thing to do in unit tests).
MAX_LOG_LEVEL = logging.INFO

# The maximum number of historical samples to read for each topic.
# This only applies to indexed SAL components, and only if
# the reader wants historical data.
MAX_HISTORY_READ = 10000

DEFAULT_LSST_KAFKA_BROKER_ADDR = "broker:29092"
DEFAULT_LSST_SCHEMA_REGISTRY_URL = "http://schema-registry:8081"

# limit_per_host argument for aiohttp.TCPConnector
LIMIT_PER_HOST = 20

# Number of acks to wait for when sending Kafka data.
PRODUCER_WAIT_ACKS = 1


class SalInfo:
    r"""Information for one SAL component and index.

    Parameters
    ----------
    domain : `Domain`
        Domain information.
    name : `str`
        SAL component name.
    index : `int`, optional
        Component index; 0 or None if this component is not indexed.
    write_only : `bool`
        If false this SalInfo will not subscribe to any topics.

    Raises
    ------
    TypeError
        If ``domain`` is not an instance of `Domain`
        or if ``index`` is not an `int`, `enum.IntEnum`, or `None`.
    ValueError
        If ``index`` is nonzero and the component is not indexed.

    Attributes
    ----------
    domain : `Domain`
        The ``domain`` constructor argument.
    index : `int`
        The ``index`` constructor argument.
    identity : `str`
        Value used for the private_identity field of DDS messages.
        Defaults to username@host, but CSCs should use the CSC name:
        * SAL_component_name for a non-indexed SAL component
        * SAL_component_name:index for an indexed SAL component.
    isopen : `bool`
        Is this read topic open? `True` until `close` is called.
    log : `logging.Logger`
        A logger.
    start_called : `bool`
        Has the start method been called?
        This instance is fully started when start_task is done.
    done_task : `asyncio.Task`
        A task which is finished when `close` is done.
    start_task : `asyncio.Task`
        A task which is finished when `start` is done,
        or to an exception if `start` fails.
    command_names : `List` [`str`]
        A tuple of command names without the ``"command_"`` prefix.
    event_names : `List` [`str`]
        A tuple of event names, without the ``"logevent_"`` prefix
    telemetry_names : `List` [`str`]
        A tuple of telemetry topic names.
    sal_topic_names : `List` [`str`]
        A tuple of SAL topic names, e.g. "logevent_summaryState",
        in alphabetical order. This is needed to determine command ID.
    component_info : `ComponentInfo`
        Information about the SAL component and its topics.
    authorized_users : `List` [`str`]
        Set of users authorized to command this component.
    non_authorized_cscs : `List` [`str`]
        Set of CSCs that are not authorized to command this component.

    Notes
    -----
    Reads the following `Environment Variables
    <https://ts-salobj.lsst.io/configuration.html#environment_variables>`_;
    follow the link for details:

    * ``LSST_DDS_ENABLE_AUTHLIST`` (optional): if set to "1"
      enable authlist-based command authorization.
      If "0" or undefined, do not enable authorization.
    * ``LSST_TOPIC_SUBNAME`` (required): a component of Kafka
      topic names and schema namespaces.

    **Usage**

    * Construct a `SalInfo` object for a particular SAL component and index.
    * Use the object to construct all topics (subclasses of `topics.BaseTopic`)
      that you want to use with this SAL component and index.
    * Call `start`.
    * When you are finished, call `close`, or at least be sure to close
      the ``domain`` when you are finished with all classes that use it
      (see Cleanup below).

    You cannot read or write topics constructed with a `SalInfo` object
    until you call `start`, and once you call `start`, you cannot
    use the `SalInfo` object to construct any more topics.

    You may use `SalInfo` as an async context manager, but this is primarily
    useful for cleanup. After you enter the context (create the object)
    you will still have to create topics and call start.
    This is different from `Domain`, `Controller`, and `Remote`,
    which are ready to use when you enter the context.

    **Cleanup**

    Each `SalInfo` automatically registers itself with the specified ``domain``
    for cleanup, using a weak reference to avoid circular dependencies.
    You may safely close a `SalInfo` before closing its domain,
    and this is recommended if you create and destroy many remotes.
    In any case, be sure to close the ``domain`` when you are done.
    """

    def __init__(
        self,
        domain: Domain,
        name: str,
        index: int | None = 0,
        write_only: bool = False,
    ) -> None:
        if not isinstance(domain, Domain):
            raise TypeError(f"domain {domain!r} must be an lsst.ts.salobj.Domain")
        if index is not None:
            if not (isinstance(index, int) or isinstance(index, enum.IntEnum)):
                raise TypeError(
                    f"index {index!r} must be an integer, enum.IntEnum, or None"
                )
        self.isopen = False
        self._closing = False
        self.domain = domain
        self.index = 0 if index is None else index
        self.write_only = write_only
        self.identity = domain.default_identity
        self.start_called = False

        self._consumer: typing.Optional[AIOKafkaConsumer] = None
        self._producer: typing.Optional[AIOKafkaProducer] = None

        topic_subname = os.environ.get("LSST_TOPIC_SUBNAME", None)
        if not topic_subname:
            raise RuntimeError(
                "You must define environment variable LSST_TOPIC_SUBNAME"
            )

        self.kafka_broker_addr = os.environ.get(
            "LSST_KAFKA_BROKER_ADDR", DEFAULT_LSST_KAFKA_BROKER_ADDR
        )
        self.schema_registry_url = os.environ.get(
            "LSST_SCHEMA_REGISTRY_URL", DEFAULT_LSST_SCHEMA_REGISTRY_URL
        )

        self.component_info = ComponentInfo(topic_subname=topic_subname, name=name)
        self.command_names = tuple(
            sorted(
                attr_name[4:]
                for attr_name in self.component_info.topics.keys()
                if attr_name.startswith("cmd_")
            )
        )
        self.event_names = tuple(
            sorted(
                attr_name[4:]
                for attr_name in self.component_info.topics.keys()
                if attr_name.startswith("evt_")
            )
        )
        self.telemetry_names = tuple(
            sorted(
                attr_name[4:]
                for attr_name in self.component_info.topics.keys()
                if attr_name.startswith("tel_")
            )
        )
        self.sal_topic_names = sorted(
            topic_info.sal_name for topic_info in self.component_info.topics.values()
        )

        self.log = logging.getLogger(name)
        if self.log.getEffectiveLevel() > MAX_LOG_LEVEL:
            self.log.setLevel(MAX_LOG_LEVEL)

        self.start_task: asyncio.Future = asyncio.Future()
        self.done_task: asyncio.Future = asyncio.Future()

        # Parse environment variable LSST_DDS_ENABLE_AUTHLIST
        # to determine whether to implement command authorization.
        # TODO DM-32379: remove this code block, including the
        # default_authorize attribute.
        authorize_str = os.environ.get("LSST_DDS_ENABLE_AUTHLIST", "0")
        if authorize_str not in ("0", "1"):
            self.log.warning(
                f"Invalid value $LSST_DDS_ENABLE_AUTHLIST={authorize_str!r}. "
                "Specify '1' to enable, '0' or undefined to disable "
                "authlist-based command authorization. Disabling."
            )
        self.default_authorize = authorize_str == "1"
        if self.default_authorize:
            self.log.debug("Enabling authlist-based command authorization")
        else:
            self.log.debug("Disabling authlist-based command authorization")

        self.authorized_users: typing.Set[str] = set()
        self.non_authorized_cscs: typing.Set[str] = set()

        # Dict of topic attr name: ReadTopic
        self._read_topics: typing.Dict[str, topics.ReadTopic] = dict()

        # Dict of topic attr name: WriteTopic
        self._write_topics: typing.Dict[str, topics.WriteTopic] = dict()

        # Dict of kafka topic name: ReadTopic
        self._kafka_name_read_topics: typing.Dict[str, topics.ReadTopic] = dict()

        # Dict of write topic attr_name: Serializer
        self._serializers: typing.Dict[str, Serializer] = dict()

        # dict of private_seqNum: salobj.topics.CommandInfo
        self._running_cmds: typing.Dict[int, topics.CommandInfo] = dict()
        # the first RemoteCommand created should set this to
        # an lsst.ts.salobj.topics.AckCmdReader
        # and set its callback to self._ackcmd_callback
        self._ackcmd_reader: topics.AckCmdReader | None = None
        # the first ControllerCommand created should set this to
        # an lsst.ts.salobj.topics.AckCmdWriter
        self._ackcmd_writer: topics.AckCmdWriter | None = None
        # wait_timeout is a failsafe for shutdown; normally all you have to do
        # is call `close` to trigger the guard condition and stop the wait
        self._read_loop_task = utils.make_done_future()

        self._run_kafka_task = utils.make_done_future()

        if self.index != 0 and not self.indexed:
            raise ValueError(
                f"Index={index!r} must be 0 or None; {name} is not an indexed SAL component"
            )
        if len(self.command_names) > 0:
            self._ackcmd_type = self.component_info.topics[
                "ack_ackcmd"
            ].make_dataclass()

        domain.add_salinfo(self)

        # Make sure the background thread terminates.
        atexit.register(self.basic_close)
        self.isopen = True

    @property
    def name(self) -> str:
        """Get the SAL component name (the ``name`` constructor argument)."""
        return self.component_info.name

    @property
    def indexed(self) -> bool:
        """Is this SAL component indexed?."""
        return self.component_info.indexed

    async def _ackcmd_callback(self, data: type_hints.AckCmdDataType) -> None:
        if not self._running_cmds:
            return
        if data.identity != self.identity or data.origin != self.domain.origin:
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
        return self._ackcmd_type  # type: ignore

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
    def running(self) -> bool:
        """Return True if started and not closed."""
        return self.started and self.isopen

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
            More information.
        timeout : `float`
            Esimated command duration. This should be specified
            if ``ack`` is ``salobj.SalRetCode.CMD_INPROGRESS``.

        Raises
        ------
        RuntimeError
            If the SAL component has no commands (because if there
            are no commands then there is no ackcmd topic).
        """
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

    def basic_close(self) -> None:
        """A synchronous and less thorough version of `close`.

        Intended for exit handlers and constructor error handlers.
        """
        if not self.isopen:
            return
        self.isopen = False
        self._read_loop_task.cancel()
        for reader in self._read_topics.values():
            reader.basic_close()
        for writer in self._write_topics.values():
            writer.basic_close()
        self.domain.remove_salinfo(self)

    async def close(self) -> None:
        """Shut down and clean up resources.

        May be called multiple times. The first call closes the SalInfo;
        subsequent calls wait until the SalInfo is closed.
        """
        if not self.isopen:
            if self._closing:
                await self.done_task
            return
        self.isopen = False
        self._closing = True
        try:
            self._read_loop_task.cancel()
            self._run_kafka_task.cancel()
            # Give the tasks time to finish cancelling.
            # In particular: give the _read_loop time to
            # decrement self.domain.num_read_loops
            await asyncio.sleep(0)
            for reader in self._read_topics.values():
                await reader.close()
            for writer in self._write_topics.values():
                await writer.close()
            while self._running_cmds:
                private_seqNum, cmd_info = self._running_cmds.popitem()
                try:
                    cmd_info.close()
                except Exception:
                    pass
            self.domain.remove_salinfo(self)
        except Exception:
            self.log.exception("close failed")
        finally:
            self._closing = False
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
        if topic.attr_name in self._read_topics:
            raise ValueError(f"Read topic {topic.attr_name} already present")
        self._read_topics[topic.topic_info.attr_name] = topic
        self._kafka_name_read_topics[topic.topic_info.kafka_name] = topic

    def add_writer(self, topic: topics.WriteTopic) -> None:
        """Add a WriteTopic, so it can be closed by `close`.

        Parameters
        ----------
        topic : `topics.WriteTopic`
            Write topic to (eventually) close.
        """
        if self.start_called:
            raise RuntimeError("Cannot add topics after the start called")
        if topic.attr_name in self._write_topics:
            raise ValueError(f"Write topic {topic.attr_name} already present")
        self._write_topics[topic.attr_name] = topic

    async def start(self) -> None:
        """Start the read loop.

        Call this after all topics have been added.

        Raises
        ------
        RuntimeError
            If `start` or `close` have already been called.
        """
        if self.start_called:
            raise RuntimeError("Start already called")
        if not self.isopen:
            raise RuntimeError("Already closing or closed")
        self.start_called = True

        self._run_kafka_task = asyncio.create_task(self._run_kafka())
        await self.start_task

    async def _run_kafka(self) -> None:
        """Initialize Kafka and run the read loop.

        Set the following attributes:

        * self._consumer
        * self._producer
        * self._deserializer
        * self._serializers

        Register schema and create missing topics.

        Wait for the read loop to finish.
        """
        try:
            async with aiohttp.TCPConnector(
                limit_per_host=LIMIT_PER_HOST
            ) as connector, aiohttp.ClientSession(connector=connector) as session:
                registry = RegistryApi(url=self.schema_registry_url, session=session)
                self._deserializer = Deserializer(registry=registry)

                # A list of Kafka topic names for creating the consumer.
                kafka_topic_names: typing.List[str] = []
                # A list of TopicInfo for read topics for which historical
                # data is wanted.
                read_history_topic_infos: typing.List[TopicInfo] = []
                for read_topic in self._read_topics.values():
                    avro_schema = read_topic.topic_info.make_avro_schema()
                    schema_id = await registry.register_schema(
                        schema=avro_schema, subject=read_topic.topic_info.avro_subject
                    )
                    kafka_topic_names.append(read_topic.topic_info.kafka_name)
                    if read_topic.max_history > 0:
                        read_history_topic_infos.append(read_topic.topic_info)

                for write_topic in self._write_topics.values():
                    avro_schema = write_topic.topic_info.make_avro_schema()
                    schema_id = await registry.register_schema(
                        schema=avro_schema, subject=write_topic.topic_info.avro_subject
                    )
                    self._serializers[write_topic.attr_name] = Serializer(
                        schema=avro_schema, schema_id=schema_id
                    )

                # Create topics
                self._blocking_create_topics()

                async with AIOKafkaProducer(
                    bootstrap_servers=self.kafka_broker_addr,
                    acks=PRODUCER_WAIT_ACKS,
                ) as self._producer, AIOKafkaConsumer(
                    *kafka_topic_names,
                    bootstrap_servers=self.kafka_broker_addr,
                ) as self._consumer:
                    self._read_loop_task = asyncio.create_task(self._read_loop())
                    await self._read_loop_task
        except asyncio.CancelledError:
            pass
        except Exception as e:
            print(f"_run_kafka failed: {e!r}")
            traceback.print_exc()
            if not self.start_task.done():
                self.start_task.set_exception(e)
            self.log.exception("_run_kafka failed")
            raise
        finally:
            await asyncio.create_task(self.close())

    def _blocking_create_topics(self) -> None:
        """Create missing Kafka topics."""
        # Dict of kafka topic name: topic_info
        topic_info_dict = {
            topic.topic_info.kafka_name: topic.topic_info
            for topic in itertools.chain(
                self._read_topics.values(), self._write_topics.values()
            )
        }
        new_topics_info = [
            NewTopic(
                topic_info.kafka_name,
                num_partitions=topic_info.partitions,
                replication_factor=1,
            )
            for topic_info in topic_info_dict.values()
        ]
        broker_client = AdminClient({"bootstrap.servers": self.kafka_broker_addr})
        if new_topics_info:
            create_result = broker_client.create_topics(new_topics_info)
            for topic_name, future in create_result.items():
                exception = future.exception()
                if exception is None:
                    continue
                elif (
                    isinstance(exception.args[0], KafkaError)
                    and exception.args[0].code() == KafkaError.TOPIC_ALREADY_EXISTS
                ):
                    pass
                else:
                    print(f"Failed to create topic {topic_name}: {exception!r}")
                    raise exception

    async def _read_loop(self) -> None:
        """Read and process messages."""
        self.domain.num_read_loops += 1
        if self._consumer is None:
            self.log.error("No consumer; quitting")
            return
        try:
            # Prepare to read historical data
            read_history_topic_infos = [
                read_topic.topic_info
                for read_topic in self._read_topics.values()
                if read_topic.max_history > 0
            ]

            # Dict of attr_name: Kafka position
            # for topics for which we want historical data
            # and historical data is available (position > 0)
            position_dict: typing.Dict[str, int] = dict()

            read_history_start_monotonic = time.monotonic()

            if read_history_topic_infos:
                # Historical data is wanted for one or more topics.

                # Dict of topic attr_name: TopicPartition
                topic_partitions: typing.Dict[str, TopicPartition] = dict()
                for topic_info in read_history_topic_infos:
                    partition_ids = self._consumer.partitions_for_topic(
                        topic_info.kafka_name
                    )
                    # Handling multiple partitions is too much effort
                    if len(partition_ids) > 1:
                        self.log.warning(
                            f"More than one partition for {topic_info.kafka_name}; "
                            "cannot get late-joiner data"
                        )
                        continue
                    partition_id = list(partition_ids)[0]
                    topic_partitions[topic_info.attr_name] = TopicPartition(
                        topic_info.kafka_name, partition_id
                    )

                # Seek back for all topics for which we want
                # historical data.
                # If the component is indexed then we read a lot of
                # historical messages, to try to get the most recent
                # message for each SAL index. We only need to go back
                # ReadTopic.max_history message for non-indexed
                # components.
                for attr_name, partition in topic_partitions.items():
                    if not self.indexed:
                        max_history = self._read_topics[attr_name].max_history
                        assert max_history > 0
                    else:
                        max_history = MAX_HISTORY_READ

                    position = await self._consumer.position(partition)
                    if position == 0:
                        # No historical data is available
                        continue
                    position_dict[attr_name] = position

                    self._consumer.seek(
                        partition=partition,
                        offset=max(0, position - max_history),
                    )

            # At this point we have know where each topic starts.
            # It is safe to let others use this object.
            self.start_task.set_result(None)
            await asyncio.sleep(0)

            if not self.indexed:
                # We don't need to read the historical data because
                # it will safely show up in the first regular read.
                # Free the event loop now so other tasks can run
                # (including Controller assigning a SalLogHandler).
                await asyncio.sleep(0)

            elif self.index == 0:
                # An indexed component with index=0.
                # Record the most recent value for each index in
                # historical_data_dicts (starting with the oldest),
                # resulting in the most recent message for each index.
                # Feed those messages to the reader.
                for attr_name, position in position_dict.items():
                    read_topic = self._read_topics[attr_name]
                    partition = topic_partitions[attr_name]

                    # Dict of SAL index: historical data dict
                    historical_data_dicts: typing.Dict[
                        int, typing.Dict[str, typing.Any]
                    ] = dict()

                    end_position = position - 1
                    while True:
                        raw_data = await self._consumer.getone(partition)
                        full_data = await self._deserializer.deserialize(raw_data.value)
                        data_dict = full_data["message"]
                        data_dict["private_rcvStamp"] = utils.current_tai()
                        historical_data_dicts[data_dict["salIndex"]] = data_dict

                        if raw_data.offset == end_position:
                            # We have read all historical data
                            # for this topic
                            break

                    data_list = [
                        read_topic.DataType(**data_dict)
                        for data_dict in historical_data_dicts.values()
                    ]
                    read_topic._queue_data(data_list)
            else:
                # An indexed component with non-zero SAL index.
                # Read the history and ignore all messages
                # with a different SAL index.
                for attr_name, position in position_dict.items():
                    # Read all the history, accumulating the
                    # read_topic.max_history most recent messages
                    read_topic = self._read_topics[attr_name]
                    partition = topic_partitions[attr_name]

                    end_position = position - 1
                    # A queue of the max_history most recent
                    # messages with this SAL index
                    data_dict_queue: typing.Deque[
                        typing.Dict[str, typing.Any]
                    ] = collections.deque(maxlen=read_topic.max_history)
                    while True:
                        raw_data = await self._consumer.getone(partition)
                        full_data = await self._deserializer.deserialize(raw_data.value)
                        data_dict = full_data["message"]
                        if data_dict["salIndex"] == self.index:
                            data_dict["private_rcvStamp"] = utils.current_tai()
                            data_dict_queue.append(data_dict)

                        if raw_data.offset == end_position:
                            # We have read all historical data
                            # for this topic
                            break

                    if data_dict_queue:
                        data_list = [
                            read_topic.DataType(**data_dict)
                            for data_dict in data_dict_queue
                        ]
                        read_topic._queue_data(data_list)

            read_history_duration = time.monotonic() - read_history_start_monotonic

            # Note: this is a bit of a cheat for a non-indexed
            # SAL component, because the historical data is
            # actually going to be the first sample seen
            # in the normal read loop below. I think it beats
            # duplicating that read code.
            self.log.info(
                f"Reading historic data took {read_history_duration:0.2f} seconds"
            )

            async for raw_data in self._consumer:  # type: ignore
                read_topic = self._kafka_name_read_topics[raw_data.topic]
                full_data = await self._deserializer.deserialize(raw_data.value)
                data_dict = full_data["message"]
                if self.index != 0 and self.index != data_dict["salIndex"]:
                    continue
                data_dict["private_rcvStamp"] = utils.current_tai()
                data = read_topic.DataType(**data_dict)
                read_topic._queue_data([data])
        except asyncio.CancelledError:
            if not self.start_task.done():
                self.start_task.cancel()
            raise
        except Exception as e:
            print(f"read_loop failed: {e!r}")
            traceback.print_exc()
            if not self.start_task.done():
                self.start_task.set_exception(e)
            self.log.exception("read loop failed")
            raise
        finally:
            self.domain.num_read_loops -= 1

    async def write_data(
        self, topic_info: TopicInfo, data_dict: typing.Dict[str, typing.Any]
    ) -> None:
        """Write a message.

        Parameters
        ----------
        topic_info : TopicInfo
            Info for the topic.
        data_dict : dict[str, Any]
            Message to write, as a dict that matches the Avro topic schema.
        """
        try:
            serializer = self._serializers[topic_info.attr_name]
            data_bytes = serializer(data_dict)
            assert self._producer is not None  # make mypy happy
            await self._producer.send_and_wait(topic_info.kafka_name, value=data_bytes)
        except Exception as e:
            print(f"write_data {topic_info.attr_name} failed: {e!r}")
            traceback.print_exc()
            self.log.exception(
                f"write_data(topic_info={topic_info}, data_dict={data_dict} failed"
            )
            raise

    async def __aenter__(self) -> SalInfo:
        if self.start_called:
            await self.start_task
        return self

    async def __aexit__(
        self,
        type: typing.Type[BaseException] | None,
        value: BaseException | None,
        traceback: types.TracebackType | None,
    ) -> None:
        await self.close()

    def __repr__(self) -> str:
        return f"SalInfo({self.name}, {self.index})"
