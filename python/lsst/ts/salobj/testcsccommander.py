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

__all__ = ["TestCscCommander"]

import typing

import numpy as np

from . import csc_commander

# All arrays for setArrays have length 5
ARR_LEN = 5


class TestCscCommander(csc_commander.CscCommander):
    """Control a Test CSC from the command line.

    Parameters
    ----------
    index : `int`, optional
        SAL index of CSC.
    enable : `bool`, optional
        Enable the CSC (when the commander starts up)?
        Note: `amain` always supplies this argument.
    exclude : ``iterable`` of `str`, optional
        Names of topics (telemetry or events) to not support.
        Topic names must not have a ``tel_`` or ``evt_`` prefix.
        If `None` or empty then no topics are excluded.
    """

    def __init__(
        self,
        index: typing.Optional[int],
        enable: bool = False,
        exclude: typing.Optional[typing.Sequence[str]] = None,
        fields_to_ignore: typing.Sequence[str] = (
            "ignored",
            "value",
            "priority",
        ),
    ) -> None:
        super().__init__(
            name="Test",
            index=index,
            enable=enable,
            exclude_commands=("abort", "enterControl", "setValue"),
        )

        def asbool(val: str) -> bool:
            """Cast an string representation of an boolean to a boolean.

            Supported values include 0, f, false, 1, t, true
            """
            return csc_commander.BOOL_DICT[val.lower()]

        self.array_field_types = dict(
            boolean0=asbool,
            byte0=np.uint8,
            short0=np.int16,
            int0=np.int32,
            long0=np.int32,
            longLong0=np.int64,
            unsignedShort0=np.uint16,
            unsignedInt0=np.uint32,
            unsignedLong0=np.uint32,
            float0=np.single,
            double0=np.double,
        )

        self.help_dict[
            "setArrays"
        ] = f"""field1=val1,val2,... field2=val1,va2,... (up to {ARR_LEN} values each)
          field: {" ".join(self.array_field_types)}
          for example: boolean0=1,2 int0=3,-4,5,6,7 float0=-42.3"""

    async def do_setArrays(self, args: typing.Sequence[str]) -> None:
        kwargs = dict()
        for field_val in args:
            field, valstr = field_val.split("=")
            if field not in self.array_field_types:
                raise RuntimeError(f"Unknown field {field}")
            field_type = self.array_field_types[field]
            vals = [field_type(val) for val in valstr.split(",")]
            if len(vals) > ARR_LEN:
                raise RuntimeError(
                    f"Field {field} has more than {ARR_LEN} values: {vals}"
                )
            elif len(vals) < ARR_LEN:
                n_to_append = ARR_LEN - len(vals)
                vals += [field_type("0")] * n_to_append
            kwargs[field] = vals
        await self.remote.cmd_setArrays.set_start(**kwargs)  # type: ignore
