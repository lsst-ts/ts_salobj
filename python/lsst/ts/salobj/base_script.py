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

__all__ = ["BaseScript"]

import abc
import argparse
import asyncio
import re
import signal
import sys
import types
import typing
import warnings
from collections.abc import Sequence

import yaml
from lsst.ts import utils
from lsst.ts.xml import type_hints
from lsst.ts.xml.enums.Script import (
    MetadataCoordSys,
    MetadataDome,
    MetadataRotSys,
    ScriptState,
)

from . import base, controller, validator

HEARTBEAT_INTERVAL = 5  # seconds


class StateType:
    """A class to make mypy happy with BaseScript.state"""

    def __init__(self) -> None:
        self.state: ScriptState = ScriptState.UNKNOWN
        self.last_checkpoint: str = ""
        self.reason: str = ""


class BaseScript(controller.Controller, abc.ABC):
    """Abstract base class for :ref:`lsst.ts.salobj_sal_scripts`.

    Parameters
    ----------
    index : `int`
        Index of SAL Script component. This must be non-zero
        and should be unique among all loaded SAL scripts
        (to avoid multiple scripts responding to a command).
    descr : `str`
        Short description of what the script does, for operator display.
    help : `str`, optional
        Detailed help for the script. Markdown formatting is encouraged.
        This need not duplicate descriptions in the configuration schema.

    Raises
    ------
    ValueError
        If index=0. This is prohibited because index=0 would cause
        the script to respond to commands meant for every other script.

    Attributes
    ----------
    log : `logging.Logger`
        A logger.
    done_task : `asyncio.Task`
        A task that is done when the script has fully executed.
    timestamps : `dict` [``lsst.ts.xml.enums.ScriptState``, `float`]
        Dict of script state: TAI unix timestamp.
        Used to set timestamp data in the ``script`` event.
    """

    def __init__(self, index: int, descr: str, help: str = "") -> None:
        if index == 0:
            raise ValueError("index must be nonzero")

        schema = self.get_schema()
        if schema is None:
            self.config_validator: validator.DefaultingValidator | None = None
        else:
            self.config_validator = validator.DefaultingValidator(schema=schema)
        self._run_task: asyncio.Future | None = None
        self._pause_future: asyncio.Future | None = None
        # Value incremented by `next_supplemented_group_id`
        # and cleared by do_setGroupId.
        self._sub_group_id = 0
        self._is_exiting = False
        # Delay (sec) to allow sending the final state and acknowleding
        # the command before exiting.
        self.final_state_delay = 0.3

        # The number of checkpoints seen
        self.num_checkpoints = 0

        # The name of the last checkpoint seen
        self.last_checkpoint = ""

        # A dict of state: timestamp (TAI seconds).
        self.timestamps: dict[ScriptState, float] = dict()

        self._heartbeat_task: asyncio.Future = asyncio.Future()

        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, self.signal_handler)

        super().__init__("Script", index, do_callbacks=True)

        self.evt_description.set(  # type: ignore
            classname=type(self).__name__,
            description=str(descr),
            help=str(help),
        )

    async def start(self) -> None:
        await super().start()
        self._heartbeat_task.cancel()  # Paranoia
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())

        remote_names = set()
        remote_start_tasks = []
        for salinfo in self.domain.salinfo_set:
            if salinfo is self.salinfo:
                continue
            remote_names.add(f"{salinfo.name}:{salinfo.index}")
            remote_start_tasks.append(salinfo.start_task)
        await asyncio.gather(*remote_start_tasks)

        await self.evt_state.set_write(state=ScriptState.UNCONFIGURED)  # type: ignore
        await self.evt_description.set_write(  # type: ignore
            remotes=",".join(sorted(remote_names)), force_output=True
        )

    @classmethod
    def make_from_cmd_line(cls, **kwargs: typing.Any) -> BaseScript | None:
        """Make a script from command-line arguments.

        Return None if ``--schema`` specified.

        Parameters
        ----------
        kwargs :
            Keyword arguments for the script constructor.
            Must not include ``index``.

        Raises
        ------
        RuntimeError
            If ``kwargs`` includes ``index``.
        """
        if "index" in kwargs:
            raise RuntimeError(f"index must not appear in kwargs={kwargs}")

        parser = argparse.ArgumentParser(f"Run {cls.__name__} from the command line")
        parser.add_argument(
            "index",
            type=int,
            help="Script SAL Component index; must be unique among running Scripts",
        )
        parser.add_argument(
            "--schema",
            action="store_true",
            help="Print the configuration schema to stdout and quit "
            "without running the script. "
            "The index argument is ignored, though it is still required.",
        )
        args = parser.parse_args()

        if args.schema:
            schema = cls.get_schema()
            if schema is not None:
                print(yaml.safe_dump(schema))
            return None

        return cls(index=args.index, **kwargs)

    @classmethod
    async def amain(cls, **kwargs: typing.Any) -> None:
        """Run the script from the command line.

        Parameters
        ----------
        kwargs :
            Keyword arguments for the script constructor.
            Must not include ``index``.
            Ignored (other than testing for ``index``)
            if the command specifies ``--schema``.

        Notes
        -----
        The final return code will be:

        * 0 if final state is `lsst.ts.xml.enums.Script.ScriptState.DONE`
          or `lsst.ts.xml.enums.Script.ScriptState.STOPPED`.
        * 1 if final state is anything else, or if script.done_task is an
          exception (which would be raised by the script's cleanup code).

        Issues a RuntimeWarning if script.done_task is an exception
        and the final script state is anything other than Failed.
        This should never happen.

        Raises
        ------
        RuntimeError
            If ``kwargs`` includes ``index``.
        """
        script = cls.make_from_cmd_line(**kwargs)

        if script is None:
            # printed schema and exited
            return

        try:
            await script.done_task
            await script.close()
        except Exception as e:
            # The script failed in cleanup
            if script.state.state != ScriptState.FAILED:
                warnings.warn(
                    f"Script {cls.__name__} failed in cleanup with {e!r}, "
                    f"but final state {script.state.state!r} != FAILED",
                    RuntimeWarning,
                )
            sys.exit(1)

        if script.state.state not in {ScriptState.DONE, ScriptState.STOPPED}:
            sys.exit(1)

    def signal_handler(self) -> None:
        """Handle termination signals."""
        self.log.info("Handling termination signal.")
        self.done_task.set_result(None)

    @property
    def checkpoints(self) -> typing.Any:
        """Get the checkpoints at which to pause and stop.

        Returns ``self.evt_checkpoints.data`` which has these fields:

        * ``pause``: checkpoints at which to pause, a regular expression
        * ``stop``: checkpoints at which to stop, a regular expression
        """
        return self.evt_checkpoints.data  # type: ignore

    @property
    def group_id(self) -> str:
        """Get the group ID (a `str`), or "" if not set."""
        return self.evt_state.data.groupId  # type: ignore

    @property
    def obs_id(self) -> str:
        """Get the block ID (a `str`), or "" if not set."""
        return self.evt_state.data.blockId  # type: ignore

    @obs_id.setter
    def obs_id(self, value: str) -> None:
        """Setter for the obs_id property.

        This method is provided for backward compatibility
        purposes. It will ignore trying to set the value
        of the variable and issue a warning message.

        Parameters
        ----------
        value : `str`
            Value of the obs_id, this is ignored.
        """
        message = (
            "Setting the value of obs_id attribute will be deprecated. "
            "Setting the value of this attribute is part of the BaseScript "
            "business logic and should not be done manually. "
            f"The received {value=} will be ignored."
        )
        warnings.warn(message, DeprecationWarning)
        self.log.warning(message)

    @property
    def state(self) -> StateType:
        """Get the current state.

        Returns ``self.evt_state.data``, which has these fields:

        * ``state``: `lsst.ts.xml.enums.Script.ScriptState`
            The current state.
        * ``lastCheckpoint``: `str`
            Name of most recently seen checkpoint.
        * ``reason``: `str`
            Reason for this state, if any.
        * ``numCheckpoints``: `int`
            The number of checkpoints seen.
        """
        return self.evt_state.data  # type: ignore

    @property
    def state_name(self) -> str:
        """Get the name of the current `state`.state."""
        try:
            return ScriptState(self.state.state).name
        except ValueError:
            return f"UNKNOWN({self.state.state})"

    async def set_state(
        self,
        state: ScriptState | int | None = None,
        reason: str | None = None,
        keep_old_reason: bool = False,
        force_output: bool = False,
    ) -> None:
        """Set the script state.

        Parameters
        ----------
        state : `ScriptState` or `int`, optional
            New state, or None if no change
        reason : `str`, optional
            Reason for state change. `None` for no new reason.
        keep_old_reason : `bool`
            If true, keep old reason; append the ``reason`` argument after ";"
            if it is is a non-empty string.
            If false replace with ``reason``, or "" if ``reason`` is `None`.
        force_output : `bool`, optional
            If true the output even if not changed.

        Notes
        -----
        The lastCheckpoint field is set from self.last_checkpoint,
        and the numCheckpoints field is set from self.num_checkpoints.
        """
        if state is not None:
            state = ScriptState(state)
            self.timestamps[state] = utils.current_tai()
        if keep_old_reason and reason is not None:
            sepstr = "; " if self.evt_state.data.reason else ""  # type: ignore
            reason = self.evt_state.data.reason + sepstr + reason  # type: ignore
        await self.evt_state.set_write(  # type: ignore
            state=state,
            reason=reason,
            lastCheckpoint=self.last_checkpoint,
            numCheckpoints=self.num_checkpoints,
            force_output=force_output,
        )

    async def checkpoint(self, name: str = "") -> None:
        """Await this at any "nice" point your script can be paused or stopped.

        Parameters
        ----------
        name : `str`, optional
            Name of checkpoint; "" if it has no name.

        Raises
        ------
        RuntimeError
            If the state is not `ScriptState.RUNNING`. This likely means
            you called checkpoint from somewhere other than `run`.
        RuntimeError
            If `_run_task` is `None` or done. This probably means your code
            incorrectly set the state.
        """
        if not self.state.state == ScriptState.RUNNING:
            raise RuntimeError(
                f"checkpoint error: state={self.state_name} instead of RUNNING; "
                "did you call checkpoint from somewhere other than `run`?"
            )
        if self._run_task is None:
            raise RuntimeError("checkpoint error: state is RUNNING but no run_task")
        if self._run_task.done():
            raise RuntimeError(
                "checkpoint error: state is RUNNING but run_task is done"
            )

        self.num_checkpoints += 1
        self.last_checkpoint = name

        if re.fullmatch(self.checkpoints.stop, name):
            await self.set_state(ScriptState.STOPPING)
            raise asyncio.CancelledError(
                f"stop by request: checkpoint {name} matches {self.checkpoints.stop}"
            )
        elif re.fullmatch(self.checkpoints.pause, name):
            self._pause_future = asyncio.Future()
            await self.set_state(ScriptState.PAUSED)
            await self._pause_future
            await self.set_state(ScriptState.RUNNING)
        else:
            await self.set_state(force_output=True)
            await asyncio.sleep(0.001)

    async def close_tasks(self) -> None:
        self._is_exiting = True
        await super().close_tasks()
        self._heartbeat_task.cancel()
        if self._run_task is not None:
            self._run_task.cancel()
        if self._pause_future is not None:
            self._pause_future.cancel()
        # Controller.close sets self.done_task to result=None if successful,
        # or to the exception if close raises.

    @abc.abstractmethod
    async def configure(self, config: types.SimpleNamespace) -> None:
        """Configure the script.

        Parameters
        ----------
        config : `types.SimpleNamespace`
            Configuration.

        Notes
        -----
        This method is called by `do_configure``.
        The script state will be `ScriptState.UNCONFIGURED`.
        """
        raise NotImplementedError()

    @abc.abstractmethod
    def set_metadata(self, metadata: type_hints.BaseMsgType) -> None:
        """Set metadata fields in the provided struct, given the
        current configuration.

        Parameters
        ----------
        metadata : ``self.evt_metadata.DataType()``
            Metadata to update. Set those fields for which
            you have useful information.

        Notes
        -----
        This method is called after `configure` by `do_configure`.
        The script state will be `ScriptState.UNCONFIGURED`.
        """
        raise NotImplementedError()

    @abc.abstractmethod
    async def run(self) -> None:
        """Run the script.

        Your subclass must provide an implementation, as follows:

        * At points where you support pausing call `checkpoint`.
        * Raise an exception on error. Raise `base.ExpectedError`
          to avoid logging a traceback.

        Notes
        -----
        This method is only called when the script state is
        `ScriptState.CONFIGURED`. The remaining state transitions
        are handled automatically.
        """
        raise NotImplementedError()

    @classmethod
    @abc.abstractmethod
    def get_schema(cls) -> dict[str, typing.Any] | None:
        """Return a jsonschema to validate configuration, as a `dict`.

        Please provide default values for all fields for which defaults
        make sense. This makes the script easier to use.

        If your script has no configuration then return `None`,
        in which case the ``config`` field of the ``configure`` command
        must be an empty string.
        """
        raise NotImplementedError()

    async def cleanup(self) -> None:
        """Perform final cleanup, if any.

        This method is called as the script state is exiting,
        unless the script had not yet started to run,
        or the script process is aborted by SIGTERM or SIGKILL.
        """
        pass

    def assert_state(self, action: str, states: Sequence[ScriptState]) -> None:
        """Assert that the current state is in ``states`` and the script
        is not exiting.

        Parameters
        ----------
        action : `str`
            Description of what you want to do.
        states : `list` [`lsst.ts.xml.enums.Script.ScriptState`]
            Allowed states.
        """
        if self._is_exiting:
            raise base.ExpectedError(f"Cannot {action}: script is exiting")
        if self.state.state not in states:
            states_str = ", ".join(s.name for s in states)
            raise base.ExpectedError(
                f"Cannot {action}: state={self.state_name} instead of {states_str}"
            )

    async def do_configure(self, data: type_hints.BaseMsgType) -> None:
        """Configure the currently loaded script.

        Parameters
        ----------
        data : ``cmd_configure.DataType``
            Configuration.

        Raises
        ------
        base.ExpectedError
            If ``self.state.state`` is not
            `lsst.ts.xml.enums.Script.ScriptState.UNCONFIGURED`.

        Notes
        -----
        This method does the following:

        * Parse the ``config`` field as yaml-encoded `dict` and validate it
          (including setting default values).
        * Call `configure`.
        * Set the pause and stop checkpoints.
        * Set the log level if ``data.logLevel != 0``.
        * Call `set_metadata`.
        * Output the metadata event.
        * Change the script state to
          `lsst.ts.xml.enums.Script.ScriptState.CONFIGURED`.
        """
        self.assert_state("configure", [ScriptState.UNCONFIGURED])
        config_yaml: str = data.config  # type: ignore
        try:
            if self.config_validator is None:
                if config_yaml:
                    raise RuntimeError(
                        "This script has no configuration so "
                        f"config={config_yaml} must be empty."
                    )
                config = types.SimpleNamespace()
            else:
                if config_yaml:
                    user_config_dict = yaml.safe_load(config_yaml)
                    # Delete metadata, if present
                    if user_config_dict:
                        user_config_dict.pop("metadata", None)
                else:
                    user_config_dict = {}
                full_config_dict = self.config_validator.validate(user_config_dict)
                config = types.SimpleNamespace(**full_config_dict)
            await self.configure(config)
        except Exception as e:
            errmsg = f"config({config_yaml}) failed"
            full_errmsg = f"{errmsg}: {e}"  # includes the exception
            self.log.exception(errmsg)
            await self.set_state(ScriptState.CONFIGURE_FAILED, reason=full_errmsg)
            await self._exit()
            raise base.ExpectedError(full_errmsg) from e

        await self._set_checkpoints(
            pause=data.pauseCheckpoint,  # type: ignore
            stop=data.stopCheckpoint,  # type: ignore
        )
        if data.logLevel != 0:  # type: ignore
            self.log.setLevel(data.logLevel)  # type: ignore
            await self.put_log_level()

        # initialize to vaguely reasonable values
        self.evt_metadata.set(  # type: ignore
            coordinateSystem=MetadataCoordSys.NONE,
            rotationSystem=MetadataRotSys.NONE,
            filters="",  # any
            dome=MetadataDome.EITHER,
            duration=0,
        )
        self.set_metadata(metadata=self.evt_metadata.data)  # type: ignore
        self.evt_state.set(blockId=data.blockId)  # type: ignore
        await self.evt_metadata.write()  # type: ignore
        await self.set_state(ScriptState.CONFIGURED)
        await asyncio.sleep(0.001)

    async def do_run(self, data: type_hints.BaseMsgType) -> None:
        """Run the script and quit.

        The script must have been configured and the group ID set.

        Parameters
        ----------
        data : ``cmd_run.DataType``
            Ignored.

        Raises
        ------
        base.ExpectedError
            If ``self.state.state`` is not
            `lsst.ts.xml.enums.Script.ScriptState.CONFIGURED`.
            If ``self.group_id`` is blank.
        """
        self.assert_state("run", [ScriptState.CONFIGURED])
        if not self.group_id:
            raise base.ExpectedError("Group ID not set")
        try:
            await self.set_state(ScriptState.RUNNING)
            self._run_task = asyncio.create_task(self.run())
            await self._run_task
            await self.set_state(ScriptState.ENDING)
        except asyncio.CancelledError:
            if self.state.state != ScriptState.STOPPING:
                await self.set_state(ScriptState.STOPPING)
        except Exception as e:
            if not isinstance(e, base.ExpectedError):
                self.log.exception("Error in run")
            await self.set_state(ScriptState.FAILING, reason=f"Error in run: {e}")
        await asyncio.sleep(0.001)
        await self._exit()

    async def do_resume(self, data: type_hints.BaseMsgType) -> None:
        """Resume the currently paused script.

        Parameters
        ----------
        data : ``cmd_resume.DataType``
            Ignored.

        Raises
        ------
        base.ExpectedError
            If ``self.state.state`` is not
            `lsst.ts.xml.enums.Script.ScriptState.PAUSED`.
        """
        self.assert_state("resume", [ScriptState.PAUSED])
        if self._pause_future is None or self._pause_future.done():
            return
        self._pause_future.set_result(None)

    async def do_setCheckpoints(self, data: type_hints.BaseMsgType) -> None:
        """Set or clear the checkpoints at which to pause and stop.

        This command is deprecated. Please set the checkpoints
        using the `configure` command.

        Parameters
        ----------
        data : ``cmd_setCheckpoints.DataType``
            Names of checkpoints for pausing and stopping, each a single
            regular expression; "" for no checkpoints, ".*" for all.

        Raises
        ------
        base.ExpectedError
            If ``self.state.state`` is not one of:

            * `lsst.ts.xml.enums.Script.ScriptState.UNCONFIGURED`
            * `lsst.ts.xml.enums.Script.ScriptState.CONFIGURED`
            * `lsst.ts.xml.enums.Script.ScriptState.RUNNING`
            * `lsst.ts.xml.enums.Script.ScriptState.PAUSED`
        """
        self.assert_state(
            "setCheckpoints",
            [
                ScriptState.UNCONFIGURED,
                ScriptState.CONFIGURED,
                ScriptState.RUNNING,
                ScriptState.PAUSED,
            ],
        )
        await self._set_checkpoints(pause=data.pause, stop=data.stop)  # type: ignore

    async def do_setGroupId(self, data: type_hints.BaseMsgType) -> None:
        """Set or clear the group_id attribute.

        The script must be in the Configured state.
        This command may be called multiple times. It is typically called
        when the script reaches the top position on the script queue.

        Parameters
        ----------
        data : ``cmd_setGroupId.DataType``
            Group ID, or "" to clear the group ID.

        Raises
        ------
        base.ExpectedError
            If ``state.state`` is not
            `lsst.ts.xml.enums.Script.ScriptState.CONFIGURED`.
        """
        self.assert_state("setGroupId", [ScriptState.CONFIGURED])
        await self.evt_state.set_write(groupId=data.groupId, force_output=True)  # type: ignore
        self._sub_group_id = 0

    async def do_stop(self, data: type_hints.BaseMsgType) -> None:
        """Stop the script.

        Parameters
        ----------
        data : ``cmd_stop.DataType``
            Ignored.

        Notes
        -----
        This is a no-op if the script is already exiting.
        This does not wait for _exit to run.
        """
        if self._is_exiting:
            return
        if self._run_task is not None and not self._run_task.done():
            self._run_task.cancel()
        else:
            await self.set_state(state=ScriptState.STOPPING)
            await self._exit()

    def next_supplemented_group_id(self) -> str:
        """Return the group ID supplemented with a new subgroup.

        The returned string has this format: f"{self.group_id}#{subgroup_id}",
        where ``subgroup_id`` is an integer that starts at 1
        and is incremented for every call to this method.

        Raises
        ------
        RuntimeError
            If there is no group ID.
        """
        if not self.group_id:
            raise RuntimeError("No group ID")
        self._sub_group_id += 1
        return f"{self.group_id}#{self._sub_group_id}"

    async def _set_checkpoints(self, *, pause: str, stop: str) -> None:
        """Set the pause and stop checkpoint fields and output the event.

        Parameters
        ----------
        pause : `str`
            Checkpoint(s) at which to pause, as a regular expression.
            "" to not pause at any checkpoint; "*" to pause at all checkpoints.
        stop : `str`
            Checkpoint(s) at which to stop, as a regular expression.
            "" to not stop at any checkpoint; "*" to stop at all checkpoints.

        Raises
        ------
        lsst.ts.base.ExpectedError
            If pause or stop are not valid regular expressions.
        """
        try:
            re.compile(pause)
        except Exception as e:
            raise base.ExpectedError(f"pause={pause!r} not a valid regex: {e}")
        try:
            re.compile(stop)
        except Exception as e:
            raise base.ExpectedError(f"stop={stop!r} not a valid regex: {e}")
        await self.evt_checkpoints.set_write(pause=pause, stop=stop, force_output=True)  # type: ignore

    async def _heartbeat_loop(self) -> None:
        """Output heartbeat at regular intervals."""
        while True:
            try:
                await asyncio.sleep(HEARTBEAT_INTERVAL)
                await self.evt_heartbeat.write()  # type: ignore
            except asyncio.CancelledError:
                break
            except Exception:
                self.log.exception("Heartbeat output failed")

    async def _exit(self) -> None:
        """Call cleanup (if the script was run) and exit the script."""
        if self._is_exiting:
            return
        self._is_exiting = True
        try:
            if self._run_task is not None:
                await self.cleanup()
            self._heartbeat_task.cancel()

            reason = None
            final_state = {
                ScriptState.ENDING: ScriptState.DONE,
                ScriptState.STOPPING: ScriptState.STOPPED,
                ScriptState.FAILING: ScriptState.FAILED,
                ScriptState.CONFIGURE_FAILED: ScriptState.CONFIGURE_FAILED,
            }.get(self.state.state)
            if final_state is None:
                reason = f"unexpected state for _exit {self.state_name}"
                final_state = ScriptState.FAILED

            self.log.info(f"Setting final state to {final_state!r}")
            await self.set_state(final_state, reason=reason, keep_old_reason=True)
            asyncio.create_task(self.close())
        except Exception as e:
            if not isinstance(e, base.ExpectedError):
                self.log.exception("Error in run")
            await self.set_state(
                ScriptState.FAILED, reason=f"failed in _exit: {e}", keep_old_reason=True
            )
            asyncio.create_task(self.close(exception=e))
