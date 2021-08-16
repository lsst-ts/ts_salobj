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

import pathlib
import typing
import unittest

import numpy as np

from lsst.ts import salobj

np.random.seed(47)


class BasicCscCommander(salobj.TestCscCommander):
    """A version of `TestCscCommander` that adds a custom "echo" command.

    This class adds a custom command ("echo") that is not supported by
    the Test CSC. This includes help for the command.

    Inherit from `TestCscCommander` instead of `CscCommander` in order to
    test a custom override of a command supported by the Test CSC
    ("setArrays") and to test hiding unsupported generic commands.
    """

    def __init__(self, **kwargs: typing.Any) -> None:
        super().__init__(**kwargs)
        self.help_dict["echo"] = "any  # echo arguments, space-separated"

    def do_echo(self, args: str) -> None:
        """Output the arguments."""
        self.output(" ".join(args))


class CscCommanderTestCase(salobj.BaseCscTestCase, unittest.IsolatedAsyncioTestCase):
    def basic_make_csc(
        self,
        initial_state: typing.Union[salobj.State, int],
        config_dir: typing.Union[str, pathlib.Path, None],
        simulation_mode: int,
    ) -> salobj.BaseCsc:
        index = self.next_index()
        self.commander = BasicCscCommander(index=index)
        self.addAsyncCleanup(self.commander.close)
        self.commander.testing = True

        return salobj.TestCsc(
            index=index,
            initial_state=initial_state,
            config_dir=config_dir,
            simulation_mode=simulation_mode,
        )

    async def test_basics(self) -> None:
        async with self.make_csc(initial_state=salobj.State.STANDBY):
            await self.commander.start()
            await self.assert_next_summary_state(salobj.State.STANDBY)

            # Test a command that will fail because the CSC is not enabled
            with salobj.assertRaisesAckError(ack=salobj.SalRetCode.CMD_FAILED):
                await self.commander.run_command(
                    f"wait {salobj.SalRetCode.CMD_COMPLETE} 5"
                )
            # Test some standard CSC commands
            await self.commander.run_command("start")
            await self.assert_next_summary_state(salobj.State.DISABLED)
            await self.commander.run_command("enable")
            await self.assert_next_summary_state(salobj.State.ENABLED)
            t0 = salobj.current_tai()
            wait_time = 2  # seconds
            await self.commander.run_command(
                f"wait {salobj.SalRetCode.CMD_COMPLETE} {wait_time}"
            )
            dt = salobj.current_tai() - t0
            # The margin of 0.2 compensates for the clock in Docker on macOS
            # not being strictly monotonic.
            self.assertGreaterEqual(dt, wait_time - 0.2)
            self.commander.output_queue.clear()

            # Test the help command
            await self.commander.run_command("help")
            self.assertEqual(len(self.commander.output_queue), 1)
            help_str = self.commander.output_queue.pop()
            for substr in ("standby", "exitControl", "echo", "help"):
                self.assertIn(substr, help_str)
            for hidden_command in ("abort", "enterControl", "setValue"):
                self.assertNotIn(hidden_command, help_str)

            # Test TestCscCommander's custom setArrays command handler
            # Too many values
            with self.assertRaises(RuntimeError):
                await self.commander.run_command("setArrays int0=1,2,3,4,5,6")
            # No such field
            with self.assertRaises(RuntimeError):
                await self.commander.run_command("setArrays no_such_field=1,2,3,4,5,6")
            # A valid command
            await self.commander.run_command("setArrays boolean0=0,1 int0=-2,33,42")
            for topic in self.csc.evt_arrays, self.csc.tel_arrays:
                self.assertEqual(
                    topic.data.boolean0, [False, True, False, False, False]
                )
                self.assertEqual(topic.data.int0, [-2, 33, 42, 0, 0])

            # Test bool argument handling. Set all other fields to 0
            # and ignore them.
            scalar_fields = [
                field
                for field in self.csc.cmd_setScalars.DataType().get_vars().keys()
                if not field.startswith("private_") and field != "TestID"
            ]
            bool_index = scalar_fields.index("boolean0")
            n_scalar_fields = len(scalar_fields)
            for good_bool_arg, value in (
                ("0", False),
                ("f", False),
                ("F", False),
                ("FaLsE", False),
                ("1", True),
                ("t", True),
                ("T", True),
                ("tRuE", True),
            ):
                args = ["0"] * n_scalar_fields
                args[bool_index] = good_bool_arg
                await self.commander.run_command("setScalars " + " ".join(args))
                self.assertEqual(self.csc.evt_scalars.data.boolean0, value)

            for bad_bool_arg in ("2", "fail", "falsely"):
                args = ["0"] * n_scalar_fields
                args[bool_index] = bad_bool_arg
                with self.assertRaises(ValueError):
                    await self.commander.run_command("setScalars " + " ".join(args))

            # Test BasicCscCommander's "echo" command
            self.commander.output_queue.clear()
            argstr = "1   2.3   arbitrary   text"
            await self.commander.run_command(f"echo {argstr}")
            self.assertEqual(len(self.commander.output_queue), 1)
            expected_output = " ".join(argstr.split())
            output_str = self.commander.output_queue.pop()
            self.assertEqual(output_str, expected_output)


if __name__ == "__main__":
    unittest.main()
