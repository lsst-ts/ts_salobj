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
import signal
import time
import types
from concurrent.futures import Future
from functools import partial
from multiprocessing import Queue

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
        self.deserializers_and_contexts: dict[
            str, tuple[AvroDeserializer, SerializationContext]
        ] = dict()

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

        last_sample_timestamps: dict[str, dict[int, float]] = dict(
            [(kafka_name, dict()) for kafka_name in self._read_topics_names_info]
        )
        consume = partial(
            self._consumer.consume,
            num_messages=self.num_messages,
            timeout=self.consume_messages_timeout,
        )

        self.log.info("Waiting for subscription to finish.")

        self.read_history_start_monotonic = time.monotonic()

        sequential_read_errors = 0
        schema_resolution_errors: dict[str, int] = dict()

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
                    schema_resolution_errors=schema_resolution_errors,
                    last_sample_timestamps=last_sample_timestamps,
                )
        self.log.info("Read loop finished.")
        self._consumer.close()

    def _process_message(
        self,
        message: Message,
        initial_sequential_read_errors: int,
        schema_resolution_errors: dict[str, int],
        last_sample_timestamps: dict[str, dict[int, float]],
    ) -> int:
        """Process message.

        Parameters
        ----------
        message :
            Message to process.
        initial_sequential_read_errors : `int`
            Initial number of sequential read errors.
        schema_resolution_errors : `dict`[`str`, `int`]
            Dictionary with schema resolution errors for
            each individual topic. This dictionary will be
            edited by the method with any new errors.
        last_sample_timestamps : `dict`[`str`, `float`]
            Dictionary with last sample timestamps for each
            topic. This dictionary will be edited by the
            method with new timestamps.

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
            if kafka_name not in schema_resolution_errors:
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

                schema_resolution_errors[kafka_name] = 0
            elif (
                schema_resolution_errors[kafka_name]
                % SCHEMA_RESOLUTION_LOG_ERROR_THRESHOLD
                == 0
            ):
                self.log.error(
                    f"Failed to deserialize {schema_resolution_errors[kafka_name]} samples of "
                    f"{kafka_name}. Check schema compatibility!"
                )
            schema_resolution_errors[kafka_name] += 1
            return sequential_read_errors

        index = data_dict.get("salIndex", 0)
        last_sample_timestamp = last_sample_timestamps[kafka_name].get(index, 0.0)

        if data_dict["private_sndStamp"] < last_sample_timestamp:
            delay = (last_sample_timestamp - data_dict["private_sndStamp"]) * 1000
            self.log.warning(
                "Ignoring old topic sample. "
                f"Topic sent {delay:0.2f}ms before last sample of {kafka_name}:{index}."
            )
            return sequential_read_errors
        last_sample_timestamps[kafka_name][index] = data_dict["private_sndStamp"]
        data_dict["private_rcvStamp"] = utils.current_tai()

        history_offset = self._history_offsets.get(kafka_name)
        if history_offset is None:
            if self.indexed and self.index != 0 and self.index != index:
                # Ignore data with mismatched index
                return sequential_read_errors

            # This is the normal case once we've read all history
            # print(f"{self.index} queue new {kafka_name} data")
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
    ) -> None:

        logging.basicConfig(
            level=logging.DEBUG, format="%(asctime)s - %(levelname)s - %(message)s"
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
