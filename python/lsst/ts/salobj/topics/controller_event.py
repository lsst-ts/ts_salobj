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

__all__ = ["ControllerEvent"]

import numpy as np

from .controller_telemetry import ControllerTelemetry


class ControllerEvent(ControllerTelemetry):
    """An object that writes a specific event topic.

    Parameters
    ----------
    salinfo : `salobj.SalInfo`
        SAL component information
    name : `str`
        Event topic name
    """
    def put(self, data=None, priority=1):
        """Output this topic.

        Parameters
        ----------
        data : ``self.DataType`` (optional)
            New data to replace ``self.data``, if any.
        priority : `int` (optional)
            Priority. ts_sal does not yet use this for anything;
            in the meantime I provide a default that works.

        Raises
        ------
        TypeError
            If ``data`` is not None and not an instance of `DataType`.
        """
        if data is not None:
            self.data = data
        retcode = self._put_func(self.data, priority)
        if retcode != self.salinfo.lib.SAL__OK:
            raise RuntimeError(f"salProcessor({self.name}) failed with return code {retcode}")

    def set_put(self, **kwargs):
        """Set one or more fields of ``self.data`` and put *if changed*.

        The data is put if it has never been set (`has_data` False)
        or if this call changes any field.

        Returns
        -------
        did_put : `bool`
            True if the data was output, False otherwise
        """
        do_output = not self.has_data
        for field_name, value in kwargs.items():
            try:
                old_value = getattr(self.data, field_name)
                field_is_array = isinstance(old_value, np.ndarray)
                if not do_output:
                    is_different = old_value != value
                    if field_is_array:
                        do_output |= is_different.any()
                    else:
                        do_output |= is_different
                if field_is_array:
                    getattr(self.data, field_name)[:] = value
                else:
                    setattr(self.data, field_name, value)
            except Exception as e:
                raise ValueError(f"Could not set {field_name} to {value!r}") from e
        if do_output:
            self.put(self.data)
        return do_output

    def _setup(self):
        """Get functions from salinfo and publish this topic."""
        self._put_func = getattr(self.salinfo.manager, "logEvent_" + self.name)
        self._DataType = getattr(self.salinfo.lib, self.salinfo.name + "_logevent_" + self.name + "C")

        topic_name = self.salinfo.name + "_logevent_" + self.name
        retcode = self.salinfo.manager.salEventPub(topic_name)
        if retcode != self.salinfo.lib.SAL__OK:
            raise RuntimeError(f"salEventPub({topic_name}) failed with return code {retcode}")
