#!/usr/bin/env python
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
import argparse

from lsst.ts import salobj


class MinimalSalobjController(salobj.Controller):
    """Minimal Test controller using ts_salobj, for unit tests.

    Responds to one command: setLogLevel.

    Parameters
    ----------
    index : `int`
        SAL index.
    initial_log_level : `int`
        Initial log level.
    """

    def __init__(self, index, initial_log_level):
        print(
            f"SalobjController: starting with index={index}, "
            f"initial_log_level={initial_log_level}"
        )
        super().__init__(name="Test", index=index, do_callbacks=False)
        self.cmd_setLogLevel.callback = self.do_setLogLevel
        self.evt_logLevel.set(level=initial_log_level)
        self.tel_scalars.set(int0=initial_log_level)

    @classmethod
    def make_from_cmd_line(cls):
        """Make an instance from the command line."""
        parser = argparse.ArgumentParser("Run a minimal Salobj Test controller")
        parser.add_argument("index", type=int, help="Script SAL Component index")
        parser.add_argument("initial_log_level", type=int, help="Initial log level")
        args = parser.parse_args()
        return MinimalSalobjController(
            index=args.index, initial_log_level=args.initial_log_level
        )

    @classmethod
    async def amain(cls):
        """Make and run a controller."""
        controller = cls.make_from_cmd_line()
        await controller.done_task

    async def start(self):
        """Finish construction."""
        await self.salinfo.start()
        print(
            f"SalobjController: writing initial logLevel.level={self.evt_logLevel.data.level} event"
        )
        self.evt_logLevel.put()

    def do_setLogLevel(self, data):
        print(
            f"SalobjController: read setLogLevel(cmdid={data.private_seqNum}; "
            f"level={data.level})"
        )

        print(
            f"SalobjController: writing logLevel={data.level} event "
            "and the same value in scalars.int0 telemetry"
        )
        self.evt_logLevel.set_put(level=data.level)
        self.tel_scalars.set_put(int0=data.level)
        if data.level == 0:
            print("SalobjController: quitting")
            asyncio.create_task(self.close())


if __name__ == "__main__":
    asyncio.run(MinimalSalobjController.amain())
    print("SalobjController: done")
