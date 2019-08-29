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

__all__ = ["SalLogHandler"]

import logging


class SalLogHandler(logging.Handler):
    """Log handler that outputs an event topic.

    Parameters
    ----------
    controller : `Controller`
        Controller with
        :ref:`Required Logger Attribute<required_logging_attributes>`
        ``evt_logEvent``.
    """
    def __init__(self, controller):
        self.controller = controller
        super().__init__()

    def emit(self, record):
        self.format(record)
        try:
            self.controller.evt_logMessage.set_put(
                level=record.levelno,
                message=record.message,
                traceback=record.exc_text or "",
                force_output=True,
            )
        finally:
            # The Python formatter documentation suggests clearing ``exc_text``
            # after calling ``format`` to avoid problems with
            # multiple formatters that have different exception formats.
            record.exc_text = ""
