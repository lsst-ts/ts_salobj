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

__all__ = ["FieldInfo"]

import dataclasses
import typing
from xml.etree import ElementTree


def find_optional(element: ElementTree.Element, name: str, default: str) -> str:
    """Find an optional sub-element in an XML element and return the text.

    Parameters
    ----------
    element : ElementTree.Element
        XML element
    name : str
        Field name.
    default : str
        Value to return if the field does not exist.
    """
    subelt = element.find(name)
    if subelt is None or subelt.text is None:
        return default
    return subelt.text


def find_required(element: ElementTree.Element, name: str) -> str:
    """Find a required sub-element in an XML element and return the text.

    Parameters
    ----------
    element : ElementTree.Element
        XML element
    name : str
        Field name.
    """
    subelt = element.find(name)
    if subelt is None or subelt.text is None:
        raise RuntimeError(f"Could not find required field {name}")
    return subelt.text


# Dict of SAL type: python type
PYTHON_TYPES = {
    "boolean": bool,
    "byte": int,
    "short": int,
    "int": int,
    "long": int,
    "long long": int,
    "unsigned short": int,
    "unsigned int": int,
    "unsigned long": int,
    "float": float,
    "double": float,
    "string": str,
}

# Dict of SAL type: Avro type
AVRO_TYPES = {
    "boolean": "boolean",
    "byte": "int",
    "short": "int",
    "int": "int",
    "long": "long",
    "long long": "long",
    "unsigned short": "int",
    "unsigned int": "int",
    "unsigned long": "long",
    "float": "float",
    "double": "double",
    "string": "string",
}


@dataclasses.dataclass
class FieldInfo:
    """Information about one field of a topic.

    Parameters
    ----------
    name : str
        Field name
    sal_type : str
        SAL data type.
    nelts : int
        For lists: the fixed list length.
    max_len : int
        For strings: the max length, or 0 for no limit.
    units : str
        Units, "unitless" if none.
    description : str
        Description (arbitrary text)

    Attributes
    ----------
    default_scalar_value : typing.Any
        For a scalar: the default value.
        For an array: the default value of one element.
    """

    name: str
    sal_type: str
    nelts: int = 1
    max_len: int = 1
    units: str = "unitless"
    description: str = ""
    default_scalar_value: typing.Any = dataclasses.field(init=False)

    def __post_init__(self) -> None:
        if self.sal_type == "string":
            if self.nelts > 1:
                raise ValueError(
                    f"nelts={self.nelts} > 1, but string fields cannot be arrays"
                )
        else:
            if self.max_len > 1:
                raise ValueError(f"max_len={self.max_len} can only be > 1 for strings")
        python_type = PYTHON_TYPES[self.sal_type]
        self.default_scalar_value = python_type()

    @classmethod
    def from_xml_element(cls, element: ElementTree.Element, indexed: bool) -> FieldInfo:
        """Construct a FieldInfo from an XML element."""
        name = find_required(element, "EFDB_Name")
        description = find_optional(element, "Description", "")
        nelts = int(find_optional(element, "Count", "1"))
        units = find_optional(element, "Units", "unitless")
        sal_type = find_required(element, "IDL_Type")
        max_len = 0
        return FieldInfo(
            name=name,
            sal_type=sal_type,
            nelts=nelts,
            max_len=max_len,
            units=units,
            description=description,
        )

    def make_dataclass_tuple(
        self,
    ) -> typing.Tuple[str, typing.Type[typing.Any], dataclasses.Field]:
        """Create field data for dataclasses.make_dataclasses."""
        scalar_type = PYTHON_TYPES[self.sal_type]
        if self.nelts > 1:
            dtype: typing.Type[typing.Any] = typing.List[scalar_type]  # type: ignore
            field: dataclasses.Field = dataclasses.field(
                default_factory=lambda: [self.default_scalar_value] * self.nelts  # type: ignore
            )
        else:
            dtype = scalar_type
            field = dataclasses.field(default=self.default_scalar_value)
        return (self.name, dtype, field)

    def make_avro_schema(self) -> typing.Dict[str, typing.Any]:
        """Return an Avro schema for this field."""
        scalar_type = AVRO_TYPES[self.sal_type]
        if self.nelts > 1:
            return {
                "name": self.name,
                "type": {"type": "array", "items": scalar_type},
                "default": [self.default_scalar_value] * self.nelts,
            }
        else:
            return {
                "name": self.name,
                "type": scalar_type,
                "default": self.default_scalar_value,
            }
