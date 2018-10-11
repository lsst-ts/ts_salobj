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

__all__ = ["ExpectedError", "SalInfo"]


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
    index : `int` or `None`
        SAL component index, or 0 or None if the component is not indexed.
    """
    def __init__(self, sallib, index=None):
        self.lib = sallib
        self.name = sallib.componentName[4:]  # lop off leading SAL_
        if sallib.componentIsMultiple:
            if index is None:
                raise RuntimeError(f"Component {self.name} is indexed, so index cannot be None")
        else:
            if index not in (0, None):
                raise RuntimeError(f"Component {self.name} is not indexed so index={index} must be None or 0")
            index = 0
        self.index = index
        Manager = getattr(self.lib, "SAL_" + self.name)
        self.manager = Manager(self.index)

    def __str__(self):
        return f"SalInfo({self.name}, {self.index})"
