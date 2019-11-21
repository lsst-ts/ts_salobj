# This file is part of ts_salobj.
#
# Developed for the LSST Telescope and Site Systems.
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
import time
import unittest

import asynctest

# TODO when we upgrade to OpenSplice 6.10, use its ddsutil:
# import ddsutil
from lsst.ts.salobj import ddsutil

from lsst.ts import salobj


class SpeedTestCase(asynctest.TestCase):
    def setUp(self):
        salobj.set_random_lsst_dds_domain()

    async def test_class_creation_speed(self):
        """Test the speed of creating topic classes on the fly.
        """
        async with salobj.Domain() as domain:
            salinfo = salobj.SalInfo(domain, "Test", index=5)
            topic_names = [f"logevent_" + name for name in salinfo.event_names] \
                + [f"command_" + name for name in salinfo.command_names] \
                + list(salinfo.telemetry_names)
            t0 = time.time()
            for topic_name in topic_names:
                revname = salinfo.revnames.get(topic_name)
                ddsutil.get_dds_classes_from_idl(salinfo.idl_loc, revname)
            dt = time.time() - t0
            ntopics = len(topic_names)
            print(f"Took {dt:0.2f} to create {ntopics} topics: {ntopics/dt:0.1f} topics/sec")

    async def test_readwrite_speed(self):
        """Measure and report read/write speed.

        This isn't really a unit test, but running it as a test
        avoids bitrot.
        """
        ntowrite = 500

        class Reader(salobj.topics.ReadTopic):
            """A ReadTopic that tracks the number of items read."""
            def __init__(self, **kwargs):
                super().__init__(**kwargs)
                self.n_read = 0
                self.callback = self.count_n_read
                self.done_reading = asyncio.Future()

            async def count_n_read(self, data):
                self.n_read += 1
                if self.n_read == ntowrite:
                    self.done_reading.set_result(None)

        async with salobj.Domain() as domain:
            salinfo = salobj.SalInfo(domain, "Test", index=0)
            names = ["errorCode", "logLevel", "scalars"]
            fields = dict(errorCode="code", logLevel="level", scalars="int0")
            readers = [Reader(salinfo=salinfo, name=name, sal_prefix="logevent_", max_history=1)
                       for name in names]
            writers = [salobj.topics.WriteTopic(salinfo=salinfo, name=name, sal_prefix="logevent_")
                       for name in names]
            for writer in writers:
                writer.field_name = fields[writer.name]
            t0 = time.time()
            await salinfo.start()
            dt = time.time() - t0
            # assume that most of the time is reading history
            print(f"Took {dt:0.2f} seconds to obtain historical data")

            async def write_loop():
                for i in range(ntowrite):
                    for writer in writers:
                        setattr(writer.data, writer.field_name, i)
                        writer.put()
                    await asyncio.sleep(0)

            t0 = time.time()
            write_task = asyncio.create_task(write_loop())
            read_tasks = [reader.done_reading for reader in readers]
            all_tasks = [write_task] + read_tasks
            try:
                await asyncio.wait_for(asyncio.gather(*all_tasks), 10)
            except asyncio.TimeoutError:
                self.assertTrue(write_task.done(), "Write tasks did not write all data")
                nread_list = [reader.n_read for reader in readers]
                self.fail(f"One or more readers did not finish; read {nread_list} of {ntowrite}")
            dt = time.time() - t0
            total_values = ntowrite * len(readers)
            print(f"Took {dt:0.2f} seconds to read/write {total_values} values: "
                  f"{total_values/dt:0.0f} values/sec")


if __name__ == "__main__":
    unittest.main()
