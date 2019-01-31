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

import asyncio
import logging
import logging.handlers
import queue
import sys

LOG_MESSAGES_INTERVAL = 0.05  # seconds


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

    When shutting down call ``await self.stop_logging()``.
    `BaseCsc` does this, so subclasses need not worry about it.
    """
    def __init__(self, initial_level=logging.WARNING):
        self.log = logging.getLogger(self.log_name)
        """A Python `logging.Logger`. You can safely log to it from
        different threads. Note that it can take up to
        ``LOG_MESSAGES_INTERVAL`` seconds before a log message is sent."""
        self._log_queue = queue.Queue()
        self.log.addHandler(logging.handlers.QueueHandler(self._log_queue))
        self._log_messages_task = asyncio.ensure_future(self._log_messages_loop())
        self._enable_logging = True

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

    async def _log_messages_loop(self):
        """Output log messages.
        """
        while self._enable_logging:
            try:
                msg = None
                if not self._log_queue.empty():
                    msg = self._log_queue.get_nowait()
                    self.evt_logMessage.set_put(
                        level=msg.levelno,
                        message=msg.message,
                        traceback=msg.exc_text or "",
                        force_output=True,
                    )
                await asyncio.sleep(LOG_MESSAGES_INTERVAL)
            except asyncio.CancelledError:
                break
            except Exception as e:
                what = f"on message {msg.message!r}" if msg else "before getting msg"
                print(f"Logger._log_messages_loop failed {what} with error {e!r}",
                      file=sys.stderr)

    async def stop_logging(self):
        """Call this to stop logging.

        It allows one pending log messages to be sent.
        """
        self._enable_logging = False
        await asyncio.wait_for(self._log_messages_task, LOG_MESSAGES_INTERVAL*5)
