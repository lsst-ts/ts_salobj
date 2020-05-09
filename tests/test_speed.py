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
import pathlib
import time
import unittest

import asynctest
import ddsutil
import astropy.units as u

try:
    from lsst import verify
except ImportError:
    verify = None

from lsst.ts import salobj

STD_TIMEOUT = 2

index_gen = salobj.index_generator()


class SpeedTestCase(asynctest.TestCase):
    """Measure the speed of salobj.

    These are not actually unit tests, but running them as tests
    makes sure they are run automatically and avoids bit rot.
    """

    @classmethod
    def setUpClass(cls):
        if verify is None:
            return
        metrics = (
            verify.Metric(
                name="salobj.CreateClasses",
                description="The number of topic classes that dds can create "
                "(from an IDL file), per second. "
                "This is measured by creating one of of each Test topic. "
                "Creating classes for topics is done once, at startup time.",
                unit=u.ct / u.second,
            ),
            verify.Metric(
                name="salobj.IssueCommands",
                description="The rate at which salobj can issue commands and await a reply. "
                "This test uses a command that has only one parameter, "
                "and the controller does nothing in reponse to the command.",
                unit=u.ct / u.second,
            ),
            verify.Metric(
                name="salobj.ReadTest_arrays",
                description="The rate at which salobj can read Test_arrays samples. "
                "This represents a fairly large sample.",
                unit=u.ct / u.second,
            ),
            verify.Metric(
                name="salobj.ReadTest_logLevel",
                description="The rate at which salobj can read Test_logevent_logLevel samples. "
                "This represents a small sample.",
                unit=u.ct / u.second,
            ),
            verify.Metric(
                name="salobj.WriteTest_arrays",
                description="The rate at which salobj can write Test_arrays samples. "
                "This represents a fairly large sample.",
                unit=u.ct / u.second,
            ),
            verify.Metric(
                name="salobj.WriteTest_logLevel",
                description="The rate at which salobj can write Test_logevent_logLevel samples. "
                "This represents a small sample.",
                unit=u.ct / u.second,
            ),
        )
        cls.verify_job = verify.Job(metrics=metrics)

    @classmethod
    def tearDownClass(cls):
        if verify is None:
            return
        measurements_dir = pathlib.Path(__file__).resolve().parent / "measurements"
        cls.verify_job.write(measurements_dir / "speed.json")

    def setUp(self):
        salobj.set_random_lsst_dds_domain()
        self.datadir = pathlib.Path(__file__).resolve().parent / "data"
        self.index = next(index_gen)

    def insert_measurement(self, measurement):
        measurement.metric = self.verify_job.metrics[measurement.metric_name]
        self.verify_job.measurements.insert(measurement)

    async def test_class_creation_speed(self):
        """Test the speed of creating topic classes on the fly.
        """
        async with salobj.Domain() as domain:
            salinfo = salobj.SalInfo(domain, "Test", index=5)
            topic_names = (
                [f"logevent_" + name for name in salinfo.event_names]
                + [f"command_" + name for name in salinfo.command_names]
                + list(salinfo.telemetry_names)
            )
            t0 = time.monotonic()
            for topic_name in topic_names:
                revname = salinfo.revnames.get(topic_name)
                ddsutil.get_dds_classes_from_idl(salinfo.metadata.idl_path, revname)
            dt = time.monotonic() - t0
            ntopics = len(topic_names)
            creation_speed = dt / ntopics
            print(
                f"Took {dt:0.2f} to create {ntopics} topics: {creation_speed:0.1f} topics/sec"
            )
            if verify is not None:
                self.insert_measurement(
                    verify.Measurement(
                        "salobj.CreateClasses", creation_speed * u.ct / u.second
                    )
                )

    async def test_readwrite_speed(self):
        """Measure and report read/write speed.
        """
        num_samples_per_topic = 1000

        class Reader(salobj.topics.ReadTopic):
            """A ReadTopic that tracks the number of items read."""

            def __init__(self, **kwargs):
                super().__init__(**kwargs)
                self.num_read = 0
                self.callback = self.count_num_read
                self.done_reading = asyncio.Future()

            async def count_num_read(self, data):
                self.num_read += 1
                if self.num_read == num_samples_per_topic:
                    self.done_reading.set_result(None)

        async with salobj.Domain() as domain:
            salinfo = salobj.SalInfo(domain, "Test", index=0)
            names = ["errorCode", "logLevel", "scalars"]
            fields = dict(errorCode="code", logLevel="level", scalars="int0")
            readers = [
                Reader(
                    salinfo=salinfo, name=name, sal_prefix="logevent_", max_history=1
                )
                for name in names
            ]
            writers = [
                salobj.topics.WriteTopic(
                    salinfo=salinfo, name=name, sal_prefix="logevent_"
                )
                for name in names
            ]
            for writer in writers:
                writer.field_name = fields[writer.name]
            t0 = time.monotonic()
            await salinfo.start()
            dt = time.monotonic() - t0
            # Assume that most of the time is reading history
            print(f"Took {dt:0.2f} seconds to obtain historical data")

            async def write_loop():
                for i in range(num_samples_per_topic):
                    for writer in writers:
                        setattr(writer.data, writer.field_name, i)
                        writer.put()
                    await asyncio.sleep(0)

            t0 = time.monotonic()
            write_task = asyncio.create_task(write_loop())
            read_tasks = [reader.done_reading for reader in readers]
            all_tasks = [write_task] + read_tasks
            try:
                await asyncio.wait_for(asyncio.gather(*all_tasks), 10)
            except asyncio.TimeoutError:
                self.assertTrue(write_task.done(), "Write tasks did not write all data")
                nread_list = [reader.num_read for reader in readers]
                self.fail(
                    f"One or more readers did not finish; "
                    f"read {nread_list} of {num_samples_per_topic} samples"
                )
            dt = time.monotonic() - t0
            total_values = num_samples_per_topic * len(readers)
            print(
                f"Took {dt:0.2f} seconds to read/write {total_values} samples: "
                f"{total_values/dt:0.0f} samples/sec"
            )

    async def test_command_speed(self):
        script_path = self.datadir / "topic_writer.py"
        process = await asyncio.create_subprocess_exec(
            str(script_path), str(self.index)
        )
        try:
            async with salobj.Domain() as domain, salobj.Remote(
                domain=domain, name="Test", index=self.index
            ) as remote:
                await remote.evt_summaryState.next(flush=False, timeout=60)
                t0 = time.monotonic()
                num_commands = 1000
                for i in range(num_commands):
                    await remote.cmd_fault.start(timeout=STD_TIMEOUT)
                dt = time.monotonic() - t0
                command_speed = num_commands / dt
                print(f"issued {command_speed:0.0f} fault commands/second")

                if verify is not None:
                    self.insert_measurement(
                        verify.Measurement(
                            "salobj.IssueCommands", command_speed * u.ct / u.second
                        )
                    )

        finally:
            if process.returncode is None:
                process.kill()

    async def test_read_speed(self):
        script_path = self.datadir / "topic_writer.py"
        process = await asyncio.create_subprocess_exec(
            str(script_path), str(self.index)
        )
        try:
            async with salobj.Domain() as domain, salobj.Remote(
                domain=domain, name="Test", index=self.index
            ) as remote:
                await salobj.set_summary_state(
                    remote=remote, state=salobj.State.ENABLED, settingsToApply="arrays",
                )

                num_samples = 10000

                # Wait for the first sample so we know the writer is running.
                data = await remote.tel_arrays.next(flush=False, timeout=STD_TIMEOUT)
                t0 = time.monotonic()
                for i in range(num_samples):
                    data = await remote.tel_arrays.next(
                        flush=False, timeout=STD_TIMEOUT
                    )
                dt = time.monotonic() - t0
                arrays_read_speed = num_samples / dt
                print(f"read {arrays_read_speed:0.0f} arrays samples/second")
                self.assertTrue(data.int0[0], num_samples)

                if verify is not None:
                    self.insert_measurement(
                        verify.Measurement(
                            "salobj.ReadTest_arrays",
                            arrays_read_speed * u.ct / u.second,
                        )
                    )

                await salobj.set_summary_state(
                    remote=remote, state=salobj.State.STANDBY,
                )
                await salobj.set_summary_state(
                    remote=remote,
                    state=salobj.State.ENABLED,
                    settingsToApply="logLevel",
                )

                # Wait for the first sample so we know the writer is running.
                data = await remote.evt_logLevel.next(flush=False, timeout=STD_TIMEOUT)
                t0 = time.monotonic()
                for i in range(num_samples):
                    data = await remote.evt_logLevel.next(
                        flush=False, timeout=STD_TIMEOUT
                    )
                dt = time.monotonic() - t0
                log_level_read_speed = num_samples / dt
                print(f"read {log_level_read_speed:0.0f} logLevel samples/second")
                self.assertTrue(data.level, num_samples)

                if verify is not None:
                    self.insert_measurement(
                        verify.Measurement(
                            "salobj.ReadTest_logLevel",
                            log_level_read_speed * u.ct / u.second,
                        )
                    )

                await salobj.set_summary_state(
                    remote=remote, state=salobj.State.OFFLINE
                )
        finally:
            if process.returncode is None:
                process.kill()

    async def test_write_speed(self):
        async with salobj.Controller(
            name="Test", index=self.index, do_callbacks=False
        ) as controller:

            num_samples = 10000

            t0 = time.monotonic()
            for i in range(num_samples):
                controller.tel_arrays.put()
                await asyncio.sleep(0)
            dt = time.monotonic() - t0
            arrays_write_speed = num_samples / dt
            print(f"wrote {arrays_write_speed:0.0f} arrays samples/second")

            if verify is not None:
                self.insert_measurement(
                    verify.Measurement(
                        "salobj.WriteTest_arrays", arrays_write_speed * u.ct / u.second
                    )
                )

            t0 = time.monotonic()
            for i in range(num_samples):
                controller.evt_logLevel.put()
                await asyncio.sleep(0)
            dt = time.monotonic() - t0
            log_level_write_speed = num_samples / dt
            print(f"wrote {log_level_write_speed:0.0f} logLevel samples/second")

            if verify is not None:
                self.insert_measurement(
                    verify.Measurement(
                        "salobj.WriteTest_logLevel",
                        log_level_write_speed * u.ct / u.second,
                    )
                )


if __name__ == "__main__":
    unittest.main()
