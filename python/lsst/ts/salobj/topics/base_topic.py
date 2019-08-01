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

__all__ = ["BaseTopic"]

import abc

# TODO when we upgrade to OpenSplice 6.10, use its ddsutil:
# import ddsutil
from .. import ddsutil

# dict of sal_prefix: attr_prefix: the prefix used for
# Controller and Remote topic attributes.
_ATTR_PREFIXES = {"": "tel_", "logevent_": "evt_", "command_": "cmd_"}


class BaseTopic(abc.ABC):
    r"""Base class for topics.

    Parameters
    ----------
    salinfo : `SalInfo`
        SAL component information
    name : `str`
        Topic name, without a "command\_" or "logevent\_" prefix.
    sal_prefix : `str`
        SAL topic prefix: one of "command\_", "logevent\_" or ""

    Raises
    ------
    RuntimeError
        If the topic cannot be constructed.
    """
    def __init__(self, *, salinfo, name, sal_prefix):
        try:
            self.salinfo = salinfo
            """The ``salinfo`` constructor argument.
            """

            self.name = str(name)
            """The ``name`` constructor argument.
            """

            self.attr_prefix = _ATTR_PREFIXES.get(sal_prefix)
            """Prefix used for attributes of `Controller` and `Remote`.

            * "cmd_" for commands
            * "evt_" for events
            * "tel_" for telemetry
            """

            if self.attr_prefix is None:
                raise ValueError(f"Uknown sal_prefix {sal_prefix!r}")
            self._sal_topic_name = sal_prefix + self.name
            self.log = salinfo.log.getChild(self._sal_topic_name)
            if name == "ackcmd":
                ddsname = f"{salinfo.name}_ackcmd"
                revname = f"{salinfo.name}::ackcmd"
                self._revCode = ""
            else:
                revname = salinfo.revnames.get(self._sal_topic_name)
                if revname is None:
                    raise ValueError(f"Could not find {self.salinfo.name} topic {self._sal_topic_name}")
                ddsname = revname.replace("::", "_")
                self._revCode = ddsname[-8:]
            self._type = ddsutil.get_dds_classes_from_idl(salinfo.idl_loc, revname)
            self._topic = self._type.register_topic(salinfo.domain.participant, ddsname,
                                                    salinfo.domain.topic_qos)
        except Exception as e:
            raise RuntimeError(f"Failed to create topic {salinfo.name}.{name}") from e

    @property
    def DataType(self):
        """The class of data for this topic."""
        return self._type.topic_data_class

    def __repr__(self):
        return f"{type(self).__name__}({self.salinfo.name}, {self.salinfo.index}, {self.name})"
