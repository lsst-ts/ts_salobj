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

import asyncio
import contextlib
import itertools
import pathlib
import unittest

import asynctest

from lsst.ts import salobj

STD_TIMEOUT = 5  # timeout for fast operations (sec)
LONG_TIMEOUT = 30  # timeout for slow operations (sec)

index_gen = salobj.index_generator()
TEST_CONFIG_DIR = pathlib.Path(__file__).resolve().parent.joinpath("data", "config")


class SetSummaryStateTestCSe(asynctest.TestCase):
    @contextlib.asynccontextmanager
    async def make_csc(self, initial_state):
        """Construct a CSC and Remote and wait for them to start.

        Sets attributes self.csc and self.remote.

        Parameters
        ----------
        initial_state : `State` or `int`
            The initial state of the CSC.
        """
        index = next(index_gen)
        salobj.set_random_lsst_dds_domain()
        self.csc = salobj.TestCsc(index=index, config_dir=TEST_CONFIG_DIR, initial_state=initial_state)
        self.remote = salobj.Remote(domain=self.csc.domain, name="Test", index=index)
        await asyncio.gather(self.csc.start_task, self.remote.start_task)
        try:
            yield
        finally:
            await self.remote.close()
            await self.csc.close()

    async def test_set_summary_state_valid(self):
        """Test set_summary_state with valid states."""
        for initial_state, final_state in itertools.product(salobj.State, salobj.State):
            if initial_state == salobj.State.OFFLINE:
                # TestCsc cannot start in OFFLINE state.
                continue
            if final_state == salobj.State.FAULT:
                # set_summary_state cannot transition to FAULT state.
                continue
            with self.subTest(initial_state=initial_state, final_state=final_state):
                await self.check_set_summary_state(initial_state=initial_state,
                                                   final_state=final_state)

    async def test_set_summary_state_invalid_state(self):
        """Test set_summary_state with invalid states."""
        for initial_state in salobj.State:
            if initial_state == salobj.State.OFFLINE:
                # TestCsc cannot start in OFFLINE state.
                continue
            async with self.make_csc(initial_state=initial_state):
                for bad_final_state in (min(salobj.State) - 1, salobj.State.FAULT, max(salobj.State) + 1):
                    with self.subTest(initial_state=initial_state, bad_final_state=bad_final_state):
                        with self.assertRaises(ValueError):
                            await salobj.set_summary_state(remote=self.remote, state=bad_final_state,
                                                           timeout=STD_TIMEOUT)

    async def check_set_summary_state(self, initial_state, final_state):
        """Check set_summary_state for valid state transitions.

        Parameters
        ----------
        initial_state : `State`
            Initial summary state.
        final_state : `State`
            Final summary state.
        """
        async with self.make_csc(initial_state=initial_state):
            self.assertEqual(self.csc.summary_state, initial_state)
            data = await self.remote.evt_summaryState.next(flush=False,
                                                           timeout=STD_TIMEOUT)
            self.assertEqual(data.summaryState, initial_state)

            states = await salobj.set_summary_state(remote=self.remote,
                                                    state=final_state,
                                                    settingsToApply="all_fields")
            self.assertEqual(states[0], initial_state)
            self.assertEqual(states[-1], final_state)
            self.assertEqual(self.csc.summary_state, final_state)
            if initial_state in (salobj.State.FAULT, salobj.State.STANDBY) \
                    and final_state in (salobj.State.DISABLED, salobj.State.ENABLED):
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
                data = await self.remote.evt_summaryState.next(flush=False,
                                                               timeout=STD_TIMEOUT)
                self.assertEqual(data.summaryState, expected_state)


if __name__ == "__main__":
    unittest.main()
