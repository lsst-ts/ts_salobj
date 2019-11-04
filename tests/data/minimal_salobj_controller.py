#!/usr/bin/env python
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
        print(f"SalobjController: starting with index={index}, "
              f"initial_log_level={initial_log_level}")
        super().__init__(name="Test", index=index, do_callbacks=False)
        self.cmd_setLogLevel.callback = self.do_setLogLevel
        self.evt_logLevel.set(level=initial_log_level)
        self.tel_scalars.set(int0=initial_log_level)

    @classmethod
    def make_from_cmd_line(cls):
        """Make an instance from the command line.
        """
        parser = argparse.ArgumentParser(f"Run a minimal Salobj Test controller")
        parser.add_argument("index", type=int, help="Script SAL Component index")
        parser.add_argument("initial_log_level", type=int, help="Initial log level")
        args = parser.parse_args()
        return MinimalSalobjController(index=args.index, initial_log_level=args.initial_log_level)

    @classmethod
    async def amain(cls):
        """Make and run a controller.
        """
        controller = cls.make_from_cmd_line()
        await controller.done_task

    async def start(self):
        """Finish construction."""
        await self.salinfo.start()
        print(f"SalobjController: outputting initial logLevel {self.evt_logLevel.data.level} "
              "and the same value in telemetry scalars.int0")
        self.evt_logLevel.put()
        self.tel_scalars.put()

    def do_setLogLevel(self, data):
        print(f"SalobjController: read setLogLevel(cmdid={data.private_seqNum}; "
              f"level={data.level})")

        print(f"SalobjController: writing logLevel={data.level}"
              "and the same value in telemetry scalars.int0")
        self.evt_logLevel.set_put(level=data.level)
        self.tel_scalars.set_put(int0=data.level)
        if data.level == 0:
            print("SalobjController: quitting")
            asyncio.create_task(self.close())


if __name__ == "__main__":
    asyncio.run(MinimalSalobjController.amain())
    print("SalobjController: done")
