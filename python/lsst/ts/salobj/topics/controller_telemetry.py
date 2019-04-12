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

__all__ = ["ControllerTelemetry"]

import time

from .base_topic import BaseOutputTopic, SAL_SLEEP


class ControllerTelemetry(BaseOutputTopic):
    """An object that writes a specific telemetry topic.

    Parameters
    ----------
    salinfo : `lsst.ts.salobj.SalInfo`
        SAL component information
    name : `str`
        Command name
    """
    def put(self, data=None):
        """Output this topic.

        Parameters
        ----------
        data : ``self.DataType`` (optional)
            New data to replace ``self.data``, if any.

        Raises
        ------
        TypeError
            If ``data`` is not None and not an instance of `DataType`.
        """
        if data is not None:
            self.data = data
        retcode = self._put_func(self.data)
        time.sleep(0.001)
        if retcode != self.salinfo.lib.SAL__OK:
            raise RuntimeError(f"put failed with return code {retcode} from {self._put_func_name}")

    def set_put(self, **kwargs):
        """Set one or more fields of ``self.data`` and put the result.

        Parameters
        ----------
        **kwargs : `dict` [`str`, ``any``]
            Dict of field name: new value for that field.
            See `set` for more information about values.

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
        """
        did_change = self.set(**kwargs)
        self.put()
        return did_change

    def _setup(self):
        """Get functions from salinfo and publish this topic."""
        self._put_func = getattr(self.salinfo.manager, "putSample_" + self.name)
        self._DataType = getattr(self.salinfo.lib, self.salinfo.name + "_" + self.name + "C")

        topic_name = self.salinfo.name + "_" + self.name
        try:  # work around lack of topic name in SAL's exception message
            self.salinfo.manager.salTelemetryPub(topic_name)
        except Exception as e:
            raise RuntimeError(f"Could not subscribe to telemetry {self.name}") from e
        time.sleep(SAL_SLEEP)
