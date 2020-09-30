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
import os
import pathlib
import sys
import unittest

import asynctest
import numpy as np

from lsst.ts import salobj

np.random.seed(47)

index_gen = salobj.index_generator()
TEST_DATA_DIR = TEST_CONFIG_DIR = pathlib.Path(__file__).resolve().parent / "data"
TEST_CONFIG_DIR = TEST_DATA_DIR / "config"


class NoIndexCsc(salobj.TestCsc):
    """A CSC whose constructor has no index argument."""

    def __init__(self, arg1, arg2, config_dir=None):
        super().__init__(index=next(index_gen), config_dir=config_dir)
        self.arg1 = arg1
        self.arg2 = arg2


class CscMakeFromCmdLineTestCase(asynctest.TestCase):
    def setUp(self):
        salobj.set_random_lsst_dds_partition_prefix()
        self.original_argv = sys.argv[:]

    def tearDown(self):
        sys.argv = self.original_argv

    async def test_no_index(self):
        for index in (0, None):
            with self.subTest(index=index):
                sys.argv = [sys.argv[0]]
                arg1 = "astring"
                arg2 = 2.75
                async with NoIndexCsc.make_from_cmd_line(
                    index=index, arg1=arg1, arg2=arg2
                ) as csc:
                    self.assertEqual(csc.arg1, arg1)
                    self.assertEqual(csc.arg2, arg2)
                    await csc.do_exitControl(data=None)
                    await asyncio.wait_for(csc.done_task, timeout=5)

    async def test_specified_index(self):
        sys.argv = [sys.argv[0]]
        index = next(index_gen)
        async with salobj.TestCsc.make_from_cmd_line(index=index) as csc:
            self.assertEqual(csc.salinfo.index, index)
            await csc.do_exitControl(data=None)
            await asyncio.wait_for(csc.done_task, timeout=5)

    async def test_index_from_argument_and_default_config_dir(self):
        index = next(index_gen)
        sys.argv = [sys.argv[0], str(index)]
        async with salobj.TestCsc.make_from_cmd_line(index=True) as csc:
            self.assertEqual(csc.salinfo.index, index)

            desired_config_pkg_name = "ts_config_ocs"
            desired_config_env_name = desired_config_pkg_name.upper() + "_DIR"
            desird_config_pkg_dir = os.environ[desired_config_env_name]
            desired_config_dir = pathlib.Path(desird_config_pkg_dir) / "Test/v1"
            self.assertEqual(csc.get_config_pkg(), desired_config_pkg_name)
            self.assertEqual(csc.config_dir, desired_config_dir)
            await csc.do_exitControl(data=None)
            await asyncio.wait_for(csc.done_task, timeout=5)

    async def test_config_from_argument(self):
        index = next(index_gen)
        sys.argv = [sys.argv[0], str(index), "--config", str(TEST_CONFIG_DIR)]
        async with salobj.TestCsc.make_from_cmd_line(index=True) as csc:
            self.assertEqual(csc.salinfo.index, index)
            self.assertEqual(csc.config_dir, TEST_CONFIG_DIR)
            await csc.do_exitControl(data=None)
            await asyncio.wait_for(csc.done_task, timeout=5)


if __name__ == "__main__":
    unittest.main()
