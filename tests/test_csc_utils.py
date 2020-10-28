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

import itertools
import pathlib
import unittest

import asynctest

from lsst.ts import salobj

# Long enough to perform any reasonable operation
# including starting a CSC or loading a script (seconds)
STD_TIMEOUT = 60

index_gen = salobj.index_generator()
TEST_CONFIG_DIR = pathlib.Path(__file__).resolve().parent / "data" / "config"


class SetSummaryStateTestCSe(salobj.BaseCscTestCase, asynctest.TestCase):
    def basic_make_csc(self, initial_state, config_dir, simulation_mode):
        return salobj.TestCsc(
            self.next_index(),
            initial_state=initial_state,
            config_dir=config_dir,
            simulation_mode=simulation_mode,
        )

    async def test_set_summary_state_valid(self):
        """Test set_summary_state with valid states."""
        for initial_state, final_state in itertools.product(salobj.State, salobj.State):
            if initial_state in (salobj.State.OFFLINE, salobj.State.FAULT):
                # TestCsc cannot start in OFFLINE or FAULT state.
                continue
            if final_state == salobj.State.FAULT:
                # set_summary_state cannot transition to FAULT state.
                continue
            with self.subTest(initial_state=initial_state, final_state=final_state):
                await self.check_set_summary_state(
                    initial_state=initial_state, final_state=final_state
                )

    async def test_set_summary_state_invalid_state(self):
        """Test set_summary_state with invalid states."""
        for initial_state in salobj.State:
            if initial_state in (salobj.State.OFFLINE, salobj.State.FAULT):
                # TestCsc cannot start in OFFLINE or FAULT state.
                continue
            async with self.make_csc(
                initial_state=initial_state, config_dir=TEST_CONFIG_DIR
            ):
                for bad_final_state in (
                    min(salobj.State) - 1,
                    salobj.State.FAULT,
                    max(salobj.State) + 1,
                ):
                    with self.subTest(
                        initial_state=initial_state, bad_final_state=bad_final_state
                    ):
                        with self.assertRaises(ValueError):
                            await salobj.set_summary_state(
                                remote=self.remote,
                                state=bad_final_state,
                                timeout=STD_TIMEOUT,
                            )

    async def check_set_summary_state(self, initial_state, final_state):
        """Check set_summary_state for valid state transitions.

        Parameters
        ----------
        initial_state : `State`
            Initial summary state.
        final_state : `State`
            Final summary state.
        """
        async with self.make_csc(
            initial_state=initial_state, config_dir=TEST_CONFIG_DIR
        ):
            self.assertEqual(self.csc.summary_state, initial_state)
            await self.assert_next_summary_state(initial_state)

            states = await salobj.set_summary_state(
                remote=self.remote,
                state=final_state,
                settingsToApply="all_fields",
                timeout=STD_TIMEOUT,
            )
            self.assertEqual(states[0], initial_state)
            self.assertEqual(states[-1], final_state)
            self.assertEqual(self.csc.summary_state, final_state)
            if initial_state in (
                salobj.State.FAULT,
                salobj.State.STANDBY,
            ) and final_state in (salobj.State.DISABLED, salobj.State.ENABLED):
                # The start command was sent, so check that the configuration
                # is as specified to the set_summary_state function.
                self.assertIsNotNone(self.csc.config)
                self.assertEqual(self.csc.config.string0, "an arbitrary string")
            elif initial_state in (salobj.State.DISABLED, salobj.State.ENABLED):
                # The start command was not sent, so check that
                # the configuration is the default.
                self.assertIsNotNone(self.csc.config)
                self.assertEqual(self.csc.config.string0, "default value for string0")
            else:
                self.assertIsNone(self.csc.config)
            # The initial state was read by the remote in set_summary_state
            # (and in the test), so only check for subsequent states.
            for expected_state in states[1:]:
                await self.assert_next_summary_state(expected_state)

            # If settingsToApply should be applied and the CSC
            # can be restored to its initial state, try again with
            # settingsToApply = None and "".
            # Both of these should result in the default configuration.
            if initial_state == salobj.State.STANDBY and final_state in (
                salobj.State.DISABLED,
                salobj.State.ENABLED,
            ):
                # Try again with settingsToApply=None and settingsToApply=""
                for settingsToApply in (None, ""):
                    with self.subTest(settingsToApply=settingsToApply):
                        # Reset state to initial state
                        states = await salobj.set_summary_state(
                            remote=self.remote, state=initial_state, timeout=STD_TIMEOUT
                        )
                        # Make sure all summaryState events are seen,
                        # so the next call to set_summary_state
                        # starts with the correct state.
                        for expected_state in states[1:]:
                            await self.assert_next_summary_state(expected_state)
                        # Set state to final state
                        states = await salobj.set_summary_state(
                            remote=self.remote,
                            state=final_state,
                            settingsToApply=settingsToApply,
                            timeout=STD_TIMEOUT,
                        )
                        # Make sure all summaryState events are seen
                        # so the next call to set_summary_state
                        # starts with the correct state.
                        for expected_state in states[1:]:
                            await self.assert_next_summary_state(expected_state)
                        self.assertEqual(
                            self.csc.config.string0, "default value for string0"
                        )


if __name__ == "__main__":
    unittest.main()
