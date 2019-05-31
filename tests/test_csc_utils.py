import asyncio
import pathlib
import unittest

from lsst.ts import salobj

STD_TIMEOUT = 5  # timeout for fast operations (sec)
LONG_TIMEOUT = 30  # timeout for slow operations (sec)

index_gen = salobj.index_generator()
TEST_CONFIG_DIR = pathlib.Path(__file__).resolve().parent.joinpath("data", "config")


class Harness:
    def __init__(self, initial_state):
        index = next(index_gen)
        salobj.set_random_lsst_dds_domain()
        self.csc = salobj.TestCsc(index=index, config_dir=TEST_CONFIG_DIR, initial_state=initial_state)
        self.remote = salobj.Remote(domain=self.csc.domain, name="Test", index=index)

    async def next_state(self, timeout=STD_TIMEOUT):
        state = await self.remote.evt_summaryState.next(flush=False, timeout=timeout)
        return state.summaryState

    async def __aenter__(self):
        await self.csc.start_task
        await self.remote.start_task
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.remote.close()
        await self.csc.close()


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
                        async with Harness(initial_state=initial_state) as harness:
                            await harness.remote.evt_summaryState.next(flush=False, timeout=LONG_TIMEOUT)
                            await salobj.set_summary_state(remote=harness.remote, state=final_state,
                                                           settingsToApply="all_fields")
                            self.assertEqual(harness.csc.summary_state, final_state)
                            if initial_state in (salobj.State.FAULT, salobj.State.STANDBY) \
                                    and final_state in (salobj.State.DISABLED, salobj.State.ENABLED):
                                # The start command was sent
                                self.assertIsNotNone(harness.csc.config)
                                self.assertEqual(harness.csc.config.string0, "an arbitrary string")
                            elif initial_state in (salobj.State.DISABLED, salobj.State.ENABLED):
                                # the constructor default-configured the CSC
                                self.assertIsNotNone(harness.csc.config)
                                # default value hard-coded in schema/Test.yaml
                                self.assertEqual(harness.csc.config.string0, "default value for string0")
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
                async with Harness(initial_state=initial_state) as harness:
                    await harness.remote.evt_summaryState.next(flush=False, timeout=LONG_TIMEOUT)
                    for bad_final_state in (min(salobj.State) - 1, salobj.State.FAULT, max(salobj.State) + 1):
                        with self.assertRaises(ValueError):
                            await salobj.set_summary_state(remote=harness.remote, state=bad_final_state,
                                                           timeout=STD_TIMEOUT)

        asyncio.get_event_loop().run_until_complete(doit())


if __name__ == "__main__":
    unittest.main()
