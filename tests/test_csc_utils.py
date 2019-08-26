import asyncio
import pathlib
import unittest

from lsst.ts import salobj

PRINT_TEST_CASES = False  # set True to print test cases

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

    async def __aenter__(self):
        await self.csc.start_task
        await self.remote.start_task
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.remote.close()
        await self.csc.close()


def print_test_cases():
    """Print code for testing test_set_summary_state."""
    for initial_state in salobj.State:
        if initial_state == salobj.State.OFFLINE:
            # TestCsc cannot start in OFFLINE state
            continue
        for final_state in salobj.State:
            if final_state == salobj.State.FAULT:
                # set_summary_state cannot transition to FAULT state
                continue
            initial_name = initial_state.name.lower()
            final_name = final_state.name.lower()
            print(f"""    def test_{initial_name}_to_{final_name}(self):
        async def doit():
            await self.check_set_summary_state(initial_state=salobj.State.{initial_state.name},
                                               final_state=salobj.State.{final_state.name})

        asyncio.get_event_loop().run_until_complete(doit())
""")


class SetSummaryStateTestCSe(unittest.TestCase):

    def test_standby_to_offline(self):
        async def doit():
            await self.check_set_summary_state(initial_state=salobj.State.STANDBY,
                                               final_state=salobj.State.OFFLINE)

        asyncio.get_event_loop().run_until_complete(doit())

    def test_standby_to_standby(self):
        async def doit():
            await self.check_set_summary_state(initial_state=salobj.State.STANDBY,
                                               final_state=salobj.State.STANDBY)

        asyncio.get_event_loop().run_until_complete(doit())

    def test_standby_to_disabled(self):
        async def doit():
            await self.check_set_summary_state(initial_state=salobj.State.STANDBY,
                                               final_state=salobj.State.DISABLED)

        asyncio.get_event_loop().run_until_complete(doit())

    def test_standby_to_enabled(self):
        async def doit():
            await self.check_set_summary_state(initial_state=salobj.State.STANDBY,
                                               final_state=salobj.State.ENABLED)

        asyncio.get_event_loop().run_until_complete(doit())

    def test_disabled_to_offline(self):
        async def doit():
            await self.check_set_summary_state(initial_state=salobj.State.DISABLED,
                                               final_state=salobj.State.OFFLINE)

        asyncio.get_event_loop().run_until_complete(doit())

    def test_disabled_to_standby(self):
        async def doit():
            await self.check_set_summary_state(initial_state=salobj.State.DISABLED,
                                               final_state=salobj.State.STANDBY)

        asyncio.get_event_loop().run_until_complete(doit())

    def test_disabled_to_disabled(self):
        async def doit():
            await self.check_set_summary_state(initial_state=salobj.State.DISABLED,
                                               final_state=salobj.State.DISABLED)

        asyncio.get_event_loop().run_until_complete(doit())

    def test_disabled_to_enabled(self):
        async def doit():
            await self.check_set_summary_state(initial_state=salobj.State.DISABLED,
                                               final_state=salobj.State.ENABLED)

        asyncio.get_event_loop().run_until_complete(doit())

    def test_enabled_to_offline(self):
        async def doit():
            await self.check_set_summary_state(initial_state=salobj.State.ENABLED,
                                               final_state=salobj.State.OFFLINE)

        asyncio.get_event_loop().run_until_complete(doit())

    def test_enabled_to_standby(self):
        async def doit():
            await self.check_set_summary_state(initial_state=salobj.State.ENABLED,
                                               final_state=salobj.State.STANDBY)

        asyncio.get_event_loop().run_until_complete(doit())

    def test_enabled_to_disabled(self):
        async def doit():
            await self.check_set_summary_state(initial_state=salobj.State.ENABLED,
                                               final_state=salobj.State.DISABLED)

        asyncio.get_event_loop().run_until_complete(doit())

    def test_enabled_to_enabled(self):
        async def doit():
            await self.check_set_summary_state(initial_state=salobj.State.ENABLED,
                                               final_state=salobj.State.ENABLED)

        asyncio.get_event_loop().run_until_complete(doit())

    def test_fault_to_offline(self):
        async def doit():
            await self.check_set_summary_state(initial_state=salobj.State.FAULT,
                                               final_state=salobj.State.OFFLINE)

        asyncio.get_event_loop().run_until_complete(doit())

    def test_fault_to_standby(self):
        async def doit():
            await self.check_set_summary_state(initial_state=salobj.State.FAULT,
                                               final_state=salobj.State.STANDBY)

        asyncio.get_event_loop().run_until_complete(doit())

    def test_fault_to_disabled(self):
        async def doit():
            await self.check_set_summary_state(initial_state=salobj.State.FAULT,
                                               final_state=salobj.State.DISABLED)

        asyncio.get_event_loop().run_until_complete(doit())

    def test_fault_to_enabled(self):
        async def doit():
            await self.check_set_summary_state(initial_state=salobj.State.FAULT,
                                               final_state=salobj.State.ENABLED)

        asyncio.get_event_loop().run_until_complete(doit())

    def test_invalid_state(self):
        """Test set_summary_state with invalid final states."""
        async def doit():
            for initial_state in salobj.State:
                if initial_state == salobj.State.OFFLINE:
                    # TestCsc cannot start in OFFLINE state
                    continue
                async with Harness(initial_state=initial_state) as harness:
                    for bad_final_state in (min(salobj.State) - 1, salobj.State.FAULT, max(salobj.State) + 1):
                        with self.subTest(initial_state=initial_state, bad_final_state=bad_final_state):
                            with self.assertRaises(ValueError):
                                await salobj.set_summary_state(remote=harness.remote, state=bad_final_state,
                                                               timeout=STD_TIMEOUT)

        asyncio.get_event_loop().run_until_complete(doit())

    async def check_set_summary_state(self, initial_state, final_state):
        """Check set_summary_state for valid state transitions.

        Parameters
        ----------
        initial_state : `State`
            Initial summary state.
        final_state : `State`
            Final summary state.
        """
        async with Harness(initial_state=initial_state) as harness:
            self.assertEqual(harness.csc.summary_state, initial_state)
            data = await harness.remote.evt_summaryState.next(flush=False,
                                                              timeout=STD_TIMEOUT)
            self.assertEqual(data.summaryState, initial_state)

            states = await salobj.set_summary_state(remote=harness.remote,
                                                    state=final_state,
                                                    settingsToApply="all_fields")
            self.assertEqual(states[0], initial_state)
            self.assertEqual(states[-1], final_state)
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
            # the initial state was read by the remote
            # in set_summary_state (and in the test),
            # so only check for subsequent states
            for expected_state in states[1:]:
                data = await harness.remote.evt_summaryState.next(flush=False,
                                                                  timeout=STD_TIMEOUT)
                self.assertEqual(data.summaryState, expected_state)


if __name__ == "__main__":
    if PRINT_TEST_CASES:
        print_test_cases()
        raise RuntimeError("PRINT_TEST_CASES True: code printed, but tests not run")
    else:
        unittest.main()
