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

__all__ = ["get_component_info"]

import argparse
import json

import lsst.ts.xml

from .component_info import ComponentInfo
from .get_enums_from_xml import get_field_and_global_enums

VALID_COMPONENT_NAMES = set(lsst.ts.xml.subsystems)


def get_component_info() -> None:
    """Get information about a SAL component, using the command line."""
    parser = argparse.ArgumentParser(
        description="""Get information about a SAL component.

    Write the information to stdout as a json-encoded dict with three items: {
        "topics": topics
        "global_enums": [global_enum_info],
        "topic_enums": [field_enum_info],
    }, where:
    * topics is a dict: {SAL topic name: topic_info}
    * topic_info is a dict with two items: {
        "avro_schema": Avro schema,
        "array_fields": array_fields_info
      }
    * array_fields_info is a dict: {field name: array length}.
    * global_enum_info is a tuple with 2 items:
      (enum class name: [enum_items]).
    * field_enum_info is a tuple with 3 items:
      (topic name, field name, [enum_info]).
    * enum_info an enum item name with an optional specified value,
      for example: "Enabled", "UNKNOWN=-1", or "LOW_AMBIENT_TEMP = 0x80".

    Write errors to stderr.""",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("name", help="Name of SAL component, e.g. 'ScriptQueue'.")
    args = parser.parse_args()

    name = args.name
    if name not in VALID_COMPONENT_NAMES:
        parser.error(f"Unknown {name=}")

    component_info = ComponentInfo(name=name, topic_subname="")
    field_enums, global_enums = get_field_and_global_enums(name=name)
    result = {
        "topics": {
            topic_info.sal_name: dict(
                avro_schema=topic_info.make_avro_schema(),
                array_fields=topic_info.array_fields,
            )
            for topic_info in component_info.topics.values()
        },
        "field_enums": [info.as_tuple() for info in field_enums],
        "global_enums": [info.as_tuple() for info in global_enums],
    }
    encoded_result = json.dumps(result)
    print(encoded_result)
