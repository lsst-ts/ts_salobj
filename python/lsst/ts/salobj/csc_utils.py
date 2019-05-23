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

__all__ = ["set_summary_state"]

import asyncio
import re

from .base_csc import State


# Support for set_summary_state
# A dict of State: index,
# where index provides an ordering from OFFLINE to ENABLED
# (the STATE enums also have integer value, but not in a useful order)
_STATE_INDEX_DICT = {
    State.OFFLINE: 0,
    State.STANDBY: 1,
    State.DISABLED: 2,
    State.ENABLED: 3,
}

# Support for set_summary_state
# State transition commands for non-fault states:
# keys are (from state index, to state index)
# values are state transition command names
_INDEX_CMD_DICT = {
    (0, 1): "enterControl",
    (1, 2): "start",
    (2, 3): "enable",
    (3, 2): "disable",
    (2, 1): "standby",
    (1, 0): "exitControl",
}


async def set_summary_state(remote, state, settingsToApply="", timeout=30):
    """Put a CSC into the specified summary state.

    Parameters
    ----------
    remote : `Remote`
        Remote for the CSC to be enabled.
    state : `State` or `int`
        Desired summary state.
    settingsToApply : `str`
        SettingsToApply argument for the ``start`` command.
        Ignored unless the CSC has to be taken from state
        `State.STANDBY` to `State.DISABLED`.
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
        # first go into standby, then use _INDEX_CMD_DICT
        await remote.cmd_standby.start(timeout=timeout)
        current_state = State.STANDBY
        if current_state == state:
            return

    old_settings_to_apply = remote.cmd_start.data.settingsToApply
    try:
        remote.cmd_start.set(settingsToApply=settingsToApply)

        current_ind = _STATE_INDEX_DICT[current_state]
        desired_ind = _STATE_INDEX_DICT[state]
        cmdnames = []
        if desired_ind > current_ind:
            for ind in range(current_ind, desired_ind):
                from_to_ind = (ind, ind+1)
                cmdnames.append(_INDEX_CMD_DICT[from_to_ind])
        elif current_ind > desired_ind:
            for ind in range(current_ind, desired_ind, -1):
                from_to_ind = (ind, ind-1)
                cmd = _INDEX_CMD_DICT[from_to_ind]
                cmdnames.append(_INDEX_CMD_DICT[from_to_ind])

        for cmdname in cmdnames:
            cmd = getattr(remote, f"cmd_{cmdname}")
            await cmd.start(timeout=timeout)
    finally:
        remote.cmd_start.data.settingsToApply = old_settings_to_apply


def _state_from_ack_error(result):
    """Get summary state from failed state change AckError result."""
    match = re.search(r"State\.[a-zA-Z]+: (\d+)", result)
    if match is None:
        raise RuntimeError(f"Could not find state in {result}")
    return int(match.group(1))
