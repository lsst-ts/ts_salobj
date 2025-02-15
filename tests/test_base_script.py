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
import logging
import pathlib
import subprocess
import types
import typing
import unittest
import warnings
from collections.abc import Iterable

import pytest
import yaml
from lsst.ts import salobj, utils
from lsst.ts.xml.enums.Script import ScriptState
from lsst.ts.xml.type_hints import BaseMsgType

# Long enough to perform any reasonable operation
# including starting a CSC or loading a script (seconds)
STD_TIMEOUT = 20

index_gen = utils.index_generator()

TEST_DATA_DIR = pathlib.Path(__file__).parent / "data"


class NonConfigurableScript(salobj.BaseScript):
    """A script that takes no configuration.

    In other words get_schema returns None.
    """

    def __init__(self, index: int) -> None:
        super().__init__(index=index, descr="Non-configurable script")
        self.config: types.SimpleNamespace | None = None
        self.run_called = False
        self.set_metadata_called = False

    @classmethod
    def get_schema(cls) -> None:
        return None

    async def configure(self, config: types.SimpleNamespace | None) -> None:
        self.config = config

    async def run(self) -> None:
        self.run_called = True

    def set_metadata(self, metadata: BaseMsgType) -> None:
        self.set_metadata_called = True


class BaseScriptTestCase(unittest.IsolatedAsyncioTestCase):
    """Test `BaseScript` using simple subclasses `TestScript` and
    `NonConfigurableScript`.
    """

    def setUp(self) -> None:
        salobj.set_test_topic_subname()
        self.index = next(index_gen)

    async def configure_and_check(
        self,
        script: salobj.TestScript,
        log_level: int = 0,
        pause_checkpoint: str = "",
        stop_checkpoint: str = "",
        **kwargs: typing.Any,
    ) -> None:
        """Configure a script by calling ``do_configure`` and set group ID
        and check the result.

        Parameters
        ----------
        script : `TestScript`
            A test script
        log_level : `int`, optional
            Log level as a `logging` level,
            or 0 to leave the script's log level unchanged.
        pause_checkpoint : `str`, optional
            Checkpoint(s) at which to pause, as a regular expression.
            "" to not pause at any checkpoint; "*" to pause at all checkpoints.
        stop_checkpoint : `str`, optional
            Checkpoint(s) at which to stop, as a regular expression.
            "" to not stop at any checkpoint; "*" to stop at all checkpoints.
        kwargs : `dict`
            A dict with one or more of the following keys:

            * ``wait_time`` (a float): how long to wait, in seconds
            * ``fail_run`` (bool): fail before waiting?
            * ``fail_cleanup`` (bool): fail in cleanup?

            If no values are specified then ``script.do_configure``
            is called with an empty string.

        Raises
        ------
        AssertionError
            If the script's ``config``, log level, or checkpoints
            do not match what was commanded.

        salobj.ExpectedError
            If ``kwargs`` includes other keywords than those
            documented above.
        """
        if kwargs:
            # strip to remove final trailing newline
            config = yaml.safe_dump(kwargs).strip()
        else:
            config = ""
        configure_data = script.cmd_configure.DataType()
        configure_data.config = config
        configure_data.logLevel = log_level
        configure_data.pauseCheckpoint = pause_checkpoint
        configure_data.stopCheckpoint = stop_checkpoint
        await script.do_configure(configure_data)
        assert script.config.wait_time == kwargs.get("wait_time", 0)
        assert script.config.fail_run == kwargs.get("fail_run", False)
        assert script.config.fail_cleanup == kwargs.get("fail_cleanup", False)
        if log_level != 0:
            assert script.log.getEffectiveLevel() == log_level
        assert script.evt_checkpoints.data.pause == pause_checkpoint
        assert script.evt_checkpoints.data.stop == stop_checkpoint
        assert script.state.state == ScriptState.CONFIGURED

        # Cannot run: groupId is not set.
        assert script.group_id == ""
        run_data = script.cmd_run.DataType()
        with pytest.raises(salobj.ExpectedError):
            await script.do_run(run_data)

        # Set and check group ID.
        group_id = "arbitrary group ID"
        group_id_data = script.cmd_setGroupId.DataType()
        group_id_data.groupId = group_id
        await script.do_setGroupId(group_id_data)
        assert script.group_id == group_id
        assert script.evt_state.data.groupId == group_id

    def test_get_schema(self) -> None:
        schema = salobj.TestScript.get_schema()
        assert isinstance(schema, dict)
        for name in ("$schema", "$id", "title", "description", "type", "properties"):
            assert name in schema
        assert not schema["additionalProperties"]

    def test_non_configurable_script_get_schema(self) -> None:
        schema = NonConfigurableScript.get_schema()
        assert schema is None

    async def test_non_configurable_script_empty_config(self) -> None:
        """Test configuring the script with no data. This should work."""
        async with NonConfigurableScript(index=self.index) as script:
            data = script.cmd_configure.DataType()
            await script.do_configure(data)
            assert len(script.config.__dict__) == 0
            assert script.set_metadata_called
            assert not script.run_called

    async def test_non_configurable_script_invalid_config(self) -> None:
        async with NonConfigurableScript(index=self.index) as script:
            data = script.cmd_configure.DataType()
            data.config = "invalid: should be empty"
            with pytest.raises(salobj.ExpectedError):
                await script.do_configure(data)
            assert script.config is None

    async def test_setCheckpoints(self) -> None:
        async with salobj.TestScript(index=self.index) as script:
            # try valid values
            data = script.cmd_setCheckpoints.DataType()
            for pause, stop in (
                ("something", ""),
                ("", "something_else"),
                (".*", "start|end"),
            ):
                data.pause = pause
                data.stop = stop
                await script.do_setCheckpoints(data)
                assert script.checkpoints.pause == pause
                assert script.checkpoints.stop == stop

            # try with at least one checkpoint not a valid regex;
            # do_setCheckpoints should raise and not change the checkpoints
            initial_pause = "initial_pause"
            initial_stop = "initial_stop"
            data.pause = initial_pause
            data.stop = initial_stop
            await script.do_setCheckpoints(data)
            for bad_pause, bad_stop in (("(", ""), ("", "("), ("[", "[")):
                data.pause = bad_pause
                data.stop = bad_stop
                with pytest.raises(salobj.ExpectedError):
                    await script.do_setCheckpoints(data)
                assert script.checkpoints.pause == initial_pause
                assert script.checkpoints.stop == initial_stop

    async def test_set_state_and_attributes(self) -> None:
        async with salobj.TestScript(index=self.index) as script:
            # check keep_old_reason argument of set_state
            reason = "initial reason"
            additional_reason = "check append"
            await script.set_state(reason=reason)
            await script.set_state(reason=additional_reason, keep_old_reason=True)
            assert script.state.reason == reason + "; " + additional_reason

            bad_state = 1 + max(s.value for s in ScriptState)
            with pytest.raises(ValueError):
                await script.set_state(bad_state)
            script.state.state = bad_state
            assert script.state_name == f"UNKNOWN({bad_state})"
            assert not script._is_exiting

            await script.set_state(ScriptState.CONFIGURED)
            assert script.state_name == "CONFIGURED"

            # check assert_states
            all_states = set(ScriptState)
            for state in ScriptState:
                await script.set_state(state)
                assert script.state_name == state.name
                with pytest.raises(salobj.ExpectedError):
                    script.assert_state(
                        "should fail because state not in allowed states",
                        all_states - set([state]),
                    )

                script.assert_state("should pass", [state])
                script._is_exiting = True
                with pytest.raises(salobj.ExpectedError):
                    script.assert_state("should fail because exiting", [state])
                script._is_exiting = False

                # check that checkpoint is prohibited
                # unless state is RUNNING
                if state == ScriptState.RUNNING:
                    continue
                with pytest.raises(RuntimeError):
                    await script.checkpoint("foo")

            assert not script.done_task.done()

    async def test_next_supplemented_group_id(self) -> None:
        async with salobj.TestScript(index=self.index) as script:
            await self.configure_and_check(script)
            group_id = script.group_id
            for i in range(5):
                # Format some other way than an f-string,
                # in order to have a different implementation than Script
                desired_supplemented_id = "%s#%s" % (group_id, i + 1)
                supplemented_id = script.next_supplemented_group_id()
                assert supplemented_id == desired_supplemented_id

            # Set a new group ID. This should reset the subgroup counter.
            new_group_id = group_id + " modified"
            group_id_data = script.cmd_setGroupId.DataType()
            group_id_data.groupId = new_group_id
            await script.do_setGroupId(group_id_data)

            for i in range(5):
                desired_supplemented_id = "%s#%s" % (new_group_id, i + 1)
                supplemented_id = script.next_supplemented_group_id()
                assert supplemented_id == desired_supplemented_id

            # Clear the group ID; getting a supplemened group ID should fail
            group_id_data = script.cmd_setGroupId.DataType()
            group_id_data.groupId = ""
            await script.do_setGroupId(group_id_data)
            with pytest.raises(RuntimeError):
                script.next_supplemented_group_id()

    async def test_configure_failed(self) -> None:
        async with salobj.TestScript(index=self.index) as script:
            # Cannot run in UNCONFIGURED state.
            run_data = script.cmd_run.DataType()
            with pytest.raises(salobj.ExpectedError):
                await script.do_run(run_data)

            # Test configure with data for a non-existent argument.
            configure_data = script.cmd_configure.DataType()
            configure_data.config = "no_such_arg: 1"
            with pytest.raises(salobj.ExpectedError):
                await script.do_configure(configure_data)
            assert script.state.state == ScriptState.CONFIGURE_FAILED
            await asyncio.wait_for(script.done_task, timeout=STD_TIMEOUT)

        async with salobj.TestScript(index=self.index) as script:
            # Test configure with invalid yaml.
            configure_data = script.cmd_configure.DataType()
            configure_data.config = "a : : 2"
            with pytest.raises(salobj.ExpectedError):
                await script.do_configure(configure_data)
            assert script.state.state == ScriptState.CONFIGURE_FAILED
            await asyncio.wait_for(script.done_task, timeout=STD_TIMEOUT)

        async with salobj.TestScript(index=self.index) as script:
            # Test configure with yaml that makes a string, not a dict.
            configure_data = script.cmd_configure.DataType()
            configure_data.config = "just_a_string"
            with pytest.raises(salobj.ExpectedError):
                await script.do_configure(configure_data)
            assert script.state.state == ScriptState.CONFIGURE_FAILED
            await asyncio.wait_for(script.done_task, timeout=STD_TIMEOUT)

        async with salobj.TestScript(index=self.index) as script:
            # Test configure with yaml that makes a list, not a dict.
            configure_data = script.cmd_configure.DataType()
            configure_data.config = "['not', 'a', 'dict']"
            with pytest.raises(salobj.ExpectedError):
                await script.do_configure(configure_data)
            assert script.state.state == ScriptState.CONFIGURE_FAILED
            await asyncio.wait_for(script.done_task, timeout=STD_TIMEOUT)

    async def test_pause(self) -> None:
        async with salobj.TestScript(index=self.index) as script:
            # Configure the script with nonexistent checkpoints,
            # to test that the configure command handles checkpoints at all.
            wait_time = 0.5
            # Specify a log level that is not the default (which is INFO)
            # and is only slightly more verbose than INFO.
            log_level = logging.INFO - 1
            prelim_pause_checkpoint = "preliminary nonexistent pause checkpoint"
            prelim_stop_checkpoint = "preliminary nonexistent stop checkpoint"
            await self.configure_and_check(
                script,
                wait_time=wait_time,
                log_level=log_level,
                pause_checkpoint=prelim_pause_checkpoint,
                stop_checkpoint=prelim_stop_checkpoint,
            )
            assert script.state.numCheckpoints == 0

            # Set a pause checkpoint that exists.
            setCheckpoints_data = script.cmd_setCheckpoints.DataType()
            start_checkpoint = "start"
            end_checkpoint = "end"
            nonexistent_checkpoint = "nonexistent checkpoint"
            setCheckpoints_data.pause = start_checkpoint
            setCheckpoints_data.stop = nonexistent_checkpoint
            await script.do_setCheckpoints(setCheckpoints_data)
            assert script.checkpoints.pause == start_checkpoint
            assert script.checkpoints.stop == nonexistent_checkpoint

            # Run the script.
            run_data = script.cmd_run.DataType()
            run_task = asyncio.create_task(script.do_run(run_data))
            niter = 0
            while script.state.state != ScriptState.PAUSED:
                niter += 1
                await asyncio.sleep(0)
            assert script.state.lastCheckpoint == start_checkpoint
            assert script.state.numCheckpoints == 1
            assert script.checkpoints.pause == start_checkpoint
            assert script.checkpoints.stop == nonexistent_checkpoint
            resume_data = script.cmd_resume.DataType()
            await script.do_resume(resume_data)
            await asyncio.wait_for(run_task, timeout=STD_TIMEOUT)
            await asyncio.wait_for(script.done_task, timeout=STD_TIMEOUT)
            assert script.state.lastCheckpoint == end_checkpoint
            assert script.state.numCheckpoints == 2
            duration = (
                script.timestamps[ScriptState.ENDING]
                - script.timestamps[ScriptState.RUNNING]
            )
            desired_duration = wait_time
            print(f"test_pause duration={duration:0.2f}")
            assert abs(duration - desired_duration) < 0.2

    async def test_stop_at_checkpoint(self) -> None:
        async with salobj.TestScript(index=self.index) as script:
            wait_time = 0.1
            await self.configure_and_check(script, wait_time=wait_time)

            # set a stop checkpoint
            setCheckpoints_data = script.cmd_setCheckpoints.DataType()
            end_checkpoint = "end"
            setCheckpoints_data.stop = end_checkpoint
            await script.do_setCheckpoints(setCheckpoints_data)
            assert script.checkpoints.pause == ""
            assert script.checkpoints.stop == end_checkpoint

            run_data = script.cmd_run.DataType()
            await asyncio.wait_for(script.do_run(run_data), timeout=STD_TIMEOUT)
            await asyncio.wait_for(script.done_task, timeout=STD_TIMEOUT)
            assert script.state.lastCheckpoint == end_checkpoint
            assert script.state.numCheckpoints == 2
            assert script.state.state == ScriptState.STOPPED
            duration = (
                script.timestamps[ScriptState.STOPPING]
                - script.timestamps[ScriptState.RUNNING]
            )
            # waited and then stopped at the "end" checkpoint
            desired_duration = wait_time
            print(f"test_stop_at_checkpoint duration={duration:0.2f}")
            assert abs(duration - desired_duration) < 0.2

    async def test_stop_while_paused(self) -> None:
        async with salobj.TestScript(index=self.index) as script:
            wait_time = 5
            await self.configure_and_check(script, wait_time=wait_time)

            # set a stop checkpoint
            setCheckpoints_data = script.cmd_setCheckpoints.DataType()
            start_checkpoint = "start"
            setCheckpoints_data.pause = start_checkpoint
            await script.do_setCheckpoints(setCheckpoints_data)
            assert script.checkpoints.pause == start_checkpoint
            assert script.checkpoints.stop == ""

            run_data = script.cmd_run.DataType()
            asyncio.create_task(script.do_run(run_data))
            while script.state.lastCheckpoint != "start":
                await asyncio.sleep(0)
            assert script.state.state == ScriptState.PAUSED
            stop_data = script.cmd_stop.DataType()
            await script.do_stop(stop_data)
            await asyncio.wait_for(script.done_task, timeout=STD_TIMEOUT)
            assert script.state.lastCheckpoint == start_checkpoint
            assert script.state.numCheckpoints == 1
            assert script.state.state == ScriptState.STOPPED
            duration = (
                script.timestamps[ScriptState.STOPPING]
                - script.timestamps[ScriptState.RUNNING]
            )
            # the script ran quickly because we stopped the script
            # just as soon as it paused at the "start" checkpoint
            desired_duration = 0
            print(f"test_stop_while_paused duration={duration:0.2f}")
            assert duration > 0.0
            assert abs(duration - desired_duration) < 0.2

    async def test_stop_while_running(self) -> None:
        async with salobj.TestScript(index=self.index) as script:
            wait_time = 5
            pause_time = 0.5
            await self.configure_and_check(script, wait_time=wait_time)

            start_checkpoint = "start"
            run_data = script.cmd_run.DataType()
            asyncio.create_task(script.do_run(run_data))
            while script.state.lastCheckpoint != start_checkpoint:
                await asyncio.sleep(0)
            assert script.state.state == ScriptState.RUNNING
            await asyncio.sleep(pause_time)
            stop_data = script.cmd_stop.DataType()
            await script.do_stop(stop_data)
            await asyncio.wait_for(script.done_task, timeout=STD_TIMEOUT)
            assert script.state.lastCheckpoint == start_checkpoint
            assert script.state.numCheckpoints == 1
            assert script.state.state == ScriptState.STOPPED
            duration = (
                script.timestamps[ScriptState.STOPPING]
                - script.timestamps[ScriptState.RUNNING]
            )
            # we waited `pause_time` seconds after the "start" checkpoint
            desired_duration = pause_time
            print(f"test_stop_while_running duration={duration:0.2f}")
            assert abs(duration - desired_duration) < 0.2

    async def check_fail(self, fail_run: bool) -> None:
        """Check failure in run or cleanup.

        Parameters
        ----------
        fail_run : `bool`
            If True then fail in the script's ``run`` method,
            else fail in the script's ``cleanup`` method.
        """
        wait_time = 0.1
        async with salobj.TestScript(index=self.index) as script:
            if fail_run:
                await self.configure_and_check(script, fail_run=True)
            else:
                await self.configure_and_check(script, fail_cleanup=True)

            run_data = script.cmd_run.DataType()
            await asyncio.wait_for(script.do_run(run_data), timeout=STD_TIMEOUT)
            if fail_run:
                await asyncio.wait_for(script.done_task, timeout=STD_TIMEOUT)
                assert script.state.lastCheckpoint == "start"
                assert script.state.numCheckpoints == 1
                assert script.state.state == ScriptState.FAILED
                end_run_state = ScriptState.FAILING
            else:
                with pytest.raises(salobj.ExpectedError):
                    await asyncio.wait_for(script.done_task, timeout=STD_TIMEOUT)
                assert script.state.lastCheckpoint == "end"
                assert script.state.numCheckpoints == 2
                end_run_state = ScriptState.ENDING
            duration = (
                script.timestamps[end_run_state]
                - script.timestamps[ScriptState.RUNNING]
            )
            # if fail_run then failed before waiting,
            # otherwise failed after
            desired_duration = 0 if fail_run else wait_time
            print(f"test_fail duration={duration:0.3f} with fail_run={fail_run}")
            assert abs(duration - desired_duration) < 0.2

    async def test_fail_run(self) -> None:
        await self.check_fail(fail_run=True)

    async def test_fail_cleanup(self) -> None:
        await self.check_fail(fail_run=False)

    async def test_zero_index(self) -> None:
        with pytest.raises(ValueError):
            salobj.TestScript(index=0)

    async def test_remote(self) -> None:
        """Test a script with remotes.

        Check that the remote_names attribute of the description event
        is properly set, and that the remotes have started when the
        script has started.
        """

        class ScriptWithRemotes(salobj.TestScript):
            def __init__(self, index: int, remote_indices: Iterable[int]) -> None:
                super().__init__(index, descr="Script with remotes")
                remotes = []
                # use remotes that read history here, to check that
                # script.start_task waits for the start_task in each remote.
                for rind in remote_indices:
                    remotes.append(
                        salobj.Remote(domain=self.domain, name="Test", index=rind)
                    )
                self.remotes = remotes

        remote_indices = [5, 7]
        async with ScriptWithRemotes(self.index, remote_indices) as script:
            remote_name_list = [f"Test:{ind}" for ind in remote_indices]
            desired_remote_names = ",".join(sorted(remote_name_list))
            assert script.evt_description.data.remotes == desired_remote_names
            for remote in script.remotes:
                assert remote.start_task.done()

    async def test_script_process(self) -> None:
        """Test running a script as a subprocess."""
        script_path = TEST_DATA_DIR / "script1"

        for fail in (None, "fail_run", "fail_cleanup"):
            with self.subTest(fail=fail):
                async with salobj.Domain() as domain:
                    index = next(index_gen)
                    remote = salobj.Remote(
                        domain=domain,
                        name="Script",
                        index=index,
                        evt_max_history=0,
                    )
                    await asyncio.wait_for(remote.start_task, timeout=STD_TIMEOUT)

                    async def logcallback(data: BaseMsgType) -> None:
                        print(f"message={data.message}")

                    remote.evt_logMessage.callback = logcallback

                    process = await asyncio.create_subprocess_exec(
                        str(script_path), str(index)
                    )
                    try:
                        assert process.returncode is None

                        descr = await remote.evt_description.next(
                            flush=False, timeout=STD_TIMEOUT
                        )
                        assert descr.classname == "TestScript"
                        assert descr.description == "test script"
                        assert "test script that waits" in descr.help
                        assert descr.remotes == ""

                        state = await remote.evt_state.next(
                            flush=False, timeout=STD_TIMEOUT
                        )
                        assert state.state == ScriptState.UNCONFIGURED
                        assert state.groupId == ""

                        logLevel_data = await remote.evt_logLevel.next(
                            flush=False, timeout=STD_TIMEOUT
                        )
                        assert logLevel_data.level == logging.INFO

                        wait_time = 0.1
                        config = f"wait_time: {wait_time}"
                        if fail:
                            config = config + f"\n{fail}: True"
                        await remote.cmd_configure.set_start(
                            config=config, timeout=STD_TIMEOUT
                        )
                        state = await remote.evt_state.next(
                            flush=False, timeout=STD_TIMEOUT
                        )
                        assert state.state == ScriptState.CONFIGURED
                        assert state.groupId == ""

                        metadata = await remote.evt_metadata.next(
                            flush=False, timeout=STD_TIMEOUT
                        )
                        assert metadata.duration == wait_time
                        assert metadata.totalCheckpoints == 2

                        group_id = "a non-blank group ID"
                        await remote.cmd_setGroupId.set_start(
                            groupId=group_id, timeout=STD_TIMEOUT
                        )
                        state = await remote.evt_state.next(
                            flush=False, timeout=STD_TIMEOUT
                        )
                        assert state.groupId == group_id

                        await remote.cmd_run.start(timeout=STD_TIMEOUT)

                        await asyncio.wait_for(process.wait(), timeout=STD_TIMEOUT)
                        if fail:
                            assert process.returncode == 1
                        else:
                            assert process.returncode == 0
                    finally:
                        if process.returncode is None:
                            process.terminate()
                            warnings.warn(
                                "Killed a process that was not properly terminated",
                                RuntimeWarning,
                            )

    async def test_amain_bad_kwargs(self) -> None:
        """Test BaseScript.amain and make_from_cmd_line with invalid kwargs"""
        bad_kwargs = dict(index=5)  # index is a forbidden key
        with pytest.raises(RuntimeError):
            salobj.TestScript.make_from_cmd_line(**bad_kwargs)

        with pytest.raises(RuntimeError):
            await salobj.TestScript.amain(**bad_kwargs)

    async def test_script_schema_process(self) -> None:
        """Test running a script with --schema as a subprocess."""
        script_path = TEST_DATA_DIR / "script1"
        index = 1  # index is ignored
        process = await asyncio.create_subprocess_exec(
            str(script_path),
            str(index),
            "--schema",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(), timeout=STD_TIMEOUT
            )
            schema = yaml.safe_load(stdout)
            assert schema == salobj.TestScript.get_schema()
            await asyncio.wait_for(process.wait(), timeout=STD_TIMEOUT)
            assert process.returncode == 0
        finally:
            if process.returncode is None:
                process.terminate()
                warnings.warn(
                    "Killed a process that was not properly terminated", RuntimeWarning
                )
