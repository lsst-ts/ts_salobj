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
import base64
import collections
import enum
import itertools
import json
import logging
import os
import time
import traceback
import types
import typing
from concurrent.futures import ThreadPoolExecutor

from confluent_kafka import (
    OFFSET_BEGINNING,
    Consumer,
    KafkaException,
    Message,
    Producer,
    TopicPartition,
)
from confluent_kafka.admin import AdminClient, NewTopic
from confluent_kafka.error import KafkaError
from confluent_kafka.schema_registry import Schema, SchemaRegistryClient
from confluent_kafka.schema_registry.avro import AvroDeserializer, AvroSerializer
from confluent_kafka.serialization import MessageField, SerializationContext
from fastavro.read import SchemaResolutionError
from lsst.ts import utils
from lsst.ts.xml import sal_enums, type_hints
from lsst.ts.xml.component_info import ComponentInfo
from lsst.ts.xml.topic_info import TopicInfo

from . import topics
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

# Maximum number of sequential errors reading data from Kafka
MAX_SEQUENTIAL_READ_ERRORS = 2

# Number of _deserializers_and_contexts to wait for when sending Kafka data.
PRODUCER_WAIT_ACKS = 1


def get_random_string() -> str:
    """Get a random string."""
    return base64.urlsafe_b64encode(os.urandom(12)).decode().replace("=", "_")


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
        If False this SalInfo will not subscribe to any topics.

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

    * ``LSST_TOPIC_SUBNAME`` (required): a component of Kafka
      topic names and schema namespaces.
    * ``LSST_DDS_ENABLE_AUTHLIST`` (optional): if set to "1"
      enable authlist-based command authorization.
      If "0" or undefined, do not enable authorization.
    * ``LSST_KAFKA_BROKER_ADDR`` (optional): address of Kafka broker.
      Defaults to ``broker:29092`` (matching the value in file
      ``docker-compose.yaml``), for unit tests.
    * ``LSST_SCHEMA_REGISTRY_URL`` (optional): url of the Confluent schema
      registry. Defaults to ``http://schema-registry:8081`` (matching the
      value in file ``docker-compose.yaml``), for unit tests.

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
        self.loop = asyncio.get_running_loop()
        self.pool = ThreadPoolExecutor(max_workers=100)
        self.write_only = write_only
        self.identity = domain.default_identity
        self.start_called = False
        self.on_assign_called = False

        # Dict of kafka_name: Kafka partition offset of first new data
        # for topics for which we want historical data
        # and historical data is available (offset > 0).
        self._history_offsets: dict[str, int] = dict()

        # Dict of kafka topic name: dict of index: data
        # Only used for indexed components.
        self._history_index_data: dict[
            str, dict[int, type_hints.BaseDdsDataType]
        ] = collections.defaultdict(dict)

        self._consumer: Consumer | None = None
        self._producer: Producer | None = None

        # Dict of kafka topic name: (deserializer, serialization context)
        # for read topics.
        self.deserializers_and_contexts: dict[
            str, tuple[AvroDeserializer, SerializationContext]
        ] = dict()
        # Dict of kafka topic name: (serializer, serialization context)
        # for write topics.
        self._serializers_and_contexts: dict[
            str, tuple[AvroSerializer, SerializationContext]
        ] = dict()

        topic_subname = os.environ.get("LSST_TOPIC_SUBNAME", None)
        if not topic_subname:
            raise RuntimeError(
                "You must define environment variable LSST_TOPIC_SUBNAME"
            )
        # TODO DM-36101: remove this test when we are ready to switch
        # from DDS-based SAL to Kafka-based SAL, and use
        # $LSST_TOPIC_SUBNAME="sal" for production code.
        # Then the EFD ingest code will see the expected topic names.
        if topic_subname == "sal":
            raise RuntimeError(
                "Environment variable LSST_TOPIC_SUBNAME must not have value 'sal', "
                "because that may interfere with EFD ingest of DDS-based SAL data"
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

        self.authorized_users: set[str] = set()
        self.non_authorized_cscs: set[str] = set()

        # Dict of topic kafka name: ReadTopic
        self._read_topics: dict[str, topics.ReadTopic] = dict()

        # Dict of topic kafka name: WriteTopic
        self._write_topics: dict[str, topics.WriteTopic] = dict()

        # dict of private_seqNum: salobj.topics.CommandInfo
        self._running_cmds: dict[int, topics.CommandInfo] = dict()
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
        # Note: we could check identity and origin here, but by
        # doing it in AckCmdReader we avoid queueing unwanted data.
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

    def assert_running(self) -> None:
        """Raise RuntimeError if not running."""
        if not self.running:
            msg = "Not started" if not self.started else "No longer open"
            raise RuntimeError(msg)

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

    def basic_close(self) -> None:
        """A synchronous and less thorough version of `close`.

        Intended for exit handlers and constructor error handlers.
        """
        if not self.isopen:
            return
        self.isopen = False
        self._read_loop_task.cancel()
        if self._consumer is not None:
            self._consumer.close()
        for reader in self._read_topics.values():
            reader.basic_close()
        for writer in self._write_topics.values():
            writer.basic_close()
        self.domain.remove_salinfo(self)
        self._close_kafka()

    async def close(self, cancel_run_kafka_task: bool = True) -> None:
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
            if cancel_run_kafka_task:
                self._run_kafka_task.cancel()
            if self._consumer is not None:
                self._consumer.close()
            # Give the tasks time to finish cancelling.
            # In particular: give the _read_loop time to
            # decrement self.domain.num_read_loops
            await asyncio.sleep(0)
            for reader in self._read_topics.values():
                await reader.close()
            for writer in self._write_topics.values():
                await writer.close()
            while self._running_cmds:
                _, cmd_info = self._running_cmds.popitem()
                try:
                    cmd_info.close()
                except Exception:
                    pass
            self.domain.remove_salinfo(self)
            self._close_kafka()
        except Exception as e:
            print(f"SalInfo.close failed: {e!r}")
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
        if self.write_only:
            raise RuntimeError("Cannot add read topics to a write-only SalInfo")
        if topic.topic_info.kafka_name in self._read_topics:
            raise ValueError(f"Read topic {topic.attr_name} already present")
        self._read_topics[topic.topic_info.kafka_name] = topic

    def add_writer(self, topic: topics.WriteTopic) -> None:
        """Add a WriteTopic, so it can be closed by `close`.

        Parameters
        ----------
        topic : `topics.WriteTopic`
            Write topic to (eventually) close.
        """
        if self.start_called:
            raise RuntimeError("Cannot add topics after the start called")
        if topic.topic_info.kafka_name in self._write_topics:
            raise ValueError(
                f"Write topic {topic.topic_info.kafka_name} already present"
            )
        self._write_topics[topic.topic_info.kafka_name] = topic

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
        * self._deserializers_and_contexts
        * self._serializers_and_contexts

        Register schemas and create missing topics.

        Wait for the read loop to finish.
        """
        try:
            # Create Kafka topics, serializers, and deserializers.
            # Set self._serializers_and_contexts and
            # self._deserializers_and_contexts.
            await self.loop.run_in_executor(self.pool, func=self._blocking_setup_kafka)

            if not self._read_topics:
                # There are no read topics, so self.start_task has to be
                # set done here, rather than in self._read_loop_task.
                if not self.start_task.done():
                    self.start_task.set_result(None)
                # Keep running until _run_kafka_task is cancelled.
                await asyncio.Future()
            else:
                # There are read topics, so self.start_task will be
                # set done in self._read_loop_task.
                self._read_loop_task = asyncio.create_task(self._read_loop())
                # Keep running until the self._read_loop_task and/or
                # self._run_kafka_task are cancelled.
                await self._read_loop_task
        except asyncio.CancelledError:
            pass
        except Exception as e:
            print(f"{self}._run_kafka failed: {e!r}")
            traceback.print_exc()
            if not self.start_task.done():
                self.start_task.set_exception(e)
            self.log.exception("_run_kafka failed")
            raise
        finally:
            await self.close(cancel_run_kafka_task=False)

    def _blocking_setup_kafka(self) -> None:
        """Set up Kafka.

        Create topics in the Kafka broker.
        Register topic schemas with the Kafka schema registry.
        CCreate serializers and deserializers.
        Create a consumer if there are any read topics.
        Create a producer if there are any write topics.

        Set the following attributes:

        * _consumer, if there are any read topics
        * _producer, if there are any write topics
        * _deserializers_and_contexts
        * _serializers_and_contexts
        """
        self._blocking_create_topics()
        self._schema_registry_client = SchemaRegistryClient(
            dict(url=self.schema_registry_url)
        )
        self._blocking_register_schema(
            schema_registry_client=self._schema_registry_client
        )
        self._blocking_create_deserializers(
            schema_registry_client=self._schema_registry_client
        )
        self._blocking_create_serializers(
            schema_registry_client=self._schema_registry_client
        )

        self._blocking_create_producer()
        self._blocking_create_consumer()

    def _blocking_create_topics(self) -> None:
        """Create missing Kafka topics for this SAL component."""
        # A dict of kafka_name: topic_info.
        # This elides duplicate names between self._read_topics
        # and self._write_topics.
        topic_infos = {
            topic.topic_info.kafka_name: topic.topic_info
            for topic in itertools.chain(
                self._read_topics.values(), self._write_topics.values()
            )
        }
        if not topic_infos:
            self.log.warning(f"{self} has no topics")
            return

        # List of NewTopic instances, one per non-duplicate topic
        new_topic_list = [
            NewTopic(
                topic=topic_info.kafka_name,
                num_partitions=topic_info.partitions,
                replication_factor=1,
            )
            for topic_info in topic_infos.values()
        ]
        # Create all topics for the SAL component, ignoring the exception
        # raised if the topic already exists. Two alternatives are:
        # * Get a list of all topics and only create missing topics.
        #   That works, but the list of existing topics is likely to be long,
        #   because it will include topics for all SAL components seen so far.
        #   And we would still have to check for topics that were already
        #   registered, because topics may be added as we run this code.
        # * Rely on automatic registration of new topics.
        #   That prevents setting non-default configuration (such as
        #   num_partitions) and it can cause ugly warnings.
        broker_client = AdminClient(
            {"bootstrap.servers": self.kafka_broker_addr, "api.version.request": True}
        )
        create_result = broker_client.create_topics(new_topic_list)
        for kafka_name, future in create_result.items():
            exception = future.exception()
            if exception is None:
                # Topic created; that's good
                continue
            elif (
                isinstance(exception.args[0], KafkaError)
                and exception.args[0].code() == KafkaError.TOPIC_ALREADY_EXISTS
            ):
                # Topic already exists; that's fine
                pass
            else:
                self.log.exception(
                    f"Failed to create topic {kafka_name}: {exception!r}"
                )
                raise exception
        # The existence of the poll method is not documented, but failing
        # to call it causes tests/test_speed.py test_write to fail.
        broker_client.poll(1)

    def _blocking_create_consumer(self) -> None:
        """Create self._consumer and subscribe to topics.

        Also schedule self._blocking_on_assign_callback to fire when partitions
        are assigned (since the task cannot be done earlier).

        A no-op if there are no read topics.
        """
        if not self._read_topics:
            return

        self._consumer = Consumer(
            {
                "bootstrap.servers": self.kafka_broker_addr,
                # Make sure every consumer is in its own consumer group,
                # since each consumer acts independently.
                "group.id": get_random_string(),
                # Require explicit topic creation, so we can control
                # topic configuration, and to reduce startup latency.
                "allow.auto.create.topics": False,
                # Protect against a race condition in the on_assign callback:
                # if the broker purges data while the on_assign callback
                # is assigning the desired historical data offset,
                # data might no longer exist at the assigned offset;
                # in that case read from the earliest data.
                "auto.offset.reset": "earliest",
            }
        )

        read_topic_names = list(self._read_topics.keys())
        self._consumer.subscribe(
            read_topic_names, on_assign=self._blocking_on_assign_callback
        )

    def _blocking_create_producer(self) -> None:
        """Create self._producer.

        A no-op if there are not write topics.
        """
        if not self._write_topics:
            return

        self._producer = Producer(
            {
                "acks": PRODUCER_WAIT_ACKS,
                "queue.buffering.max.ms": 0,
                "bootstrap.servers": self.kafka_broker_addr,
            }
        )
        # Work around https://github.com/confluentinc/
        # confluent-kafka-dotnet/issues/701
        # a 1 second delay in the first message for a topic.
        self._producer.list_topics()

    def _blocking_register_schema(
        self, schema_registry_client: SchemaRegistryClient
    ) -> None:
        """Register Avro schemas for all topics."""
        for topic in itertools.chain(
            self._read_topics.values(), self._write_topics.values()
        ):
            topic_info = topic.topic_info
            schema = Schema(json.dumps(topic_info.make_avro_schema()), "AVRO")
            schema_registry_client.register_schema(topic_info.avro_subject, schema)

    def _blocking_create_deserializers(
        self, schema_registry_client: SchemaRegistryClient
    ) -> None:
        """Create Kafka deserializers for read topics.

        Set self._deserializers_and_contexts
        """
        # Use a temporary variable to accumlate the info,
        # because this runs in a background thread
        deserializers_and_contexts = {
            topic.topic_info.kafka_name: (
                AvroDeserializer(
                    schema_registry_client=schema_registry_client,
                    schema_str=json.dumps(topic.topic_info.make_avro_schema()),
                ),
                SerializationContext(
                    topic=topic.topic_info.kafka_name, field=MessageField.VALUE
                ),
            )
            for topic in self._read_topics.values()
        }
        self._deserializers_and_contexts = deserializers_and_contexts

    def _blocking_create_serializers(
        self, schema_registry_client: SchemaRegistryClient
    ) -> None:
        """Create Kafka serializers for write topics.

        Set self._serializers_and_contexts
        """
        # Use a temporary variable to accumlate the info,
        # because this runs in a background thread
        serializers_and_contexts = {
            topic.topic_info.kafka_name: (
                AvroSerializer(
                    schema_registry_client=schema_registry_client,
                    schema_str=json.dumps(topic.topic_info.make_avro_schema()),
                    conf={"auto.register.schemas": False},
                ),
                SerializationContext(
                    topic=topic.topic_info.kafka_name, field=MessageField.VALUE
                ),
            )
            for topic in self._write_topics.values()
        }
        self._serializers_and_contexts = serializers_and_contexts

    def _blocking_on_assign_callback(
        self, consumer: Consumer, partitions: list[TopicPartition]
    ) -> None:
        """Set partition offsets to read historical data.

        Intended as the Consumer.subscribe on_assign callback function.

        Parameters
        ----------
        consumer
            Kafka consumer (ignored).
        partitions
            List of TopicPartitions assigned to self._consumer.

        Notes
        -----
        Read the current low and high watermarks for each topic.
        For topics that want history and have existing data,
        record the high watermark in ``self._history_position``.
        Adjust the offset of the partitions to get the desired
        amount of historical data.

        Note: the on_assign callback must call self._consumer.assign
        with all partitions passed in, and it also must set the ``offset``
        attribute of each of these partitions, regardless if whether want
        historical data for that topic.
        """
        if self.on_assign_called:
            self.log.info("on_assign called again; partitions[0]=%s", partitions[0])
            # We must call self._consumer.assign in order to continue reading,
            # but do not want any more historical data.
            read_history_topics = set()
        else:
            self.on_assign_called = True
            # Kafka topic names for topics for which we want history
            read_history_topics = {
                read_topic.topic_info.kafka_name
                for read_topic in self._read_topics.values()
                if read_topic.max_history > 0
            }

        assert self._consumer is not None  # Make mypy happy

        # Local copy of self._history_offsets
        # (needed because this code runs in a thread)
        history_offsets: dict[str, int] = dict()

        for partition in partitions:
            min_offset, max_offset = self._consumer.get_watermark_offsets(
                partition, cached=False
            )
            # print(
            #     f"{self.index} {partition.topic} "
            #     f"{min_offset=}, {max_offset=}"
            # )
            if max_offset <= 0:
                # No data yet written, and we want all new data.
                # Use OFFSET_BEGINNING in case new data arrives
                # while we are assigning.
                partition.offset = OFFSET_BEGINNING
                continue

            if partition.topic not in read_history_topics:
                # No historical data wanted; start from now
                partition.offset = max_offset
            else:
                if self.indexed:
                    max_history = MAX_HISTORY_READ
                else:
                    max_history = self._read_topics[partition.topic].max_history
                desired_offset = max_offset - max_history
                if desired_offset <= min_offset:
                    desired_offset = OFFSET_BEGINNING
                partition.offset = desired_offset
            history_offsets[partition.topic] = max_offset - 1

        self._consumer.assign(partitions)
        # print(f"{self.index} assign:")
        # for partition in partitions:
        #     print(f"  {partition}")

        self._history_offsets = history_offsets
        # print(f"{self.index} {history_offsets=}")

        # Give threads time to work
        if not self.start_task.done():
            self.loop.call_soon_threadsafe(self.start_task.set_result, None)

    def _blocking_write(
        self,
        topic_info: TopicInfo,
        data_dict: dict[str, typing.Any],
        future: asyncio.Future,
    ) -> None:
        """Write a Kafka message and wait for acknowledgement.

        kafka_name : `str`
            Kafka topic name.
        raw_data : `bytes`
            Raw data to write.
        future : `asyncio.Future`
            Future to set done when the data has been acknowledged.
        """
        assert self._producer is not None  # Make mypy happy

        kafka_name = topic_info.kafka_name
        serializer, serialization_context = self._serializers_and_contexts[kafka_name]
        raw_data = serializer(data_dict, serialization_context)

        t0 = time.monotonic()

        def callback(err: KafkaError, _: Message) -> None:
            if err:
                self.loop.call_soon_threadsafe(
                    future.set_exception, KafkaException(err)
                )
            else:
                self.loop.call_soon_threadsafe(future.set_result, None)
                dt = time.monotonic() - t0
                if dt > 0.1:
                    print(
                        f"warning: {self.index} write {kafka_name} took {dt:0.2f} seconds"
                    )
                # else:
                #     print(
                #         f"{data_dict['private_sndStamp']:0.2f} {self.index} "
                #         f"write {kafka_name} took {dt:0.2f} seconds"
                #     )

        self._producer.produce(kafka_name, raw_data, on_delivery=callback)
        self._producer.flush()

    def _close_kafka(self) -> None:
        """Close the Kafka objects and shut down self.pool.

        Destroying the Kafka objects prevents pytest from accumulating
        threads as it runs.
        """
        self.pool.shutdown(wait=True, cancel_futures=True)

        if self._producer is not None:
            self._producer.purge()
        self._producer = None
        self._consumer = None
        self._serializers_and_contexts = dict()
        self._deserializers_and_contexts = dict()
        self._schema_registry_client = None

    async def _read_loop(self) -> None:
        """Read and process messages."""
        self.domain.num_read_loops += 1
        if self._consumer is None:
            self.log.error("No consumer; quitting")
            return
        try:
            # Read historial and new data
            read_history_start_monotonic = time.monotonic()

            sequential_read_errors = 0

            while self.isopen:
                message = await self.loop.run_in_executor(
                    self.pool, self._consumer.poll, 0.1
                )
                if message is None:
                    continue
                message_error = message.error()
                if message_error is not None:
                    sequential_read_errors += 1
                    self.log.warning(
                        f"Ignoring Kafka message with error {message_error!r}"
                    )
                    if sequential_read_errors > MAX_SEQUENTIAL_READ_ERRORS:
                        raise RuntimeError("Too many sequential read errors; giving up")
                    continue

                kafka_name = message.topic()
                if kafka_name is None:
                    sequential_read_errors += 1
                    self.log.warning("Ignoring Kafka message with null topic name")
                    if sequential_read_errors > MAX_SEQUENTIAL_READ_ERRORS:
                        raise RuntimeError("Too many sequential read errors; giving up")
                    continue

                sequential_read_errors = 0

                # print(
                #     f"{self.index} read {kafka_name}\n"
                #     f"serialized={message.value()}"
                # )

                read_topic = self._read_topics[kafka_name]

                deserializer, context = self._deserializers_and_contexts[kafka_name]
                try:
                    data_dict = deserializer(message.value(), context)
                except SchemaResolutionError as e:
                    self.log.error(
                        f"failed to deserialized {kafka_name} {message.value()}: {e!r}"
                    )
                    raise
                data_dict["private_rcvStamp"] = utils.current_tai()
                data = read_topic.DataType(**data_dict)

                # print(
                #     f"{utils.current_tai():0.2f} "
                #     f"{self.index} read {kafka_name} with index="
                #     f"{data_dict.get('salIndex')}, offset={message.offset()}"
                # )

                history_offset = self._history_offsets.get(kafka_name)
                if history_offset is None:
                    if self.index != 0 and self.index != data.salIndex:
                        # Ignore data with mismatched index
                        # print(
                        #     f"{self.index} ignore new {kafka_name}; "
                        #     f"mismatched index={data.salIndex}"
                        # )
                        continue

                    # This is the normal case once we've read all history
                    # print(f"{self.index} queue new {kafka_name} data")
                    read_topic._queue_data([data])
                    continue

                offset = message.offset()
                if offset is None:
                    raise RuntimeError(
                        f"Cannot get offset of message for topic {kafka_name}"
                    )

                if self.indexed and (self.index == 0 or self.index == data.salIndex):
                    self._history_index_data[kafka_name][data.salIndex] = data

                if offset >= history_offset:
                    # We're done with history for this topic
                    del self._history_offsets[kafka_name]

                    if self.indexed:
                        # Publish the most recent historical message seen
                        # for each index (data with mis-matched index
                        # was not put into index_data, so it's all valid).
                        index_data = self._history_index_data.pop(kafka_name, None)
                        if index_data is not None:
                            for hist_data in index_data.values():
                                # print(
                                #     f"{self.index} queue hist {kafka_name} "
                                #     f"with index={hist_data.salIndex}"
                                # )
                                read_topic._queue_data([hist_data])
                    else:
                        read_topic._queue_data([data])

                    if not self._history_offsets:
                        read_history_duration = (
                            time.monotonic() - read_history_start_monotonic
                        )
                        self.log.info(
                            f"Reading historic data took {read_history_duration:0.2f} seconds"
                        )

        except asyncio.CancelledError:
            if not self.start_task.done():
                self.start_task.cancel()
            raise
        except Exception as e:
            print(f"{self} read_loop failed: {e!r}")
            traceback.print_exc()
            if not self.start_task.done():
                self.start_task.set_exception(e)
            self.log.exception("read loop failed")
            raise
        finally:
            self.domain.num_read_loops -= 1

    async def write_data(
        self, topic_info: TopicInfo, data_dict: dict[str, typing.Any]
    ) -> None:
        """Write a message.

        Parameters
        ----------
        topic_info : TopicInfo
            Info for the topic.
        data_dict : dict[str, Any]
            Message to write, as a dict that matches the Avro topic schema.
        """
        self.assert_running()

        try:
            future = self.loop.create_future()
            await self.loop.run_in_executor(
                self.pool, self._blocking_write, topic_info, data_dict, future
            )
            await future

        except Exception:
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
        type: BaseException | None,
        value: BaseException | None,
        traceback: types.TracebackType | None,
    ) -> None:
        await self.close()

    def __repr__(self) -> str:
        return f"SalInfo({self.name}, {self.index})"
