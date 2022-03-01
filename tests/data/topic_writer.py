#!/usr/bin/env python

# type: ignore

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

from lsst.ts import utils
from lsst.ts import salobj


class TopicWriter(salobj.BaseCsc):
    """A simple CSC that writes samples as fast as possible.

    Uses the Test API. Specify override:

    * logLevel: to write logLevel events when enabled
    * arrays: to write arrays telemetry when enabled

    Accepts and ignores the fault command (in ANY state),
    to allow testing the speed of commands.
    I suggest not enabling the CSC to test command speed,
    since that will make it busy writing topics.

    Parameters
    ----------
    index : `int`
        SAL index.
    """

    valid_simulation_modes = [0]
    version = "none"

    def __init__(self, index):
        print(f"TopicWriter: starting with index={index}")
        for cmd in ("setArrays", "setScalars", "wait"):
            setattr(self, f"do_{cmd}", self._unsupported_command)
        self.write_task = utils.make_done_future()
        self.is_log_level = False
        super().__init__(name="Test", index=index)

    async def do_fault(self, data):
        """This command does nothing, to allow timing command overhead."""
        pass

    async def begin_start(self, data):
        if data.configurationOverride == "logLevel":
            self.is_log_level = True
        elif data.configurationOverride == "arrays":
            self.is_log_level = False
        else:
            raise salobj.ExpectedError(
                f"data.configurationOverride={data.configurationOverride} must be logLevel or arrays"
            )
        print(f"TopicWriter: writing {data.configurationOverride}")

    async def handle_summary_state(self):
        if self.summary_state == salobj.State.ENABLED:
            if self.write_task.done():
                if self.is_log_level:
                    self.write_task = asyncio.create_task(self.write_log_level())
                else:
                    self.write_task = asyncio.create_task(self.write_arrays())
        else:
            self.write_task.cancel()

    async def write_arrays(self):
        i = 0
        while True:
            self.tel_arrays.data.int0[0] = i
            await self.tel_arrays.write()
            i += 1
            # Awaiting write doesn't release the event loop
            # (which surprises me) so release it once in awhile
            # Pick values that do not slow down the read results
            # very much and don't lose many initial samples.
            if i % 20 == 0:
                await asyncio.sleep(0.0001)

    async def write_log_level(self):
        i = 0
        while True:
            await self.evt_logLevel.set_write(level=i)
            i += 1
            # Awaiting write doesn't release the event loop
            # (which surprises me) so release it once in awhile.
            # Pick values that do not slow down the read results
            # very much and don't lose many initial samples.
            if i % 20 == 0:
                await asyncio.sleep(0.0001)

    async def _unsupported_command(self, data):
        raise salobj.ExpectedError("Not supported")


if __name__ == "__main__":
    asyncio.run(TopicWriter.amain(index=True))
    print("TopicWriter: done")
