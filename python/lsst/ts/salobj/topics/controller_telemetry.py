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

from .base_topic import BaseOutputTopic


class ControllerTelemetry(BaseOutputTopic):
    """An object that writes a specific telemetry topic.

    Parameters
    ----------
    salinfo : `salobj.SalInfo`
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
        if retcode != self.salinfo.lib.SAL__OK:
            raise RuntimeError(f"put failed with return code {retcode} from {self._put_func_name}")

    def set_put(self, **kwargs):
        """Set one or more fields of ``self.data`` and put the result."""
        self.set(**kwargs)
        self.put()

    def _setup(self):
        """Get functions from salinfo and publish this topic."""
        self._put_func = getattr(self.salinfo.manager, "putSample_" + self.name)
        self._DataType = getattr(self.salinfo.lib, self.salinfo.name + "_" + self.name + "C")

        topic_name = self.salinfo.name + "_" + self.name
        retcode = self.salinfo.manager.salTelemetryPub(topic_name)
        if retcode != self.salinfo.lib.SAL__OK:
            raise RuntimeError(f"salTelemetryPub({topic_name}) failed with return code {retcode}")
