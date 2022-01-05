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
import contextlib
import pathlib
import time
import typing
import unittest

from lsst.ts import salobj

# Long enough to perform any reasonable operation
# including starting a CSC or loading a script (seconds)
STD_TIMEOUT = 60

index_gen = salobj.index_generator()


class SpeedTestCase(unittest.IsolatedAsyncioTestCase):
    """Measure the speed of salobj.

    These are not actually unit tests, but running them as tests
    makes sure they are run automatically and avoids bit rot.
    """

    def setUp(self) -> None:
        salobj.set_random_lsst_dds_partition_prefix()
        self.datadir = pathlib.Path(__file__).resolve().parent / "data"

    @contextlib.asynccontextmanager
    async def make_remote_and_topic_writer(
        self,
    ) -> typing.AsyncGenerator[salobj.Remote, None]:
        """Make a remote and launch a topic writer in a subprocess.

        Return the remote.
        """
        script_path = self.datadir / "topic_writer.py"
        process = await asyncio.create_subprocess_exec(str(script_path))
        try:
            async with salobj.Domain() as domain, salobj.Remote(
                domain=domain, name="MTM1M3"
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

    async def test_read_speed(self) -> None:
        async with self.make_remote_and_topic_writer() as remote:
            await salobj.set_summary_state(
                remote=remote,
                state=salobj.State.ENABLED,
                timeout=STD_TIMEOUT,
            )

            num_samples = 1000

            # Wait for the first sample so we know the writer is running.
            data = await remote.tel_forceActuatorData.next(
                flush=False, timeout=STD_TIMEOUT
            )
            initial_seqNum = data.private_seqNum
            t0 = time.monotonic()
            for i in range(num_samples):
                data = await remote.tel_forceActuatorData.next(
                    flush=False, timeout=STD_TIMEOUT
                )
            dt = time.monotonic() - t0
            read_speed = num_samples / dt
            nlost = (data.private_seqNum - initial_seqNum) - num_samples
            print(
                f"Read {read_speed:0.0f} samples/second "
                f"({num_samples} samples); "
                f"lost {nlost} samples"
            )

    async def test_write_speed(self) -> None:
        async with salobj.Controller(name="MTM1M3", do_callbacks=False) as controller:

            num_samples = 1000

            t0 = time.monotonic()
            for i in range(num_samples):
                controller.tel_forceActuatorData.put()
                # Free the event loop, since writers usually should.
                await asyncio.sleep(0)
            dt = time.monotonic() - t0
            write_speed = num_samples / dt
            print(f"Wrote {write_speed:0.0f} samples/second ({num_samples} samples)")
