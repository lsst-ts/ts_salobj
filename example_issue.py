# mypy: ignore-errors

import base64
import os
import random
import string
import time

from confluent_kafka import Producer
from confluent_kafka.admin import AdminClient, NewTopic

PRODUCER_WAIT_ACKS = 1
BROKER_ADDR = "127.0.0.1"


def make_producer():
    return Producer(
        {
            "acks": PRODUCER_WAIT_ACKS,
            "queue.buffering.max.ms": 0,
            "bootstrap.servers": BROKER_ADDR,
        }
    )


def create_topic(topic_name):
    broker_client = AdminClient({"bootstrap.servers": BROKER_ADDR})
    new_topic = NewTopic(topic=topic_name, num_partitions=1, replication_factor=1)
    create_result = broker_client.create_topics([new_topic])
    for topic_name, future in create_result.items():
        assert future.exception() is None
    print(f"created topic {topic_name}")


def write(producer, topic_name, raw_data):
    t0 = time.monotonic()

    def callback(err, _):
        assert err is None
        dt = time.monotonic() - t0
        print(f"write took {dt:0.2f} seconds")

    producer.produce(topic_name, raw_data, on_delivery=callback)
    producer.flush()


def main():
    random_str = base64.urlsafe_b64encode(os.urandom(9)).decode().replace("=", "_")
    topic_name = f"test_{random_str}"
    print(f"topic_name={topic_name}")
    create_topic(topic_name)
    producer = make_producer()

    for _ in range(10):
        random_data = "".join(
            random.choice(string.printable) for i in range(100)
        ).encode()
        write(producer, topic_name, random_data)


main()
