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

    Uses the Test API. Specify settingsToApply:

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

    def __init__(self):
        print("TopicWriter: starting")

        # Add limited support for unsupported commands
        # (just enough to make BaseCsc happy):
        for name in [
            "do_abortProfile",
            "do_abortRaiseM1M3",
            "do_applyAberrationForces",
            "do_applyAberrationForcesByBendingModes",
            "do_applyActiveOpticForces",
            "do_applyActiveOpticForcesByBendingModes",
            "do_applyOffsetForces",
            "do_applyOffsetForcesByMirrorForce",
            "do_clearAberrationForces",
            "do_clearActiveOpticForces",
            "do_clearOffsetForces",
            "do_disableHardpointChase",
            "do_disableHardpointCorrections",
            "do_enableHardpointChase",
            "do_enableHardpointCorrections",
            "do_enterEngineering",
            "do_exitEngineering",
            "do_forceActuatorBumpTest",
            "do_killForceActuatorBumpTest",
            "do_lowerM1M3",
            "do_modbusTransmit",
            "do_moveHardpointActuators",
            "do_positionM1M3",
            "do_programILC",
            "do_raiseM1M3",
            "do_resetPID",
            "do_runMirrorForceProfile",
            "do_stopHardpointMotion",
            "do_testAir",
            "do_testForceActuator",
            "do_testHardpoint",
            "do_translateM1M3",
            "do_turnAirOff",
            "do_turnAirOn",
            "do_turnLightsOff",
            "do_turnLightsOn",
            "do_turnPowerOff",
            "do_turnPowerOn",
            "do_updatePID",
        ]:
            setattr(self, name, self.reject_command)

        super().__init__(name="MTM1M3", index=0)
        self.write_task = utils.make_done_future()

    async def reject_command(self, data):
        raise salobj.ExpectedError("Not supported")

    async def handle_summary_state(self):
        if self.summary_state == salobj.State.ENABLED:
            if self.write_task.done():
                self.write_task = asyncio.create_task(self.write_forceActuatorData())
        else:
            self.write_task.cancel()

    async def write_forceActuatorData(self):
        print("TopicWriter: writing")
        while True:
            self.tel_forceActuatorData.put()
            await asyncio.sleep(0)


if __name__ == "__main__":
    asyncio.run(TopicWriter.amain(index=None))
    print("TopicWriter: done")
