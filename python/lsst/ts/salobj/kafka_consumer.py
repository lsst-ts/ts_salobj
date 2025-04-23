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

__all__ = ["KafkaConsumerInfo", "KafkaConsumer"]

import collections
import dataclasses
import json
import logging
import os
import pathlib
import signal
import time
import types
from concurrent.futures import Future
from functools import partial
from multiprocessing import Queue

import yaml
from confluent_kafka import OFFSET_BEGINNING, Consumer, Message, TopicPartition
from confluent_kafka.schema_registry import Schema, SchemaRegistryClient
from confluent_kafka.schema_registry.avro import AvroDeserializer
from confluent_kafka.serialization import (
    MessageField,
    SerializationContext,
    SerializationError,
)
from fastavro.read import SchemaResolutionError
from lsst.ts import utils

# The maximum number of historical samples to read for each topic.
# This only applies to indexed SAL components, and only if
# the reader wants historical data.
MAX_HISTORY_READ = 10000

# Maximum number of sequential errors reading data from Kafka
MAX_SEQUENTIAL_READ_ERRORS = 2
SCHEMA_RESOLUTION_LOG_ERROR_THRESHOLD = 10


@dataclasses.dataclass
class KafkaConsumerInfo:
    max_history: int
    avro_schema: Schema


@dataclasses.dataclass
class ThrottleSettings:
    """Enable throttling?"""

    enable_throttling: bool = True

    """The throuput used to trigger throttling (messages/s)."""
    throughput_measurement_warn_threshold: int = 100

    """The queue size limit to trigger throttling."""
    auto_throttle_qsize_limit: int = 5

    """Maximum throttle. This is how many messages are discarded
    for each message kept. A value of 10 means we only keep 1 message
    every 10."""
    max_throttle: int = 50

    """Maximum change in throttle value at each throttling iteration.
    This helps prevent throttling from spiking up and down constantly."""
    max_throttle_change: int = 3

    """How many times we pass the throttling loop without adjusting
    it before we try to adjust it."""
    no_throttle_pass_adjust: int = 5

    """Topics to include in the throttling. All telemetry topics are
    included by default, use this to include events. One should be
    carefull when including events as they usually carry important
    asynchronous information, but things like logMessage can be
    throttled without issue."""
    include_topics: list[str] = dataclasses.field(default_factory=list)

    """Topics to exclude from throttling. Use this to exclude telemetry
    from throttling. For example if it is something needed for critical
    operations and no throttling should be done."""
    exclude_topics: list[str] = dataclasses.field(default_factory=list)

    """Apply a fixed throttle value for selected topics. If this is
    defined, the topics listed here will be throttled from the start
    with the specified value and throttle will not be adjusted."""
    static_throttle: dict[str, dict[int, int]] = dataclasses.field(default_factory=dict)


def get_throttle_settings() -> ThrottleSettings:
    """Build ThrottleSettings from a configuration file if
    the environment variable LSST_KAFKA_THROTTLE_SETTINGS is
    defined and points to a valid configuration file or returns
    the default settings.

    Returns
    -------
    throttle_settings : `ThrottleSettings`
        Throttle settings.
    """

    settings = dict()
    if "LSST_KAFKA_THROTTLE_SETTINGS" in os.environ:
        throttle_settings_path = pathlib.Path(
            os.environ["LSST_KAFKA_THROTTLE_SETTINGS"]
        )
        assert throttle_settings_path.exists()
        with open(throttle_settings_path) as fp:
            settings = yaml.safe_load(fp)
            assert (
                settings is not None
            ), f"Settings cannot be empty. Bad configuration for KafkaConsumer: {throttle_settings_path}."

    return ThrottleSettings(**settings)


class KafkaConsumer:
    def __init__(
        self,
        index: None | int,
        consumer_configuration: dict,
        read_topic_names_info: dict[str, KafkaConsumerInfo],
        schema_registry_url: str,
        data_queue: Queue,
        num_messages: int = 1,
        consume_messages_timeout: float = 0.1,
    ) -> None:
        self.log = logging.getLogger(type(self).__name__)
        self.on_assign_called = False
        self.data_queue = data_queue
        self.num_messages = num_messages
        self.consume_messages_timeout = consume_messages_timeout

        self.group_id = consumer_configuration.get("group.id")

        self._partitions: dict[str, TopicPartition] = dict()
        self._read_topics_names_info = read_topic_names_info
        self.throttle_settings = get_throttle_settings()

        self.deserializers_and_contexts: dict[
            str, tuple[AvroDeserializer, SerializationContext]
        ] = dict()

        self.last_sample_timestamps: dict[str, dict[int, float]] = dict(
            [(kafka_name, dict()) for kafka_name in self._read_topics_names_info]
        )
        self.telemetry_n_reads: dict[str, dict[int, int]] = dict(
            [
                (kafka_name, dict())
                for kafka_name in self._read_topics_names_info
                if "logevent" not in kafka_name
                and "ackcmd" not in kafka_name
                and "command" not in kafka_name
                and kafka_name not in self.throttle_settings.exclude_topics
                or kafka_name in self.throttle_settings.include_topics
            ]
        )
        self.throughput_measurement_n_messages = max([self.num_messages, 1000])
        self.throughput_measurement_n_reads = 0
        self.throughput_measurement_start = utils.current_tai()

        self.throttle_telemetry: dict[str, dict[int, int]] = dict(
            [
                (kafka_name, dict())
                for kafka_name in self._read_topics_names_info
                if "logevent" not in kafka_name
                and "ackcmd" not in kafka_name
                and "command" not in kafka_name
                and kafka_name not in self.throttle_settings.exclude_topics
                or kafka_name in self.throttle_settings.include_topics
            ]
        )
        self.throttle_telemetry.update(self.throttle_settings.static_throttle)

        # How many times we passed the throttle
        # loop without changing throttling sets?
        # This might be an indication that we need
        # to reduce throttling.
        self._no_throttle_passes = 0

        self.schema_resolution_errors: dict[str, int] = dict()

        self.support_auto_throttle = self._supports_auto_throttle()

        self._subscription_done: Future = Future()
        self.start_task: Future = Future()
        self._history_offsets_retrieved = False
        self._history_index_data: dict[str, dict[int, dict]] = collections.defaultdict(
            dict
        )
        self.indexed = index is not None
        self.index = index

        self._schema_registry_client = SchemaRegistryClient(
            dict(url=schema_registry_url)
        )
        self._create_deserializers(self._schema_registry_client)
        self._consumer = Consumer(consumer_configuration)
        self._consumer.subscribe(
            list(read_topic_names_info.keys()), on_assign=self._on_assign_callback
        )

        self.isopen = True
        signal.signal(signal.SIGINT, self._handle_terminate_signal)
        signal.signal(signal.SIGTERM, self._handle_terminate_signal)

    def _on_assign_callback(
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
        self.log.debug("on assing called")
        if self._subscription_done.done():
            self.log.info("on_assign called again; partitions[0]=%s", partitions[0])
            # We must call self._consumer.assign in order to continue reading,
            # but do not want any more historical data.
            read_history_topics = set()
        else:
            # Kafka topic names for topics for which we want history
            read_history_topics = {
                kafka_name
                for kafka_name, info in self._read_topics_names_info.items()
                if info.max_history > 0
            }

        # Local copy of self._history_offsets
        # (needed because this code runs in a thread)
        history_offsets: dict[str, int] = dict()

        for partition in partitions:
            self._partitions[partition.topic] = partition
            min_offset, max_offset = self._consumer.get_watermark_offsets(
                partition, cached=False
            )
            if max_offset <= 0:
                # No data yet written, and we want all new data.
                # Use OFFSET_BEGINNING in case new data arrives
                # while we are assigning.
                partition.offset = OFFSET_BEGINNING
                continue

            if partition.topic not in read_history_topics:
                # No historical data wanted; start from now
                partition.offset = max_offset
                continue
            else:
                if self.indexed:
                    max_history = MAX_HISTORY_READ
                else:
                    max_history = self._read_topics_names_info[
                        partition.topic
                    ].max_history
                desired_offset = max_offset - max_history
                if desired_offset <= min_offset:
                    desired_offset = OFFSET_BEGINNING
                partition.offset = desired_offset
            history_offsets[partition.topic] = max_offset - 1

        self._consumer.assign(partitions)

        self._history_offsets = history_offsets
        self._history_offsets_retrieved = True

        self._subscription_done.set_result(None)

    def _create_deserializers(
        self, schema_registry_client: SchemaRegistryClient
    ) -> None:
        """Create Kafka deserializers for read topics.

        Set self._deserializers_and_contexts
        """
        self._deserializers_and_contexts = {
            kafka_name: (
                AvroDeserializer(
                    schema_registry_client=schema_registry_client,
                    schema_str=json.dumps(info.avro_schema),
                ),
                SerializationContext(topic=kafka_name, field=MessageField.VALUE),
            )
            for kafka_name, info in self._read_topics_names_info.items()
        }

    def read_loop(self) -> None:

        consume = partial(
            self._consumer.consume,
            num_messages=self.num_messages,
            timeout=self.consume_messages_timeout,
        )

        self.log.info("Waiting for subscription to finish.")

        self.read_history_start_monotonic = time.monotonic()

        sequential_read_errors = 0

        self.log.info(
            "Starting read loop, "
            f"{self.group_id=} {self.num_messages=} {self.consume_messages_timeout=}s."
        )

        while self.isopen:
            messages = consume()
            if not messages:
                if (
                    not self.start_task.done()
                    and self._history_offsets_retrieved
                    and not self._history_offsets
                ):
                    started_duration = (
                        time.monotonic() - self.read_history_start_monotonic
                    )
                    self.log.info(f"Started in {started_duration:0.2f} seconds")
                    self.start_task.set_result(None)
                    self.data_queue.put(("", None))
                continue
            for message in messages:
                sequential_read_errors = self._process_message(
                    message=message,
                    initial_sequential_read_errors=sequential_read_errors,
                )
                self._handle_throttle()

        self.log.info("Read loop finished.")
        self._consumer.close()

    def _process_message(
        self,
        message: Message,
        initial_sequential_read_errors: int,
    ) -> int:
        """Process message.

        Parameters
        ----------
        message :
            Message to process.
        initial_sequential_read_errors : `int`
            Initial number of sequential read errors.

        Returns
        -------
        sequential_read_errors : `int`
            Number of sequential read errors.

        Raises
        ------
        RuntimeError
            If number of sequential read errors surpasses maximum sequential
            read errors.
        """
        sequential_read_errors = initial_sequential_read_errors

        message_error = message.error()
        if message_error is not None:
            sequential_read_errors += 1
            self.log.warning(f"Ignoring Kafka message with error {message_error!r}")
            if sequential_read_errors > MAX_SEQUENTIAL_READ_ERRORS:
                raise RuntimeError("Too many sequential read errors; giving up")
            return sequential_read_errors

        kafka_name = message.topic()
        if kafka_name is None:
            sequential_read_errors += 1
            self.log.warning("Ignoring Kafka message with null topic name")
            if sequential_read_errors > MAX_SEQUENTIAL_READ_ERRORS:
                raise RuntimeError("Too many sequential read errors; giving up")
            return sequential_read_errors

        sequential_read_errors = 0

        deserializer, context = self._deserializers_and_contexts[kafka_name]
        try:
            data_dict = deserializer(message.value(), context)
        except (SchemaResolutionError, SerializationError):
            if kafka_name not in self.schema_resolution_errors:
                self.log.exception(
                    f"Failed to deserialize {kafka_name}."
                    "This usually means the topic was published "
                    "with an incompatible version of the schema from this instance. "
                    "You might need to check which component has the incompatible schema and "
                    "update it. "
                    "It could be that the publisher is incompatible or this instance reading "
                    "the topic. "
                    "If this is a single old historical data, it might be safe to ignore this "
                    "error. Additional deserialization error messages of this topic will be "
                    "suppressed and will show as shorter error messages every "
                    f"{SCHEMA_RESOLUTION_LOG_ERROR_THRESHOLD} failed attempt. "
                    "If this error persist "
                    "you should investigate it further."
                )

                self.schema_resolution_errors[kafka_name] = 0
            elif (
                self.schema_resolution_errors[kafka_name]
                % SCHEMA_RESOLUTION_LOG_ERROR_THRESHOLD
                == 0
            ):
                self.log.error(
                    f"Failed to deserialize {self.schema_resolution_errors[kafka_name]} samples of "
                    f"{kafka_name}. Check schema compatibility!"
                )
            self.schema_resolution_errors[kafka_name] += 1
            return sequential_read_errors

        index = data_dict.get("salIndex", 0)
        last_sample_timestamp = self.last_sample_timestamps[kafka_name].get(index, 0.0)

        if (
            data_dict["private_sndStamp"] < last_sample_timestamp
            and self.start_task.done()
        ):
            delay = (last_sample_timestamp - data_dict["private_sndStamp"]) * 1000
            self.log.warning(
                "Ignoring old topic sample. "
                f"Topic sent {delay:0.2f}ms before last sample of {kafka_name}:{index}."
            )
            return sequential_read_errors
        self.last_sample_timestamps[kafka_name][index] = data_dict["private_sndStamp"]
        throttle = False
        if (
            self.throttle_settings.enable_throttling
            and kafka_name in self.telemetry_n_reads
        ):
            if index in self.telemetry_n_reads[kafka_name]:
                self.telemetry_n_reads[kafka_name][index] += 1
            else:
                self.telemetry_n_reads[kafka_name][index] = 1
            throttle = (
                self.telemetry_n_reads[kafka_name][index]
                % self.throttle_telemetry[kafka_name].get(index, 1)
                > 0
            )

        data_dict["private_rcvStamp"] = utils.current_tai()

        history_offset = self._history_offsets.get(kafka_name)
        if history_offset is None:
            if self.indexed and self.index != 0 and self.index != index:
                # Ignore data with mismatched index
                return sequential_read_errors

            # This is the normal case once we've read all history
            # print(f"{self.index} queue new {kafka_name} data")
            if not throttle:
                self.data_queue.put((kafka_name, data_dict))
            return sequential_read_errors

        offset = message.offset()
        if offset is None:
            raise RuntimeError(f"Cannot get offset of message for topic {kafka_name}")

        if self.indexed and (self.index == 0 or self.index == index):
            self._history_index_data[kafka_name][data_dict["salIndex"]] = data_dict

        if offset >= history_offset:

            self.log.debug(
                f"{self.group_id=}::Finished handling historical data for {kafka_name=}."
            )
            # We're done with history for this topic
            del self._history_offsets[kafka_name]

            if self.indexed:
                # Publish the most recent historical message seen
                # for each index (data with mis-matched index
                # was not put into index_data, so it's all valid).
                index_data = self._history_index_data.pop(kafka_name, None)
                if index_data is not None:
                    for hist_data in index_data.values():
                        self.data_queue.put((kafka_name, hist_data))
            else:
                self.data_queue.put((kafka_name, data_dict))

            if not self._history_offsets:
                read_history_duration = (
                    time.monotonic() - self.read_history_start_monotonic
                )
                self.log.info(
                    f"Reading historic data took {read_history_duration:0.2f} seconds"
                )
                if not self.start_task.done():
                    self.start_task.set_result(None)
                    self.data_queue.put(("", None))

        return sequential_read_errors

    def _handle_throttle(self) -> None:
        """Check if data needs to be throttled.

        If running on a system that supports auto-throtle,
        (e.g. we can measure queue size) will use the queue
        size to determine throttle conditions. If not, will
        throttle using some pre-defined parameters.
        """
        if not self.throttle_settings.enable_throttling:
            return

        self.throughput_measurement_n_reads += 1

        if (
            self.throughput_measurement_n_reads
            >= self.throughput_measurement_n_messages
        ):
            now = utils.current_tai()
            dt = now - self.throughput_measurement_start
            throughput = self.throughput_measurement_n_reads / dt
            qsize = (
                self.data_queue.qsize()
                if self.support_auto_throttle
                else self.throttle_settings.auto_throttle_qsize_limit
            )
            should_throttle = (
                qsize > self.throttle_settings.auto_throttle_qsize_limit
                if self.support_auto_throttle
                else True
            )
            if (
                throughput
                > self.throttle_settings.throughput_measurement_warn_threshold
                and should_throttle
            ):
                self.log.debug(f"{throughput=} messages/s / {qsize=}.")
                self.adjust_throttle(throughput=throughput, dt=dt, qsize=qsize)
            elif (
                self._no_throttle_passes
                > self.throttle_settings.no_throttle_pass_adjust
            ):
                self.adjust_throttle(
                    throughput=throughput,
                    dt=dt,
                    qsize=qsize if self.support_auto_throttle else 1,
                )
                self._no_throttle_passes = 0
            else:
                self._no_throttle_passes += 1
                for kafka_name, index_n_reads in self.telemetry_n_reads.items():
                    for index, n_read in index_n_reads.items():
                        self.telemetry_n_reads[kafka_name][index] = 1
            self.throughput_measurement_n_reads = 0
            self.throughput_measurement_start = now

    def adjust_throttle(self, throughput: float, dt: float, qsize: int) -> None:
        """Adjut the topic throttle values."""
        if not self.telemetry_n_reads:
            # No telemetry read.
            return

        allocation = throughput / len(self.telemetry_n_reads)
        for kafka_name, index_n_reads in self.telemetry_n_reads.items():
            self.log.debug(f"{kafka_name=}; {index_n_reads=}")
            for index, n_read in index_n_reads.items():
                if (
                    kafka_name in self.throttle_settings.static_throttle
                    and index in self.throttle_settings.static_throttle[kafka_name]
                ):
                    continue
                throttle = min(
                    [
                        max(
                            [
                                int(
                                    n_read
                                    / dt
                                    * qsize
                                    / allocation
                                    / self.throttle_settings.auto_throttle_qsize_limit
                                ),
                                1,
                            ]
                        ),
                        self.throttle_settings.max_throttle,
                    ]
                )
                old_throttle = self.throttle_telemetry[kafka_name].get(index, throttle)
                if throttle > old_throttle + self.throttle_settings.max_throttle_change:
                    throttle = old_throttle + self.throttle_settings.max_throttle_change
                elif (
                    throttle < old_throttle - self.throttle_settings.max_throttle_change
                ):
                    throttle = old_throttle - self.throttle_settings.max_throttle_change
                self.log.debug(
                    f"{kafka_name}: {index=} throughput={n_read/dt} messages/s ({throttle=})."
                )
                self.throttle_telemetry[kafka_name][index] = throttle
                self.telemetry_n_reads[kafka_name][index] = 1

    @classmethod
    def run(
        cls,
        index: None | int,
        consumer_configuration: dict,
        read_topic_names_info: dict[str, KafkaConsumerInfo],
        schema_registry_url: str,
        data_queue: Queue,
        num_messages: int = 1,
        consume_messages_timeout: float = 0.1,
        log_level: int = logging.INFO,
    ) -> None:

        logging.basicConfig(
            level=log_level, format="%(asctime)s - %(levelname)s - %(message)s"
        )
        kafka_consumer = cls(
            index=index,
            consumer_configuration=consumer_configuration,
            read_topic_names_info=read_topic_names_info,
            schema_registry_url=schema_registry_url,
            data_queue=data_queue,
            num_messages=num_messages,
            consume_messages_timeout=consume_messages_timeout,
        )

        kafka_consumer.read_loop()

    def _handle_terminate_signal(
        self, signum: int, frame: types.FrameType | None
    ) -> None:
        self.log.info("Terminating...")
        self.isopen = False

    def _supports_auto_throttle(self) -> bool:
        """Check if system supports auto-throtle.

        On MacOS there is no support for Queue.qsize()
        so it is not possible to run auto throttle.
        """
        try:
            self.data_queue.qsize()
            return True
        except NotImplementedError:
            return False
