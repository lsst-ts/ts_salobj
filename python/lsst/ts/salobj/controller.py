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

__all__ = ["Controller", "OPTIONAL_COMMAND_NAMES"]

import asyncio
import types
import typing

from . import base
from . import type_hints
from .domain import Domain
from .sal_info import SalInfo
from .sal_log_handler import SalLogHandler
from .topics import ControllerEvent, ControllerTelemetry, ControllerCommand

# Set of generic commands that need not have an associated do_ method.
# TODO DM-17157: Remove this constant and the code that uses it.
# This requires ts_xml 10.2 or 11 and ts_sal 6. (It would have been ts_xml 10.1
# but the MT Hexapod and Rotator had unwanted enterControl commands.)
OPTIONAL_COMMAND_NAMES = set(("abort", "enterControl", "setValue", "setSimulationMode"))

# Delay before closing the domain participant (seconds).
# This gives remotes time to read final DDS messages before they disappear.
SHUTDOWN_DELAY = 1


def parse_as_prefix_and_set(items_str: str) -> typing.Tuple[str, typing.Set[str]]:
    """Parse a string as an optional +/- prefix and a set of items.

    Parameters
    ----------
    items_str : `str`
        Data string formatted as an optional prefix of "+" or "-"
        followed by a set of comma-separated items (each of which
        must not contain a comma or space).
        Whitespace is ignored after the optional prefix and after each comma.

    Returns
    -------
    prefix_data : `List` [`str`, `set`]
        A tuple of two items:
        * The prefix: "+", "-", or "" (no prefix).
        * The set of items. Each item is a `str` with no whitespace or comma.
    """
    prefix = ""
    if items_str and items_str[0] in ("+", "-"):
        prefix = items_str[0]
        items_str = items_str[1:]
    data_set = set([name.strip() for name in items_str.split(",")])
    data_set -= set([""])
    return prefix, data_set


class Controller:
    """A class that receives commands for a SAL component
    and sends telemetry and events from that component.

    This class provides much of the behavior for `BaseCsc`,
    basically everything except the standard summary states
    and associated transition commands.

    Parameters
    ----------
    name : `str`
        Name of SAL component.
    index : `int` or `None`, optional
        SAL component index, or 0 or None if the component is not indexed.
        A value is required if the component is indexed.
    do_callbacks : `bool`, optional
        Set ``do_<name>`` methods as callbacks for commands?
        If True then there must be exactly one ``do_<name>`` method
        for each command.

    Attributes
    ----------
    log : `logging.Logger`
        A logger.
    salinfo : `SalInfo`
        SAL info.
    isopen : `bool`
        Is this instance open? `True` until `close` is called.
        The instance is fully closed when done_task is done.
    start_called : `bool`
        Has the start method been called?
        The instance is fully started when start_task is done.
    done_task : `asyncio.Task`
        A task which is finished when `close` or `basic_close` is done.
    start_task : `asyncio.Task`
        A task which is finished when `start` is done,
        or to an exception if `start` fails.
    cmd_<command_name> : `topics.ControllerCommand`
        Controller command topic. There is one for each command supported by
        the SAL component.
    evt_<event_name> : `topics.ControllerEvent`
        Controller event topic. There is one for each event topic supported by
        the SAL component.
    tel_<telemetry_name> : `topics.ControllerTelemetry`
        Controller telemetry topic. There is one for each telemetry topic
        supported by the SAL component.

    Notes
    -----
    .. _writing_a_controller:

    **Writing a Controller**

    (To write a CSC see :ref:`Writing a CSC<lsst.ts.salobj-writing_a_csc>`,
    instead)

    To write a controller that is not a CSC (one that does not provide
    the standard summary states and associated state transition commands):

    * Inherit from this class.
    * Provide all
      :ref:`Required Logging Attributes<required_logging_attributes>`;
      these are automatically provided to CSCs, but not other controllers.
    * Implement `close_tasks`.

    Here is an example that makes a Test controller and displays
    the topic-related attributes, but has no code to do anything
    useful with those topics (see `TestCsc` for that)::

        include salobj

        # the index is arbitrary, but a remote must use the same index
        # to talk to this controller
        test_controller = salobj.Controller("Test", index=5)
        print(dir(test_controller))

    You should see the following topic-related attributes:

    * Commands, each an instance of `topics.ControllerCommand`:

        * ``cmd_standby``
        * ``cmd_start``
        * ... and so on for all other standard CSC commands
        * ``cmd_setArrays``
        * ``cmd_setScalars``

    * Events, each an instance of `topics.ControllerEvent`:

        * ``evt_appliedSettingsMatchStart``
        * ``evt_errorCode``
        * ... and so on for all other standard CSC events
        * ``evt_arrays``
        * ``evt_scalars``

    * Telemetry, each an instance of `topics.ControllerTelemetry`
      (note that there are no standard CSC telemetry topics):

        * ``tel_arrays``
        * ``tel_scalars``


    .. _required_logging_attributes:

    **Required Logging Attributes**

    Each `Controller` must support the following topics,
    as specified in ts_xml in ``SALGenerics.xml``:

    * setLogLevel command
    * logLevel event
    * logMessage event
    """

    def __init__(
        self,
        name: str,
        index: typing.Optional[int] = None,
        *,
        do_callbacks: bool = False,
    ) -> None:
        self.isopen = False
        self.start_called = False
        self.done_task: asyncio.Future = asyncio.Future()
        self._do_callbacks = do_callbacks

        domain = Domain()
        try:
            self.salinfo = SalInfo(domain=domain, name=name, index=index)
            new_identity = self.salinfo.name_index
            self.salinfo.identity = new_identity
            domain.default_identity = new_identity
            self.log = self.salinfo.log

            if do_callbacks:
                # This must be called after the cmd_ attributes
                # have been added.
                self._assert_do_methods_present()

            for cmd_name in self.salinfo.command_names:
                cmd = ControllerCommand(self.salinfo, cmd_name)
                setattr(self, cmd.attr_name, cmd)

            for evt_name in self.salinfo.event_names:
                evt = ControllerEvent(self.salinfo, evt_name)
                setattr(self, evt.attr_name, evt)

            for tel_name in self.salinfo.telemetry_names:
                tel = ControllerTelemetry(self.salinfo, tel_name)
                setattr(self, tel.attr_name, tel)

            for required_name in ("logMessage", "logLevel", "authList"):
                if not hasattr(self, f"evt_{required_name}"):
                    raise RuntimeError(f"{self!r} has no {required_name} event")

            self._sal_log_handler = SalLogHandler(controller=self)
            self.log.addHandler(self._sal_log_handler)

            # This task is set done when the CSC is fully started.
            # If `start` fails then the task has an exception set
            # and the CSC is not usable.
            self.start_task = asyncio.create_task(self._protected_start())

        except Exception:
            # Note: Domain.basic_close closes all its SalInfo instances.
            domain.basic_close()
            raise
        self.isopen = True

    async def _protected_start(self) -> None:
        """Call `start` and handle exceptions."""
        if self.start_called:
            raise RuntimeError("Start already called")
        self.start_called = True
        try:
            await self.start()
        except asyncio.CancelledError:
            self.log.warning("start canceled")
        except Exception as e:
            self.log.exception("start failed")
            await self.close(exception=e, cancel_start=False)
            raise

    async def start(self) -> None:
        """Finish construction."""

        # Allow each remote constructor to begin running its start method.
        await asyncio.sleep(0)

        # Wait for all remote salinfos to start.
        start_tasks = []
        for salinfo in self.domain.salinfo_set:
            if not salinfo.start_called:
                # This is either self.salinfo or (very unusual) a remote
                # constructed with start=False.
                continue
            start_tasks.append(salinfo.start_task)
        await asyncio.gather(*start_tasks)
        await self.salinfo.start()

        # Assign command callbacks; give up if this fails, since the CSC
        # will be at least partly broken.
        if self._do_callbacks:
            try:
                self._assign_cmd_callbacks()
            except Exception:
                self.log.exception(
                    "Failed in start on _assign_cmd_callbacks; quitting."
                )
                await self.close()
                return

        self.put_log_level()
        self.evt_authList.set_put(  # type: ignore
            authorizedUsers=", ".join(sorted(self.salinfo.authorized_users)),
            nonAuthorizedCSCs=", ".join(sorted(self.salinfo.non_authorized_cscs)),
        )

    @property
    def domain(self) -> Domain:
        return self.salinfo.domain

    async def close(
        self, exception: typing.Optional[Exception] = None, cancel_start: bool = True
    ) -> None:
        """Shut down, clean up resources and set done_task done.

        May be called multiple times. The first call closes the Controller;
        subsequent calls wait until the Controller is closed.

        Subclasses should override `close_tasks` instead of `close`,
        unless you have a good reason to do otherwise.

        Parameters
        ----------
        exception : `Exception`, optional
            The exception that caused stopping, if any, in which case
            the ``self.done_task`` exception is set to this value.
            Specify `None` for a normal exit, in which case
            the ``self.done_task`` result is set to `None`.
        cancel_start : `bool`, optional
            Cancel the start task? Leave this true unless calling
            this from the start task.

        Notes
        -----
        Removes the SAL log handler, calls `close_tasks` to stop
        all background tasks, pauses briefly to allow final SAL messages
        to be sent, then closes the dds domain.
        """
        if not hasattr(self, "start_task"):
            # Not fully constructed; nothing to do.
            return

        if cancel_start and not self.start_task.done():
            self.start_task.cancel()

        if not self.isopen:
            # Closed or closing (we know this instance is fully constructed
            # because we checked that start_task is exists).
            # Wait for done_task to be finished,
            # ignoring any exception. If you want to know about the exception
            # you can examine done_task yourself.
            try:
                self.log.info("Already closing; waiting for done_task")
                await self.done_task
            except Exception:
                pass
            return

        self.isopen = False
        try:
            await self.close_tasks()
        except Exception:
            self.log.exception("Controller.close_tasks failed; close continues")
        try:
            # Give remotes time to read final DDS messages before closing
            # the domain participant.
            self.log.removeHandler(self._sal_log_handler)
            await asyncio.sleep(SHUTDOWN_DELAY)
            await self.domain.close()
        except asyncio.CancelledError:
            self.domain.basic_close()
        except Exception:
            self.domain.basic_close()
            self.log.exception("Controller.close failed near the end; close continues")
        finally:
            if not self.done_task.done():
                if exception is not None:
                    self.done_task.set_exception(exception)
                else:
                    self.done_task.set_result(None)

    async def close_tasks(self) -> None:
        """Shut down pending tasks. Called by `close`.

        Perform all cleanup other than disabling logging to SAL
        and closing the dds domain.
        """
        pass

    def do_setAuthList(self, data: type_hints.BaseDdsDataType) -> None:
        """Update the authorization list.

        Parameters
        ----------
        data : ``cmd_setAuthList.DataType``
            Authorization lists.

        Notes
        -----
        Add items if the data string starts with "+", ignoring duplicates
        (both with respect to the existing items and within the data string).
        Remove items if the data string starts with "-", ignoring missing
        items (items specified for removal that do not exist).
        Ignore whitespace after each comma and after the +/- prefix.
        """
        users_prefix, users_set = parse_as_prefix_and_set(
            data.authorizedUsers,  # type: ignore
        )
        # Remove "me" from users list.
        users_set.discard(self.salinfo.domain.user_host)

        cscs_prefix, cscs_set = parse_as_prefix_and_set(
            data.nonAuthorizedCSCs,  # type: ignore
        )
        # Strip :0 suffix, if present, for consistency.
        cscs_set = {csc[:-2] if csc.endswith(":0") else csc for csc in cscs_set}

        if users_prefix == "+":
            # + prefix: add users.
            self.salinfo.authorized_users |= users_set
        elif users_prefix == "-":
            # - prefix: remove users.
            self.salinfo.authorized_users -= users_set
        else:
            # No prefix: replace users.
            self.salinfo.authorized_users = users_set

        if cscs_prefix == "+":
            # + prefix: add CSCs.
            self.salinfo.non_authorized_cscs |= cscs_set
        elif cscs_prefix == "-":
            # - prefix: remove CSCs.
            self.salinfo.non_authorized_cscs -= cscs_set
        else:
            # No prefix: replace CSCs.
            self.salinfo.non_authorized_cscs = cscs_set

        self.evt_authList.set_put(  # type: ignore
            authorizedUsers=", ".join(sorted(self.salinfo.authorized_users)),
            nonAuthorizedCSCs=", ".join(sorted(self.salinfo.non_authorized_cscs)),
            force_output=True,
        )

    def do_setLogLevel(self, data: type_hints.BaseDdsDataType) -> None:
        """Set logging level.

        Parameters
        ----------
        data : ``cmd_setLogLevel.DataType``
            Logging level.
        """
        self.log.setLevel(data.level)  # type: ignore
        self.put_log_level()

    def put_log_level(self) -> None:
        """Output the logLevel event."""
        self.evt_logLevel.set_put(level=self.log.getEffectiveLevel(), force_output=True)  # type: ignore

    def _assert_do_methods_present(self) -> None:
        """Assert that all needed do_<name> methods are present."""
        command_names = self.salinfo.command_names
        do_names = [name for name in dir(self) if name.startswith("do_")]
        supported_command_names = [name[3:] for name in do_names]
        if set(command_names) != set(supported_command_names):
            err_msgs = []
            unsupported_commands = (
                set(command_names)
                - set(supported_command_names)
                - OPTIONAL_COMMAND_NAMES
            )
            if unsupported_commands:
                needed_do_str = ", ".join(
                    f"do_{name}" for name in sorted(unsupported_commands)
                )
                err_msgs.append(f"must add {needed_do_str} methods")
            extra_commands = sorted(set(supported_command_names) - set(command_names))
            if extra_commands:
                extra_do_str = ", ".join(
                    f"do_{name}" for name in sorted(extra_commands)
                )
                err_msgs.append(f"must remove {extra_do_str} methods")
            if not err_msgs:
                return
            err_msg = " and ".join(err_msgs)
            raise TypeError(f"This class {err_msg}")

    def _assign_cmd_callbacks(self) -> None:
        """Assign each do_ method as a callback to the appropriate command.

        Must not be called until the command attributes have been added.
        """
        command_names = self.salinfo.command_names
        for cmd_name in command_names:
            cmd = getattr(self, f"cmd_{cmd_name}")
            do_method_name = f"do_{cmd_name}"
            func = getattr(self, do_method_name, None)
            if func is not None:
                cmd.callback = func
            elif cmd_name not in OPTIONAL_COMMAND_NAMES:
                raise RuntimeError(f"Can't find method {do_method_name}")
            else:

                def reject_command(data: typing.Any) -> None:
                    raise base.ExpectedError("Not supported by this CSC")

                cmd.callback = reject_command

    async def __aenter__(self) -> Controller:
        await self.start_task
        return self

    async def __aexit__(
        self,
        type: typing.Optional[typing.Type[BaseException]],
        value: typing.Optional[BaseException],
        traceback: typing.Optional[types.TracebackType],
    ) -> None:
        await self.close()
