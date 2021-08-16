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
import logging
import os
import pathlib
import typing
import unittest

import numpy as np

from lsst.ts import salobj

# Long enough to perform any reasonable operation
# including starting a CSC or loading a script (seconds)
STD_TIMEOUT = 60
# Timeout for when we expect no new data (seconds).
NODATA_TIMEOUT = 0.1

np.random.seed(47)

index_gen = salobj.index_generator()
TEST_DATA_DIR = TEST_CONFIG_DIR = pathlib.Path(__file__).resolve().parent / "data"
TEST_CONFIG_DIR = TEST_DATA_DIR / "config"


class FailedCallbackCsc(salobj.TestCsc):
    """A CSC whose do_wait command raises a RuntimeError"""

    def __init__(self, *args: typing.Any, **kwargs: typing.Any) -> None:
        super().__init__(*args, **kwargs)
        self.exc_msg = "do_wait raised an exception on purpose"

    async def do_wait(self, data: salobj.BaseDdsDataType) -> None:
        raise RuntimeError(self.exc_msg)


class ControllerLoggingTestCase(
    salobj.BaseCscTestCase, unittest.IsolatedAsyncioTestCase
):
    def basic_make_csc(
        self,
        initial_state: typing.Union[salobj.State, int],
        config_dir: typing.Union[str, pathlib.Path, None],
        simulation_mode: int,
    ) -> salobj.BaseCsc:
        return FailedCallbackCsc(
            initial_state=initial_state,
            index=self.next_index(),
            config_dir=config_dir,
            simulation_mode=simulation_mode,
        )

    async def test_logging(self) -> None:
        async with self.make_csc(
            initial_state=salobj.State.ENABLED, config_dir=TEST_CONFIG_DIR
        ):
            logLevel = await self.remote.evt_logLevel.next(
                flush=False, timeout=STD_TIMEOUT
            )
            self.assertEqual(logLevel.level, logging.INFO)

            self.remote.evt_logMessage.flush()

            # We may still get one or two startup log messages
            # so read until we see the one we want.
            info_message = "test info message"
            self.csc.log.info(info_message)
            while True:
                msg = await self.remote.evt_logMessage.next(
                    flush=False, timeout=STD_TIMEOUT
                )
                if msg.message == info_message:
                    break
            self.assertEqual(msg.level, logging.INFO)
            self.assertEqual(msg.traceback, "")

            filepath = pathlib.Path(__file__)
            subpath = "/".join(filepath.parts[-2:])
            self.assertTrue(
                msg.filePath.endswith(subpath),
                f"{msg.filePath} does not end with {subpath!r}",
            )
            self.assertEqual(msg.functionName, "test_logging")
            self.assertGreater(msg.lineNumber, 0)
            self.assertEqual(msg.process, os.getpid())

            # Test a warning with an unencodable character
            encodable_message = "test warn message"
            warn_message = encodable_message + "\u2013"
            self.csc.log.warning(warn_message)
            msg = await self.remote.evt_logMessage.next(
                flush=False, timeout=STD_TIMEOUT
            )
            encodable_len = len(encodable_message)
            self.assertEqual(msg.message[0:encodable_len], encodable_message)
            self.assertEqual(msg.level, logging.WARNING)
            self.assertEqual(msg.traceback, "")

            with self.assertRaises(asyncio.TimeoutError):
                await self.remote.evt_logMessage.next(
                    flush=False, timeout=NODATA_TIMEOUT
                )

            await self.remote.cmd_setLogLevel.set_start(
                level=logging.ERROR, timeout=STD_TIMEOUT
            )

            logLevel = await self.remote.evt_logLevel.next(
                flush=False, timeout=STD_TIMEOUT
            )
            self.assertEqual(logLevel.level, logging.ERROR)

            info_message = "test info message"
            self.csc.log.info(info_message)
            with self.assertRaises(asyncio.TimeoutError):
                await self.remote.evt_logMessage.next(
                    flush=False, timeout=NODATA_TIMEOUT
                )

            warn_message = "test warn message"
            self.csc.log.warning(warn_message)
            with self.assertRaises(asyncio.TimeoutError):
                await self.remote.evt_logMessage.next(
                    flush=False, timeout=NODATA_TIMEOUT
                )

            with salobj.assertRaisesAckError():
                await self.remote.cmd_wait.set_start(duration=5, timeout=STD_TIMEOUT)

            msg = await self.remote.evt_logMessage.next(
                flush=False, timeout=STD_TIMEOUT
            )
            self.assertIn(self.csc.exc_msg, msg.traceback)
            self.assertIn("Traceback", msg.traceback)
            self.assertIn("RuntimeError", msg.traceback)
            self.assertEqual(msg.level, logging.ERROR)
            self.assertTrue(msg.filePath.endswith("topics/controller_command.py"))
            self.assertNotEqual(msg.functionName, "")
            self.assertGreater(msg.lineNumber, 0)
            self.assertEqual(msg.process, os.getpid())


if __name__ == "__main__":
    unittest.main()
