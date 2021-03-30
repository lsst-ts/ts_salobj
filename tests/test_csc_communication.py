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
import subprocess
import unittest
import warnings

import numpy as np

from lsst.ts import salobj

# Long enough to perform any reasonable operation
# including starting a CSC or loading a script (seconds)
STD_TIMEOUT = 60
# Timeout for when we expect no new data (seconds).
NODATA_TIMEOUT = 0.1

np.random.seed(47)

index_gen = salobj.index_generator()
TEST_DATA_DIR = TEST_CONFIG_DIR = pathlib.Path(__file__).resolve().parent / "data"
TEST_CONFIG_DIR = TEST_DATA_DIR / "config"


def all_permutations(items):
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

    def __init__(self, index, doraise, report_first):
        super().__init__(index=index, initial_state=salobj.State.ENABLED)
        self.doraise = doraise
        self.report_first = report_first

    def report_summary_state(self):
        if self.report_first:
            super().report_summary_state()
        if self.summary_state == salobj.State.FAULT:
            if self.doraise:
                raise RuntimeError(
                    "Intentionally raise an exception when going to the FAULT state"
                )
            else:
                self.fault(
                    code=10934,
                    report="a report that will be ignored",
                    traceback="a traceback that will be ignored",
                )
        if not self.report_first:
            super().report_summary_state()


class CommunicateTestCase(salobj.BaseCscTestCase, unittest.IsolatedAsyncioTestCase):
    def basic_make_csc(self, initial_state, config_dir, simulation_mode):
        return salobj.TestCsc(
            self.next_index(),
            initial_state=initial_state,
            config_dir=config_dir,
            simulation_mode=simulation_mode,
        )

    @contextlib.asynccontextmanager
    async def make_remote(
        self,
        identity,
    ):
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
        self.assertEqual(remote.salinfo.identity, identity)
        try:
            await remote.start_task
            yield remote
        finally:
            await remote.close()

    async def test_authorization(self):
        """Test authorization.

        For simplicity this test calls setAuthList without a +/- prefix.
        The prefix is tested elsewhere.
        """
        async with self.make_csc(initial_state=salobj.State.ENABLED):
            # TODO DM-26605 remove this line as no longer needed:
            self.csc.authorize = True
            await self.assert_next_sample(
                self.remote.evt_authList,
                authorizedUsers="",
                nonAuthorizedCSCs="",
            )

            domain = self.csc.salinfo.domain

            # Note that self.csc and self.remote have the same user_host.
            csc_user_host = domain.user_host

            # Make a remote that pretends to be from a different CSC
            # and test non-authorized CSCs
            other_name_index = "Script:5"
            async with self.make_remote(identity=other_name_index) as other_csc_remote:

                all_csc_names = ["ATDome", "Hexapod:1", other_name_index]
                for csc_names in all_permutations(all_csc_names):
                    csc_names_str = ", ".join(csc_names)
                    with self.subTest(csc_names_str=csc_names_str):
                        await self.remote.cmd_setAuthList.set_start(
                            nonAuthorizedCSCs=csc_names_str, timeout=STD_TIMEOUT
                        )
                        await self.assert_next_sample(
                            self.remote.evt_authList,
                            authorizedUsers="",
                            nonAuthorizedCSCs=", ".join(sorted(csc_names)),
                        )
                        if other_name_index in csc_names:
                            # A blocked CSC; this should fail.
                            with salobj.assertRaisesAckError(
                                ack=salobj.SalRetCode.CMD_NOPERM
                            ):
                                await other_csc_remote.cmd_wait.set_start(
                                    duration=0, timeout=STD_TIMEOUT
                                )
                        else:
                            # Not a blocked CSC; this should work.
                            await other_csc_remote.cmd_wait.set_start(
                                duration=0, timeout=STD_TIMEOUT
                            )

                        # My user_host should work regardless of
                        # non-authorized CSCs.
                        await self.remote.cmd_wait.set_start(
                            duration=0, timeout=STD_TIMEOUT
                        )

                        # Disabling authorization should always work
                        self.csc.cmd_wait.authorize = False
                        try:
                            await other_csc_remote.cmd_wait.set_start(
                                duration=0, timeout=STD_TIMEOUT
                            )
                        finally:
                            self.csc.cmd_wait.authorize = True

            # Test authorized users that are not me.
            # Reported auth users should always be in alphabetical order;
            # test this by sending users NOT in alphabetical order.
            all_other_user_hosts = [f"notme{i}{csc_user_host}" for i in (3, 2, 1)]
            other_user_host = all_other_user_hosts[1]

            async with self.make_remote(identity=other_user_host) as other_user_remote:
                for auth_user_hosts in all_permutations(all_other_user_hosts):
                    users_str = ", ".join(auth_user_hosts)
                    with self.subTest(users_str=users_str):
                        await self.remote.cmd_setAuthList.set_start(
                            authorizedUsers=users_str,
                            nonAuthorizedCSCs="",
                            timeout=STD_TIMEOUT,
                        )
                        await self.assert_next_sample(
                            self.remote.evt_authList,
                            authorizedUsers=", ".join(sorted(auth_user_hosts)),
                            nonAuthorizedCSCs="",
                        )
                        if other_user_host in auth_user_hosts:
                            # An allowed user; this should work.
                            await other_user_remote.cmd_wait.set_start(
                                duration=0, timeout=STD_TIMEOUT
                            )
                        else:
                            # Not an allowed user; this should fail.
                            with salobj.assertRaisesAckError(
                                ack=salobj.SalRetCode.CMD_NOPERM
                            ):
                                await other_user_remote.cmd_wait.set_start(
                                    duration=0, timeout=STD_TIMEOUT
                                )

                        # Temporarily disable authorization and try again;
                        # this should always work.
                        self.csc.cmd_wait.authorize = False
                        try:
                            await other_user_remote.cmd_wait.set_start(
                                duration=0, timeout=STD_TIMEOUT
                            )
                        finally:
                            self.csc.cmd_wait.authorize = True

                        # My user_host should work regardless of
                        # authorized users.
                        self.remote.salinfo.domain.identity = csc_user_host
                        await self.remote.cmd_wait.set_start(
                            duration=0, timeout=STD_TIMEOUT
                        )

    async def test_set_auth_list_prefix(self):
        """Test the setAuthList command with a +/- prefix"""
        async with self.make_csc(initial_state=salobj.State.ENABLED):
            await self.assert_next_sample(
                self.remote.evt_authList,
                authorizedUsers="",
                nonAuthorizedCSCs="",
            )

            all_csc_names = ["Test:5", "ATDome:0", "ATDome"]
            expected_cscs_set = set()
            # Test adding non-authorized CSCs.
            # Test that a trailing :0 is stripped (so, in this test
            # setAuthList treats ATDome:0 and ATDome as the same CSC).
            # Reported non-auth CSCs should always be in alphabetical order;
            # test this by sending CSC names NOT in alphabetical order.
            for i in range(len(all_csc_names)):
                csc_names = all_csc_names[:i]
                # Compute a variant of csc_names with trailing :0 stripped
                # and use that for the expected output from the authList event.
                nonzero_csc_names = [
                    csc[:-2] if csc.endswith(":0") else csc for csc in csc_names
                ]
                expected_cscs_set |= set(nonzero_csc_names)
                add_some_str = "+ " + ", ".join(csc_names)
                await self.remote.cmd_setAuthList.set_start(
                    nonAuthorizedCSCs=add_some_str, timeout=STD_TIMEOUT
                )
                await self.assert_next_sample(
                    self.remote.evt_authList,
                    authorizedUsers="",
                    nonAuthorizedCSCs=", ".join(sorted(expected_cscs_set)),
                )

            # Removing CSCs should have the expected effect
            for i in range(len(all_csc_names)):
                csc_names = all_csc_names[:i]
                # Compute a variant of csc_names with trailing :0 stripped
                # and use that for the expected output from the authList event.
                nonzero_csc_names = [
                    csc[:-2] if csc.endswith(":0") else csc for csc in csc_names
                ]
                expected_cscs_set -= set(nonzero_csc_names)
                remove_some_str = "- " + ", ".join(csc_names)
                await self.remote.cmd_setAuthList.set_start(
                    nonAuthorizedCSCs=remove_some_str, timeout=STD_TIMEOUT
                )
                await self.assert_next_sample(
                    self.remote.evt_authList,
                    authorizedUsers="",
                    nonAuthorizedCSCs=", ".join(sorted(expected_cscs_set)),
                )

            # Test setting authorized users.
            # Test that user = csc_user_host (the CSC's user_host) is ignored.
            # Reported auth users should always be in alphabetical order;
            # test this by sending users NOT in alphabetical order.
            csc_user_host = salobj.get_user_host()
            all_users_hosts = [csc_user_host] + [
                f"notme{i}{csc_user_host}" for i in (3, 2, 1)
            ]
            expected_user_set = set()
            # Test adding authorized users; only users other than "me"
            # are actually added.
            for i in range(len(all_users_hosts)):
                user_names = all_users_hosts[:i]
                expected_user_set |= set(user_names)
                expected_user_set -= {csc_user_host}
                add_some_str = "+ " + ", ".join(user_names)
                await self.remote.cmd_setAuthList.set_start(
                    authorizedUsers=add_some_str, timeout=STD_TIMEOUT
                )
                await self.assert_next_sample(
                    self.remote.evt_authList,
                    authorizedUsers=", ".join(sorted(expected_user_set)),
                    nonAuthorizedCSCs="",
                )

            # Removing authorized users should have the expected effect
            for i in range(len(all_users_hosts)):
                user_names = all_users_hosts[:i]
                expected_user_set -= set(user_names)
                remove_some_str = "- " + ", ".join(user_names)
                await self.remote.cmd_setAuthList.set_start(
                    authorizedUsers=remove_some_str, timeout=STD_TIMEOUT
                )
                await self.assert_next_sample(
                    self.remote.evt_authList,
                    authorizedUsers=", ".join(sorted(expected_user_set)),
                    nonAuthorizedCSCs="",
                )

    async def test_heartbeat(self):
        async with self.make_csc(initial_state=salobj.State.STANDBY):
            self.csc.heartbeat_interval = 0.1
            await self.remote.evt_heartbeat.next(flush=True, timeout=STD_TIMEOUT)
            await self.remote.evt_heartbeat.next(flush=True, timeout=0.2)
            await self.remote.evt_heartbeat.next(flush=True, timeout=0.2)
            await self.remote.evt_heartbeat.next(flush=True, timeout=0.2)

    async def test_bin_script_run(self):
        """Test running the Test CSC from the bin script.

        Note that the bin script calls class method ``amain``.
        """
        for initial_state, settings_to_apply in (
            (None, None),
            (salobj.State.STANDBY, None),
            (salobj.State.DISABLED, "all_fields.yaml"),
            (salobj.State.ENABLED, ""),
        ):
            index = self.next_index()
            with self.subTest(
                initial_state=initial_state, settings_to_apply=settings_to_apply
            ):
                await self.check_bin_script(
                    name="Test",
                    index=index,
                    exe_name="run_test_csc.py",
                    initial_state=initial_state,
                    settings_to_apply=settings_to_apply,
                )

    async def test_bin_script_version(self):
        """Test running the Test CSC from the bin script.

        Note that the bin script calls class method ``amain``.
        """
        salobj.set_random_lsst_dds_partition_prefix()
        index = self.next_index()
        exec_path = pathlib.Path(__file__).parents[1] / "bin" / "run_test_csc.py"

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
            self.assertEqual(stdout.decode()[:-1], salobj.__version__)
            await asyncio.wait_for(process.wait(), timeout=STD_TIMEOUT)
            self.assertEqual(process.returncode, 0)
        finally:
            if process.returncode is None:
                process.terminate()
                warnings.warn("Killed a process that was not properly terminated")

    async def test_log_level(self):
        """Test that specifying a log level to make_csc works."""
        # If specified then log level is the value given.
        async with self.make_csc(
            initial_state=salobj.State.STANDBY, log_level=logging.DEBUG
        ):
            self.assertEqual(self.csc.log.getEffectiveLevel(), logging.DEBUG)

        async with self.make_csc(
            initial_state=salobj.State.STANDBY, log_level=logging.WARNING
        ):
            self.assertEqual(self.csc.log.getEffectiveLevel(), logging.WARNING)

        # At this point log level is WARNING; now check that by default
        # log verbosity is increased (log level decreased) to INFO.
        async with self.make_csc(initial_state=salobj.State.STANDBY):
            self.assertEqual(self.csc.log.getEffectiveLevel(), logging.INFO)

    async def test_setArrays_command(self):
        async with self.make_csc(initial_state=salobj.State.ENABLED):
            # until the controller gets its first setArrays
            # it will not send any arrays events or telemetry
            self.assertFalse(self.csc.evt_arrays.has_data)
            self.assertFalse(self.csc.tel_arrays.has_data)
            self.assertFalse(self.remote.evt_arrays.has_data)
            self.assertFalse(self.remote.tel_arrays.has_data)
            self.assertIsNone(self.remote.evt_arrays.get())
            self.assertIsNone(self.remote.tel_arrays.get())

            # send the setArrays command with random data
            cmd_data_sent = self.csc.make_random_cmd_arrays()
            await self.remote.cmd_setArrays.start(cmd_data_sent, timeout=STD_TIMEOUT)

            # see if new data was broadcast correctly
            evt_data = await self.remote.evt_arrays.next(
                flush=False, timeout=STD_TIMEOUT
            )
            self.csc.assert_arrays_equal(cmd_data_sent, evt_data)
            tel_data = await self.remote.tel_arrays.next(
                flush=False, timeout=STD_TIMEOUT
            )
            self.csc.assert_arrays_equal(cmd_data_sent, tel_data)

            self.assertTrue(self.csc.evt_arrays.has_data)
            self.assertTrue(self.csc.tel_arrays.has_data)
            self.assertTrue(self.remote.evt_arrays.has_data)
            self.assertTrue(self.remote.tel_arrays.has_data)

            # also test get
            self.csc.assert_arrays_equal(cmd_data_sent, self.remote.tel_arrays.get())
            self.csc.assert_arrays_equal(cmd_data_sent, self.remote.evt_arrays.get())

    async def test_setScalars_command(self):
        async with self.make_csc(initial_state=salobj.State.ENABLED):
            # until the controller gets its first setArrays
            # it will not send any arrays events or telemetry
            self.assertFalse(self.csc.evt_scalars.has_data)
            self.assertFalse(self.csc.tel_scalars.has_data)
            self.assertFalse(self.remote.evt_scalars.has_data)
            self.assertFalse(self.remote.tel_scalars.has_data)
            self.assertIsNone(self.remote.evt_scalars.get())
            self.assertIsNone(self.remote.tel_scalars.get())

            # send the setScalars command with random data
            cmd_data_sent = self.csc.make_random_cmd_scalars()
            await self.remote.cmd_setScalars.start(cmd_data_sent, timeout=STD_TIMEOUT)

            # see if new data is being broadcast correctly
            evt_data = await self.remote.evt_scalars.next(
                flush=False, timeout=STD_TIMEOUT
            )
            self.csc.assert_scalars_equal(cmd_data_sent, evt_data)
            tel_data = await self.remote.tel_scalars.next(
                flush=False, timeout=STD_TIMEOUT
            )
            self.csc.assert_scalars_equal(cmd_data_sent, tel_data)

            self.assertTrue(self.csc.evt_scalars.has_data)
            self.assertTrue(self.csc.tel_scalars.has_data)
            self.assertTrue(self.remote.evt_scalars.has_data)
            self.assertTrue(self.remote.tel_scalars.has_data)

            # also test get
            self.csc.assert_scalars_equal(cmd_data_sent, self.remote.tel_scalars.get())
            self.csc.assert_scalars_equal(cmd_data_sent, self.remote.evt_scalars.get())

    async def test_fault_state_transitions(self):
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

    async def test_fault_method(self):
        """Test BaseCsc.fault with and without optional arguments."""
        async with self.make_csc(initial_state=salobj.State.STANDBY):
            await self.assert_next_summary_state(salobj.State.STANDBY)
            with self.assertRaises(asyncio.TimeoutError):
                await self.remote.evt_errorCode.next(
                    flush=False, timeout=NODATA_TIMEOUT
                )

            code = 52
            report = "Report for error code"
            traceback = "Traceback for error code"

            # if an invalid code is specified then errorCode is not output
            # but the CSC stil goes into a FAULT state
            self.csc.fault(code="not a valid code", report=report)
            await self.assert_next_summary_state(salobj.State.FAULT)
            with self.assertRaises(asyncio.TimeoutError):
                await self.remote.evt_errorCode.next(
                    flush=False, timeout=NODATA_TIMEOUT
                )

            await self.remote.cmd_standby.start(timeout=STD_TIMEOUT)
            await self.assert_next_summary_state(salobj.State.STANDBY)

            # if code is specified then errorReport is output;
            # first test with report and traceback specified,
            # then without, to make sure those values are not cached
            self.csc.fault(code=code, report=report, traceback=traceback)
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
            await self.assert_next_summary_state(salobj.State.STANDBY)

            self.csc.fault(code=code, report="")
            await self.assert_next_summary_state(salobj.State.FAULT)
            await self.assert_next_sample(
                topic=self.remote.evt_errorCode,
                errorCode=code,
                errorReport="",
                traceback="",
            )

            await self.remote.cmd_standby.start(timeout=STD_TIMEOUT)
            await self.remote.cmd_exitControl.start(timeout=STD_TIMEOUT)

    async def test_fault_problems(self):
        """Test BaseCsc.fault when report_summary_state misbehaves."""
        index = self.next_index()
        for doraise, report_first in itertools.product((False, True), (False, True)):
            with self.subTest(doraise=doraise, report_first=report_first):
                async with FailInReportFaultCsc(
                    index=index, doraise=doraise, report_first=report_first
                ) as csc, salobj.Remote(
                    domain=csc.domain, name="Test", index=index
                ) as remote:
                    await self.assert_next_summary_state(
                        salobj.State.ENABLED, remote=remote
                    )

                    code = 51
                    report = "Report for error code"
                    traceback = "Traceback for error code"
                    csc.fault(code=code, report=report, traceback=traceback)

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
                    with self.assertRaises(asyncio.TimeoutError):
                        await remote.evt_summaryState.next(
                            flush=False, timeout=NODATA_TIMEOUT
                        )
                    with self.assertRaises(asyncio.TimeoutError):
                        await remote.evt_errorCode.next(
                            flush=False, timeout=NODATA_TIMEOUT
                        )

    async def test_make_csc_timeout(self):
        """Test that setting the timeout argument to make_csc works."""
        with self.assertRaises(asyncio.TimeoutError):
            # Use such a short timeout that make_csc times out
            async with self.make_csc(initial_state=salobj.State.STANDBY, timeout=0):
                pass

    async def test_standard_state_transitions(self):
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
                settingsToApply="all_fields",
            )


if __name__ == "__main__":
    unittest.main()
