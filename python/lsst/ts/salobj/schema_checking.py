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

__all__ = ["schema_checking"]

import argparse
import json
import os

from confluent_kafka.schema_registry import (
    Schema,
    SchemaRegistryClient,
    SchemaRegistryError,
)
from lsst.ts.xml import subsystems
from lsst.ts.xml.component_info import ComponentInfo


def msg(chk: bool) -> str:
    """Assemble short string for boolean.

    Parameters
    ----------
    chk : bool
          State of check.

    Returns
    -------
    str
          Resulting string for state of check.
    """
    return "is" if chk else "is not"


def print_summary(info: list[str], message: str) -> None:
    """Print summary information from a list.

    Parameters
    ----------
    info : list[str]
        Information needing to be printed.
    message : str
        Message to print before list or if list is empty.
    """
    if info:
        print(message)
        for x in info:
            print(x)
    else:
        print(f"No {message.lower()} found")


def checks(csc: str, subname: str, src: SchemaRegistryClient, verbose: bool) -> None:
    """Perform schema and topic related checks.

    Parameters
    ----------
    csc : str
        The CSC to check.
    subname : str
        The topic subname to use.
    src : SchemaRegistryClient
        Instance of the SchemaRegistryClient.
    verbose : bool
        Whether or not to print certain statements.
    """
    current_topics = []
    new_topics = []
    incompatible_schemas = []

    subjects = src.get_subjects()

    for subject in subjects:
        values = subject.split(".")
        if values[2] == csc:
            ctopic = values[-1].split("-")[0]
            current_topics.append(ctopic)

    c = ComponentInfo(csc, subname)
    schemas = c.make_avro_schema_dict()

    for topic, schema_dict in schemas.items():
        if "evt_" in topic:
            topic = topic.replace("evt_", "logevent_")
        if "tel_" in topic:
            topic = topic.replace("tel_", "")
        if "cmd_" in topic:
            topic = topic.replace("cmd_", "command_")
        if "ack_" in topic:
            topic = topic.replace("ack_", "")

        try:
            current_topics.remove(topic)
        except ValueError:
            pass

        full_topic = f"lsst.{subname}.{csc}.{topic}-value"

        schema_json = json.dumps(schema_dict)
        schema_class = Schema(schema_json, "AVRO")

        try:
            _ = src.get_latest_version(full_topic)
        except SchemaRegistryError:
            if verbose:
                print(f"{topic} is new")
            new_topics.append(topic)

        check = src.test_compatibility(full_topic, schema_class)
        if verbose:
            print(f"{topic} {msg(check)} schema compatible")
        if not check:
            incompatible_schemas.append(topic)

    if new_topics or current_topics or incompatible_schemas:
        print(csc)
        print()
        print_summary(new_topics, "New topics")
        print()
        print_summary(current_topics, "Renamed/Removed topics")
        print()
        print_summary(incompatible_schemas, "Incompatible schemas")
        print()


def main(opts: argparse.Namespace) -> None:
    topic_subname = os.environ["LSST_TOPIC_SUBNAME"]

    schema_registry_url = os.environ["LSST_SCHEMA_REGISTRY_URL"]
    schema_registry_conf = {"url": schema_registry_url}
    schema_registry_client = SchemaRegistryClient(schema_registry_conf)

    if opts.backward:
        level = "BACKWARD"
    else:
        level = "FORWARD"
    schema_registry_client.set_compatibility(level=level)

    component_names = set(opts.components) if not opts.all else set(subsystems)
    if opts.verbose:
        print(f"Checking {len(component_names)} components")
    for component_name in component_names:
        if opts.verbose:
            print(f"Checking {component_name}")
        checks(component_name, topic_subname, schema_registry_client, opts.verbose)


def schema_checking() -> None:
    parser = argparse.ArgumentParser()

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

    parser.add_argument(
        "-b", "--backward", action="store_true", help="Use backward compatibility"
    )

    parser.add_argument(
        "-v", "--verbose", action="store_true", help="Add debug prints."
    )

    args = parser.parse_args()

    main(args)
