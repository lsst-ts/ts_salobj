# This file is part of ts_salobj.
#
# Developed for the Rubin Observatory Telescope and Site System.
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

import unittest

import numpy as np
import pytest
from lsst.ts import salobj, utils

# Long enough to perform any reasonable operation
# including starting a CSC or loading a script (seconds)
STD_TIMEOUT = 20

np.random.seed(47)

index_gen = utils.index_generator()


class RemoteTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        salobj.set_test_topic_subname()

    async def test_constructor_include_exclude(self) -> None:
        """Test the include and exclude arguments for salobj.Remote."""

        index = next(index_gen)
        async with salobj.Domain() as domain, salobj.SalInfo(
            domain=domain, name="Test", index=index
        ) as salinfo:
            # all possible expected topic names
            all_command_names = set(salinfo.command_names)
            all_event_names = set(salinfo.event_names)
            all_telemetry_names = set(salinfo.telemetry_names)

            # the associated method names
            all_command_method_names = set(f"cmd_{name}" for name in all_command_names)
            all_event_method_names = set(f"evt_{name}" for name in all_event_names)
            all_telemetry_method_names = set(
                f"tel_{name}" for name in all_telemetry_names
            )

            # remote0 specifies neither include nor exclude;
            # it should have everything
            remote0 = salobj.Remote(
                domain=domain, name="Test", index=index, start=False
            )
            remote_command_names = set(
                [name for name in dir(remote0) if name.startswith("cmd_")]
            )
            assert remote_command_names == all_command_method_names
            remote_event_names = set(
                [name for name in dir(remote0) if name.startswith("evt_")]
            )
            assert remote_event_names == all_event_method_names
            remote_telemetry_names = set(
                [name for name in dir(remote0) if name.startswith("tel_")]
            )
            assert remote_telemetry_names == all_telemetry_method_names

            # specify the include argument
            include = ["errorCode", "scalars"]
            remote1 = salobj.Remote(
                domain=domain, name="Test", index=index, include=include, start=False
            )
            remote1_command_names = set(
                [name for name in dir(remote1) if name.startswith("cmd_")]
            )
            assert remote1_command_names == all_command_method_names
            remote1_event_names = set(
                [name for name in dir(remote1) if name.startswith("evt_")]
            )
            assert remote1_event_names == set(
                f"evt_{name}" for name in include if name in all_event_names
            )
            remote1_telemetry_names = set(
                [name for name in dir(remote1) if name.startswith("tel_")]
            )
            assert remote1_telemetry_names == set(
                f"tel_{name}" for name in include if name in all_telemetry_names
            )
            await remote1.close()

            # specify the exclude argument
            exclude = ["errorCode", "arrays"]
            remote2 = salobj.Remote(
                domain=domain, name="Test", index=index, exclude=exclude, start=False
            )
            remote2_command_names = set(
                [name for name in dir(remote2) if name.startswith("cmd_")]
            )
            assert remote2_command_names == all_command_method_names
            remote2_event_names = set(
                [name for name in dir(remote2) if name.startswith("evt_")]
            )
            assert remote2_event_names == set(
                f"evt_{name}" for name in all_event_names if name not in exclude
            )
            remote2_telemetry_names = set(
                [name for name in dir(remote2) if name.startswith("tel_")]
            )
            assert remote2_telemetry_names == set(
                f"tel_{name}" for name in all_telemetry_names if name not in exclude
            )
            await remote2.close()

            # remote3 omits commands
            remote3 = salobj.Remote(
                domain=domain, name="Test", index=index, readonly=True, start=False
            )
            remote_command_names = set(
                [name for name in dir(remote3) if name.startswith("cmd_")]
            )
            assert remote_command_names == set()
            remote_event_names = set(
                [name for name in dir(remote3) if name.startswith("evt_")]
            )
            assert remote_event_names == all_event_method_names
            remote_telemetry_names = set(
                [name for name in dir(remote3) if name.startswith("tel_")]
            )
            assert remote_telemetry_names == all_telemetry_method_names
            await remote3.close()

            # remote4 uses include=[]
            remote4 = salobj.Remote(
                domain=domain, name="Test", index=index, include=[], start=False
            )
            remote_command_names = set(
                [name for name in dir(remote4) if name.startswith("cmd_")]
            )
            assert remote_command_names == all_command_method_names
            remote_event_names = set(
                [name for name in dir(remote4) if name.startswith("evt_")]
            )
            assert remote_event_names == set()
            remote_telemetry_names = set(
                [name for name in dir(remote4) if name.startswith("tel_")]
            )
            assert remote_telemetry_names == set()
            await remote4.close()

            # specify exclude=[] (though there is no reason to doubt
            # that it will work the same as exclude=None)
            remote5 = salobj.Remote(
                domain=domain, name="Test", index=index, exclude=[], start=False
            )
            remote_command_names = set(
                [name for name in dir(remote5) if name.startswith("cmd_")]
            )
            assert remote_command_names == all_command_method_names
            remote_event_names = set(
                [name for name in dir(remote5) if name.startswith("evt_")]
            )
            assert remote_event_names == all_event_method_names
            remote_telemetry_names = set(
                [name for name in dir(remote5) if name.startswith("tel_")]
            )
            assert remote_telemetry_names == all_telemetry_method_names
            await remote5.close()

            # make sure one cannot specify both include and exclude
            with pytest.raises(ValueError):
                salobj.Remote(
                    domain=domain,
                    name="Test",
                    index=index,
                    include=include,
                    exclude=exclude,
                )

    def assert_max_history(
        self, remote: salobj.Remote, evt_max_history: int = 1
    ) -> None:
        for evt in [
            getattr(remote, f"evt_{name}") for name in remote.salinfo.event_names
        ]:
            assert evt.max_history == evt_max_history

        for tel in [
            getattr(remote, f"tel_{name}") for name in remote.salinfo.telemetry_names
        ]:
            assert tel.max_history == 0

    async def test_default_max_history(self) -> None:
        """Test default evt_max_history ctor argument."""
        index = next(index_gen)
        async with salobj.Domain() as domain:
            remote = salobj.Remote(domain=domain, name="Test", index=index, start=False)
            self.assert_max_history(remote)
            await remote.close()

    async def test_evt_max_history(self) -> None:
        """Test non-default evt_max_history Remote constructor argument."""
        evt_max_history = 0
        index = next(index_gen)
        async with salobj.Domain() as domain:
            remote = salobj.Remote(
                domain=domain,
                name="Test",
                index=index,
                evt_max_history=evt_max_history,
                start=False,
            )
            self.assert_max_history(remote, evt_max_history=evt_max_history)
            await remote.close()

    async def test_start_false(self) -> None:
        """Test the start argument of Remote."""

        index = next(index_gen)
        async with salobj.Domain() as domain, salobj.Remote(
            domain=domain, name="Test", index=index, start=False
        ) as remote:
            assert not hasattr(remote, "start_task")
            await remote.close()

    async def test_repr(self) -> None:
        index = next(index_gen)
        async with salobj.Domain() as domain:
            remote = salobj.Remote(domain=domain, name="Test", index=index, start=False)
            reprstr = repr(remote)
            assert "Remote" in reprstr
            assert f"index={index}" in reprstr
            assert f"name={remote.salinfo.name}" in reprstr
            await remote.close()
