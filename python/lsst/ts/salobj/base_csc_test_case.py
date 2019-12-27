# This file is part of ts_salobj.
#
# Developed for the LSST Data Management System.
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
import logging
import shutil

from . import base
from . import sal_enums
from . import testutils
from .domain import Domain
from .remote import Remote

STD_TIMEOUT = 5  # timeout for command ack
LONG_TIMEOUT = 30  # timeout for CSCs to start


class BaseCscTestCase(metaclass=abc.ABCMeta):
    """Base class for CSC tests.

    Subclasses must:

    * Inherit both from this and `asynctest.TestCase`.
    * Override `basic_make_csc` to return a CSC.

    Also we suggest:

    * Add a method ``test_standard_state_transitions`` which calls
      `check_standard_state_transitions`.
    * Add a method ``test_bin_script`` which calls `check_bin_script`,
      assuming you have a binary script to run your CSC.
    """

    _index_iter = base.index_generator()

    @abc.abstractmethod
    def basic_make_csc(self, initial_state, config_dir, simulation_mode):
        """Make and return a CSC.

        initial_state : `lsst.ts.salobj.State` or `int` (optional)
            The initial state of the CSC. Ignored except in simulation mode
            because in normal operation the initial state is the current state
            of the controller.
        config_dir : `str`
            Directory of configuration files, or None for the standard
            configuration directory (obtained from `get_default_config_dir`).
        simulation_mode : `int`
            Simulation mode.
        """
        raise NotImplementedError()

    def next_index(self):
        return next(self._index_iter)

    @contextlib.asynccontextmanager
    async def make_csc(self, initial_state,
                       config_dir=None,
                       simulation_mode=0,
                       log_level=logging.INFO):
        """Create a CSC and remote and wait for them to start.

        The csc is accessed as ``self.csc`` and the remote as ``self.remote``.

        If your CSC is indexed, we suggest you use a different index
        for each call, e.g. by using `index_generator`.

        Parameters
        ----------
        name : `str`
            Name of SAL component.
        index : `int` or `None` (optional)
            SAL component index, or 0 or None if the component is not indexed.
            A value is required if the component is indexed.
        initial_state : `lsst.ts.salobj.State` or `int` (optional)
            The initial state of the CSC. Ignored except in simulation mode
            because in normal operation the initial state is the current state
            of the controller.
        config_dir : `str` (optional)
            Directory of configuration files, or None for the standard
            configuration directory (obtained from `get_default_config_dir`).
        simulation_mode : `int` (optional)
            Simulation mode.
        log_level : `int` (optional)
            Logging level, such as `logging.INFO`.
        """
        testutils.set_random_lsst_dds_domain()
        self.csc = self.basic_make_csc(initial_state=initial_state,
                                       config_dir=config_dir,
                                       simulation_mode=simulation_mode)
        if len(self.csc.log.handlers) < 2:
            self.csc.log.addHandler(logging.StreamHandler())
            self.csc.log.setLevel(log_level)
        self.remote = Remote(domain=self.csc.domain,
                             name=self.csc.salinfo.name,
                             index=self.csc.salinfo.index)

        await asyncio.wait_for(asyncio.gather(self.csc.start_task, self.remote.start_task),
                               timeout=LONG_TIMEOUT)
        try:
            yield
        finally:
            await self.remote.close()
            await self.csc.close()

    async def assert_next_summary_state(self, state, flush=False, timeout=STD_TIMEOUT, remote=None):
        """Wait for and check the next ``summaryState`` event.

        Parameters
        ----------
        state : `lsst.ts.salobj.State` or `int`
            Desired summary state.
        flush : `bool` (optional)
            Flush the read queue before waiting?
        timeout : `float` (optional)
            Time limit for getting the data sample (sec).
        remote : `Remote` (optional)
            Remote to use; ``self.remote`` if None.
        """
        if remote is None:
            remote = self.remote
        await self.assert_next_sample(topic=remote.evt_summaryState,
                                      flush=flush,
                                      timeout=timeout,
                                      summaryState=state)

    async def assert_next_sample(self, topic, flush=False, timeout=STD_TIMEOUT, **kwargs):
        """Wait for the next data sample for the specified topic,
        check specified fields for equality, and return the data.

        Parameters
        ----------
        topic : `topics.ReadTopic`
            Topic to read, e.g. ``remote.evt_logMessage``.
        flush : `bool` (optional)
            Flush the read queue before waiting?
        timeout : `double` (optional)
            Time limit for getting the data sample (sec).
        kwargs : `dict`
            Dict of field_name: expected_value
            The specified fields will be checked for equality.

        Returns
        -------
        data : topic data type
            The data read.
        """
        data = await topic.next(flush=flush, timeout=timeout)
        for field_name, expected_value in kwargs.items():
            read_value = getattr(data, field_name, None)
            if read_value is None:
                self.fail(f"No such field {field_name} in topic {topic}")
            self.assertEqual(read_value, expected_value)
        return data

    async def check_bin_script(self, name, index, exe_name, *cmdline_args):
        """Test running the CSC command line script.

        Parameters
        ----------
        name : `str`
            Name of SAL component, e.g. "Rotator"
        index : `int` or `None`
            SAL index of component.
        exe_name : `str`
            Name of executable, e.g. "run_rotator.py"
        *cmdline_args : `List` [`str`]
            Additional command-line arguments, such as "--simulate".
        """
        exe_path = shutil.which(exe_name)
        if exe_path is None:
            self.fail(f"Could not find bin script {exe_name}; did you setup or install this package?")

        if index is None:
            process = await asyncio.create_subprocess_exec(exe_name, *cmdline_args)
        else:
            process = await asyncio.create_subprocess_exec(exe_name, *cmdline_args)
        try:
            async with Domain() as domain:
                remote = Remote(domain=domain, name=name, index=index)
                summaryState_data = await remote.evt_summaryState.next(flush=False, timeout=60)
                self.assertEqual(summaryState_data.summaryState, sal_enums.State.OFFLINE)

        finally:
            process.terminate()

    async def check_standard_state_transitions(self, enabled_commands):
        """Test standard CSC state transitions.

        Parameters
        ----------
        enabled_commands : `List` [`str`]
            List of CSC-specific commands that are valid in the enabled state.
            Need not include the standard commands, which are "disable"
            and "setLogLevel" (which is valid in any state).
        """
        # Start in STANDBY state.
        self.assertEqual(self.csc.summary_state, sal_enums.State.STANDBY)
        await self.assert_next_summary_state(sal_enums.State.STANDBY)
        await self.check_bad_commands(good_commands=("start", "exitControl", "setLogLevel"))

        # Send start; new state is DISABLED.
        await self.remote.cmd_start.start(timeout=STD_TIMEOUT)
        self.assertEqual(self.csc.summary_state, sal_enums.State.DISABLED)
        await self.assert_next_summary_state(sal_enums.State.DISABLED)
        await self.check_bad_commands(good_commands=("enable", "standby", "setLogLevel"))

        # Send enable; new state is ENABLED.
        await self.remote.cmd_enable.start(timeout=STD_TIMEOUT)
        self.assertEqual(self.csc.summary_state, sal_enums.State.ENABLED)
        await self.assert_next_summary_state(sal_enums.State.ENABLED)
        all_enabled_commands = tuple(sorted(set(("disable", "setLogLevel")) | set(enabled_commands)))
        await self.check_bad_commands(good_commands=all_enabled_commands)

        # Send disable; new state is DISABLED.
        await self.remote.cmd_disable.start(timeout=STD_TIMEOUT)
        self.assertEqual(self.csc.summary_state, sal_enums.State.DISABLED)
        await self.assert_next_summary_state(sal_enums.State.DISABLED)

        # Send standby; new state is STANDBY.
        await self.remote.cmd_standby.start(timeout=STD_TIMEOUT)
        self.assertEqual(self.csc.summary_state, sal_enums.State.STANDBY)
        await self.assert_next_summary_state(sal_enums.State.STANDBY)

        # Send exitControl; new state is OFFLINE.
        await self.remote.cmd_exitControl.start(timeout=STD_TIMEOUT)
        self.assertEqual(self.csc.summary_state, sal_enums.State.OFFLINE)
        await self.assert_next_summary_state(sal_enums.State.OFFLINE)

    async def check_bad_commands(self, bad_commands=None, good_commands=None):
        """Check that bad commands fail.

        Parameters
        ----------
        bad_commands : `List`[`str`] or `None` (optional)
            Names of bad commands to try, or None for all commands.
        good_commands : `List`[`str`] or `None` (optional)
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
            with self.subTest(command=command):
                cmd_attr = getattr(self.remote, f"cmd_{command}")
                with testutils.assertRaisesAckError(ack=sal_enums.SalRetCode.CMD_FAILED):
                    await cmd_attr.start(timeout=STD_TIMEOUT)