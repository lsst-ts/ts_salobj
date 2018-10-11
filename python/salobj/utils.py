# This file is part of salobj.
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

__all__ = ["ExpectedError", "SalInfo", "split_component_name"]


class ExpectedError(Exception):
    """Report an error that does not benefit from a traceback.

    For example, a command is invalid in the current state.
    """
    pass


class SalInfo:
    """SALPY information for a component, including the
    SALPY library, component name, component index and SALPY manager

    Parameters
    ----------
    sallib : `module`
        SALPY library for a SAL component
    component_name : `str`
        Component name and optional index, separated by a colon, e.g.
        "scheduler" or "electrometer:2".
    """
    def __init__(self, sallib, component_name):
        self.lib = sallib
        self.component_name = component_name
        self.name, self.index = split_component_name(component_name)
        get_manager = getattr(self.lib, "SAL_" + self.name)
        self.manager = get_manager() if self.index is None else get_manager(self.index)


def split_component_name(name):
    """Split a component name of the form "foo:i" into (foo, int(i))
    or "foo" into (foo, None).
    """
    nameind = name.split(":")
    if len(nameind) == 1:
        return name, None
    elif len(nameind) == 2:
        return nameind[0], int(nameind[1])
    else:
        raise ValueError(f"Could not split {name!r} into name, integer index")
