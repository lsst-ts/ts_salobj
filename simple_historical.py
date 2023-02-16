# mypy: ignore-errors

import base64
import os

from confluent_kafka import OFFSET_BEGINNING, Consumer, Producer
from confluent_kafka.admin import AdminClient, NewTopic

BROKER_ADDR = "127.0.0.1"

# The maximum number of historical messages we want
MAX_HISTORY_DEPTH = 10


def get_random_string() -> str:
    """Get a random string."""
    return base64.urlsafe_b64encode(os.urandom(12)).decode().replace("=", "_")


class HistoryExample:
    def __init__(self):
        base_name = get_random_string()
        self.topic_names = [f"historical.{base_name}.topic{i}" for i in range(3)]
        self.on_assign_called = False

    def setup(self):
        # Create topics
        broker_client = AdminClient({"bootstrap.servers": BROKER_ADDR})
        for topic_name in self.topic_names:
            new_topic = NewTopic(
                topic=topic_name, num_partitions=1, replication_factor=1
            )
            create_result = broker_client.create_topics([new_topic])
            for _, future in create_result.items():
                assert future.exception() is None
            print(f"created topic {topic_name}")

        # Create producer
        self.producer = Producer(
            {
                "acks": 1,
                "queue.buffering.max.ms": 0,
                "bootstrap.servers": BROKER_ADDR,
            }
        )

        # Create lots of historical data for topic 0
        # a few items for topic 1 and none for topic 2
        for topic_name, num_hist_messages in zip(self.topic_names, (20, 3, 0)):
            for i in range(num_hist_messages):
                raw_data = f"{topic_name} message {i}".encode()
                self.producer.produce(topic_name, raw_data)
                self.producer.flush()

        # Create the consumer
        self.consumer = Consumer(
            {
                "bootstrap.servers": BROKER_ADDR,
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
        self.consumer.subscribe(self.topic_names, on_assign=self.on_assign_callback)

    def on_assign_callback(self, consumer, partitions):
        """Set partition offsets to read historical data.

        Intended as the Consumer.subscribe on_assign callback function.

        Parameters
        ----------
        consumer
            Kafka consumer.
        partitions
            List of TopicPartitions assigned to consumer.

        Notes
        -----
        Read the current low and high watermarks for each topic.
        For topics that want history and have existing data,
        record the high watermark in ``self._history_position``.
        Adjust the offset of the partitions to get the desired
        amount of historical data.

        Note: the on_assign callback must call consumer.assign
        with all partitions passed in, and it also must set the ``offset``
        attribute of each of these partitions, regardless if whether want
        historical data for that topic.
        """
        for partition in partitions:
            min_offset, max_offset = consumer.get_watermark_offsets(
                partition, cached=False
            )
            print(f"{partition.topic} {min_offset=}, {max_offset=}")
            if max_offset <= 0:
                # No data yet written, and we want all new data.
                # Use OFFSET_BEGINNING in case new data arrives
                # while we are assigning.
                partition.offset = OFFSET_BEGINNING
                continue

            if self.on_assign_called:
                # No more historical data wanted; start from now
                partition.offset = max_offset
            else:
                desired_offset = max_offset - MAX_HISTORY_DEPTH
                if desired_offset <= min_offset:
                    desired_offset = OFFSET_BEGINNING
                partition.offset = desired_offset

        consumer.assign(partitions)

    def consume(self):
        while True:
            message = self.consumer.poll(0.1)
            if message is None:
                continue
            message_error = message.error()
            if message_error is not None:
                print(f"Ignoring Kafka message with error {message_error!r}")
                continue
            print(f"Read {message.topic()}: {message.value()}")


example = HistoryExample()
example.setup()
example.consume()
