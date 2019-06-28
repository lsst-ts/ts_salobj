#!/usr/bin/env python
import argparse
import asyncio

import SALPY_Test

SAL__CMD_COMPLETE = 303


class MinimalSALPYController:
    def __init__(self, index, initial_log_level):
        print(f"SALPYController: starting with index={index}, "
              f"initial_log_level={initial_log_level}")
        self.manager = SALPY_Test.SAL_Test(index)
        self.manager.setDebugLevel(0)
        self.manager.salEventPub("Test_logevent_logLevel")
        self.manager.salTelemetryPub("Test_scalars")
        self.manager.salProcessor("Test_command_setLogLevel")
        self.done_task = asyncio.ensure_future(self.run(initial_log_level=initial_log_level))

    async def run(self, initial_log_level):
        setLogLevel_data = SALPY_Test.Test_command_setLogLevelC()
        logLevel_data = SALPY_Test.Test_logevent_logLevelC()
        scalars_data = SALPY_Test.Test_scalarsC()
        print(f"SALPYController: outputting initial logLevel {initial_log_level} "
              "and the same value in telemetry scalars.int0")
        logLevel_data.level = initial_log_level
        self.manager.logEvent_logLevel(logLevel_data, 1)
        scalars_data.int0 = initial_log_level
        self.manager.putSample_scalars(scalars_data)

        while True:
            while True:
                cmdid = self.manager.acceptCommand_setLogLevel(setLogLevel_data)
                if cmdid > 0:
                    break
                elif cmdid < 0:
                    raise RuntimeError(f"SALPYController: error reading setLogLevel command; "
                                       "cmdid={cmdid}")
                await asyncio.sleep(0.1)
            print(f"SALPYController: read setLogLevel(cmdid={cmdid}; "
                  f"level={setLogLevel_data.level})")
            self.manager.ackCommand_setLogLevel(cmdid, SAL__CMD_COMPLETE, 0, "")
            await asyncio.sleep(0.001)

            print(f"SALPYController: writing logLevel={logLevel_data.level}"
                  "and the same value in telemetry scalars.int0")
            logLevel_data.level = setLogLevel_data.level
            scalars_data.int0 = setLogLevel_data.level
            self.manager.logEvent_logLevel(logLevel_data, 1)
            self.manager.putSample_scalars(scalars_data)
            await asyncio.sleep(0.001)
            if setLogLevel_data.level == 0:
                print("SALPYController: quitting")
                break

        # make sure SALPY has time to send the final logLevel event
        await asyncio.sleep(0.1)
        self.manager.salShutdown()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(f"Run a minimal SALPY Test controller")
    parser.add_argument("index", type=int, help="Script SAL Component index")
    parser.add_argument("initial_log_level", type=int, help="Initial log level")
    args = parser.parse_args()
    controller = MinimalSALPYController(index=args.index, initial_log_level=args.initial_log_level)
    asyncio.get_event_loop().run_until_complete(controller.done_task)
    print("SALPYController: done")
