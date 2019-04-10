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

__all__ = ["SAL_SLEEP", "BaseTopic", "BaseOutputTopic"]

import abc

import numpy as np

# Time to sleep after each SAL command to give the C++ threads time to work.
# Note: always use `time.sleep(SAL_SLEEP)` instead of
# `await asyncio.sleep(SAL_SLEEP)` because the latter may keep Python too busy.
SAL_SLEEP = 0.001  # time to sleep after each SAL command


class BaseTopic(abc.ABC):
    """Base class for topics.

    Parameters
    ----------
    salinfo : `SalInfo`
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
        TypeError
            If ``data`` is not an instance of `DataType`

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
            Dict of field name: new value for that field:

            * Any key whose value is `None` is checked for existence,
              but the value of the field is not changed.
            * If the field being set is an array then the value must either
              be an array of the same length or a scalar (which replaces
              every element of the array).

        Returns
        -------
        did_change : `bool`
            True if data was changed or if this was the first call to `set`.

        Raises
        ------
        AttributeError
            If the topic does not have the specified field.
        ValueError
            If the field cannot be set to the specified value.

        Notes
        -----
        If one or more fields cannot be set, the data may be partially updated.
        This is not ideal, but is pragmatic because it is difficult to copy
        SAL topics (see TSS-3195).
        """
        did_change = not self.has_data
        for field_name, value in kwargs.items():
            if value is None:
                if not hasattr(self.data, field_name):
                    raise AttributeError(f"{self.data} has no attribute {field_name}")
                continue
            old_value = getattr(self.data, field_name)
            try:
                if isinstance(old_value, np.ndarray):
                    if not did_change:
                        # numpy.array_equiv performs the desired check
                        # even if value is a scalar
                        did_change |= not np.array_equiv(old_value, value)
                    old_value[:] = value
                else:
                    if not did_change:
                        is_different = old_value != value
                        did_change |= is_different
                    setattr(self.data, field_name, value)
            except Exception as e:
                raise ValueError(f"Could not set {self.data}.{field_name} to {value!r}") from e
        self._has_data = True
        return did_change
