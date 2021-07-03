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

__all__ = ["ControllerEvent"]

import typing

from .. import type_hints
from . import write_topic

if typing.TYPE_CHECKING:
    from ..sal_info import SalInfo


class ControllerEvent(write_topic.WriteTopic):
    """Write a specific event topic.

    Parameters
    ----------
    salinfo : `.SalInfo`
        SAL component information
    name : `str`
        Event topic name
    """

    def __init__(self, salinfo: SalInfo, name: str) -> None:
        super().__init__(salinfo=salinfo, name=name, sal_prefix="logevent_")

    def put(
        self,
        data: typing.Optional[type_hints.BaseDdsDataType] = None,
        priority: int = 0,
    ) -> None:
        """Output this topic.

        Parameters
        ----------
        data : ``self.DataType`` or `None`
            New message data to replace ``self.data``, if any.
        priority : `int`, optional
            Priority; used to set the priority field of events.
            Ignored for commands and telemetry.

        Raises
        ------
        TypeError
            If ``data`` is not None and not an instance of `DataType`.
        """
        self.data.priority = priority  # type: ignore
        super().put(data)

    def set_put(self, *, force_output: bool = False, **kwargs: typing.Any) -> bool:
        """Set zero or more fields of ``self.data`` and put if changed
        or if ``force_output`` true.

        The data is put if it has never been set (`has_data` False), or this
        call changes the value of any field, or ``force_output`` is true.

        Parameters
        ----------
        force_output : `bool`, optional
            If True then output the event, even if no fields have changed.
        **kwargs : `dict` [`str`, ``any``]
            The remaining keyword arguments are
            field name = new value for that field.
            See `set` for more information about values.

        Returns
        -------
        did_put : `bool`
            True if the data was output, False otherwise

        Raises
        ------
        AttributeError
            If the topic does not have the specified field.
        ValueError
            If the field cannot be set to the specified value.
        """
        did_change = self.set(**kwargs)
        do_output = did_change or force_output
        if do_output:
            self.put(self.data)
        return do_output
