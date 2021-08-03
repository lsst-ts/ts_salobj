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
    "BaseDdsDataType",
    "PathType",
]

import dataclasses
import pathlib
import typing

from . import sal_enums


@dataclasses.dataclass
class BaseDdsDataType:
    r"""Base DDS sample data type, for type annotations.

    This is missing:

    * _SAL_component_name_\ ID (e.g. ScriptID): only present
      for indexed SAL components
    * priority: present for events, but not used
    * all topic-specific public fields
    """
    private_revCode: str = ""
    private_sndStamp: float = 0
    private_rcvStamp: float = 0
    private_seqNum: int = 0
    private_identity: str = ""
    private_origin: int = 0

    def get_vars(self) -> typing.Dict[str, typing.Any]:
        raise NotImplementedError()


@dataclasses.dataclass
class AckCmdDataType(BaseDdsDataType):
    """AckCmd topic data type, for type annotations."""

    ack: sal_enums.SalRetCode = sal_enums.SalRetCode.CMD_ACK
    error: int = 0
    result: str = ""
    identity: str = ""
    origin: int = 0
    timeout: float = 0


PathType = typing.Union[str, pathlib.Path]
