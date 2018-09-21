import asyncio
import unittest

import numpy as np

try:
    import SALPY_Test
except ImportError:
    SALPY_Test = None
import salobj

np.random.seed(47)

if SALPY_Test:
    class Harness:
        index = 30

        def __init__(self, arrays_interval=0.1, scalars_interval=0.03):
            self.index = salobj.test_utils.get_test_index()
            salobj.test_utils.set_random_lsst_dds_domain()
            self.component = salobj.test_utils.TestComponent(index=self.index,
                                                             arrays_interval=arrays_interval,
                                                             scalars_interval=scalars_interval)
            self.controller = self.component.controller  # convenience
            self.remote = salobj.Remote(SALPY_Test, f"Test:{self.index}")


@unittest.skipIf(SALPY_Test is None, "Could not import SALPY_Test")
class CommunicateTestCase(unittest.TestCase):
    def test_setArrays_command(self):
        async def doit():
            harness = Harness()
            # until the controller gets its first setArrays
            # it will not send any arrays events or telemetry
            self.assertIsNone(harness.remote.evt_arrays.get())
            self.assertIsNone(harness.remote.tel_arrays.get())

            # send the setArrays command with random data
            # but first start looking for the event that should be triggered
            evt_coro = harness.remote.evt_arrays.next(flush=True, timeout=1)
            cmd_data_sent = harness.component.make_random_cmd_arrays()
            await harness.remote.cmd_setArrays.start(cmd_data_sent, timeout=1)

            # see if new data is being broadcast correctly
            evt_data = await evt_coro
            harness.component.assert_arrays_equal(cmd_data_sent, evt_data)
            tel_data = await harness.remote.tel_arrays.next(flush=True, timeout=1)
            harness.component.assert_arrays_equal(cmd_data_sent, tel_data)

        asyncio.get_event_loop().run_until_complete(doit())

    def test_setScalars_command(self):
        async def doit():
            harness = Harness()
            # until the controller gets its first setArrays
            # it will not send any arrays events or telemetry
            self.assertIsNone(harness.remote.evt_scalars.get())
            self.assertIsNone(harness.remote.tel_scalars.get())

            # send the setScalars command with random data
            # but first start looking for the event that should be triggered
            evt_coro = harness.remote.evt_scalars.next(flush=True, timeout=1)
            cmd_data_sent = harness.component.make_random_cmd_scalars()
            await harness.remote.cmd_setScalars.start(cmd_data_sent, timeout=1)

            # see if new data is being broadcast correctly
            evt_data = await evt_coro
            harness.component.assert_scalars_equal(cmd_data_sent, evt_data)
            tel_data = await harness.remote.tel_scalars.next(flush=True, timeout=1)
            harness.component.assert_scalars_equal(cmd_data_sent, tel_data)

        asyncio.get_event_loop().run_until_complete(doit())

    def test_command_timeout(self):
        async def doit():
            harness = Harness()
            sallib = harness.remote.salinfo.lib
            wait_data = harness.remote.cmd_wait.DataType()
            wait_data.duration = 5
            wait_data.ack = sallib.SAL__CMD_COMPLETE
            result = await harness.remote.cmd_wait.start(wait_data, timeout=0.5)
            self.assertEqual(result.ack.ack, sallib.SAL__CMD_TIMEOUT)

        asyncio.get_event_loop().run_until_complete(doit())

    def test_multiple_commands(self):
        """Test that we can have multiple instances of the same command
        running at the same time.
        """
        async def doit():
            harness = Harness()
            sallib = harness.remote.salinfo.lib
            wait_data = harness.remote.cmd_wait.DataType()
            futures = []
            for duration in (0.4, 0.3):
                wait_data.duration = duration
                wait_data.ack = sallib.SAL__CMD_COMPLETE
                futures.append(harness.remote.cmd_wait.start(wait_data, timeout=5))
            results = await asyncio.gather(*futures)
            for result in results:
                self.assertEqual(result.ack.ack, sallib.SAL__CMD_COMPLETE)

        asyncio.get_event_loop().run_until_complete(doit())

    def test_remote_include_exclude(self):
        """Test the include and exclude arguments for salobj.Remote"""
        index = salobj.test_utils.get_test_index()
        component_name = f"Test:{index}"
        salinfo = salobj.utils.SalInfo(SALPY_Test, component_name)
        manager = salinfo.manager

        # all possible expected topic names
        all_command_topic_names = set(salobj.utils.get_command_names(manager))
        all_event_topic_names = set(salobj.utils.get_event_names(manager))
        all_telemetry_topic_names = set(salobj.utils.get_telemetry_names(manager))

        # the associated method names
        all_command_method_names = set(f"cmd_{name}" for name in all_command_topic_names)
        all_event_method_names = set(f"evt_{name}" for name in all_event_topic_names)
        all_telemetry_method_names = set(f"tel_{name}" for name in all_telemetry_topic_names)

        # remote0 specifies neither include nor exclude; it should have everything
        remote0 = salobj.Remote(SALPY_Test, component_name)
        remote_command_names = set([name for name in dir(remote0) if name.startswith("cmd_")])
        self.assertEqual(remote_command_names, all_command_method_names)
        remote_event_names = set([name for name in dir(remote0) if name.startswith("evt_")])
        self.assertEqual(remote_event_names, all_event_method_names)
        remote_telemetry_names = set([name for name in dir(remote0) if name.startswith("tel_")])
        self.assertEqual(remote_telemetry_names, all_telemetry_method_names)

        # remote1 uses the include argument
        include = ["errorCode", "scalars"]
        remote1 = salobj.Remote(SALPY_Test, component_name, include=include)
        remote1_command_names = set([name for name in dir(remote1) if name.startswith("cmd_")])
        self.assertEqual(remote1_command_names, all_command_method_names)
        remote1_event_names = set([name for name in dir(remote1) if name.startswith("evt_")])
        self.assertEqual(remote1_event_names, set(f"evt_{name}" for name in include
                                                  if name in all_event_topic_names))
        remote1_telemetry_names = set([name for name in dir(remote1) if name.startswith("tel_")])
        self.assertEqual(remote1_telemetry_names, set(f"tel_{name}" for name in include
                                                      if name in all_telemetry_topic_names))

        # remote2 uses the exclude argument
        exclude = ["appliedSettingsMatchStart", "arrays"]
        remote2 = salobj.Remote(SALPY_Test, component_name, exclude=exclude)
        remote2_command_names = set([name for name in dir(remote2) if name.startswith("cmd_")])
        self.assertEqual(remote2_command_names, all_command_method_names)
        remote2_event_names = set([name for name in dir(remote2) if name.startswith("evt_")])
        self.assertEqual(remote2_event_names, set(f"evt_{name}" for name in all_event_topic_names
                                                  if name not in exclude))
        remote2_telemetry_names = set([name for name in dir(remote2) if name.startswith("tel_")])
        self.assertEqual(remote2_telemetry_names, set(f"tel_{name}" for name in all_telemetry_topic_names
                                                      if name not in exclude))

        # make sure one cannot specify both include and exclude
        with self.assertRaises(ValueError):
            salobj.Remote(SALPY_Test, component_name, include=include, exclude=exclude)


if __name__ == "__main__":
    unittest.main()
