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

__all__ = ["RemoteEvent"]

import typing

from . import read_topic

if typing.TYPE_CHECKING:
    from ..sal_info import SalInfo


class RemoteEvent(read_topic.ReadTopic):
    """Read a specific event topic.

    Parameters
    ----------
    salinfo : `.SalInfo`
        SAL component information
    name : `str`
        Event topic name
    max_history : `int`, optional
        Maximum number of historical items to read. 1 is typical.
    queue_len : `int`, optional
        Number of elements that can be queued for `get_oldest`.
    """

    def __init__(
        self,
        salinfo: SalInfo,
        name: str,
        max_history: int = 1,
        queue_len: int = read_topic.DEFAULT_QUEUE_LEN,
    ) -> None:
        super().__init__(
            salinfo=salinfo,
            name=name,
            sal_prefix="logevent_",
            max_history=max_history,
            queue_len=queue_len,
        )
