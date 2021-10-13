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

__all__ = ["get_dds_version", "parse_idl_file", "make_dds_topic_class"]

import pathlib
import re
import subprocess
import typing
from xml.etree import ElementTree

import dds

from . import _ddsutil
from . import type_hints


def get_dds_version(dds_file: typing.Optional[str] = None) -> str:
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


def parse_idl_file(idl_path: type_hints.PathType) -> ElementTree.Element:
    """Parse an IDL file as XML.

    Intended for use with `make_dds_topic_class`.
    """
    out = subprocess.Popen(
        ["idlpp", "-l", "pythondesc", idl_path], stdout=subprocess.PIPE
    ).communicate()[0]
    # print ("Descriptor : ", out)

    # Eval version of idlpp puts out a problematic header, remove it.
    evalHeader = br"[^\n]*EVALUATION VERSION\r?\n"
    match = re.match(evalHeader, out)
    if match:
        out = out[match.end() :].strip()  # strip leading/training spaces, too

    if not out.startswith(b"<topics"):
        raise RuntimeError("Problem found with given IDL file:\n" + out.decode())

    return ElementTree.fromstring(out)


def make_dds_topic_class(parsed_idl: ElementTree.Element, revname: str) -> typing.Any:
    """Make a data class for a DDS topic.

    Parameters
    ----------
    parsed_idl : `xml.xml.etree.ElementTree.Element`
        IDL file parsed by `parse_idl_file`.
    revname : `str`
        Full name of DDS topic, including revision suffix.

    Returns
    -------
    The topic data class.
    """
    revname = revname
    topictype = parsed_idl.find("topictype[id='%s']" % revname)
    if topictype is None:
        raise RuntimeError(f"IDL file does not define revname={revname}")
    descriptor = topictype.findtext("descriptor")
    keys = topictype.findtext("keys")

    root = ElementTree.fromstring(descriptor)  # type: ignore
    # Compose xpath to find a topic struct
    gen_classes: typing.Any = {}
    _ddsutil._process_descriptor_element(root, "", gen_classes)  # type: ignore

    if revname not in _ddsutil._class_dict:  # type: ignore
        raise RuntimeError(f"Could not find topic data for revname={revname}.")

    data_class = _ddsutil._class_dict[revname]  # type: ignore
    typesupport_class = _ddsutil._dds_type_support(  # type: ignore
        descriptor, revname, keys, data_class
    )
    return _ddsutil.GeneratedClassInfo(  # type: ignore
        data_class,
        typesupport_class,
        gen_classes,
    )
