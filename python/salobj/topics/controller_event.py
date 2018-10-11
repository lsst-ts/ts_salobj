# This file is part of salobj.
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
    def put(self, data, priority=1):
        """Write a new value for this topic.

        Parameters
        ----------
        data : ``self.DataType``
            Command parameters.
        priority : `int`
            Priority. ts_sal does not yet use this for anything;
            in the meantime I provide a default that works.
        """
        if not isinstance(data, self.DataType):
            raise TypeError(f"data={data!r} must be an instance of {self.DataType}")
        retcode = self._put_func(data, priority)
        if retcode != self.salinfo.lib.SAL__OK:
            raise RuntimeError(f"salProcessor({self.name}) failed with return code {retcode}")

    def _setup(self):
        """Get functions from salinfo and publish this topic."""
        self._put_func = getattr(self.salinfo.manager, "logEvent_" + self.name)
        self._DataType = getattr(self.salinfo.lib, self.salinfo.name + "_logevent_" + self.name + "C")

        topic_name = self.salinfo.name + "_logevent_" + self.name
        retcode = self.salinfo.manager.salEventPub(topic_name)
        if retcode != self.salinfo.lib.SAL__OK:
            raise RuntimeError(f"salEventPub({topic_name}) failed with return code {retcode}")
