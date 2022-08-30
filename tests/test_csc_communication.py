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

import asyncio
import contextlib
import itertools
import logging
import pathlib
import shutil
import subprocess
import typing
import unittest
import warnings
from collections.abc import AsyncGenerator, Iterator, Sequence

import numpy as np
import pytest
from lsst.ts import salobj, utils

# Long enough to perform any reasonable operation
# including starting a CSC or loading a script (seconds)
STD_TIMEOUT = 20
# Timeout for when we expect no new data (seconds).
NODATA_TIMEOUT = 0.5

np.random.seed(47)

index_gen = utils.index_generator()
TEST_DATA_DIR = pathlib.Path(__file__).resolve().parent / "data"
TEST_CONFIG_DIR = TEST_DATA_DIR / "configs" / "good_no_site_file"


def all_permutations(items: Sequence[typing.Any]) -> Iterator[typing.Any]:
    """Return all permutations of a list of items and of all sublists,
    including [].
    """
    for i in range(len(items) + 1):
        for val in itertools.permutations(items, r=i):
            yield val


class FailInReportFaultCsc(salobj.TestCsc):
    """A Test CSC that fails in report_summary_state when reporting fault.

    This CSC always starts up in the ENABLED state.

    Used to test for infinite loops and other issues when something
    goes wrong while going to the fault state.

    Parameters
    ----------
    index : `int`
        SAL index.
    doraise : `bool`
        Raise in report_summary_state?
        If false then call fault instead.
    report_first : `bool`
        Call super().report_summary_state first in report_summary_state?
        If false then call it last.
    """

    def __init__(self, index: int, doraise: bool, report_first: bool) -> None:
        super().__init__(index=index, initial_state=salobj.State.ENABLED)
        self.doraise = doraise
        self.report_first = report_first

    async def _report_summary_state(self) -> None:
        if self.report_first:
            await super()._report_summary_state()
        if self.summary_state == salobj.State.FAULT:
            if self.doraise:
                raise RuntimeError(
                    "Intentionally raise an exception when going to the FAULT state"
                )
            else:
                await self.fault(
                    code=10934,
                    report="a report that will be ignored",
                    traceback="a traceback that will be ignored",
                )
        if not self.report_first:
            await super()._report_summary_state()


class CommunicateTestCase(salobj.BaseCscTestCase, unittest.IsolatedAsyncioTestCase):
    def basic_make_csc(
        self,
        initial_state: salobj.State | int,
        config_dir: str | pathlib.Path | None,
        simulation_mode: int,
    ) -> salobj.BaseCsc:
        return salobj.TestCsc(
            self.next_index(),
            initial_state=initial_state,
            config_dir=config_dir,
            simulation_mode=simulation_mode,
        )

    @contextlib.asynccontextmanager
    async def make_remote(self, identity: str) -> AsyncGenerator[salobj.Remote, None]:
        """Create a remote to talk to self.csc with a specified identity.

        Uses the domain created by make_csc.

        Parameters
        ----------
        identity : `str`
            Identity for remote.

        Notes
        -----
        Adds a logging.StreamHandler if one is not already present.
        """
        domain = self.csc.domain
        original_default_identity = domain.default_identity
        try:
            domain.default_identity = identity
            remote = salobj.Remote(
                domain=domain,
                name=self.csc.salinfo.name,
                index=self.csc.salinfo.index,
            )
        finally:
            domain.default_identity = original_default_identity
        assert remote.salinfo.identity == identity
        try:
            await remote.start_task
            yield remote
        finally:
            await remote.close()

    async def test_duplicate_rejection(self) -> None:
        async with self.make_csc(initial_state=salobj.State.STANDBY):
            assert not self.csc.check_if_duplicate

            duplicate_csc = salobj.TestCsc(
                index=self.csc.salinfo.index, check_if_duplicate=True
            )
            try:
                # Change origin so heartbeat private_origin differs.
                duplicate_csc.salinfo.domain.origin += 1
                assert duplicate_csc.check_if_duplicate
                with pytest.raises(
                    salobj.ExpectedError, match="found another instance"
                ):
                    await asyncio.wait_for(duplicate_csc.done_task, timeout=STD_TIMEOUT)
            finally:
                await duplicate_csc.close()

    async def test_heartbeat(self) -> None:
        async with self.make_csc(initial_state=salobj.State.STANDBY):
            self.csc.heartbeat_interval = 0.1
            timeout = self.csc.heartbeat_interval * 5
            await self.remote.evt_heartbeat.next(flush=True, timeout=STD_TIMEOUT)
            await self.remote.evt_heartbeat.next(flush=True, timeout=timeout)
            await self.remote.evt_heartbeat.next(flush=True, timeout=timeout)
            await self.remote.evt_heartbeat.next(flush=True, timeout=timeout)

    async def test_bin_script_run(self) -> None:
        """Test running the Test CSC from the bin script.

        Note that the bin script calls class method ``amain``.
        """
        for initial_state, override in (
            (None, None),
            (salobj.State.STANDBY, None),
            (salobj.State.DISABLED, "all_fields.yaml"),
            (salobj.State.ENABLED, ""),
        ):
            index = self.next_index()
            with self.subTest(initial_state=initial_state, override=override):
                await self.check_bin_script(
                    name="Test",
                    index=index,
                    exe_name="run_test_csc",
                    initial_state=initial_state,
                    override=override,
                )

    async def test_bin_script_duplicate(self) -> None:
        index = next(index_gen)
        exe_name = "run_test_csc"
        exe_path = shutil.which(exe_name)
        if exe_path is None:
            raise AssertionError(
                f"Could not find bin script {exe_name}; did you setup or install this package?"
            )

        args = [exe_name, str(index), "--state", "standby"]

        async with salobj.Domain() as domain, salobj.Remote(
            domain=domain,
            name="Test",
            index=index,
            include=["summaryState"],
        ) as self.remote:
            process1 = await asyncio.create_subprocess_exec(
                *args,
                stderr=subprocess.PIPE,
            )
            try:
                await self.assert_next_summary_state(
                    salobj.State.STANDBY, timeout=STD_TIMEOUT
                )
                # Start a duplicate CSC and wait for it to quit early.
                process2 = await asyncio.create_subprocess_exec(
                    *args,
                    stderr=subprocess.PIPE,
                )
                try:
                    await asyncio.wait_for(process2.wait(), timeout=STD_TIMEOUT)
                    assert process2.returncode is not None
                    assert process2.returncode > 0
                    assert process2.stderr is not None  # make mypy happy
                    try:
                        errbytes = await asyncio.wait_for(
                            process2.stderr.read(), timeout=STD_TIMEOUT
                        )
                        assert b"found another instance" in errbytes
                    except asyncio.TimeoutError:
                        raise AssertionError("timed out trying to read process2 stderr")
                except asyncio.TimeoutError:
                    process2.terminate()
                    await asyncio.wait_for(process2.wait(), timeout=STD_TIMEOUT)
                    raise AssertionError("CSC 2 did not die in time.")
            finally:
                if process1.returncode is None:
                    process1.terminate()
                    await asyncio.wait_for(process1.wait(), timeout=STD_TIMEOUT)
                else:
                    # CSC 1 quit early; try to print stderr, then fail.
                    try:
                        assert process1.stderr is not None  # make mypy happy
                        errbytes = await asyncio.wait_for(
                            process1.stderr.read(), timeout=STD_TIMEOUT
                        )
                        print("Subprocess stderr: ", errbytes.decode())
                    except Exception as e:
                        print(f"Could not read subprocess stderr: {e}")
                    raise AssertionError("CSC 1 process terminated early")

    async def test_bin_script_version(self) -> None:
        """Test running the Test CSC from the bin script.

        Note that the bin script calls class method ``amain``.
        """
        index = self.next_index()
        exec_path = pathlib.Path(__file__).parents[1] / "bin" / "run_test_csc"

        process = await asyncio.create_subprocess_exec(
            str(exec_path),
            str(index),
            "--version",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(), timeout=STD_TIMEOUT
            )
            assert stdout.decode()[:-1] == salobj.__version__
            await asyncio.wait_for(process.wait(), timeout=STD_TIMEOUT)
            assert process.returncode == 0
        finally:
            if process.returncode is None:
                process.terminate()
                warnings.warn(
                    "Killed a process that was not properly terminated", RuntimeWarning
                )

    async def test_log_level(self) -> None:
        """Test that specifying a log level to make_csc works."""
        # If specified then log level is the value given.
        async with self.make_csc(
            initial_state=salobj.State.STANDBY, log_level=logging.DEBUG
        ):
            assert self.csc.log.getEffectiveLevel() == logging.DEBUG
            # Check that the remote has the same log
            # (and hence the same effective log level).
            assert self.remote.salinfo.log is self.csc.log

        max_log_level = salobj.sal_info.MAX_LOG_LEVEL
        excessive_log_level = max_log_level + 5
        async with self.make_csc(
            initial_state=salobj.State.STANDBY, log_level=excessive_log_level
        ):
            assert self.csc.log.getEffectiveLevel() == excessive_log_level

        # At this point log level is WARNING; now check that by default
        # log verbosity is increased (log level decreased) to INFO.
        async with self.make_csc(initial_state=salobj.State.STANDBY):
            assert self.csc.log.getEffectiveLevel() == max_log_level

    async def test_setArrays_command(self) -> None:
        async with self.make_csc(initial_state=salobj.State.ENABLED):
            # until the controller gets its first setArrays
            # it will not send any arrays events or telemetry
            assert not self.csc.evt_arrays.has_data
            assert not self.csc.tel_arrays.has_data
            assert not self.remote.evt_arrays.has_data
            assert not self.remote.tel_arrays.has_data
            assert self.remote.evt_arrays.get() is None
            assert self.remote.tel_arrays.get() is None

            # send the setArrays command with random data
            arrays_dict = self.csc.make_random_arrays_dict()
            await self.remote.cmd_setArrays.set_start(
                **arrays_dict, timeout=STD_TIMEOUT
            )
            cmd_data_sent = self.remote.cmd_setArrays.data

            # see if new data was broadcast correctly
            evt_data = await self.remote.evt_arrays.next(
                flush=False, timeout=STD_TIMEOUT
            )
            self.csc.assert_arrays_equal(cmd_data_sent, evt_data)
            tel_data = await self.remote.tel_arrays.next(
                flush=False, timeout=STD_TIMEOUT
            )
            self.csc.assert_arrays_equal(cmd_data_sent, tel_data)

            assert self.csc.evt_arrays.has_data
            assert self.csc.tel_arrays.has_data
            assert self.remote.evt_arrays.has_data
            assert self.remote.tel_arrays.has_data

            # also test get
            self.csc.assert_arrays_equal(cmd_data_sent, self.remote.tel_arrays.get())
            self.csc.assert_arrays_equal(cmd_data_sent, self.remote.evt_arrays.get())

    async def test_setScalars_command(self) -> None:
        async with self.make_csc(initial_state=salobj.State.ENABLED):
            # until the controller gets its first setArrays
            # it will not send any arrays events or telemetry
            assert not self.csc.evt_scalars.has_data
            assert not self.csc.tel_scalars.has_data
            assert not self.remote.evt_scalars.has_data
            assert not self.remote.tel_scalars.has_data
            assert self.remote.evt_scalars.get() is None
            assert self.remote.tel_scalars.get() is None

            # send the setScalars command with random data
            scalars_dict = self.csc.make_random_scalars_dict()
            await self.remote.cmd_setScalars.set_start(
                **scalars_dict, timeout=STD_TIMEOUT
            )
            cmd_data_sent = self.remote.cmd_setScalars.data

            # see if new data is being broadcast correctly
            evt_data = await self.remote.evt_scalars.next(
                flush=False, timeout=STD_TIMEOUT
            )
            self.csc.assert_scalars_equal(cmd_data_sent, evt_data)
            tel_data = await self.remote.tel_scalars.next(
                flush=False, timeout=STD_TIMEOUT
            )
            self.csc.assert_scalars_equal(cmd_data_sent, tel_data)

            assert self.csc.evt_scalars.has_data
            assert self.csc.tel_scalars.has_data
            assert self.remote.evt_scalars.has_data
            assert self.remote.tel_scalars.has_data

            # also test get
            self.csc.assert_scalars_equal(cmd_data_sent, self.remote.tel_scalars.get())
            self.csc.assert_scalars_equal(cmd_data_sent, self.remote.evt_scalars.get())

    async def test_fault_state_transitions(self) -> None:
        """Test CSC state transitions into fault and out again.

        Going into the fault state is done via the ``fault`` command.
        """
        for initial_state in salobj.State:
            if initial_state == salobj.State.OFFLINE:
                # Not a valid initial state
                continue
            if initial_state == salobj.State.FAULT:
                # The ``fault`` command does nothing if TestCsc
                # is already in the FAULT state
                continue
            with self.subTest(initial_state=initial_state):
                async with self.make_csc(initial_state=initial_state):
                    await self.assert_next_summary_state(initial_state)
                    await self.assert_next_sample(
                        topic=self.remote.evt_errorCode, errorCode=0, errorReport=""
                    )

                    # Issue the ``fault`` command
                    # and check the state and error code.
                    await self.remote.cmd_fault.start(timeout=STD_TIMEOUT)
                    await self.assert_next_summary_state(salobj.State.FAULT)
                    await self.assert_next_sample(
                        topic=self.remote.evt_errorCode, errorCode=1
                    )

                    # Issue the ``standby`` command to recover.
                    await self.remote.cmd_standby.start(timeout=STD_TIMEOUT)
                    await self.assert_next_summary_state(salobj.State.STANDBY)
                    await self.assert_next_sample(
                        topic=self.remote.evt_errorCode, errorCode=0, errorReport=""
                    )

    async def test_fault_method(self) -> None:
        """Test BaseCsc.fault with and without optional arguments."""
        async with self.make_csc(initial_state=salobj.State.STANDBY):
            await self.assert_next_summary_state(salobj.State.STANDBY)
            await self.assert_next_sample(
                topic=self.remote.evt_errorCode, errorCode=0, errorReport=""
            )

            code = 52
            report = "Report for error code"
            traceback = "Traceback for error code"

            # if an invalid code is specified then errorCode is not output
            # but the CSC stil goes into a FAULT state
            await self.csc.fault(code="not a valid code", report=report)
            await self.assert_next_summary_state(salobj.State.FAULT)
            with pytest.raises(asyncio.TimeoutError):
                await self.remote.evt_errorCode.next(
                    flush=False, timeout=NODATA_TIMEOUT
                )

            await self.remote.cmd_standby.start(timeout=STD_TIMEOUT)
            await self.assert_next_sample(
                topic=self.remote.evt_errorCode, errorCode=0, errorReport=""
            )
            await self.assert_next_summary_state(salobj.State.STANDBY)

            # if code is specified then errorReport is output;
            # first test with report and traceback specified,
            # then without, to make sure those values are not cached
            await self.csc.fault(code=code, report=report, traceback=traceback)
            await self.assert_next_summary_state(salobj.State.FAULT)
            await self.assert_next_sample(
                topic=self.remote.evt_errorCode,
                errorCode=code,
                errorReport=report,
                traceback=traceback,
            )

            # Try a disallowed command and check that the error report
            # is part of the traceback.
            with salobj.assertRaisesAckError(result_contains=report):
                await self.remote.cmd_wait.set_start(duration=5, timeout=STD_TIMEOUT)

            await self.remote.cmd_standby.start(timeout=STD_TIMEOUT)
            await self.assert_next_sample(
                topic=self.remote.evt_errorCode, errorCode=0, errorReport=""
            )
            await self.assert_next_summary_state(salobj.State.STANDBY)

            await self.csc.fault(code=code, report="")
            await self.assert_next_summary_state(salobj.State.FAULT)
            await self.assert_next_sample(
                topic=self.remote.evt_errorCode,
                errorCode=code,
                errorReport="",
                traceback="",
            )

            await self.remote.cmd_standby.start(timeout=STD_TIMEOUT)
            await self.assert_next_sample(
                topic=self.remote.evt_errorCode, errorCode=0, errorReport=""
            )
            await self.remote.cmd_exitControl.start(timeout=STD_TIMEOUT)

    async def test_fault_problems(self) -> None:
        """Test BaseCsc.fault when report_summary_state misbehaves."""
        for doraise, report_first in itertools.product((False, True), (False, True)):
            with self.subTest(doraise=doraise, report_first=report_first):
                index = self.next_index()
                async with FailInReportFaultCsc(
                    index=index, doraise=doraise, report_first=report_first
                ) as csc, salobj.Remote(
                    domain=csc.domain, name="Test", index=index
                ) as remote:
                    await self.assert_next_summary_state(
                        salobj.State.ENABLED, remote=remote
                    )
                    await self.assert_next_sample(
                        topic=remote.evt_errorCode, errorCode=0, errorReport=""
                    )

                    code = 51
                    report = "Report for error code"
                    traceback = "Traceback for error code"
                    await csc.fault(code=code, report=report, traceback=traceback)

                    await self.assert_next_summary_state(
                        salobj.State.FAULT, remote=remote
                    )
                    await self.assert_next_sample(
                        topic=remote.evt_errorCode,
                        errorCode=code,
                        errorReport=report,
                        traceback=traceback,
                    )

                    # make sure FAULT state and errorCode are only sent once
                    with pytest.raises(asyncio.TimeoutError):
                        await remote.evt_summaryState.next(
                            flush=False, timeout=NODATA_TIMEOUT
                        )
                    with pytest.raises(asyncio.TimeoutError):
                        await remote.evt_errorCode.next(
                            flush=False, timeout=NODATA_TIMEOUT
                        )

    async def test_make_csc_timeout(self) -> None:
        """Test that setting the timeout argument to make_csc works."""
        with pytest.raises(asyncio.TimeoutError):
            # Use such a short timeout that make_csc times out
            async with self.make_csc(initial_state=salobj.State.STANDBY, timeout=0):
                pass

    async def test_standard_state_transitions(self) -> None:
        """Test standard CSC state transitions.

        The initial state is STANDBY.
        The standard commands and associated state transitions are:

        * start: STANDBY to DISABLED
        * enable: DISABLED to ENABLED

        * disable: ENABLED to DISABLED
        * standby: DISABLED or FAULT to STANDBY
        * exitControl: STANDBY to OFFLINE (quit)
        """
        async with self.make_csc(
            initial_state=salobj.State.STANDBY, config_dir=TEST_CONFIG_DIR
        ):
            await self.check_standard_state_transitions(
                enabled_commands=("setArrays", "setScalars", "wait"),
                skip_commands=("fault",),
                override="all_fields.yaml",
            )
