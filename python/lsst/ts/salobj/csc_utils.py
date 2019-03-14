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

__all__ = ["enable_csc", "set_summary_state"]

import asyncio
import re
import warnings

from lsst.ts import salobj
from .base_csc import State


class _SummaryStateSetter:
    """Functor to put a CSC into a specified summary state.
    """
    def __init__(self):
        # state index provides an ordering from OFFLINE to ENABLED
        # (the STATE enums also have integer value, but not in a useful order)
        self._state_index_dict = {
            State.OFFLINE: 0,
            State.STANDBY: 1,
            State.DISABLED: 2,
            State.ENABLED: 3,
        }
        # state transitions for non-fault states:
        # keys are (from state index, to state index)
        # values are state transition command names
        self._index_cmd_dict = {
            (0, 1): "enterControl",
            (1, 2): "start",
            (2, 3): "enable",
            (3, 2): "disable",
            (2, 1): "standby",
            (1, 0): "exitControl",
        }

    async def __call__(self, remote, state, settingsToApply="", timeout=1):
        """Put a CSC into the specified summary state.

        Parameters
        ----------
        remote : `Remote`
            Remote for the CSC to be enabled
        state : `State` or `int`
            Desired summary state.
        settingsToApply : `str`
            SettingsToApply argument for the ``start`` command.
            Ignored unless the CSC has to be taken from state
            `State.STANDBY` to `STATE.DISABLED`.
        timeout : `float`
            Timeout for each state transition command and a possible initial
            summaryState read (sec).

        Notes
        -----
        This function assumes the CSC is listening to SAL commands. If the CSC
        is not running then this function will time out (unless the last
        reported summary state has been cached and matches ``state``.
        """
        state = State(state)
        if state == State.FAULT:
            raise ValueError("Cannot go into FAULT state using state transition commands")

        # get current summary state
        state_data = remote.evt_summaryState.get()
        if state_data is None:
            # get failed; try waiting for it, in case the CSC is starting up
            try:
                state_data = await remote.evt_summaryState.next(flush=False, timeout=timeout)
            except asyncio.TimeoutError:
                raise RuntimeError(f"Cannot get summaryState from {remote.salinfo.name}")
        current_state = State(state_data.summaryState)

        if current_state == state:
            # we are already in the desired state
            return
        elif current_state == State.FAULT:
            # first go into standby, then use self._index_cmd_dict
            await remote.cmd_standby.start(timeout=timeout)
            current_state = State.STANDBY
            if current_state == state:
                return

        old_settings_to_apply = remote.cmd_start.data.settingsToApply
        try:
            remote.cmd_start.set(settingsToApply=settingsToApply)

            current_ind = self._state_index_dict[current_state]
            desired_ind = self._state_index_dict[state]
            cmdnames = []
            if desired_ind > current_ind:
                for ind in range(current_ind, desired_ind):
                    from_to_ind = (ind, ind+1)
                    cmdnames.append(self._index_cmd_dict[from_to_ind])
            elif current_ind > desired_ind:
                for ind in range(current_ind, desired_ind, -1):
                    from_to_ind = (ind, ind-1)
                    cmd = self._index_cmd_dict[from_to_ind]
                    cmdnames.append(self._index_cmd_dict[from_to_ind])

            for cmdname in cmdnames:
                cmd = getattr(remote, f"cmd_{cmdname}")
                await cmd.start(timeout=timeout)
        finally:
            remote.cmd_start.data.settingsToApply = old_settings_to_apply


set_summary_state = _SummaryStateSetter()


def _state_from_ack_error(result):
    """Get summary state from failed state change AckError result."""
    match = re.search(r"State\.[a-zA-Z]+: (\d+)", result)
    if match is None:
        raise RuntimeError(f"Could not find state in {result}")
    return int(match.group(1))


async def enable_csc(remote, settingsToApply="", force_config=False, timeout=1):
    """Enable a CSC from its current state.

    Superseded by set_summary_state.

    Parameters
    ----------
    remote : `Remote`
        Remote for the CSC to be enabled
    settingsToApply : `str`
        SettingsToApply argument for the ``start`` command.
        This will be ignored if the CSC is already in `State.DISABLED` state,
        unless ``force_config`` is true.
    force_config : `bool`
        If true then go to `State.STANDBY` state, then `State.ENABLED` state;
        otherwise take the shortest path to `State.ENABLED` state.
    timeout : `float`
        Timeout for each state transition command and a possible initial
        summaryState read (sec).

    Notes
    -----
    This function assumes the CSC is listening to SAL commands. If the CSC
    is not running then this function will time out (unless the last reported
    summary state has been cached and was `State.ENABLED` and ``force_config``
    is False).
    """
    warnings.warn("Superseded by set_summary_state", DeprecationWarning)
    # get current summary state
    state = None
    # try a simple get
    state_data = remote.evt_summaryState.get()
    if state_data is None:
        # get failed; try waiting for it, in case the CSC is starting up
        try:
            state_data = await remote.evt_summaryState.next(flush=False, timeout=timeout)
        except asyncio.TimeoutError:
            # Either the CSC is not running or this is SAL bug DM-18035
            # late joiners do not reliably get topic data,
            # so try a state change command:
            # * If it succeeds then we know the state
            # * If it fails then the error message should contain the state
            # * If it times out (NOACK) then the CSC is dead
            # TODO DM-18168: remove the code that tries to send a command
            # once DM-18035 is fixed.
            try:
                if force_config:
                    await remote.cmd_disable.start(timeout=timeout)
                    state = salobj.State.DISABLED
                else:
                    await remote.cmd_enable.start(timeout=timeout)
                    state = salobj.State.ENABLED
            except salobj.AckError as e:
                if e.ack.ack == remote.salinfo.lib.SAL__CMD_FAILED:
                    state = _state_from_ack_error(e.ack.result)
                elif e.ack.ack != remote.salinfo.lib.SAL__CMD_NOACK:
                    raise salobj.ExpectedError(f"CSC {remote.name} is not responding")
                else:
                    raise
    if state is None:
        assert state_data is not None
        state = state_data.summaryState

    remote.cmd_start.set(settingsToApply=settingsToApply)

    async def standby_to_enabled():
        await remote.cmd_start.start(timeout=timeout)
        await remote.cmd_enable.start(timeout=timeout)

    if force_config:
        # first go to STANDBY state, then to enabled state
        if state == salobj.State.ENABLED:
            await remote.cmd_disable.start(timeout=timeout)
            await remote.cmd_standby.start(timeout=timeout)
            await standby_to_enabled()
        elif state in (salobj.State.DISABLED, salobj.State.FAULT, salobj.State.OFFLINE):
            await remote.cmd_standby.start(timeout=timeout)
            await standby_to_enabled()
        elif state == salobj.State.STANDBY:
            await standby_to_enabled()
    else:
        # take the shortest path to ENABLED
        if state == salobj.State.ENABLED:
            pass
        elif state == salobj.State.DISABLED:
            await remote.cmd_enable.start(timeout=timeout)
        elif state == salobj.State.STANDBY:
            await standby_to_enabled()
        if state in (salobj.State.OFFLINE, salobj.State.FAULT):
            await remote.cmd_standby.start(timeout=timeout)
            await standby_to_enabled()
