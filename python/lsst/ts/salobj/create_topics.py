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

__all__ = ["create_topics"]

import argparse
import asyncio

from lsst.ts.xml import subsystems

from . import Domain, Remote


def create_topics() -> None:
    """Utility to create topics."""

    parser = argparse.ArgumentParser(description="Utility to create topics.")

    parser.add_argument(
        "components",
        nargs="*",
        help="Names of SAL components, e.g. 'Script ScriptQueue'. "
        "Ignored if --all is specified",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Create topics for all components.",
    )
    args = parser.parse_args()

    asyncio.run(
        create_topics_for_components(
            component_names=set(args.components) if not args.all else set(subsystems)
        )
    )


async def create_topics_for_components(component_names: set[str]) -> None:
    """Create topics for the input components.

    Parameters
    ----------
    components : `set`[`str`]
        Set with the components names.
    """
    async with Domain() as d:
        for component in component_names:
            print(f"Creating topics for {component}.")
            async with Remote(d, component):
                await asyncio.sleep(0)
