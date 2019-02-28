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

__all__ = ["AckError", "CommandIdAck", "CommandIdData", "ExpectedError",
           "index_generator", "SalInfo", "MAX_SAL_INDEX"]


MAX_SAL_INDEX = (2 << 30) - 1


def _ack_str(ack):
    """Format an Ack as a string"""
    return f"(ack={ack.ack}, error={ack.error}, result={ack.result!r})"


class AckError(Exception):
    """Exception raised if a command fails.

    Parameters
    ----------
    msg : `str`
        Error message
    ack : ``AckType``
        Command acknowledgement.
    """
    def __init__(self, msg, cmd_id, ack):
        super().__init__(msg)
        self.cmd_id = cmd_id
        """Command ID."""
        self.ack = ack
        """Command acknowledgement."""

    def __str__(self):
        return f"msg={self.args[0]!r}, cmd_id={self.cmd_id}, ack={_ack_str(self.ack)}"

    def __repr__(self):
        return f"{type(self).__name__}({self!s})"


class CommandIdAck:
    """Struct to hold a command ID and its associated acknowledgement.

    Parameters
    ----------
    cmd_id : `int`
        Command ID.
    ack : ``AckType``
        Command acknowledgement.
    """
    def __init__(self, cmd_id, ack):
        self.cmd_id = int(cmd_id)
        self.ack = ack

    def __str__(self):
        return f"cmd_id={self.cmd_id}, ack={_ack_str(self.ack)}"

    def __repr__(self):
        return f"CommandIdAck({self!s})"


class CommandIdData:
    """Struct to hold a command ID and its associated data"""
    def __init__(self, cmd_id, data):
        self.cmd_id = cmd_id
        self.data = data


class ExpectedError(Exception):
    """Report an error that does not benefit from a traceback.

    For example, a command is invalid in the current state.
    """
    pass


def index_generator(imin=1, imax=MAX_SAL_INDEX):
    """Sequential index generator, e.g. for SAL components.

    Returns values min, min+1, ..., max, min, min + 1, ...

    Parameters
    ----------
    imin : `int`
        Minimum index (inclusive).
    imax : `int`
        Maximum index (inclusive).

    Raises
    ------
    ValueError
        If imin >= imax
    """
    if imax <= imin:
        raise ValueError(f"imin={imin} must be less than imax={imax}")

    # define an inner generator and return that
    # in order to get immediate argument checking
    def index_impl():
        index = imin - 1
        while True:
            index += 1
            if index > imax:
                index = imin

            yield index

    return index_impl()


class SalInfo:
    """SALPY information for a component, including the
    SALPY library, component name, component index and SALPY manager

    Parameters
    ----------
    sallib : ``module``
        SALPY library for a SAL component
    index : `int` (optional)
        SAL component index, or 0 or `None` if the component is not indexed.
    debug : `int` (optional)
        SAL debug level; 0 to not print SAL debug statements.
    """
    def __init__(self, sallib, index=None, debug=0):
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
        self.manager.setDebugLevel(debug)
        self._AckType = getattr(self.lib, self.name + "_ackcmdC")

    def __repr__(self):
        return f"SalInfo({self.name}, {self.index})"

    @property
    def AckType(self):
        """The class of command acknowledgement.

        It is contructed with the following parameters
        and has these fields:

        ack : `int`
            Acknowledgement code; one of the ``self.lib.SAL__CMD_``
            constants, such as ``self.lib.SAL__CMD_COMPLETE``.
        error : `int`
            Error code; 0 for no error.
        result : `str`
            Explanatory message, or "" for no message.
        """
        return self._AckType

    def makeAck(self, ack, error=0, result=""):
        """Make an AckType object from keyword arguments.
        """
        data = self.AckType()
        data.ack = ack
        data.error = error
        data.result = result
        return data

    def __del__(self):
        # use getattr in case this is called during failed construction
        manager = getattr(self, "manager", None)
        if manager is not None:
            manager.salShutdown()
