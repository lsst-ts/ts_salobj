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

import copy
import unittest

import pytest
from lsst.ts import salobj


class HierarchicalTestCase(unittest.IsolatedAsyncioTestCase):
    def test_basics(self) -> None:
        dict1 = dict(
            key1="dict1 value1",
            hierkey1=dict(
                key11="dict1 value11",
                hierkey11=dict(
                    key111="dict1 value111",
                ),
            ),
            hierkey2=dict(
                key12="dict1 value12",
                hierkey12=dict(
                    key122="dict1 value122",
                ),
            ),
        )
        dict2 = dict(
            key1="dict2 value1",
            key2="dict2 value2",
            hierkey1=dict(
                key11="dict2 value11",
                hierkey11=dict(
                    key111="dict2 value111",
                ),
            ),
            hierkey3=dict(
                key13="dict2 value13",
                hierkey13=dict(
                    key113="dict2 value113",
                ),
            ),
        )

        # Overriding a dict with itself should produce no changes
        dict1copy = copy.deepcopy(dict1)
        salobj.hierarchical_update(
            main=dict1copy, override=dict1, main_name="main", override_name="override"
        )
        assert dict1copy == dict1

        dict2copy = copy.deepcopy(dict2)
        salobj.hierarchical_update(
            main=dict2copy, override=dict2, main_name="main", override_name="override"
        )
        assert dict2copy == dict2

        dict1copy = copy.deepcopy(dict1)
        salobj.hierarchical_update(
            main=dict1copy, override=dict2, main_name="dict1", override_name="dict2"
        )
        assert dict1copy == dict(
            key1="dict2 value1",
            key2="dict2 value2",
            hierkey1=dict(
                key11="dict2 value11",
                hierkey11=dict(
                    key111="dict2 value111",
                ),
            ),
            hierkey2=dict(
                key12="dict1 value12",
                hierkey12=dict(
                    key122="dict1 value122",
                ),
            ),
            hierkey3=dict(
                key13="dict2 value13",
                hierkey13=dict(
                    key113="dict2 value113",
                ),
            ),
        )

    def test_errors(self) -> None:
        dict1 = dict(
            key1="dict1 value1",
            hierkey1=dict(
                key11="dict1 value11",
                hierkey11=dict(
                    key111="dict1 value111",
                ),
            ),
            hierkey2=dict(
                key12="dict1 value12",
                hierkey12=dict(
                    key122="dict1 value122",
                ),
            ),
        )
        for bad_dict, errmsg_re in (
            (
                dict(
                    key1=dict(key11="a dict instead of a scalar or array"),
                ),
                r"dict1\[key1\].+is not a dict",
            ),
            (
                dict(hierkey1="a scalar instead of a dict"),
                r"dict1\[hierkey1\].+is a dict.+bad_dict\[hierkey1\].+is not",
            ),
        ):
            dict1copy = copy.deepcopy(dict1)
            with pytest.raises(ValueError, match=errmsg_re):
                salobj.hierarchical_update(
                    main=dict1copy,
                    override=bad_dict,
                    main_name="dict1",
                    override_name="bad_dict",
                )
