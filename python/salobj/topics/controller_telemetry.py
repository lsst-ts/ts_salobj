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

__all__ = ["ControllerTelemetry"]


class ControllerTelemetry:
    """An object that writes a specific telemetry topic.

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
        self._setup()

    @property
    def DataType(self):
        """The class of data for this topic."""
        return self._DataType

    def put(self, data):
        """Write a new value for this topic.

        Parameters
        ----------
        data : ``self.DataType``
            Command parameters.
        """
        if not isinstance(data, self.DataType):
            raise TypeError(f"data={data!r} must be an instance of {self.DataType}")
        retcode = self._put_func(data)
        if retcode != self.salinfo.lib.SAL__OK:
            raise RuntimeError(f"put failed with return code {retcode} from {self._put_func_name}")

    def __repr__(self):
        return f"{type(self).__name__}({self.salinfo}, {self.name})"

    def _setup(self):
        """Get functions from salinfo and publish this topic."""
        self._put_func = getattr(self.salinfo.manager, "putSample_" + self.name)
        self._DataType = getattr(self.salinfo.lib, self.salinfo.name + "_" + self.name + "C")

        topic_name = self.salinfo.name + "_" + self.name
        retcode = self.salinfo.manager.salTelemetryPub(topic_name)
        if retcode != self.salinfo.lib.SAL__OK:
            raise RuntimeError(f"salTelemetryPub({topic_name}) failed with return code {retcode}")
