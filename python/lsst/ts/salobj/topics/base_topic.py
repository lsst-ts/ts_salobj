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

__all__ = ["BaseTopic", "BaseOutputTopic"]

import abc

import numpy as np


class BaseTopic(abc.ABC):
    """Base class for topics.

    Parameters
    ----------
    salinfo : `salobj.SalInfo`
        SAL component information
    name : `str`
        Command name
    """
    def __init__(self, salinfo, name):
        self.salinfo = salinfo
        self.name = str(name)
        self._has_data = False
        self._setup()
        self._data = self.DataType()

    @property
    def DataType(self):
        """The class of data for this topic."""
        return self._DataType

    @property
    def data(self):
        """Get or set internally cached data.

        Parameters
        ----------
        data : `DataType`
            New data.

        Raises
        ------
        TypeError if ``data`` is not an instance of `DataType`

        Notes
        -----
        You must not modify the returned data, nor assume that it will be
        constant. If you need a copy then make it yourself.
        """
        return self._data

    @data.setter
    def data(self, data):
        if not isinstance(data, self.DataType):
            raise TypeError(f"data={data!r} must be an instance of {self.DataType}")
        self._data = data
        self._has_data = True

    @property
    def has_data(self):
        """Has `data` ever been set?"""
        return self._has_data

    def __repr__(self):
        return f"{type(self).__name__}({self.salinfo}, {self.name})"

    @abc.abstractmethod
    def _setup(self):
        """Get functions from salinfo and subscribe to this topic."""


class BaseOutputTopic(BaseTopic):
    """Base class for topics that are output.

    This includes  controller events, controller telemetry and remote commands.
    """
    def set(self, **kwargs):
        """Set one or more fields of ``self.data``.

        Parameters
        ----------
        **kwargs : `dict` [`str`, ``any``]
            Dict of field name: new value for that field
        """
        for field_name, value in kwargs.items():
            old_value = getattr(self.data, field_name)
            is_array = isinstance(old_value, np.ndarray)
            if is_array:
                getattr(self.data, field_name)[:] = value
            else:
                setattr(self.data, field_name, value)
        self._has_data = True
