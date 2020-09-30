#!/usr/bin/env python
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

import argparse
import asyncio

import SALPY_Test

SAL__CMD_COMPLETE = 303


class MinimalSALPYController:
    def __init__(self, index, initial_log_level):
        print(
            f"SALPYController: starting with index={index}, "
            f"initial_log_level={initial_log_level}"
        )
        self.manager = SALPY_Test.SAL_Test(index)
        self.manager.setDebugLevel(0)
        self.manager.salEventPub("Test_logevent_logLevel")
        self.manager.salTelemetryPub("Test_scalars")
        self.manager.salProcessor("Test_command_setLogLevel")
        self.initial_log_level = initial_log_level

    @classmethod
    def make_from_cmd_line(cls):
        """Make an instance from the command line.
        """
        parser = argparse.ArgumentParser("Run a minimal SALPY Test controller")
        parser.add_argument("index", type=int, help="Script SAL Component index")
        parser.add_argument("initial_log_level", type=int, help="Initial log level")
        args = parser.parse_args()
        return MinimalSALPYController(
            index=args.index, initial_log_level=args.initial_log_level
        )

    @classmethod
    async def amain(cls):
        """Make and run a controller.
        """
        controller = cls.make_from_cmd_line()
        await controller.run()

    async def run(self):
        setLogLevel_data = SALPY_Test.Test_command_setLogLevelC()
        logLevel_data = SALPY_Test.Test_logevent_logLevelC()
        scalars_data = SALPY_Test.Test_scalarsC()
        print(
            f"SALPYController: writing initial logLevel.level={self.initial_log_level} event"
        )
        logLevel_data.level = self.initial_log_level
        self.manager.logEvent_logLevel(logLevel_data, 1)

        while True:
            while True:
                cmdid = self.manager.acceptCommand_setLogLevel(setLogLevel_data)
                if cmdid > 0:
                    break
                elif cmdid < 0:
                    raise RuntimeError(
                        f"SALPYController: error reading setLogLevel command; cmdid={cmdid}"
                    )
                await asyncio.sleep(0.1)
            print(
                f"SALPYController: read setLogLevel(cmdid={cmdid}; "
                f"level={setLogLevel_data.level})"
            )
            self.manager.ackCommand_setLogLevel(cmdid, SAL__CMD_COMPLETE, 0, "")
            await asyncio.sleep(0.001)

            print(
                f"SALPYController: writing logLevel={logLevel_data.level} event "
                "and the same value in scalars.int0 telemetry"
            )
            logLevel_data.level = setLogLevel_data.level
            scalars_data.int0 = setLogLevel_data.level
            self.manager.logEvent_logLevel(logLevel_data, 1)
            self.manager.putSample_scalars(scalars_data)
            await asyncio.sleep(0.001)
            if setLogLevel_data.level == 0:
                print("SALPYController: quitting")
                break

        # Give remotes time to read final DDS messages before closing
        # the domain participant.
        await asyncio.sleep(1)
        self.manager.salShutdown()


if __name__ == "__main__":
    asyncio.run(MinimalSALPYController.amain())
    print("SALPYController: done")
