import unittest

import asynctest
import numpy as np

from lsst.ts import salobj

np.random.seed(47)

index_gen = salobj.index_generator()


class ControllerWithDoMethods(salobj.Controller):
    """A Test controller with a trivial do_<name> method for each
    specified command name.

    Parameters
    ----------
    command_names : `iterable` of `str`
        List of command names for which to make trivial ``do_<name>``
        methods.
    """
    def __init__(self, command_names):
        index = next(index_gen)
        for name in command_names:
            setattr(self, f"do_{name}", self.mock_do_method)
        super().__init__("Test", index, do_callbacks=True)

    def mock_do_method(self, *args, **kwargs):
        pass


class ControllerConstructorTestCase(asynctest.TestCase):
    def setUp(self):
        salobj.set_random_lsst_dds_domain()

    async def test_do_callbacks_false(self):
        index = next(index_gen)
        async with salobj.Controller("Test", index, do_callbacks=False) as controller:
            command_names = controller.salinfo.command_names
            for name in command_names:
                with self.subTest(name=name):
                    cmd = getattr(controller, "cmd_" + name)
                    self.assertFalse(cmd.has_callback)

    async def test_do_callbacks_true(self):
        index = next(index_gen)
        async with salobj.Domain() as domain:
            salinfo = salobj.SalInfo(domain=domain, name="Test", index=index)
            command_names = salinfo.command_names

            # make sure I can build one
            async with ControllerWithDoMethods(command_names) as good_controller:
                for cmd_name in command_names:
                    with self.subTest(cmd_name=cmd_name):
                        cmd = getattr(good_controller, "cmd_" + cmd_name)
                        self.assertTrue(cmd.has_callback)

            skip_names = salobj.OPTIONAL_COMMAND_NAMES.copy()
            # do_setLogLevel is provided by Controller
            skip_names.add("setLogLevel")
            for missing_name in command_names:
                if missing_name in skip_names:
                    continue
                with self.subTest(missing_name=missing_name):
                    bad_names = [name for name in command_names if name != missing_name]
                    with self.assertRaises(TypeError):
                        ControllerWithDoMethods(bad_names)

            extra_names = list(command_names) + ["extra_command"]
            with self.assertRaises(TypeError):
                ControllerWithDoMethods(extra_names)


if __name__ == "__main__":
    unittest.main()
