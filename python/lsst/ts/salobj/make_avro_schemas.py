#!/usr/bin/env python3

__all__ = ["make_avro_schemas"]

import argparse
import collections.abc
import json
import typing

import lsst.ts.xml
from lsst.ts import salobj


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
        description="Make Avro schemas for one or more SAL components.\n\n"
        "Write the schemas to stdout as a json-encoded string of "
        "a dict of [component: topic_data], "
        "where topic_data is a dict of [SAL topic name: Avro schema]. "
        "Write errors to stderr. "
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
        component_info = salobj.ComponentInfo(name=name, topic_subname="")
        result[name] = {
            topic_info.sal_name: topic_info.make_avro_schema()
            for topic_info in component_info.topics.values()
        }
    encoded_result = json.dumps(result)
    print(encoded_result)
