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

__all__ = ["BaseCscTestCase"]

import abc
import asyncio
import contextlib
import enum
import os
import pathlib
import shutil
import subprocess
import typing
from collections.abc import AsyncGenerator, Sequence

from lsst.ts import utils
from lsst.ts.xml import sal_enums, type_hints

from . import base_csc, testutils
from .csc_utils import get_expected_summary_states
from .domain import Domain
from .remote import Remote
from .topics.read_topic import ReadTopic

# Standard timeout (sec)
# Long to avoid unnecessary timeouts on slow CI systems.
STD_TIMEOUT = 30

# Timeout when constructing a CSC with duplicate checking enabled.
STD_WITH_DUPLICATE_CHECK_TIMEOUT = STD_TIMEOUT + 10


class BaseCscTestCase(metaclass=abc.ABCMeta):
    """Base class for CSC tests.

    Subclasses must:

    * Inherit both from this and `unittest.IsolatedAsyncioTestCase`.
    * Override `basic_make_csc` to return a CSC.

    Also we suggest:

    * Add a method ``test_standard_state_transitions`` which calls
      `check_standard_state_transitions`.
    * Add a method ``test_bin_script`` which calls `check_bin_script`,
      assuming you have a binary script to run your CSC.
    """

    _index_iter = utils.index_generator()
    # The following attribute allows users to enforce randomizing topic
    # subname. You can set it up in setUpClass, by setting
    # cls._randomize_topic_subname=True.
    _randomize_topic_subname = False

    def run(self, result: typing.Any = None) -> None:  # type: ignore
        """Set a random LSST_TOPIC_SUBNAME
        and set LSST_SITE=test for every test.

        Unlike setUp, a user cannot forget to override this.
        (This is also a good place for context managers).
        """
        testutils.set_test_topic_subname(randomize=self._randomize_topic_subname)

        # set LSST_SITE using os.environ instead of utils.modify_environ
        # so that check_bin_script works.
        os.environ["LSST_SITE"] = "test"
        super().run(result)  # type: ignore

    @abc.abstractmethod
    def basic_make_csc(
        self,
        initial_state: sal_enums.State | int | None,
        config_dir: str | pathlib.Path | None,
        simulation_mode: int,
        **kwargs: typing.Any,
    ) -> base_csc.BaseCsc:
        """Make and return a CSC.

        Parameters
        ----------
        initial_state : `lsst.ts.salobj.State` or `int`
            The initial state of the CSC.
        config_dir : `str` or `pathlib.Path` or `None`
            Directory of configuration files, or None for the standard
            configuration directory (obtained from
            `ConfigureCsc._get_default_config_dir`).
        simulation_mode : `int`
            Simulation mode.
        kwargs : `dict`
            Extra keyword arguments, if needed.
        """
        raise NotImplementedError()

    def next_index(self) -> int:
        """Get the next SAL index."""
        return next(self._index_iter)

    @contextlib.asynccontextmanager
    async def make_csc(
        self,
        initial_state: sal_enums.State | int | None = None,
        config_dir: str | pathlib.Path | None = None,
        simulation_mode: int = 0,
        log_level: int | None = None,
        timeout: float = STD_TIMEOUT,
        **kwargs: typing.Any,
    ) -> AsyncGenerator[None, None]:
        """Create a CSC and remote and wait for them to start.

        The csc is accessed as ``self.csc`` and the remote as ``self.remote``.

        The topics in `self.remote` will queue all telemetry and events
        from when the CSC is constructed, with one exception:
        self.remote.evt_summaryState will only have the final summary state,
        because earlier values are read and checked against the expected
        startup states. (The final summary state is left queued for backwards
        compatibility.)

        Parameters
        ----------
        name : `str`
            Name of SAL component.
        initial_state : `lsst.ts.salobj.State` or `int`, optional
            The initial state of the CSC.
            If None use the CSC's default initial state.
        config_dir : `str`, optional
            Directory of configuration files, or `None` (the default)
            for the standard configuration directory (obtained from
            `ConfigureCsc._get_default_config_dir`).
        simulation_mode : `int`, optional
            Simulation mode. Defaults to 0 because not all CSCs support
            simulation. However, tests of CSCs that support simulation
            will almost certainly want to set this nonzero.
        log_level : `int` or `None`, optional
            Logging level, such as `logging.INFO`.
            If `None` then do not set the log level, leaving the default
            behavior of `SalInfo`: increase the log level to INFO.
        timeout : `float`, optional
            Time limit for the CSC to start (seconds).
        **kwargs : `dict`, optional
            Extra keyword arguments for `basic_make_csc`.
            For a configurable CSC this may include ``override``,
            especially if ``initial_state`` is DISABLED or ENABLED.

        Raises
        ------
        asyncio.TimeoutError
            If the CSC cannot be constructed within the specified time limit.
        """
        items_to_close: list[base_csc.BaseCsc | Remote] = []
        try:
            # Create the CSC, but prevent it from starting
            # until the remote is fully started
            self.csc = self.basic_make_csc(
                initial_state=initial_state,
                config_dir=config_dir,
                simulation_mode=simulation_mode,
                **kwargs,
            )
            self.csc.delay_start_event.clear()
            items_to_close.append(self.csc)

            # Create and start the remote
            self.remote = Remote(
                domain=self.csc.domain,
                name=self.csc.salinfo.name,
                index=self.csc.salinfo.index,
            )
            items_to_close.append(self.remote)
            await asyncio.wait_for(self.remote.start_task, timeout=timeout)

            # Allow the CSC to start.
            self.csc.delay_start_event.set()
            await asyncio.wait_for(self.csc.start_task, timeout=timeout)

            if log_level is not None:
                self.csc.log.setLevel(log_level)

            await asyncio.wait_for(
                asyncio.gather(self.csc.start_task, self.remote.start_task),
                timeout=timeout,
            )

            if initial_state != self.csc.default_initial_state:
                assert initial_state is not None
                # Check all expected summary states expect the final state.
                # That is omitted for backwards compatibility.
                expected_states = get_expected_summary_states(
                    initial_state=self.csc.default_initial_state,
                    final_state=initial_state,
                )[:-1]
                for state in expected_states:
                    await self.assert_next_summary_state(state)

            yield
        except Exception as e:
            print(f"BaseCscTestCase.make_csc failed: {e!r}")
            raise
        finally:
            for item in items_to_close:
                await item.close()

    async def assert_next_summary_state(
        self,
        state: sal_enums.State,
        flush: bool = False,
        timeout: float = STD_TIMEOUT,
        remote: Remote | None = None,
    ) -> None:
        """Wait for and check the next ``summaryState`` event.

        Parameters
        ----------
        state : `lsst.ts.salobj.State` or `int`
            Desired summary state.
        flush : `bool`, optional
            Flush the read queue before waiting?
        timeout : `float`, optional
            Time limit for getting the data sample (sec).
        remote : `Remote`, optional
            Remote to use; ``self.remote`` if None.

        Raises
        ------
        asyncio.TimeoutError
            If summary state is not seen within the specified time limit.
        """
        if remote is None:
            remote = self.remote
        await self.assert_next_sample(
            topic=remote.evt_summaryState,  # type: ignore
            flush=flush,
            timeout=timeout,
            summaryState=state,
        )

    async def assert_next_sample(
        self,
        topic: ReadTopic,
        flush: bool = False,
        timeout: float = STD_TIMEOUT,
        **kwargs: typing.Any,
    ) -> type_hints.BaseMsgType:
        """Wait for the next data sample for the specified topic,
        check specified fields for equality, and return the data.

        Parameters
        ----------
        topic : `topics.ReadTopic`
            Topic to read, e.g. ``remote.evt_logMessage``.
        flush : `bool`, optional
            Flush the read queue before waiting?
        timeout : `double`, optional
            Time limit for getting the data sample (sec).
        kwargs : `dict`
            Dict of field_name: expected_value
            The specified fields will be checked for equality.

        Returns
        -------
        data : topic data type
            The data read.

        Raises
        ------
        asyncio.TimeoutError
            If no message is available within the specified time limit.
        """
        data = await topic.next(flush=flush, timeout=timeout)
        for field_name, expected_value in kwargs.items():
            read_value = getattr(data, field_name, None)
            if read_value is None:
                raise AssertionError(f"No such field {field_name} in topic {topic}")
            if isinstance(expected_value, enum.IntEnum):
                try:
                    read_value = type(expected_value)(read_value)
                except Exception:
                    pass
            assert (
                read_value == expected_value
            ), f"Failed on field {field_name}: read {read_value!r} != expected {expected_value!r}"
        return data

    async def check_bin_script(
        self,
        name: str,
        index: int,
        exe_name: str,
        default_initial_state: sal_enums.State = sal_enums.State.STANDBY,
        initial_state: sal_enums.State | None = None,
        override: str | None = None,
        cmdline_args: Sequence[str] = (),
        timeout: float = STD_WITH_DUPLICATE_CHECK_TIMEOUT,
    ) -> None:
        """Test running the CSC command line script.

        Parameters
        ----------
        name : `str`
            Name of SAL component, e.g. "Rotator"
        index : `int` or `None`
            SAL index of component.
        exe_name : `str`
            Name of executable, e.g. "run_rotator.py"
        default_initial_state : `lsst.ts.salobj.State`, optional
            The default initial state of the CSC.
            Ignored unless `initial_state` is None.
        initial_state : `lsst.ts.salobj.State` or `int` or `None`, optional
            The desired initial state of the CSC; used to specify
            the ``--state`` command-argument.
        override : `str` or `None`, optional
            Value for the ``--override`` command-line argument,
            which is omitted if override is None.
        cmdline_args : `List` [`str`]
            Additional command-line arguments, such as "--simulate".
        timeout : `float`, optional
            Time limit for the CSC to start and output
            the summaryState event.

        Raises
        ------
        asyncio.TimeoutError
            If the CSC cannot be started within the specified time limit.
        """
        exe_path = shutil.which(exe_name)
        if exe_path is None:
            raise AssertionError(
                f"Could not find bin script {exe_name}; did you setup or install this package?"
            )

        args = [exe_name]
        if index not in (None, 0):
            args += [str(index)]
        if initial_state is None:
            expected_states = [default_initial_state]
        else:
            args += ["--state", initial_state.name.lower()]
            expected_states = get_expected_summary_states(
                initial_state=default_initial_state,
                final_state=initial_state,
            )
        if override is not None:
            args += ["--override", override]
        args += cmdline_args

        async with Domain() as domain, Remote(
            domain=domain, name=name, index=index
        ) as self.remote:
            print("check_bin_script running:", " ".join(args))
            process = await asyncio.create_subprocess_exec(
                *args,
                stderr=subprocess.PIPE,
            )
            try:
                for state in expected_states:
                    await self.assert_next_summary_state(state, timeout=timeout)
                if override:
                    # The override should appear in
                    # evt_configurationApplied.configurations
                    data = await self.assert_next_sample(
                        topic=self.remote.evt_configurationApplied,  # type: ignore
                    )
                    assert override in data.configurations  # type: ignore
            finally:
                if process.returncode is None:
                    process.terminate()
                    await asyncio.wait_for(process.wait(), timeout=STD_TIMEOUT)
                else:
                    print("Warning: subprocess had already quit.")
                    try:
                        assert process.stderr is not None  # make mypy happy
                        errbytes = await process.stderr.read()
                        print("Subprocess stderr: ", errbytes.decode())
                    except Exception as e:
                        print(f"Could not read subprocess stderr: {e}")

    async def check_standard_state_transitions(
        self,
        enabled_commands: Sequence[str],
        skip_commands: Sequence[str] | None = None,
        override: str = "",
        timeout: float = STD_TIMEOUT,
    ) -> None:
        """Test standard CSC state transitions.

        Parameters
        ----------
        enabled_commands : `List` [`str`]
            List of CSC-specific commands that are valid in the enabled state.
            Need not include the standard commands, which are "disable"
            and "setLogLevel" (which is valid in any state).
        skip_commands : `List` [`str`] or `None`, optional
            List of commands to skip.
        override : `str`, optional
            Configuration override file to apply when the CSC is taken
            from state `State.STANDBY` to `State.DISABLED`.
        timeout : `float`, optional
            Time limit for state transition commands (seconds).

        Raises
        ------
        asyncio.TimeoutError
            If any state transition takes longer than the specified time limit.

        Notes
        -----
        ``timeout`` is only used for state transition commands that
        are expected to succceed. ``STD_TIMEOUT`` is used for things
        that should happen quickly:

        * Commands that should fail, due to the CSC being in the wrong state.
        * The ``summaryState`` event after each state transition:
        """
        enabled_commands = tuple(enabled_commands)
        skip_commands = tuple(skip_commands) if skip_commands else ()

        # Start in STANDBY state.
        assert self.csc.summary_state == sal_enums.State.STANDBY
        await self.assert_next_summary_state(sal_enums.State.STANDBY)
        await self.check_bad_commands(
            good_commands=("start", "exitControl", "setAuthList", "setLogLevel")
            + skip_commands
        )

        # Send start; new state is DISABLED.
        await self.remote.cmd_start.set_start(  # type: ignore
            configurationOverride=override, timeout=timeout
        )
        assert self.csc.summary_state == sal_enums.State.DISABLED
        await self.assert_next_summary_state(sal_enums.State.DISABLED)
        await self.check_bad_commands(
            good_commands=("enable", "standby", "setAuthList", "setLogLevel")
            + skip_commands
        )

        # Send enable; new state is ENABLED.
        await self.remote.cmd_enable.start(timeout=timeout)  # type: ignore
        assert self.csc.summary_state == sal_enums.State.ENABLED
        await self.assert_next_summary_state(sal_enums.State.ENABLED)
        all_enabled_commands = tuple(
            sorted(
                set(("disable", "setAuthList", "setLogLevel")) | set(enabled_commands)
            )
        )
        await self.check_bad_commands(
            good_commands=all_enabled_commands + skip_commands
        )

        # Send disable; new state is DISABLED.
        await self.remote.cmd_disable.start(timeout=timeout)  # type: ignore
        assert self.csc.summary_state == sal_enums.State.DISABLED
        await self.assert_next_summary_state(sal_enums.State.DISABLED)

        # Send standby; new state is STANDBY.
        await self.remote.cmd_standby.start(timeout=timeout)  # type: ignore
        assert self.csc.summary_state == sal_enums.State.STANDBY
        await self.assert_next_summary_state(sal_enums.State.STANDBY)

        # Send exitControl; new state is OFFLINE.
        await self.remote.cmd_exitControl.start(timeout=timeout)  # type: ignore
        assert self.csc.summary_state == sal_enums.State.OFFLINE
        await self.assert_next_summary_state(sal_enums.State.OFFLINE)

    async def check_bad_commands(
        self,
        bad_commands: Sequence[str] | None = None,
        good_commands: Sequence[str] | None = None,
    ) -> None:
        """Check that bad commands fail.

        Parameters
        ----------
        bad_commands : `List`[`str`] or `None`, optional
            Names of bad commands to try, or None for all commands.
        good_commands : `List`[`str`] or `None`, optional
            Names of good commands to skip, or None to skip none.

        Notes
        -----
        If a command appears in both lists, it is considered a good command,
        so it is skipped.
        """
        if bad_commands is None:
            bad_commands = self.remote.salinfo.command_names
        if good_commands is None:
            good_commands = ()
        commands = self.remote.salinfo.command_names
        for command in commands:
            if command in good_commands:
                continue
            with self.subTest(command=command):  # type: ignore
                cmd_attr = getattr(self.remote, f"cmd_{command}")
                with testutils.assertRaisesAckError(
                    ack=sal_enums.SalRetCode.CMD_FAILED
                ):
                    await cmd_attr.start(timeout=STD_TIMEOUT)
