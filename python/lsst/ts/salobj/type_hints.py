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

__all__ = [
    "AckCmdDataType",
    "BaseMsgType",
    "BaseDdsDataType",
    "PathType",
]

import dataclasses
import pathlib
import typing

from . import sal_enums


@dataclasses.dataclass
class BaseMsgType:
    r"""Base DDS sample data type, for type annotations.

    This has the ``salIndex`` field, which is only present for indexed
    SAL components, and is missing all topic-specific fields.
    """

    private_revCode: str = ""
    private_sndStamp: float = 0
    private_rcvStamp: float = 0
    private_seqNum: int = 0
    private_identity: str = ""
    private_origin: int = 0
    salIndex: int = 0

    def get_vars(self) -> dict[str, typing.Any]:
        raise NotImplementedError()


# Backwards compatibility
BaseDdsDataType = BaseMsgType


@dataclasses.dataclass
class AckCmdDataType(BaseMsgType):
    """AckCmd topic data type, for type annotations."""

    ack: sal_enums.SalRetCode = sal_enums.SalRetCode.CMD_COMPLETE
    error: int = 0
    result: str = ""
    identity: str = ""
    origin: int = 0
    timeout: float = 0


PathType = str | pathlib.Path
