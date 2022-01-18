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

from .. import type_hints

if typing.TYPE_CHECKING:
    from ..sal_info import SalInfo


class BaseTopic(abc.ABC):
    r"""Base class for topics.

    Parameters
    ----------
    salinfo : `.SalInfo`
        SAL component information.
    attr_name : `str`
        Topic name with attribute prefix: one of "cmd_", "evt_", or "tel_",
        or "ack_" for the ackcmd topic.

    Raises
    ------
    RuntimeError
        If the topic cannot be constructed.

    Attributes
    ----------
    salinfo : `SalInfo`
        The ``salinfo`` constructor argument.
    topic_info : `TopicInfo`
        Metadata about the topic.
    log : `logging.Logger`
        A logger.
    """

    def __init__(self, *, salinfo: SalInfo, attr_name: str) -> None:
        try:
            self.salinfo = salinfo
            self.topic_info = self.salinfo.component_info.topics[attr_name]
            self.log = salinfo.log.getChild(self.sal_name)
            self._type = self.topic_info.make_dataclass()

        except Exception as e:
            raise RuntimeError(
                f"Failed to create topic {salinfo.name}.{attr_name}"
            ) from e

    @property
    def attr_name(self) -> str:
        """Get the salobj topic attribute name, e.g. evt_summaryState."""
        return self.topic_info.attr_name

    @property
    def sal_name(self) -> str:
        """Get the SAL topic name, e.g. logevent_summaryState."""
        return self.topic_info.sal_name

    @property
    def DataType(self) -> typing.Type[type_hints.BaseMsgType]:
        """The type (class) for a message of this topic.

        When you read or write a message for this topic you are reading
        or writing an instance of `DataType`.

        Notes
        -----
        The preferred way to write a message for a topic is:

        * `RemoteCommand.set_start` to start a command.
        * `CommandEvent.set_put` to write an event.
        * `CommandTelemetry.set_put` to write a telemetry message.

        However, it is also possible to use `DataType` to create a message,
        then write, it as separate operations. For example,
        assuming we have a `Remote` for SAL component "Test"::

            # The preferred way to issue a command:
            await = remote.cmd_wait.set_put(duration=2, timeout=5)

            # But an alternative is to first create the command,
            # then send it, as two separate operations:
            message = remote.cmd_wait.DataType(duration=2)
            await remote.cmd_wait.start(message, timeout=5)

            # Or, even more verbosely:
            message = remote.cmd_wait.DataType()
            message.duration = 2
            await remote.cmd_wait.start(message, timeout=5)
        """
        return self._type

    def __repr__(self) -> str:
        return f"{type(self).__name__}({self.salinfo.name}, {self.salinfo.index}, {self.attr_name})"
