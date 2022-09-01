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

__all__ = ["hierarchical_update"]

import typing


def hierarchical_update(
    main: dict[str, typing.Any],
    override: dict[str, typing.Any],
    main_name: str,
    override_name: str,
    prefix: str = "",
) -> None:
    """Hierarchically update one dict with values from another.

    If a value in ``override`` is a dict, then work item by item,
    recursively.

    Parameters
    ----------
    main : `dict`
        Dict to update.
    override : `dict`
        Dict of update values.
    main_name : `str`
        Name of main dict; used for error messages.
    override_name : `str`
        Name of override dict; used for error messages.
    prefix : `str`
        The key prefix for error messages.
        Should be blank for the first call
        and be "[key][subkey]...[sub...subkey]" for each successive key.

    Raise
    -----
     ValueError
        If a value exists in both dicts but is a dict in one
        and not in the other.
    """
    for arg, argname in ((main, main_name), (override, override_name)):
        if not isinstance(arg, dict):
            raise ValueError(f"{argname}{prefix}={arg!r} is not a dict")

    for key, override_value in override.items():
        if key in main:
            if isinstance(override_value, dict):
                # Recursively override dict values with dict values.
                # Note: hierarchical_update tests that main[key] is a dict
                # so there is no need to do that here.
                hierarchical_update(
                    main=main[key],
                    override=override_value,
                    main_name=main_name,
                    override_name=override_name,
                    prefix=f"{prefix}[{key}]",
                )
            else:
                main_value = main[key]
                if isinstance(main_value, dict):
                    raise ValueError(
                        f"{main_name}{prefix}[{key}]={main_value} is a dict, "
                        f"but {override_name}{prefix}[{key}] = {override_value!r} is not"
                    )
                # Replace non-dict with non-dict
                main[key] = override_value
        else:
            # Add override_value to main
            main[key] = override_value
