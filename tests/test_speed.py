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
import collections
import contextlib
import os
import pathlib
import time
import unittest
import warnings
from collections.abc import AsyncGenerator
from unittest.mock import MagicMock

import astropy.units as u

from unittest.mock import MagicMock

from lsst.ts import salobj, utils


class MockVerify:
    Measurement = MagicMock()
    Metric = MagicMock()
    Job = MagicMock()


try:
    from lsst import verify  # type: ignore

    raise ImportError("TODO: re-enable verify when we decide to use Kafkfa")
except ImportError:
    warnings.warn(
        "verify could not be imported; measurements will not be uploaded", UserWarning
    )
    verify = MockVerify

# Long enough to perform any reasonable operation
# including starting a CSC or loading a script (seconds)
STD_TIMEOUT = 20

index_gen = utils.index_generator()


class SpeedTestCase(unittest.IsolatedAsyncioTestCase):
    """Measure the speed of salobj.

    These are not actually unit tests, but running them as tests
    makes sure they are run automatically and avoids bit rot.
    """

    @classmethod
    def setUpClass(cls) -> None:
        metrics = (
            verify.Metric(
                name="salobj.CreateClasses",
                description="The number of topic dataclasses salobj can create "
                "from ts_xml file, per second. "
                "This is measured by parsing the XML for MTM1M3 "
                "and then creating a dataclass for each topic.",
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
                name="salobj.ReadTest_forceActuatorData",
                description="The rate at which salobj can read Test_forceActuatorData samples. "
                "This is one of our largest topics.",
                unit=u.ct / u.second,
            ),
            verify.Metric(
                name="salobj.ReadTest_logLevel",
                description="The rate at which salobj can read Test_logevent_logLevel samples. "
                "This is one of our smallest topics.",
                unit=u.ct / u.second,
            ),
            verify.Metric(
                name="salobj.WriteTest_forceActuatorData",
                description="The rate at which salobj can write Test_forceActuatorData samples. "
                "This is one of our largest topics.",
                unit=u.ct / u.second,
            ),
            verify.Metric(
                name="salobj.WriteTest_logLevel",
                description="The rate at which salobj can write Test_logevent_logLevel samples. "
                "This is one of our smallest topics.",
                unit=u.ct / u.second,
            ),
        )
        cls.verify_job = verify.Job(metrics=metrics)  # type: ignore

    @classmethod
    def tearDownClass(cls) -> None:
        measurements_dir = pathlib.Path(__file__).resolve().parent / "measurements"
        cls.verify_job.write(measurements_dir / "speed.json")  # type: ignore

    def setUp(self) -> None:
        salobj.set_random_topic_subname()
        self.datadir = pathlib.Path(__file__).resolve().parent / "data"
        self.index = next(index_gen)

    def insert_measurement(self, measurement: verify.Measurement) -> None:
        measurement.metric = self.verify_job.metrics[measurement.metric_name]  # type: ignore
        self.verify_job.measurements.insert(measurement)  # type: ignore

    @contextlib.asynccontextmanager
    async def make_remote_and_topic_writer(
        self,
    ) -> AsyncGenerator[salobj.Remote, None]:
        """Make a remote and launch a topic writer in a subprocess.

        Return the remote.
        """
        script_path = self.datadir / "topic_writer.py"
        process = await asyncio.create_subprocess_exec(
            str(script_path), str(self.index)
        )
        try:
            async with salobj.Domain() as domain, salobj.Remote(
                domain=domain, name="Test", index=self.index
            ) as remote:
                yield remote
                await salobj.set_summary_state(
                    remote=remote, state=salobj.State.OFFLINE, timeout=STD_TIMEOUT
                )
                await asyncio.wait_for(process.wait(), timeout=STD_TIMEOUT)
        finally:
            if process.returncode is None:
                print("Warning: killing the topic writer")
                process.kill()

    async def test_class_creation_speed(self) -> None:
        """Test the speed of creating dataclasses for topics.

        Include the time required to parse the XML for the component.
        Use MTM1M3 because it has some of the largest topics.
        """
        topic_subname = os.environ["LSST_TOPIC_SUBNAME"]
        t0 = time.monotonic()
        component_info = salobj.ComponentInfo(
            topic_subname=topic_subname, name="MTM1M3"
        )
        data_classes = [
            topic_info.make_dataclass() for topic_info in component_info.topics.values()
        ]
        dt = time.monotonic() - t0
        ntopics = len(data_classes)
        creation_speed = ntopics / dt
        print(
            f"Created {creation_speed:0.1f} topic classes/sec ({ntopics} topic classes); "
            f"total duration {dt:0.2f} seconds."
        )
        self.insert_measurement(
            verify.Measurement("salobj.CreateClasses", creation_speed * u.ct / u.second)
        )

    async def test_command_speed(self) -> None:
        async with self.make_remote_and_topic_writer() as remote:
            await remote.evt_summaryState.next(flush=False, timeout=60)
            t0 = time.monotonic()
            num_commands = 1000
            for _ in range(num_commands):
                await remote.cmd_fault.start(timeout=STD_TIMEOUT)
            dt = time.monotonic() - t0
            command_speed = num_commands / dt
            print(
                f"Issued {command_speed:0.0f} fault commands/second ({num_commands} commands)"
            )

            self.insert_measurement(
                verify.Measurement(
                    "salobj.IssueCommands", command_speed * u.ct / u.second
                )
            )

    async def test_read_speed(self) -> None:
        async with self.make_remote_and_topic_writer() as remote:
            await salobj.set_summary_state(
                remote=remote,
                state=salobj.State.ENABLED,
                override="arrays",
                timeout=STD_TIMEOUT,
            )

            num_samples = 1000

            # Wait for the first sample so we know the writer is running
            # and to get an initial sequence number.
            data0 = await remote.tel_arrays.next(flush=False, timeout=STD_TIMEOUT)
            t0 = time.monotonic()
            for _ in range(num_samples):
                data = await remote.tel_arrays.next(flush=False, timeout=STD_TIMEOUT)
            dt = time.monotonic() - t0
            arrays_read_speed = num_samples / dt
            nlost = data.private_seqNum - data0.private_seqNum - num_samples
            print(
                f"Read {arrays_read_speed:0.0f} arrays samples/second "
                f"({num_samples} samples); "
                f"lost {nlost} samples once started; "
                f"lost {data0.int0[0]} samples during startup"
            )

            self.insert_measurement(
                verify.Measurement(
                    "salobj.ReadTest_forceActuatorData",
                    arrays_read_speed * u.ct / u.second,
                )
            )

            await salobj.set_summary_state(
                remote=remote, state=salobj.State.STANDBY, timeout=STD_TIMEOUT
            )
            await salobj.set_summary_state(
                remote=remote,
                state=salobj.State.ENABLED,
                override="logLevel",
                timeout=STD_TIMEOUT,
            )

            # Wait for the first logLevel sample. This is automatically
            # output by the Controller and probably has level=20
            # (unless data has been lost).
            await remote.evt_logLevel.next(flush=False, timeout=STD_TIMEOUT)
            # Wait for the next logLevel sample, which is the first one
            # output by the write loop (unless data has been lost).
            data0 = await remote.evt_logLevel.next(flush=False, timeout=STD_TIMEOUT)
            t0 = time.monotonic()
            for _ in range(num_samples):
                data = await remote.evt_logLevel.next(flush=False, timeout=STD_TIMEOUT)
            dt = time.monotonic() - t0
            log_level_read_speed = num_samples / dt
            nlost = data.private_seqNum - data0.private_seqNum - num_samples
            print(
                f"Read {log_level_read_speed:0.0f} logLevel samples/second "
                f"({num_samples} samples); "
                f"lost {nlost} samples once started; "
                f"lost {data0.level} samples during startup"
            )

            self.insert_measurement(
                verify.Measurement(
                    "salobj.ReadTest_logLevel",
                    log_level_read_speed * u.ct / u.second,
                )
            )

    async def test_write_speed(self) -> None:
        async with salobj.Controller(
            name="Test", index=self.index, do_callbacks=False
        ) as controller:
            num_samples = 1000

            t0 = time.monotonic()
            for _ in range(num_samples):
                await controller.tel_arrays.write()
            dt = time.monotonic() - t0
            arrays_write_speed = num_samples / dt
            print(
                f"Wrote {arrays_write_speed:0.0f} arrays samples/second ({num_samples} samples)"
            )

            self.insert_measurement(
                verify.Measurement(
                    "salobj.WriteTest_forceActuatorData",
                    arrays_write_speed * u.ct / u.second,
                )
            )

            t0 = time.monotonic()
            for _ in range(num_samples):
                await controller.evt_logLevel.write()
                await asyncio.sleep(0)
            dt = time.monotonic() - t0
            log_level_write_speed = num_samples / dt
            print(
                f"Wrote {log_level_write_speed:0.0f} logLevel samples/second ({num_samples} samples)"
            )

            self.insert_measurement(
                verify.Measurement(
                    "salobj.WriteTest_logLevel",
                    log_level_write_speed * u.ct / u.second,
                )
            )


if __name__ == "__main__":
    unittest.main()
