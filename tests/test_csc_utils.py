import asyncio
import unittest

try:
    import SALPY_Test
except ImportError:
    SALPY_Test = None
from lsst.ts import salobj

index_gen = salobj.index_generator()


class Harness:
    def __init__(self, initial_state):
        index = next(index_gen)
        salobj.set_random_lsst_dds_domain()
        self.csc = salobj.TestCsc(index=index, initial_state=initial_state)
        self.remote = salobj.Remote(SALPY_Test, index)

    async def next_state(self, timeout=1):
        state = await self.remote.evt_summaryState.next(flush=False, timeout=timeout)
        return state.summaryState


class EnableCscTestCase(unittest.TestCase):
    async def assert_state(self, harness, state, timeout=1):
        actual_state = await harness.next_state(timeout=timeout)
        self.assertEqual(actual_state, actual_state)

    def test_enabled_noforce(self):
        async def doit():
            harness = Harness(initial_state=salobj.State.ENABLED)
            await self.assert_state(harness, salobj.State.ENABLED)
            await salobj.enable_csc(harness.remote, force_config=False)
            with self.assertRaises(asyncio.TimeoutError):
                await harness.next_state(timeout=0.1)

        asyncio.get_event_loop().run_until_complete(doit())

    def test_disabled_noforce(self):
        async def doit():
            harness = Harness(initial_state=salobj.State.DISABLED)
            await self.assert_state(harness, salobj.State.DISABLED)
            await salobj.enable_csc(harness.remote, force_config=False)
            await self.assert_state(harness, salobj.State.ENABLED)

        asyncio.get_event_loop().run_until_complete(doit())

    def test_standby_noforce(self):
        async def doit():
            harness = Harness(initial_state=salobj.State.STANDBY)
            await self.assert_state(harness, salobj.State.STANDBY)
            await salobj.enable_csc(harness.remote, force_config=False)
            await self.assert_state(harness, salobj.State.DISABLED)
            await self.assert_state(harness, salobj.State.ENABLED)

        asyncio.get_event_loop().run_until_complete(doit())

    def test_fault_noforce(self):
        async def doit():
            harness = Harness(initial_state=salobj.State.FAULT)
            await self.assert_state(harness, salobj.State.FAULT)
            await salobj.enable_csc(harness.remote, force_config=False)
            await self.assert_state(harness, salobj.State.STANDBY)
            await self.assert_state(harness, salobj.State.DISABLED)
            await self.assert_state(harness, salobj.State.ENABLED)

        asyncio.get_event_loop().run_until_complete(doit())

    def test_enabled_force(self):
        async def doit():
            harness = Harness(initial_state=salobj.State.ENABLED)
            await self.assert_state(harness, salobj.State.ENABLED)
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
                    await salobj.enable_csc(harness.remote, force_config=True)
                    await self.assert_state(harness, salobj.State.STANDBY)
                    await self.assert_state(harness, salobj.State.DISABLED)
                    await self.assert_state(harness, salobj.State.ENABLED)

        asyncio.get_event_loop().run_until_complete(doit())

    def test_standby_force(self):
        async def doit():
            harness = Harness(initial_state=salobj.State.STANDBY)
            await self.assert_state(harness, salobj.State.STANDBY)
            await salobj.enable_csc(harness.remote, force_config=True)
            await self.assert_state(harness, salobj.State.DISABLED)
            await self.assert_state(harness, salobj.State.ENABLED)

        asyncio.get_event_loop().run_until_complete(doit())


if __name__ == "__main__":
    unittest.main()
