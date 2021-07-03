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

__all__ = ["ControllerTelemetry"]

import typing

from . import write_topic

if typing.TYPE_CHECKING:
    from ..sal_info import SalInfo


class ControllerTelemetry(write_topic.WriteTopic):
    """Write a specific telemetry topic.

    Parameters
    ----------
    salinfo : `.SalInfo`
        SAL component information
    name : `str`
        Command name
    """

    def __init__(self, salinfo: SalInfo, name: str) -> None:
        super().__init__(salinfo=salinfo, name=name, sal_prefix="")

    def set_put(self, **kwargs: typing.Any) -> bool:
        """Set zero or more fields of ``self.data`` and put the result.

        Parameters
        ----------
        **kwargs : `dict` [`str`, ``any``]
            The keyword arguments are field name = new value for that field.
            See `set` for more information about values.

        Returns
        -------
        did_change : `bool`
            True if ``self.data`` was changed, or if this was the first call
            to `set`.

        Raises
        ------
        AttributeError
            If the topic does not have the specified field.
        ValueError
            If the field cannot be set to the specified value.
        """
        did_change = self.set(**kwargs)
        self.put()
        return did_change
