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

__all__ = ["get_dds_version"]

import pathlib
import re

import dds


def get_dds_version(dds_file=None):
    """Get the version of OpenSplice dds library.

    If it cannot be determined, return "?".

    Parameters
    ----------
    dds_file : `str` or `None`, optional
        Value of ``dds.__file__``.
        Use `None` except when testing this function.
    """
    # In case ADLink adds the expected attribute...
    version = getattr(dds, "__version__", None)
    if version is not None:
        return version

    # Else try to get the version from the __file__ attribute
    if dds_file is None:
        dds_file = dds.__file__
    dds_path = pathlib.Path(dds_file)
    if len(dds_path.parts) < 2:
        return "?"
    parent_dir = dds_path.parts[-2]
    match = re.search(r"(\d+\.\d+\.\d+)", parent_dir)
    if match is None:
        return "?"
    return match.groups()[0]
