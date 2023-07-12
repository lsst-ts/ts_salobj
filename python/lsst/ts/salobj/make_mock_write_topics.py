from __future__ import annotations

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

__all__ = ["make_mock_write_topics"]

import contextlib
import types
from collections.abc import AsyncGenerator

from .domain import Domain
from .sal_info import SalInfo
from .topics import MockWriteTopic


@contextlib.asynccontextmanager
async def make_mock_write_topics(
    name: str,
    attr_names: list[str],
    index: int | None = None,
) -> AsyncGenerator[types.SimpleNamespace, None]:
    """Make a struct of mock write topics for unit testing data clients.

    The struct attribute names are the topic attr_names, and the values
    are instances of `topics.MockWriteTopic`.

    Parameters
    ----------
    name : `str`
        SAL component name.
    attr_names : `list` [`str`]
        List of topic attribute names, e.g.
        ["tel_temperature", "evt_lightningStrike"]
    index : `int` | `None`, optional
        The SAL index. Irrelevant unless you want to check the salIndex
        field of the data. None results in 0 for a non-indexed
        compoonent and 1 for an indexed component.
    """
    if not attr_names:
        raise ValueError("You must provide one or more topic attr_names")

    async with Domain() as domain, SalInfo(
        domain=domain, name=name, index=index
    ) as salinfo:
        if index is None:
            index = 1 if salinfo.indexed else 0
        topics_dict = {
            attr_name: MockWriteTopic(salinfo=salinfo, attr_name=attr_name)
            for attr_name in attr_names
        }
        yield types.SimpleNamespace(**topics_dict)
