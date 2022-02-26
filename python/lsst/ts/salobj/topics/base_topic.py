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

__all__ = ["BaseTopic"]

import abc
import typing

import ddsutil

from .. import type_hints
from ..idl_metadata import TopicMetadata

if typing.TYPE_CHECKING:
    from ..sal_info import SalInfo

# dict of attr prefix: SAL prefix
_SAL_PREFIXES = {"ack": "", "cmd": "command_", "evt": "logevent_", "tel": ""}


class BaseTopic(abc.ABC):
    r"""Base class for topics.

    Parameters
    ----------
    salinfo : `SalInfo`
        SAL component information.
    attr_name : `str`
        Topic name with attribute prefix. The prefix must be one of:
        ``cmd_``, ``evt_``, ``tel_``, or (only for the ackcmd topic) ``ack_``.

    Raises
    ------
    RuntimeError
        If the topic cannot be constructed.

    Attributes
    ----------
    salinfo : `SalInfo`
        The ``salinfo`` constructor argument.
    attr_name : `str`
        The attr_name constructor argument: the name of topic attribute
        in `Controller` and `Remote`. For example: ``evt_summaryState``.
    name : `str`
        The topic name without any prefix. For example: ``summaryState``.
    sal_name : `str`
        The topic name used by SAL. Commands have prefix ``command_``,
        events have prefix ``logevent_``, and other topics have no prefix.
        For example: ``logevent_summaryState``.
    log : `logging.Logger`
        A logger.
    qos_set : `salobj.QosSet`
        Quality of service set.
    volatile : `bool`
        Is this topic volatile (in which case it has no historical data)?
    rev_code : `str`
        Revision hash code for the topic.
        This code changes whenever the schema for the topic changes,
        and it is part of the DDS topic name. For example: ``90255bf1``.
    dds_name : `str`
        Name of topic seen by DDS.
        For example: ``Test_logevent_summaryState_90255bf1``.
    """

    def __init__(self, *, salinfo: SalInfo, attr_name: str) -> None:
        try:
            self.salinfo = salinfo
            self.attr_name = attr_name

            attr_prefix, name = attr_name.split("_", 1)
            if attr_prefix not in _SAL_PREFIXES:
                raise RuntimeError(
                    f"Uknown prefix {attr_prefix!r} in attr_name={attr_name!r}"
                )
            self.name = name
            sal_prefix = _SAL_PREFIXES[attr_prefix]
            self.sal_name = sal_prefix + self.name
            self.log = salinfo.log.getChild(self.sal_name)

            if name == "ackcmd":
                self.qos_set = salinfo.domain.ackcmd_qos_set
            elif sal_prefix == "command_":
                self.qos_set = salinfo.domain.command_qos_set
            elif sal_prefix == "logevent_":
                self.qos_set = salinfo.domain.event_qos_set
            else:
                self.qos_set = salinfo.domain.telemetry_qos_set

            revname = salinfo.revnames.get(self.sal_name)
            if revname is None:
                raise RuntimeError(
                    f"Could not find {self.salinfo.name} topic {self.sal_name}"
                )
            self.dds_name = revname.replace("::", "_")
            self.rev_code = self.dds_name.rsplit("_", 1)[1]

            self._type = ddsutil.make_dds_topic_class(
                parsed_idl=salinfo.parsed_idl, revname=revname
            )
            self._topic = self._type.register_topic(
                salinfo.domain.participant, self.dds_name, self.qos_set.topic_qos
            )

        except Exception as e:
            raise RuntimeError(
                f"Failed to create topic {salinfo.name}.{attr_name}"
            ) from e

    @property
    def DataType(self) -> typing.Type[type_hints.BaseMsgType]:
        """The type (class) for a message of this topic.

        When you read or write a message for this topic you are reading
        or writing an instance of `DataType`.

        Notes
        -----
        The preferred way to write a message for a topic is:

        * `RemoteCommand.start` to start a command.
        * `CommandEvent.write` to write an event.
        * `CommandTelemetry.write` to write a telemetry message.
        """
        return self._type.topic_data_class

    @property
    def volatile(self) -> bool:
        """Does this topic have volatile durability?"""
        return self.qos_set.volatile

    @property
    def metadata(self) -> typing.Optional[TopicMetadata]:
        """Get topic metadata as a `TopicMetadata`, if available,else None."""
        return self.salinfo.metadata.topic_info.get(self.sal_name)

    def __repr__(self) -> str:
        return f"{type(self).__name__}({self.salinfo.name}, {self.salinfo.index}, {self.name})"
