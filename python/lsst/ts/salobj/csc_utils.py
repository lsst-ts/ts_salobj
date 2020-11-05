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

__all__ = [
    "make_state_transition_dict",
    "get_expected_summary_states",
    "set_summary_state",
]

import asyncio

from .sal_enums import State


def make_state_transition_dict():
    """Make a dict of state transition commands and states

    The keys are (beginning state, ending state).
    The values are a list of tuples:

    * A state transition command
    * The expected state after that command
    """
    ordered_states = (State.OFFLINE, State.STANDBY, State.DISABLED, State.ENABLED)

    basic_state_transition_commands = {
        (State.OFFLINE, State.STANDBY): "enterControl",
        (State.STANDBY, State.DISABLED): "start",
        (State.DISABLED, State.ENABLED): "enable",
        (State.ENABLED, State.DISABLED): "disable",
        (State.DISABLED, State.STANDBY): "standby",
        (State.STANDBY, State.OFFLINE): "exitControl",
    }

    # compute transitions from non-FAULT to all other states
    state_transition_dict = dict()
    for beg_ind, beg_state in enumerate(ordered_states):
        for end_ind, end_state in enumerate(ordered_states):
            if beg_ind == end_ind:
                state_transition_dict[(beg_state, end_state)] = []
                continue
            step = 1 if end_ind > beg_ind else -1
            command_state_list = []
            for next_ind in range(beg_ind, end_ind, step):
                from_state = ordered_states[next_ind]
                to_state = ordered_states[next_ind + step]
                command = basic_state_transition_commands[from_state, to_state]
                command_state_list.append((command, to_state))
            state_transition_dict[(beg_state, end_state)] = command_state_list

    # add transitions from FAULT to all other states
    for end_state in ordered_states:
        command_state_list = [("standby", State.STANDBY)]
        if end_state != State.STANDBY:
            command_state_list += state_transition_dict[State.STANDBY, end_state]
        state_transition_dict[State.FAULT, end_state] = command_state_list
    return state_transition_dict


_STATE_TRANSITION_DICT = make_state_transition_dict()


def get_expected_summary_states(initial_state, final_state):
    """Return all summary states expected when transitioning from
    one state to another.
    """
    cmd_state_list = _STATE_TRANSITION_DICT[(initial_state, final_state)]
    # cmd_state_list lists the state after each state transition
    # command, but we want the initial state, as well.
    return [initial_state] + [cmd_state[1] for cmd_state in cmd_state_list]


async def set_summary_state(remote, state, settingsToApply="", timeout=30):
    """Put a CSC into the specified summary state.

    Parameters
    ----------
    remote : `Remote`
        Remote for the CSC to be enabled.
    state : `State` or `int`
        Desired summary state.
    settingsToApply : `str` or `None`
        SettingsToApply argument for the ``start`` command.
        Ignored unless the CSC has to be taken from state
        `State.STANDBY` to `State.DISABLED`.
    timeout : `float`
        Timeout for each state transition command and a possible initial
        summaryState read (sec).

    Returns
    -------
    states : `list` [`State`]
        A list of the initial summary state and all summary states
        this function transitioned the CSC through,
        ending with the desired state.

    Notes
    -----
    This function assumes the CSC is listening to SAL commands. If the CSC
    is not running then this function will time out (unless the last
    reported summary state has been cached and matches ``state``.
    """
    state = State(state)
    if state == State.FAULT:
        raise ValueError("Cannot go into FAULT state using state transition commands")
    if settingsToApply is None:
        settingsToApply = ""

    # get current summary state
    try:
        state_data = await remote.evt_summaryState.aget(timeout=timeout)
    except asyncio.TimeoutError:
        raise RuntimeError(f"Cannot get summaryState from {remote.salinfo.name}")
    current_state = State(state_data.summaryState)

    states = [current_state]
    if current_state == state:
        # we are already in the desired state
        return states

    command_state_list = _STATE_TRANSITION_DICT[(current_state, state)]

    old_settings_to_apply = remote.cmd_start.data.settingsToApply
    try:
        remote.cmd_start.data.settingsToApply = settingsToApply

        for command, state in command_state_list:
            cmd = getattr(remote, f"cmd_{command}")
            try:
                await cmd.start(timeout=timeout)
            except Exception as e:
                raise RuntimeError(
                    f"Error on cmd=cmd_{command}, initial_state={current_state}: {e}"
                ) from e
            states.append(state)
    finally:
        remote.cmd_start.data.settingsToApply = old_settings_to_apply
    return states
