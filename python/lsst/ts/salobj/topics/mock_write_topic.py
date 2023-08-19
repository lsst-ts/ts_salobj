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

__all__ = ["MockWriteTopic"]

import typing

from lsst.ts.xml import type_hints

from .write_topic import MAX_SEQ_NUM, WriteTopic

if typing.TYPE_CHECKING:
    from ..sal_info import SalInfo


class MockWriteTopic(WriteTopic):
    """A version of WriteTopic that records every message written
    instead of actually writing it.

    It is easiest to construct these by calling `make_mock_write_topics`.
    MockWriteTopic is only intended for unit tests and related short-term use;
    it saves every message, so long term use will leak memory.

    Parameters
    ----------
    salinfo : `SalInfo`
        SAL component information
    attr_name : `str`
        Topic name with attribute prefix. The prefix must be one of:
        ``cmd_``, ``evt_``, ``tel_``, or (only for the ackcmd topic) ``ack_``.
    min_seq_num : `int` or `None`, optional
        Minimum value for the ``private_seqNum`` field. The default is 1.
        If `None` then ``private_seqNum`` is not set; this is needed
        for the ackcmd writer, which sets the field itself.
    max_seq_num : `int`, optional
        Maximum value for ``private_seqNum``, inclusive.
        The default is the maximum allowed positive value
        (``private_seqNum`` is a 4-byte signed int).
        Ignored if ``min_seq_num`` is `None`.
    initial_seq_num : `int`, optional
        Initial sequence number; if `None` use min_seq_num.

    Attributes
    ----------
    data_list : `list` [`type_hints.BaseMsgType`]
        List of data written, with newer data at the end.
    Plus the attributes of:
       `WriteTopic`
    """

    def __init__(
        self,
        *,
        salinfo: SalInfo,
        attr_name: str,
        min_seq_num: int | None = 1,
        max_seq_num: int = MAX_SEQ_NUM,
        initial_seq_num: int | None = None,
    ) -> None:
        super().__init__(
            salinfo=salinfo,
            attr_name=attr_name,
            min_seq_num=min_seq_num,
            max_seq_num=max_seq_num,
            initial_seq_num=initial_seq_num,
        )
        self.data_list: list[type_hints.BaseMsgType] = []

    async def write(self) -> type_hints.BaseMsgType:
        """Write the current data and return a copy of the data written.

        Returns
        -------
        data : self.DataType
            The data that was written.
            This can be useful to avoid race conditions
            (as found in RemoteCommand).

        Raises
        ------
        RuntimeError
            If not running.
        """
        data = self._prepare_data_to_write()
        self.data_list.append(data)
        return data
