from __future__ import annotations

# This file is part of ts_salobj.
#
# Developed for the Rubin Observatory Telescope and Site System.
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

import asyncio
import logging
import sys
import typing

if typing.TYPE_CHECKING:
    from .controller import Controller


class SalLogHandler(logging.Handler):
    """Log handler that outputs an event topic.

    Parameters
    ----------
    controller : `Controller`
        Controller with
        :ref:`Required Logger Attribute<required_logging_attributes>`
        ``evt_logEvent``.
    """

    def __init__(self, controller: Controller) -> None:
        self.controller = controller
        super().__init__()

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.format(record)
            if record.exc_text is not None:
                traceback = record.exc_text.encode("utf-8", "replace").decode(
                    "latin-1", "replace"
                )
            else:
                traceback = ""
            asyncio.create_task(
                self.controller.evt_logMessage.set_write(  # type: ignore
                    name=record.name,
                    level=record.levelno,
                    # OpenSplice requires latin-1 (utf-8 doesn't work).
                    message=record.message.encode("utf-8", "replace").decode(
                        "latin-1", "replace"
                    ),
                    traceback=traceback,
                    filePath=record.pathname,
                    functionName=record.funcName,
                    lineNumber=record.lineno,
                    process=record.process,
                )
            )
        except Exception as e:
            print(f"SalLogHandler.emit failed: {e!r}", file=sys.stderr)
        finally:
            # The Python formatter documentation suggests clearing ``exc_text``
            # after calling ``format`` to avoid problems with
            # multiple formatters that have different exception formats.
            record.exc_text = ""
