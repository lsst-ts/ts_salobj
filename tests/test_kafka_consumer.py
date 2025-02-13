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
import unittest
from multiprocessing import Process, Queue

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
