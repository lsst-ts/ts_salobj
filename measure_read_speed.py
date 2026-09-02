#!/usr/bin/env python
# This file is part of ts_salobj.
#
# Developed for the Vera C. Rubin Observatory Telescope and Site Systems.
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
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program. If not, see <https://www.gnu.org/licenses/>.

import argparse
import asyncio

import numpy as np
from lsst.ts import salobj, utils


async def measure_read_speed(
    component_name: str, sal_index: int, attr_name: str, num_messages: int
) -> None:
    """Measure read speed and latency for a specified SAL component and topic.

    Parameters
    ----------
    component_name : `str`
        Name of SAL component, e.g. MTM1M3
    sal_index : `int`
        SAL index; 0 if the component is not indexed.
    attr_name : `str`
        Name of SAL topic, with cmd_, evt_, or tel_ prefix,
        e.g. tel_forceActuatorData.
    num_messages : `int`
        Number of messages to read.
    """
    if num_messages < 2:
        raise ValueError(f"num_messages={num_messages} must be >= 2")
    async with salobj.Domain() as domain, salobj.SalInfo(
        domain=domain, name=component_name, index=sal_index
    ) as salinfo:
        topic = salobj.topics.ReadTopic(
            salinfo=salinfo, attr_name=attr_name, max_history=0
        )

        await salinfo.start()
        print("Reader is ready")

        latencies = np.zeros(num_messages - 1)

        # Wait for the first message before we measure anything,
        # since we don't know when the writer will start.
        initial_data = await topic.next(flush=False)
        if initial_data.private_seqNum != 1:
            print(f"Warning: initial seqNum = {initial_data.private_seqNum} != 1")

        # Measure speed and latency for the remaining messages.
        t0 = utils.current_tai()
        for i in range(num_messages - 1):
            data = await topic.next(flush=False)
            latencies[i] = utils.current_tai() - data.private_sndStamp
        dt = utils.current_tai() - t0
        read_speed = (num_messages - 1) / dt
        num_lost = (
            1 + (data.private_seqNum - initial_data.private_seqNum) - num_messages
        )
        print(f"Read {read_speed:0.0f} samples/second ({num_messages} samples)")
        print(
            f"Latency mean = {latencies.mean():0.3f}, stdev = {latencies.std():0.3f}, "
            f"min = {latencies.min():0.3f}, max = {latencies.max():0.3f} seconds"
        )
        print(f"Lost {num_lost} samples")


parser = argparse.ArgumentParser("Measure read speed and latency for one SAL topic")
parser.add_argument(
    "component_name_index", help="SAL component name[:sal_index], e.g. Test:1"
)
parser.add_argument(
    "topic_attr_name", help="Topic attribute name, e.g. evt_summaryState"
)
parser.add_argument(
    "-n", "--number", type=int, default=2000, help="Number of messages to read"
)
args = parser.parse_args()
component_name, sal_index = salobj.name_to_name_index(args.component_name_index)
asyncio.run(
    measure_read_speed(
        component_name=component_name,
        sal_index=sal_index,
        attr_name=args.topic_attr_name,
        num_messages=args.number,
    )
)
