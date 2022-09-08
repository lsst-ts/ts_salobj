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

__all__ = ["make_avro_schemas"]

import argparse
import collections.abc
import json
import typing

import lsst.ts.xml

from .component_info import ComponentInfo


def check_components(
    parser: argparse.ArgumentParser, descr: str, components: collections.abc.Iterable
) -> None:
    """Check that all component names are valid.

    Call parser.error if not.

    Parameters
    ----------
    parser : `argparse.ArgumentParser`
        Argument parser
    descr : `str`
        Brief description of components list, e.g. "excluded components"
    components : iterable[`str`]
        Component names.
    """
    invalid_components = set(components) - set(lsst.ts.xml.subsystems)

    if len(invalid_components) > 0:
        parser.error(
            f"The following {descr} are not part of sal subsystems: "
            f"{sorted(invalid_components)}. Check spelling and try again."
        )


def make_avro_schemas() -> None:
    """Make Avro schemas for components specified on the command line.

    Run with option ``--help`` for more option.
    """
    parser = argparse.ArgumentParser(
        description="""Make Avro schemas for one or more SAL components.

    Write the schemas to stdout as a json-encoded string of
    a dict of [component_name: component_info], where:
    * component_info is a dict of {SAL topic name: topic_info}
    * topic_info is a dict {"avro_schema": Avro schema, "array_fields": array_fields_info}
    * array_fields_info is a dict of {field name: array length}
    Write errors to stderr. """,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "components",
        nargs="*",
        help="Names of SAL components, e.g. 'Script ScriptQueue'. "
        "Ignored if --all is specified",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Make all components except those listed in --exclude.",
    )
    parser.add_argument(
        "--exclude",
        nargs="+",
        help="Names of SAL components to exclude. "
        "If an entry appears in both `components` and `exclude` then it is excluded.",
    )
    args = parser.parse_args()

    if args.all:
        components = lsst.ts.xml.subsystems
    else:
        components = args.components
        check_components(parser=parser, descr="components", components=components)

    if args.exclude:
        exclude_set = set(args.exclude)
        check_components(
            parser=parser, descr="excluded components", components=exclude_set
        )
        components = [name for name in components if name not in exclude_set]

    result: dict[str, dict[str, typing.Any]] = dict()
    for name in components:
        component_info = ComponentInfo(name=name, topic_subname="")
        result[name] = {
            topic_info.sal_name: dict(
                avro_schema=topic_info.make_avro_schema(),
                array_fields=topic_info.array_fields,
            )
            for topic_info in component_info.topics.values()
        }
    encoded_result = json.dumps(result)
    print(encoded_result)
