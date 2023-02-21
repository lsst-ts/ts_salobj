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
import concurrent.futures
import logging
import sys
import threading
import typing

if typing.TYPE_CHECKING:
    from .controller import Controller

MixedFutureType = asyncio.Future | concurrent.futures.Future


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
        self.loop = asyncio.get_running_loop()
        self.main_thread_id = threading.get_ident()
        self.futures: list[MixedFutureType] = list()
        super().__init__()

    def close(self) -> None:
        while self.futures:
            f = self.futures.pop(-1)
            f.cancel()
        super().close()

    def emit(self, record: logging.LogRecord) -> None:
        message = "(unknown)"
        try:
            self.format(record)
            message = record.message.encode("utf-8", "replace").decode(
                "latin-1", "replace"
            )
            if threading.get_ident() == self.main_thread_id:
                new_future: MixedFutureType = asyncio.create_task(
                    self._async_emit(
                        name=record.name,
                        level=record.levelno,
                        message=message,
                        traceback=record.exc_text or "",
                        filePath=record.pathname,
                        functionName=record.funcName,
                        lineNumber=record.lineno,
                        process=record.process or 0,
                    )
                )
            else:
                new_future = asyncio.run_coroutine_threadsafe(
                    coro=self._async_emit(
                        name=record.name,
                        level=record.levelno,
                        message=message,
                        traceback=record.exc_text or "",
                        filePath=record.pathname,
                        functionName=record.funcName,
                        lineNumber=record.lineno,
                        process=record.process or 0,
                    ),
                    loop=self.loop,
                )
            self.futures = [f for f in self.futures if not f.done()] + [new_future]
        except Exception as e:
            print(
                f"SalLogHandler.emit of level={record.levelno}, "
                f"message={message!r} failed: {e!r}",
                file=sys.stderr,
            )
        finally:
            # The Python formatter documentation suggests clearing ``exc_text``
            # after calling ``format`` to avoid problems with
            # multiple formatters that have different exception formats.
            record.exc_text = ""

    async def _async_emit(
        self,
        name: str,
        level: int,
        message: str,
        traceback: str,
        filePath: str,
        functionName: str,
        lineNumber: int,
        process: int,
    ) -> None:
        try:
            await self.controller.evt_logMessage.set_write(  # type: ignore
                name=name,
                level=level,
                message=message,
                traceback=traceback,
                filePath=filePath,
                functionName=functionName,
                lineNumber=lineNumber,
                process=process,
            )
        except Exception as e:
            print(
                f"SalLogHandler._async_emit of level={level}, "
                f"message={message!r} failed: {e!r}",
                file=sys.stderr,
            )
