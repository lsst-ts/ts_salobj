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

    def set_put(self, force_output=False, **kwargs):
        """Set one or more fields of ``self.data`` and put *if changed*.

        The data is put if it has never been set (`has_data` False), or this
        call changes the value of any field, or ``force_output`` is true.

        Parameters
        ----------
        force_output : `bool` (optional)
            If True then output the event, even if not changed.
        **kwargs : `dict` [`str`, ``any``]
            Dict of field name: new value for that field.
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

    def _setup(self):
        """Get functions from salinfo and publish this topic."""
        self._put_func = getattr(self.salinfo.manager, "logEvent_" + self.name)
        self._DataType = getattr(self.salinfo.lib, self.salinfo.name + "_logevent_" + self.name + "C")

        topic_name = self.salinfo.name + "_logevent_" + self.name
        try:  # work around lack of topic name in SAL's exception message
            self.salinfo.manager.salEventPub(topic_name)
        except Exception as e:
            raise RuntimeError(f"Could not subscribe to event {self.name}") from e
