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

__all__ = ["enable_csc"]


from lsst.ts import salobj


async def enable_csc(remote, settingsToApply="", force_config=False, timeout=1):
    """Enable a CSC from its current state.

    Parameters
    ----------
    remote : `ts.salobj.Remote`
        Remote for the CSC to be enabled
    settingsToApply : `str`
        SettingsToApply argument for the ``start`` command.
        This will be ignored if the CSC is already in `State.DISABLED` state,
        unless ``force_config`` is true.
    force_config : `bool`
        If true then go to `State.STANDBY` state, then `State.ENABLED` state;
        otherwise take the shortest path to `State.ENABLED` state.
    timeut : `float`
        Timeout for each state transition command (sec).

    Notes
    -----
    This function assumes the CSC is listening to SAL commands. If the CSC
    is not running then this function will time out (unless the last reported
    summary state was `State.ENABLED` and ``force_config`` is False).
    """
    state = remote.evt_summaryState.get().summaryState
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
