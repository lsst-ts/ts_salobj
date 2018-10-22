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

__all__ = ["RemoteEvent"]

from .remote_telemetry import RemoteTelemetry


class RemoteEvent(RemoteTelemetry):
    """An object that reads a specific event topic from a SAL component.

    Parameters
    ----------
    salinfo : `salobj.SalInfo`
        SAL component information
    name : `str`
        Event topic name
    """
    def _setup(self):
        """Get functions from salinfo and subscribe to the topic."""
        self._get_newest_func_name = "getSample_logevent_" + self.name
        # TODO TSS-3196: remove the None from this getattr:
        self._get_newest_func = getattr(self.salinfo.manager, self._get_newest_func_name, None)
        self._get_oldest_func_name = "getEvent_" + self.name
        self._get_oldest_func = getattr(self.salinfo.manager, self._get_oldest_func_name)
        self._flush_func_name = "flushSamples_logevent_" + self.name
        self._flush_func = getattr(self.salinfo.manager, self._flush_func_name)
        self._DataType_name = self.salinfo.name + "_logevent_" + self.name + "C"
        self._DataType = getattr(self.salinfo.lib, self._DataType_name)

        topic_name = self.salinfo.name + "_logevent_" + self.name
        retcode = self.salinfo.manager.salEventSub(topic_name)
        if retcode != self.salinfo.lib.SAL__OK:
            raise RuntimeError(f"salEventSub({topic_name}) failed with return code {retcode}")

    def get(self):
        """Read the most recent data.

        If data has never been seen, then return None.

        If there is no callback function (which is typical)
        then this also flushes the queue.

        If there is a callback function then get will always
        return the most recently cached data. If the callback function
        is working its way through queued data then this may not be
        the most recent data.
        """
        # TODO TSS-3196: remove this implementation
        if self.has_callback:
            return self._cached_data

        while True:
            new_data = self.DataType()
            retcode = self._get_oldest_func(new_data)
            if retcode == self.salinfo.lib.SAL__OK:
                self._cached_data = new_data
            elif retcode == self.salinfo.lib.SAL__NO_UPDATES:
                return self._cached_data
            else:
                raise RuntimeError(f"get failed with retcode={retcode} from {self._get_oldest_func_name}")
