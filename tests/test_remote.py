import asyncio
import unittest

import numpy as np

from lsst.ts import salobj

STD_TIMEOUT = 5  # timeout for command ack
LONG_TIMEOUT = 30  # timeout for CSCs to start
EVENT_DELAY = 0.1  # time for events to be output as a result of a command
NODATA_TIMEOUT = 0.1  # timeout for when we expect no new data

np.random.seed(47)

index_gen = salobj.index_generator()


class RemoteTestCase(unittest.TestCase):
    def test_constructor_include_exclude(self):
        """Test the include and exclude arguments for salobj.Remote."""

        async def doit():
            index = next(index_gen)
            async with salobj.Domain() as domain:
                salinfo = salobj.SalInfo(domain=domain, name="Test", index=index)

                # all possible expected topic names
                all_command_names = set(salinfo.command_names)
                all_event_names = set(salinfo.event_names)
                all_telemetry_names = set(salinfo.telemetry_names)

                # the associated method names
                all_command_method_names = set(f"cmd_{name}" for name in all_command_names)
                all_event_method_names = set(f"evt_{name}" for name in all_event_names)
                all_telemetry_method_names = set(f"tel_{name}" for name in all_telemetry_names)

                # remote0 specifies neither include nor exclude;
                # it should have everything
                remote0 = salobj.Remote(domain=domain, name="Test", index=index)
                remote_command_names = set([name for name in dir(remote0) if name.startswith("cmd_")])
                self.assertEqual(remote_command_names, all_command_method_names)
                remote_event_names = set([name for name in dir(remote0) if name.startswith("evt_")])
                self.assertEqual(remote_event_names, all_event_method_names)
                remote_telemetry_names = set([name for name in dir(remote0) if name.startswith("tel_")])
                self.assertEqual(remote_telemetry_names, all_telemetry_method_names)

                # remote1 uses the include argument
                include = ["errorCode", "scalars"]
                remote1 = salobj.Remote(domain=domain, name="Test", index=index, include=include)
                remote1_command_names = set([name for name in dir(remote1) if name.startswith("cmd_")])
                self.assertEqual(remote1_command_names, all_command_method_names)
                remote1_event_names = set([name for name in dir(remote1) if name.startswith("evt_")])
                self.assertEqual(remote1_event_names, set(f"evt_{name}" for name in include
                                                          if name in all_event_names))
                remote1_telemetry_names = set([name for name in dir(remote1) if name.startswith("tel_")])
                self.assertEqual(remote1_telemetry_names, set(f"tel_{name}" for name in include
                                                              if name in all_telemetry_names))

                # remote2 uses the exclude argument
                exclude = ["appliedSettingsMatchStart", "arrays"]
                remote2 = salobj.Remote(domain=domain, name="Test", index=index, exclude=exclude)
                remote2_command_names = set([name for name in dir(remote2) if name.startswith("cmd_")])
                self.assertEqual(remote2_command_names, all_command_method_names)
                remote2_event_names = set([name for name in dir(remote2) if name.startswith("evt_")])
                self.assertEqual(remote2_event_names, set(f"evt_{name}" for name in all_event_names
                                                          if name not in exclude))
                remote2_telemetry_names = set([name for name in dir(remote2) if name.startswith("tel_")])
                self.assertEqual(remote2_telemetry_names, set(f"tel_{name}" for name in all_telemetry_names
                                                              if name not in exclude))

                # remote3 omits commands
                remote3 = salobj.Remote(domain=domain, name="Test", index=index, readonly=True)
                remote_command_names = set([name for name in dir(remote3) if name.startswith("cmd_")])
                self.assertEqual(remote_command_names, set())
                remote_event_names = set([name for name in dir(remote3) if name.startswith("evt_")])
                self.assertEqual(remote_event_names, all_event_method_names)
                remote_telemetry_names = set([name for name in dir(remote3) if name.startswith("tel_")])
                self.assertEqual(remote_telemetry_names, all_telemetry_method_names)

                # make sure one cannot specify both include and exclude
                with self.assertRaises(ValueError):
                    salobj.Remote(domain=domain, name="Test", index=index, include=include, exclude=exclude)

        asyncio.get_event_loop().run_until_complete(doit())

    def assert_max_history(self, remote, evt_max_history=1, tel_max_history=1):
        for evt in [getattr(remote, f"evt_{name}") for name in remote.salinfo.event_names]:
            self.assertEqual(evt.max_history, evt_max_history)

        for tel in [getattr(remote, f"tel_{name}") for name in remote.salinfo.telemetry_names]:
            self.assertEqual(tel.max_history, tel_max_history)

    def test_default_max_history(self):
        """Test default evt_max_history and tel_max_history ctor arguments.
        """
        async def doit():
            index = next(index_gen)
            async with salobj.Domain() as domain:
                remote = salobj.Remote(domain=domain, name="Test", index=index)
                self.assert_max_history(remote)

        asyncio.get_event_loop().run_until_complete(doit())

    def test_tel_max_history(self):
        """Test non-default tel_max_history Remote constructor argument.
        """
        async def doit():
            tel_max_history = 9
            index = next(index_gen)
            async with salobj.Domain() as domain:
                remote = salobj.Remote(domain=domain, name="Test", index=index,
                                       tel_max_history=tel_max_history)
                self.assert_max_history(remote, tel_max_history=tel_max_history)

        asyncio.get_event_loop().run_until_complete(doit())

    def test_evt_max_history(self):
        """Test non-default evt_max_history Remote constructor argument.
        """
        async def doit():
            evt_max_history = 0
            index = next(index_gen)
            async with salobj.Domain() as domain:
                remote = salobj.Remote(domain=domain, name="Test", index=index,
                                       evt_max_history=evt_max_history)
                self.assert_max_history(remote, evt_max_history=evt_max_history)

        asyncio.get_event_loop().run_until_complete(doit())


if __name__ == "__main__":
    unittest.main()
