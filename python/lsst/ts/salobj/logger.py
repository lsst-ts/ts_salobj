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

__all__ = ["Logger"]

import logging
import warnings


class SalLogHandler(logging.Handler):
    def __init__(self, controller):
        """Log handler that outputs to an event topic.

        Parameters
        ----------
        controller : `Controller`
            Controller containing atrribute evt_logEvent, a `ControllerEvent`
            with the standard CSC `logEvent` fields.
        """
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


class Logger:
    """Support logging to SAL.

    Parameters
    ----------
    index : `int`
        Index of SAL Script component. This must be unique among all
        SAL scripts that are currently running.
    descr : `str`
        Short description of what the script does, for operator display.
    remotes_dict : `dict` of `str` : `salobj.Remote` (optional)
        Dict of attribute name: `salobj.Remote`, or `None` if no remotes.
        These remotes are added as attributes of ``self`` and are also
        used to generate a list of remote names for script metadata.

    Notes
    -----
    .. _logger_sal_topics:

    Logger uses the following SAL topics:

    * command ``setLogLevel``
    * logevent ``logLevel``
    * logevent ``logMessage``

    These topics are automatically provided to any SAL component
    that uses generics, but for other SAL components you must provide
    them yourself. See ``SALGenerics.xml`` in ``ts_xml`` for the format
    of these topics.

    Override `log_name` if you want the logger name to be something
    other than the class name.
    """
    def __init__(self, initial_level=logging.WARNING):
        self.log = logging.getLogger(self.log_name)
        """A Python `logging.Logger`. You can safely log to it from
        different threads."""
        self.log.addHandler(SalLogHandler(controller=self))

    @property
    def log_name(self):
        """Get a name used for the logger.

        This default implementation returns teh class name.
        Override to return something else.
        """
        return type(self).__name__

    def do_setLogLevel(self, id_data):
        """Set logging level.

        Parameters
        ----------
        id_data : `salobj.CommandIdData`
            Logging level.
        """
        self.log.setLevel(id_data.data.level)
        self.put_log_level()

    def put_log_level(self):
        """Output the logLevel event.
        """
        self.evt_logLevel.set_put(level=self.log.getEffectiveLevel(),
                                  force_output=True)

    async def stop_logging(self):
        """Call this to stop logging.
        """
        warnings.warn("stop_logging is no longer needed", DeprecationWarning)
