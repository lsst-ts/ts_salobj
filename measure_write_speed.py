#!/usr/bin/env python
import argparse
import asyncio
import random
import string
import time
import typing

from lsst.ts import salobj


async def measure_write_speed(
    component_name: str,
    sal_index: int,
    attr_name: str,
    interval: float,
    num_messages: int,
) -> None:
    """Measure write speed for a specified SAL component and topic.

    Parameters
    ----------
    component_name
        Name of SAL component, e.g. MTM1M3
    sal_index
        SAL index; 0 if the component is not indexed.
    attr_name
        Name of SAL topic, with cmd_, evt_, or tel_ prefix,
        e.g. tel_forceActuatorData.
    interval
        Interval between messages (seconds)
    num_messages
        Number of messages to write.
    """
    async with salobj.Domain() as domain:
        salinfo = salobj.SalInfo(domain=domain, name=component_name, index=sal_index)
        topic = salobj.topics.WriteTopic(salinfo=salinfo, attr_name=attr_name)
        await salinfo.start()

        # Set random data for public fields,
        # to avoid gains from compression or not sending default values
        data = topic.DataType()
        if hasattr(data, "get_vars"):
            data_dict = data.get_vars()
        else:
            data_dict = vars(data)
        random_data_dict = dict()
        for field_name, value in data_dict.items():
            if field_name.startswith("private_"):
                continue
            if field_name == "salIndex":
                continue

            # Random generators by type
            # Use arbitrary ranges; for int make sure the range
            # is compatible with unsigned short
            random_generator_dict = {
                bool: lambda: random.choice([False, True]),
                int: lambda: random.randint(0, 100),
                float: lambda: random.randrange(-1000, 1000),
                str: lambda: "".join(
                    random.choice(string.ascii_letters) for _ in range(256)
                ),
            }
            if isinstance(value, list):
                arr_len = len(value)
                item_type = type(value[0])
                rand_gen = random_generator_dict[item_type]
                rand_value: typing.Any = [rand_gen() for _ in range(arr_len)]
            else:
                rand_gen = random_generator_dict[type(value)]
                rand_value = rand_gen()
            random_data_dict[field_name] = rand_value
        topic.set(**random_data_dict)

        t0 = time.monotonic()
        for i in range(num_messages):
            desired_msg_time = i * interval + t0
            wait_time = desired_msg_time - time.monotonic()
            if wait_time > 0:
                await asyncio.sleep(wait_time)
            await topic.write()
        dt = time.monotonic() - t0
        write_speed = num_messages / dt
        print(f"Wrote {write_speed:0.0f} samples/second ({num_messages} samples)")
        # Give DDS time to read the messages
        await asyncio.sleep(1)


parser = argparse.ArgumentParser(
    "Measure the speed of writing messages for one SAL topic"
)
parser.add_argument(
    "component_name_index", help="SAL component name[:sal_index], e.g. Test:1"
)
parser.add_argument(
    "topic_attr_name", help="Topic attribute name, e.g. evt_summaryState"
)
parser.add_argument(
    "-i",
    "--interval",
    type=float,
    default=0,
    help="Interval between each message (seconds)",
)
parser.add_argument(
    "-n", "--number", type=int, default=2000, help="Number of messages to write"
)
args = parser.parse_args()
component_name, sal_index = salobj.name_to_name_index(args.component_name_index)
asyncio.run(
    measure_write_speed(
        component_name=component_name,
        sal_index=sal_index,
        attr_name=args.topic_attr_name,
        interval=args.interval,
        num_messages=args.number,
    )
)
