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

import asyncio
import functools
import os
import tempfile
import unittest
from multiprocessing import Process, Queue

import pytest
import yaml
from lsst.ts import salobj

STD_TIMEOUT = 5


class TestKafkaConsumer(unittest.IsolatedAsyncioTestCase):

    def setUp(self) -> None:
        salobj.set_test_topic_subname()

    async def test_basics(self) -> None:
        async with salobj.Domain() as domain, salobj.SalInfo(
            domain=domain,
            name="Test",
            index=4,
        ) as salinfo:
            tel_writter = salobj.topics.WriteTopic(
                salinfo=salinfo, attr_name="tel_scalars"
            )
            await asyncio.wait_for(salinfo.start(), timeout=STD_TIMEOUT)

            consumer_configuration = {
                # Make sure every consumer is in its own consumer group,
                # since each consumer acts independently.
                "group.id": salinfo.group_id,
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

            consumer_configuration.update(salinfo.get_broker_client_configuration())
            read_topic_names_info = {
                topic.topic_info.kafka_name: salobj.KafkaConsumerInfo(
                    max_history=1,
                    avro_schema=topic.topic_info.make_avro_schema(),
                )
                for topic in salinfo._write_topics.values()
            }
            data_queue: Queue = Queue()

            run_kafka_consumer = functools.partial(
                salobj.KafkaConsumer.run,
                index=salinfo.index if salinfo.indexed else None,
                consumer_configuration=consumer_configuration,
                read_topic_names_info=read_topic_names_info,
                schema_registry_url=salinfo.schema_registry_url,
                data_queue=data_queue,
            )

            kafka_consumer_process = Process(target=run_kafka_consumer, daemon=True)
            kafka_consumer_process.start()
            await asyncio.sleep(1.0)
            assert kafka_consumer_process.is_alive()

            get_data = functools.partial(
                data_queue.get,
                timeout=30,
            )
            print("Wait for kafka consumer to start.")
            data = await asyncio.get_event_loop().run_in_executor(None, get_data)
            assert data[0] == ""
            assert data[1] is None

            for i in range(100):
                await tel_writter.set_write(int0=i + 1)

            for i in range(100):
                data = await asyncio.get_event_loop().run_in_executor(None, get_data)
                assert data is not None
                assert data[0] == tel_writter.topic_info.kafka_name
                assert data[1]["int0"] == i + 1

            kafka_consumer_process.terminate()
            kafka_consumer_process.join()

    async def test_throttling(self) -> None:
        async with salobj.Domain() as domain, salobj.SalInfo(
            domain=domain,
            name="Test",
            index=5,
        ) as salinfo:
            evt_writter = salobj.topics.WriteTopic(
                salinfo=salinfo, attr_name="evt_scalars"
            )
            tel_writter = salobj.topics.WriteTopic(
                salinfo=salinfo, attr_name="tel_scalars"
            )
            await asyncio.wait_for(salinfo.start(), timeout=STD_TIMEOUT)

            consumer_configuration = {
                # Make sure every consumer is in its own consumer group,
                # since each consumer acts independently.
                "group.id": salinfo.group_id,
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

            consumer_configuration.update(salinfo.get_broker_client_configuration())
            read_topic_names_info = {
                topic.topic_info.kafka_name: salobj.KafkaConsumerInfo(
                    max_history=0,
                    avro_schema=topic.topic_info.make_avro_schema(),
                )
                for topic in salinfo._write_topics.values()
            }
            data_queue: Queue = Queue()

            kafka_consumer = salobj.KafkaConsumer(
                index=salinfo.index if salinfo.indexed else None,
                consumer_configuration=consumer_configuration,
                read_topic_names_info=read_topic_names_info,
                schema_registry_url=salinfo.schema_registry_url,
                data_queue=data_queue,
            )

            assert (
                tel_writter.topic_info.kafka_name in kafka_consumer.throttle_telemetry
            )
            assert (
                evt_writter.topic_info.kafka_name
                not in kafka_consumer.throttle_telemetry
            )
            assert not kafka_consumer.throttle_telemetry[
                tel_writter.topic_info.kafka_name
            ]

            loop = asyncio.get_event_loop()

            read_loop_task = loop.run_in_executor(None, kafka_consumer.read_loop)
            try:

                data = await asyncio.wait_for(
                    loop.run_in_executor(None, data_queue.get), timeout=STD_TIMEOUT
                )
                assert data[1] is None

                for i in range(kafka_consumer.throughput_measurement_n_messages - 1):
                    await tel_writter.write()
                    if (
                        i
                        < kafka_consumer.throughput_measurement_n_messages
                        - 1
                        - kafka_consumer.throttle_settings.auto_throttle_qsize_limit * 2
                    ):
                        data = await asyncio.wait_for(
                            loop.run_in_executor(None, data_queue.get),
                            timeout=STD_TIMEOUT,
                        )
                        assert data[0] == tel_writter.topic_info.kafka_name

                assert not kafka_consumer.throttle_telemetry[
                    tel_writter.topic_info.kafka_name
                ]
                await tel_writter.write()
                while not data_queue.empty():
                    data = await asyncio.wait_for(
                        loop.run_in_executor(None, data_queue.get), timeout=STD_TIMEOUT
                    )
                    assert data[0] == tel_writter.topic_info.kafka_name

                assert (
                    salinfo.index
                    in kafka_consumer.throttle_telemetry[
                        tel_writter.topic_info.kafka_name
                    ]
                )
                # set throttle manually now so we can check
                # that throttling is working.
                throttle = 5
                kafka_consumer.throttle_telemetry[tel_writter.topic_info.kafka_name][
                    salinfo.index
                ] = throttle

                assert data_queue.empty()

                # writting the same number of messages as
                # the throttle value should yield a single
                # message.
                for _ in range(throttle):
                    await tel_writter.write()

                # this should return a value.
                data = await asyncio.wait_for(
                    loop.run_in_executor(None, data_queue.get), timeout=STD_TIMEOUT
                )
                # and then reading again should timeout
                with pytest.raises(asyncio.TimeoutError):
                    data = await asyncio.wait_for(
                        loop.run_in_executor(None, data_queue.get), timeout=STD_TIMEOUT
                    )

            finally:

                kafka_consumer.isopen = False

                await read_loop_task
                while not data_queue.empty():
                    data_queue.get_nowait()
                data_queue.close()

    async def test_empty_settings(self) -> None:
        async with salobj.Domain() as domain, salobj.SalInfo(
            domain=domain,
            name="Test",
            index=5,
        ) as salinfo:
            with tempfile.NamedTemporaryFile(suffix=".yaml") as temp_file:
                await asyncio.wait_for(salinfo.start(), timeout=STD_TIMEOUT)

                consumer_configuration = {
                    # Make sure every consumer is in its own consumer group,
                    # since each consumer acts independently.
                    "group.id": salinfo.group_id,
                    # Require explicit topic creation, so we can control
                    # topic configuration, and to reduce startup latency.
                    "allow.auto.create.topics": False,
                    # Protect against a race condition in the on_assign
                    # callback:
                    # if the broker purges data while the on_assign callback
                    # is assigning the desired historical data offset,
                    # data might no longer exist at the assigned offset;
                    # in that case read from the earliest data.
                    "auto.offset.reset": "earliest",
                }

                consumer_configuration.update(salinfo.get_broker_client_configuration())
                read_topic_names_info = {
                    topic.topic_info.kafka_name: salobj.KafkaConsumerInfo(
                        max_history=0,
                        avro_schema=topic.topic_info.make_avro_schema(),
                    )
                    for topic in salinfo._write_topics.values()
                }
                data_queue: Queue = Queue()

                os.environ["LSST_KAFKA_THROTTLE_SETTINGS"] = temp_file.name

                with pytest.raises(AssertionError):

                    _ = salobj.KafkaConsumer(
                        index=salinfo.index if salinfo.indexed else None,
                        consumer_configuration=consumer_configuration,
                        read_topic_names_info=read_topic_names_info,
                        schema_registry_url=salinfo.schema_registry_url,
                        data_queue=data_queue,
                    )

                os.environ.pop("LSST_KAFKA_THROTTLE_SETTINGS")

    async def test_throttling_events(self) -> None:
        async with salobj.Domain() as domain, salobj.SalInfo(
            domain=domain,
            name="Test",
            index=5,
        ) as salinfo:
            with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml") as temp_file:
                evt_writter = salobj.topics.WriteTopic(
                    salinfo=salinfo, attr_name="evt_scalars"
                )
                tel_writter = salobj.topics.WriteTopic(
                    salinfo=salinfo, attr_name="tel_scalars"
                )
                tel_writter2 = salobj.topics.WriteTopic(
                    salinfo=salinfo, attr_name="tel_arrays"
                )
                await asyncio.wait_for(salinfo.start(), timeout=STD_TIMEOUT)

                consumer_configuration = {
                    # Make sure every consumer is in its own consumer group,
                    # since each consumer acts independently.
                    "group.id": salinfo.group_id,
                    # Require explicit topic creation, so we can control
                    # topic configuration, and to reduce startup latency.
                    "allow.auto.create.topics": False,
                    # Protect against a race condition in the on_assign
                    # callback:
                    # if the broker purges data while the on_assign callback
                    # is assigning the desired historical data offset,
                    # data might no longer exist at the assigned offset;
                    # in that case read from the earliest data.
                    "auto.offset.reset": "earliest",
                }

                consumer_configuration.update(salinfo.get_broker_client_configuration())
                read_topic_names_info = {
                    topic.topic_info.kafka_name: salobj.KafkaConsumerInfo(
                        max_history=0,
                        avro_schema=topic.topic_info.make_avro_schema(),
                    )
                    for topic in salinfo._write_topics.values()
                }
                data_queue: Queue = Queue()

                static_throttle = 10
                config = dict(
                    include_topics=[evt_writter.topic_info.kafka_name],
                    exclude_topics=[tel_writter.topic_info.kafka_name],
                    static_throttle={
                        tel_writter2.topic_info.kafka_name: {
                            salinfo.index: static_throttle
                        }
                    },
                )
                temp_file.write(yaml.safe_dump(config))
                temp_file.flush()

                os.environ["LSST_KAFKA_THROTTLE_SETTINGS"] = temp_file.name

                kafka_consumer = salobj.KafkaConsumer(
                    index=salinfo.index if salinfo.indexed else None,
                    consumer_configuration=consumer_configuration,
                    read_topic_names_info=read_topic_names_info,
                    schema_registry_url=salinfo.schema_registry_url,
                    data_queue=data_queue,
                )

                os.environ.pop("LSST_KAFKA_THROTTLE_SETTINGS")

                assert (
                    tel_writter.topic_info.kafka_name
                    not in kafka_consumer.throttle_telemetry
                )
                assert (
                    evt_writter.topic_info.kafka_name
                    in kafka_consumer.throttle_telemetry
                )
                assert (
                    tel_writter2.topic_info.kafka_name
                    in kafka_consumer.throttle_telemetry
                )
                assert (
                    kafka_consumer.throttle_telemetry[
                        tel_writter2.topic_info.kafka_name
                    ][salinfo.index]
                    == static_throttle
                )

                loop = asyncio.get_event_loop()

                read_loop_task = loop.run_in_executor(None, kafka_consumer.read_loop)
                try:

                    data = await asyncio.wait_for(
                        loop.run_in_executor(None, data_queue.get), timeout=STD_TIMEOUT
                    )
                    assert data[1] is None

                    for i in range(
                        kafka_consumer.throughput_measurement_n_messages - 1
                    ):
                        await evt_writter.write()
                        if (
                            i
                            < kafka_consumer.throughput_measurement_n_messages
                            - 1
                            - kafka_consumer.throttle_settings.auto_throttle_qsize_limit
                            * 2
                        ):
                            data = await asyncio.wait_for(
                                loop.run_in_executor(None, data_queue.get),
                                timeout=STD_TIMEOUT,
                            )
                            assert data[0] == evt_writter.topic_info.kafka_name

                    assert not kafka_consumer.throttle_telemetry[
                        evt_writter.topic_info.kafka_name
                    ]
                    await evt_writter.write()
                    while not data_queue.empty():
                        data = await asyncio.wait_for(
                            loop.run_in_executor(None, data_queue.get),
                            timeout=STD_TIMEOUT,
                        )
                        assert data[0] == evt_writter.topic_info.kafka_name

                    assert (
                        salinfo.index
                        in kafka_consumer.throttle_telemetry[
                            evt_writter.topic_info.kafka_name
                        ]
                    )
                    assert (
                        kafka_consumer.throttle_telemetry[
                            tel_writter2.topic_info.kafka_name
                        ][salinfo.index]
                        == static_throttle
                    )
                    assert (
                        tel_writter.topic_info.kafka_name
                        not in kafka_consumer.throttle_telemetry
                    )

                    # set throttle manually now so we can check
                    # that throttling is working.
                    throttle = 5
                    kafka_consumer.throttle_telemetry[
                        evt_writter.topic_info.kafka_name
                    ][salinfo.index] = throttle

                    assert data_queue.empty()

                    # writting the same number of messages as
                    # the throttle value should yield a single
                    # message.
                    for _ in range(throttle):
                        await evt_writter.write()

                    # this should return a value.
                    data = await asyncio.wait_for(
                        loop.run_in_executor(None, data_queue.get), timeout=STD_TIMEOUT
                    )
                    # and then reading again should timeout
                    with pytest.raises(asyncio.TimeoutError):
                        data = await asyncio.wait_for(
                            loop.run_in_executor(None, data_queue.get),
                            timeout=STD_TIMEOUT,
                        )

                finally:

                    kafka_consumer.isopen = False

                    await read_loop_task
                    while not data_queue.empty():
                        data_queue.get_nowait()
                    data_queue.close()
