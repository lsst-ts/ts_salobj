import asyncio
import pathlib
import unittest

import pytest

try:
    import SALPY_Test
except ImportError:
    SALPY_Test = None
from lsst.ts import salobj

STD_TIMEOUT = 2  # timeout for fast operations (sec)

index_gen = salobj.index_generator()
CONFIG_DIR = pathlib.Path(__file__).resolve().parent.joinpath("data", "config")


class Harness:
    def __init__(self, initial_state):
        index = next(index_gen)
        salobj.set_random_lsst_dds_domain()
        self.csc = salobj.TestCsc(index=index, config_dir=CONFIG_DIR, initial_state=initial_state)
        self.remote = salobj.Remote(SALPY_Test, index)

    async def next_state(self, timeout=STD_TIMEOUT):
        state = await self.remote.evt_summaryState.next(flush=False, timeout=timeout)
        return state.summaryState


class SetSummaryStateTestCSe(unittest.TestCase):
    async def assert_state(self, harness, state, timeout=STD_TIMEOUT):
        actual_state = await harness.next_state(timeout=timeout)
        self.assertEqual(actual_state, actual_state)

    def test_transitions(self):
        """Test transitions between all states.
        """
        async def doit():
            for initial_state in salobj.State:
                if initial_state == salobj.State.OFFLINE:
                    continue
                    # the Test CSC cannot start in OFFLINE state
                for final_state in salobj.State:
                    if final_state == salobj.State.FAULT:
                        continue
                        # The function cannot go into FAULT state
                    with self.subTest(initial_state=initial_state, final_state=final_state):
                        print(f"initial_state={initial_state!r}; final_state={final_state!r}")
                        harness = Harness(initial_state=initial_state)
                        # wait for the initial state (meaning harness is ready)
                        await harness.remote.evt_summaryState.next(flush=False, timeout=10)
                        await salobj.set_summary_state(remote=harness.remote, state=final_state,
                                                       timeout=STD_TIMEOUT)
                        self.assertEqual(harness.csc.summary_state, final_state)
                        if initial_state in (salobj.State.FAULT, salobj.State.STANDBY) \
                                and final_state in (salobj.State.DISABLED, salobj.State.ENABLED):
                            # the start command should have been sent
                            self.assertIsNotNone(harness.csc.config)
                        else:
                            self.assertIsNone(harness.csc.config)
                        await asyncio.sleep(0.1)
                        state = harness.remote.evt_summaryState.get()
                        self.assertEqual(state.summaryState, final_state)

        asyncio.get_event_loop().run_until_complete(doit())

    def test_invalid_state(self):
        """Test transition to an invalid state."""
        async def doit():
            for initial_state in salobj.State:
                if initial_state == salobj.State.OFFLINE:
                    continue
                    # the Test CSC cannot start in OFFLINE state
                print(f"initial_state={initial_state!r}")
                harness = Harness(initial_state=initial_state)
                # wait for the initial state (meaning the harness is ready)
                await harness.remote.evt_summaryState.next(flush=False, timeout=10)
                for bad_final_state in (min(salobj.State) - 1, salobj.State.FAULT, max(salobj.State) + 1):
                    with self.assertRaises(ValueError):
                        await salobj.set_summary_state(remote=harness.remote, state=bad_final_state,
                                                       timeout=STD_TIMEOUT)

        asyncio.get_event_loop().run_until_complete(doit())


class EnableCscTestCase(unittest.TestCase):
    async def assert_state(self, harness, state, timeout=STD_TIMEOUT):
        actual_state = await harness.next_state(timeout=timeout)
        self.assertEqual(actual_state, actual_state)

    def test_enabled_noforce(self):
        async def doit():
            harness = Harness(initial_state=salobj.State.ENABLED)
            await self.assert_state(harness, salobj.State.ENABLED)
            with pytest.warns(DeprecationWarning):
                await salobj.enable_csc(harness.remote, force_config=False)
            with self.assertRaises(asyncio.TimeoutError):
                await harness.next_state(timeout=0.1)

        asyncio.get_event_loop().run_until_complete(doit())

    def test_disabled_noforce(self):
        async def doit():
            harness = Harness(initial_state=salobj.State.DISABLED)
            await self.assert_state(harness, salobj.State.DISABLED)
            with pytest.warns(DeprecationWarning):
                await salobj.enable_csc(harness.remote, force_config=False)
            await self.assert_state(harness, salobj.State.ENABLED)

        asyncio.get_event_loop().run_until_complete(doit())

    def test_standby_noforce(self):
        async def doit():
            harness = Harness(initial_state=salobj.State.STANDBY)
            await self.assert_state(harness, salobj.State.STANDBY)
            with pytest.warns(DeprecationWarning):
                await salobj.enable_csc(harness.remote, force_config=False)
            await self.assert_state(harness, salobj.State.DISABLED)
            await self.assert_state(harness, salobj.State.ENABLED)

        asyncio.get_event_loop().run_until_complete(doit())

    def test_fault_noforce(self):
        async def doit():
            harness = Harness(initial_state=salobj.State.FAULT)
            await self.assert_state(harness, salobj.State.FAULT)
            with pytest.warns(DeprecationWarning):
                await salobj.enable_csc(harness.remote, force_config=False)
            await self.assert_state(harness, salobj.State.STANDBY)
            await self.assert_state(harness, salobj.State.DISABLED)
            await self.assert_state(harness, salobj.State.ENABLED)

        asyncio.get_event_loop().run_until_complete(doit())

    def test_enabled_force(self):
        async def doit():
            harness = Harness(initial_state=salobj.State.ENABLED)
            await self.assert_state(harness, salobj.State.ENABLED)
            with pytest.warns(DeprecationWarning):
                await salobj.enable_csc(harness.remote, force_config=True)
            await self.assert_state(harness, salobj.State.DISABLED)
            await self.assert_state(harness, salobj.State.STANDBY)
            await self.assert_state(harness, salobj.State.DISABLED)
            await self.assert_state(harness, salobj.State.ENABLED)

        asyncio.get_event_loop().run_until_complete(doit())

    def test_disabled_or_fault_force(self):
        async def doit():
            for initial_state in (salobj.State.DISABLED, salobj.State.FAULT):
                with self.subTest(initial_state=initial_state):
                    harness = Harness(initial_state=initial_state)
                    await self.assert_state(harness, initial_state)
                    with pytest.warns(DeprecationWarning):
                        await salobj.enable_csc(harness.remote, force_config=True)
                    await self.assert_state(harness, salobj.State.STANDBY)
                    await self.assert_state(harness, salobj.State.DISABLED)
                    await self.assert_state(harness, salobj.State.ENABLED)

        asyncio.get_event_loop().run_until_complete(doit())

    def test_standby_force(self):
        async def doit():
            harness = Harness(initial_state=salobj.State.STANDBY)
            await self.assert_state(harness, salobj.State.STANDBY)
            with pytest.warns(DeprecationWarning):
                await salobj.enable_csc(harness.remote, force_config=True)
            await self.assert_state(harness, salobj.State.DISABLED)
            await self.assert_state(harness, salobj.State.ENABLED)

        asyncio.get_event_loop().run_until_complete(doit())


if __name__ == "__main__":
    unittest.main()
