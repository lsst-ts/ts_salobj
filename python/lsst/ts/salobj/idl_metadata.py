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

__all__ = ["IdlMetadata", "TopicMetadata", "FieldMetadata", "parse_idl"]

import re
import typing

from . import type_hints


class IdlMetadata:
    """Information about SAL topics in an IDL file.

    Parameters
    ----------
    name : `str`
        SAL component name, e.g. "ATPtg".
    idl_path : `str` or `pathlib.Path`
        Path to IDL file.
    sal_version : `str` or `None`
        Version of ts_sal used to generate the IDL file,
        or `None` if not found.
    xml_version : `str`
        Version of ts_xml used to generate the IDL file,
        or `None` if not found.
    topic_info : `dict` [`str`: `TopicMetadata`]
        Dict of SAL topic name: topic metadata.
    """

    def __init__(
        self,
        name: str,
        idl_path: type_hints.PathType,
        sal_version: typing.Optional[str],
        xml_version: typing.Optional[str],
        topic_info: typing.Dict[str, TopicMetadata],
    ) -> None:
        self.name = name
        self.idl_path = idl_path
        self.sal_version = sal_version
        self.xml_version = xml_version
        self.topic_info = topic_info

    def __repr__(self) -> str:
        return (
            f"IdlMetadata(idl_path={self.idl_path}, "
            f"sal_version={repr(self.sal_version)}, "
            f"xml_version={repr(self.xml_version)})"
        )


class TopicMetadata:
    """Metadata about a topic.

    Parameters
    ----------
    sal_name : `str`
        SAL topic name, e.g. `logevent_summaryState`.
    version_hash : `str`
        Version has code.
    description : `str` or `None`
        Topic description, or `None` if unknown.

    Attributes
    ----------
    field_info : `dict` [`str`, `FieldMetadata`]
        Dict of field name: field metadata.
    """

    def __init__(
        self, sal_name: str, version_hash: str, description: typing.Optional[str]
    ) -> None:
        self.sal_name = sal_name
        self.version_hash = version_hash
        self.description = description
        self.field_info: typing.Dict[str, FieldMetadata] = dict()

    def __repr__(self) -> str:
        return f"TopicMetadata(sal_name={repr(self.sal_name)}, description={self.description})"


class FieldMetadata:
    """Information about a field.

    Parameters
    ----------
    name : `str`
        Field name.
    description : `str` or `None`
        Description; `None` if not specified.
    units : `str` or `None`
        Units; `None` if not specified.
    type_name : `str`
        Data type name from the IDL file, e.g.
        "string<8>", "float", "double".
        This may not match the Python data type of the field.
        For instance dds maps most integer types to `int`,
        and both "float" and "double" to `double`.
    array_length : `int`
        Number of elements if an array; None if not an array.
    """

    def __init__(
        self,
        name: str,
        description: typing.Optional[str],
        units: typing.Optional[str],
        type_name: str,
        array_length: typing.Optional[int],
    ):
        self.name = name
        self.description = description
        self.units = units
        self.type_name = type_name
        self.array_length = array_length

    def __repr__(self) -> str:
        return (
            f"FieldMetadata(name={repr(self.name)}, "
            f"description={repr(self.description)}, "
            f"units={repr(self.units)}, "
            f"type_name={repr(self.type_name)},"
            f"array_length={self.array_length})"
        )

    def __str__(self) -> str:
        return f"description={repr(self.description)}, units={repr(self.units)}"


def parse_idl(name: str, idl_path: type_hints.PathType) -> IdlMetadata:
    """Parse the SAL-generated IDL file.

    Parameters
    ----------
    name : str`
        SAL component name, e.g. "ATPtg".
    idl_path : `str` or `pathlib.Path`
        Path to IDL file

    Returns
    -------
    metadata : `IdlMetadata`
        Parsed metadata.
    """
    # List of field types used in IDL, excluding "unsigned".
    type_names = (
        "string",
        "boolean",
        "float",
        "double",
        "octet",
        "short",
        "int",
        "long",
        "long long",
    )
    type_names_str = "|".join(type_names)

    sal_version_pattern = re.compile(
        r"//\sSAL_VERSION=(?P<sal_version>\S+) XML_VERSION=(?P<xml_version>\S+)"
    )
    topic_start_pattern = re.compile(
        r"\s*struct\s+(?P<sal_topic_name>.+)_(?P<version_hash>[a-zA-Z0-9]+) +{"
        r'\s*(?:// @Metadata=\((?:Description="(?P<description>.*)")?\))?'
    )
    topic_end_pattern = re.compile(r"\s};")
    field_pattern = re.compile(
        rf"\s*(?P<type_name>(?:unsigned )?(?:{type_names_str}))(?:<(?P<str_length>\d+)>)?"
        r"\s+(?P<field_name>[a-zA-Z][a-zA-Z0-9_-]*)(?:\[(?P<array_length>\d+)\])?;"
        r"\s*(?://\s*private)?"
        r'\s*(?://\s+@Metadata=\((?:Units="(?P<units>[^"]*)",)?'
        r'\s*(?:Description="(?P<description>.*)")?\))?'
    )

    # dict of sal_topic_name: `TopicMetadata`
    topic_info = dict()

    # Set topic_metadata to a `TopicMetadata` when parsing data for a topic
    # and None when not.
    topic_metadata = None
    isfirst = True
    sal_version = None
    xml_version = None
    with open(idl_path, "r") as f:
        for line in f:
            # The first line should contain version information
            # encoded as a comment.
            if isfirst:
                isfirst = False
                version_match = sal_version_pattern.match(line)
                if version_match:
                    sal_version = version_match.group("sal_version")
                    xml_version = version_match.group("xml_version")
                    continue

            if topic_metadata is None:
                # Look for the start of a new topic.
                topic_match = topic_start_pattern.match(line)
                if not topic_match:
                    continue

                sal_topic_name = topic_match.group("sal_topic_name")
                if sal_topic_name in topic_info:
                    raise RuntimeError(
                        f"Already parsed data for topic {sal_topic_name}"
                    )
                version_hash = topic_match.group("version_hash")
                topic_description = topic_match.group("description")
                topic_metadata = TopicMetadata(
                    sal_name=sal_topic_name,
                    version_hash=version_hash,
                    description=topic_description,
                )
                topic_info[sal_topic_name] = topic_metadata
            else:
                # Look for the next field or the end of this topic.
                field_match = field_pattern.match(line)
                if field_match:
                    field_name = field_match.group("field_name")
                    array_length = field_match.group("array_length")
                    if array_length is not None:
                        array_length = int(array_length)
                    topic_metadata.field_info[field_name] = FieldMetadata(
                        name=field_name,
                        type_name=field_match.group("type_name"),
                        description=field_match.group("description"),
                        units=field_match.group("units"),
                        array_length=array_length,
                    )
                elif topic_end_pattern.match(line):
                    topic_metadata = None

    return IdlMetadata(
        name=name,
        idl_path=idl_path,
        sal_version=sal_version,
        xml_version=xml_version,
        topic_info=topic_info,
    )
