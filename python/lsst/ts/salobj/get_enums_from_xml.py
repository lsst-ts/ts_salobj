from __future__ import annotations

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

__all__ = [
    "get_field_enums_from_file_root",
    "get_global_enums_from_file_root",
    "get_enums_from_xml",
]

import argparse
import dataclasses
import json
import re
import typing
from xml.etree import ElementTree

import lsst.ts.xml

from .make_avro_schemas import check_components
from .xml_utils import (
    FILE_SUFFIX_DICT,
    TopicType,
    find_optional_text,
    find_required_text,
)


@dataclasses.dataclass
class FieldEnumInfo:
    topic_name: str
    field_name: str
    items: list[str]

    def as_tuple(self) -> tuple[str, str, list[str]]:
        """Get as a tuple of plain old data, for json encoding.

        Return (topic_name, field_name, items)
        """
        return (self.topic_name, self.field_name, self.items)


@dataclasses.dataclass
class GlobalEnumInfo:
    class_name: str
    items: list[str]

    def as_tuple(self) -> tuple[str, list[str]]:
        """Get as a tuple of plain old data, for json encoding.

        Return (class_name, items)
        """
        return (self.class_name, self.items)

    @classmethod
    def from_enum_text(cls, enum_text: str) -> GlobalEnumInfo:
        """Make GlobalEnumInfo from text for a global enum XML element."""
        enum_text = enum_text.strip()
        raw_enums = re.split(r" *, *\n? *", enum_text)
        prefix_item_list = [raw.split("_", 1) for raw in raw_enums]
        prefixes, items = zip(*prefix_item_list)
        if not all(prefix == prefixes[0] for prefix in prefixes):
            raise RuntimeError(f"One or more inconsistent prefixes in {enum_text}")
        return cls(class_name=prefixes[0], items=items)


def get_enums_for_one_component(
    name: str,
) -> tuple[list[FieldEnumInfo], list[GlobalEnumInfo]]:
    """Parse ts_xml for enums for one SAL component.

    Parameters
    ----------
    name : `str`
        SAL component name.
    """
    interfaces_dir = lsst.ts.xml.get_sal_interfaces_dir()
    field_enums: list[FieldEnumInfo] = []
    global_enums: list[GlobalEnumInfo] = []
    for topic_type in TopicType:
        file_suffix = FILE_SUFFIX_DICT[topic_type]
        filepath = interfaces_dir / name / f"{name}_{file_suffix}.xml"
        if not filepath.is_file():
            continue
        file_root = ElementTree.parse(filepath).getroot()
        field_enums += get_field_enums_from_file_root(
            topic_type=topic_type, file_root=file_root
        )
        global_enums += get_global_enums_from_file_root(file_root)
    return field_enums, global_enums


def get_field_enums_from_file_root(
    topic_type: TopicType, file_root: ElementTree.Element
) -> list[FieldEnumInfo]:
    """Get global enum info from a component file's xmlroot.

    Parameters
    ----------
    topic_type : `TopicType`
        Type of topics defined in this file.
    file_root : `ElementTree.Element`
        Root of one XML file (e.g. the root for ATDome_Commands.xml).

    Returns
    -------
    global_enum_infos : `list[GlobalEnumInfo]`
        List of global enum info.
    """
    field_enums: list[FieldEnumInfo] = []
    sal_topic_tag_name = {
        TopicType.COMMAND: "SALCommand",
        TopicType.EVENT: "SALEvent",
        TopicType.TELEMETRY: "SALTelemetry",
    }[topic_type]
    topic_elements = file_root.findall(sal_topic_tag_name)
    for topic_element in topic_elements:
        field_enums += get_field_enums_from_topic_element(topic_element)
    return field_enums


def get_field_enums_from_topic_element(
    topic_element: ElementTree.Element,
) -> list[FieldEnumInfo]:
    """Find all field enums in a given topic's XML element"""
    field_enums: list[FieldEnumInfo] = []
    topic_name = find_required_text(topic_element, "EFDB_Topic")
    item_elements = topic_element.findall("item")
    for item_element in item_elements:
        enum_text = find_optional_text(item_element, "Enumeration", "")
        if not enum_text:
            continue
        field_name = find_required_text(item_element, "EFDB_Name")
        items = re.split(r" *, *\n? *", enum_text)
        field_enums.append(
            FieldEnumInfo(topic_name=topic_name, field_name=field_name, items=items)
        )
    return field_enums


def get_global_enums_from_file_root(
    file_root: ElementTree.Element,
) -> list[GlobalEnumInfo]:
    """Get global enum info from a component file's xmlroot.

    Parameters
    ----------
    file_root : `ElementTree.Element`
        Root of one XML file (e.g. the root for ATDome_Commands.xml).

    Returns
    -------
    global_enum_infos : `list[GlobalEnumInfo]`
        List of global enum info.
    """
    enum_elements = file_root.findall("Enumeration")
    return [
        GlobalEnumInfo.from_enum_text(enum_text=element.text)
        for element in enum_elements
        if element.text is not None
    ]


def get_enums_from_xml() -> None:
    """Get enum information for SAL components specified on the command line.

    Run with option ``--help`` for more option.
    """
    parser = argparse.ArgumentParser(
        description="""Get enum info for one or more SAL components.

    Write the data to stdout as a json-encoded dict:
      {
        component name: {
            "global_enums": global_enum_info,
            "field_specific_enums": field_specific_enum_info
      }
    where:
    * global_enum_info is a list of (enum_class_name, [enum_item])
    * enum_class_name is the first field of each enumeration item.
    * enum_item is the rest of each enumumeration item (including
      the value, if specified).
    * field_specific_enum_info a list of (topic_name, field_name, [enum_item])
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
        field_enums, global_enums = get_enums_for_one_component(name=name)

        result[name] = dict(
            field_enums=[info.as_tuple() for info in field_enums],
            global_enums=[info.as_tuple() for info in global_enums],
        )
    encoded_result = json.dumps(result)
    print(encoded_result)
