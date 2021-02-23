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

import unittest
import pathlib

from lsst.ts import idl
from lsst.ts import salobj


class IdlParserTestCase(unittest.TestCase):
    def setUp(self):
        self.data_path = pathlib.Path(__file__).resolve().parents[0] / "data"

    def test_parse_simple_with_metadata(self):
        self.check_parse_simple(has_metadata=True)

    def test_parse_simple_without_metadata(self):
        self.check_parse_simple(has_metadata=False)

    def check_parse_simple(self, has_metadata):
        """Parse one of the Simple IDL files and check all of the
        resulting metadata.

        Note that the Simple IDL file is a simplified version of the Test IDL
        file, with only a few topics and removing user-defined fields
        with duplicate types.
        """
        if has_metadata:
            idl_path = self.data_path / "sal_revCoded_SimpleWithMetadata.idl"
        else:
            idl_path = self.data_path / "sal_revCoded_SimpleWithoutMetadata.idl"
        metadata = salobj.parse_idl(name="Simple", idl_path=idl_path)
        self.assertEqual(metadata.name, "Simple")
        self.assertTrue(idl_path.samefile(metadata.idl_path))
        if has_metadata:
            self.assertEqual(metadata.sal_version, "4.1.0")
            self.assertEqual(metadata.xml_version, "1.0.0")
        else:
            self.assertIsNone(metadata.sal_version)
            self.assertIsNone(metadata.xml_version)
        self.assertEqual(
            set(metadata.topic_info.keys()),
            set(("command_setArrays", "logevent_scalars")),
        )

        # Dict of field name: expected type name
        field_types = dict(
            TestID="long",
            private_revCode="string",
            private_sndStamp="double",
            private_rcvStamp="double",
            private_seqNum="long",
            private_identity="string",
            private_origin="long",
            boolean0="boolean",
            char0="string",
            short0="short",
            long0="long",
            longLong0="long long",
            octet0="octet",
            string0="string",
            unsignedShort0="unsigned short",
            unsignedLong0="unsigned long",
            float0="float",
            double0="double",
            priority="long",
        )

        for sal_topic_name, topic_metadata in metadata.topic_info.items():
            with self.subTest(sal_topic_name=sal_topic_name):
                self.assertEqual(topic_metadata.sal_name, sal_topic_name)
                self.assertEqual(topic_metadata.version_hash, "1234abcd")
                if has_metadata:
                    expected_description = f"Description of {sal_topic_name}"
                    self.assertEqual(topic_metadata.description, expected_description)
                else:
                    self.assertIsNone(topic_metadata.description)
                expected_field_names = set(field_types.keys())
                if sal_topic_name == "command_setArrays":
                    expected_field_names = set(
                        name
                        for name in expected_field_names
                        if name not in ("char0", "string0", "priority")
                    )

                self.assertEqual(
                    set(topic_metadata.field_info.keys()), expected_field_names
                )
                for field_name, field_metadata in topic_metadata.field_info.items():
                    self.assertEqual(field_metadata.name, field_name)
                    if has_metadata:
                        expected_units = (
                            "secs"
                            if field_metadata.name.endswith("Stamp")
                            else "unitless"
                        )
                        self.assertEqual(field_metadata.units, expected_units)
                        self.assertEqual(
                            field_metadata.description, f"Description of {field_name}"
                        )
                    else:
                        self.assertIsNone(field_metadata.units)
                        self.assertIsNone(field_metadata.description)
                    expected_str_length = {"string0": 20, "private_revCode": 8}.get(
                        field_name
                    )
                    self.assertEqual(field_metadata.str_length, expected_str_length)
                    self.assertEqual(field_metadata.type_name, field_types[field_name])
                    if sal_topic_name == "command_setArrays":
                        expected_array_length = 5 if field_name.endswith("0") else None
                    else:
                        expected_array_length = None
                    self.assertEqual(field_metadata.array_length, expected_array_length)

    def test_test_idl(self):
        """Test a Test IDL file generated by the current version of ts_sal.

        This is to catch format changes relative to the local Simple IDL files.
        It is not as thorough as the tests for the local Simple IDL files
        because I don't want to make too many assumptions about minor details
        of the XML.
        """
        idl_path = idl.get_idl_dir() / "sal_revCoded_Test.idl"
        metadata = salobj.parse_idl(name="Test", idl_path=idl_path)
        self.assertEqual(metadata.name, "Test")
        self.assertTrue(idl_path.samefile(metadata.idl_path))

        # Check that names match between info dict keys
        # and the name in the metadata.
        for sal_topic_name, topic_metadata in metadata.topic_info.items():
            self.assertEqual(topic_metadata.sal_name, sal_topic_name)
            for field_name, field_metadata in topic_metadata.field_info.items():
                self.assertEqual(field_metadata.name, field_name)

        # Check that some of the expected topic names are present.
        some_expected_topic_names = (
            "command_enable",
            "command_setArrays",
            "command_setScalars",
            "logevent_arrays",
            "logevent_scalars",
            "arrays",
            "scalars",
        )
        self.assertTrue(
            set(some_expected_topic_names).issubset(set(metadata.topic_info.keys()))
        )

        # Dict of field name: expected type name
        field_types = dict(
            TestID="long",
            private_revCode="string",
            private_sndStamp="double",
            private_rcvStamp="double",
            private_seqNum="long",
            private_identity="string",
            private_origin="long",
            private_host="long",
            boolean0="boolean",
            byte0="octet",
            char0="string",
            short0="short",
            int0="long",
            long0="long",
            longLong0="long long",
            octet0="octet",
            string0="string",
            unsignedShort0="unsigned short",
            unsignedInt0="unsigned long",
            unsignedLong0="unsigned long",
            float0="float",
            double0="double",
            priority="long",
        )

        # Check some details of arrays topics, including data type,
        # array length and string length.
        for topic_name in ("arrays", "logevent_arrays", "command_setArrays"):
            with self.subTest(topic_name=topic_name):
                topic_metadata = metadata.topic_info[topic_name]
                expected_field_names = set(field_types.keys())
                expected_field_names.remove("string0")  # only in scalars
                if not topic_name.startswith("logevent_"):
                    expected_field_names.remove("priority")
                # There is no char0 field in arrays
                expected_field_names.remove("char0")
                self.assertEqual(
                    set(topic_metadata.field_info.keys()), expected_field_names
                )
                for field_metadata in topic_metadata.field_info.values():
                    if field_metadata.name[-1] != "0":
                        self.assertIsNone(field_metadata.array_length)
                    elif field_metadata.name == "char0":
                        self.assertIsNone(field_metadata.array_length)
                    else:
                        self.assertEqual(field_metadata.array_length, 5)
                    if field_metadata.name == "TestID":
                        self.assertIsNone(field_metadata.description)
                    else:
                        self.assertIsInstance(field_metadata.description, str)
                    self.assertEqual(
                        field_metadata.type_name, field_types[field_metadata.name]
                    )

        # Check some details of scalars topics, including data type,
        # array length and string length.
        for topic_name in ("scalars", "logevent_scalars", "command_setScalars"):
            with self.subTest(topic_name=topic_name):
                topic_metadata = metadata.topic_info[topic_name]
                expected_field_names = set(field_types.keys())
                if not topic_name.startswith("logevent_"):
                    expected_field_names.remove("priority")
                self.assertEqual(
                    set(topic_metadata.field_info.keys()), expected_field_names
                )
                for field_metadata in topic_metadata.field_info.values():
                    self.assertIsNone(field_metadata.array_length)
                    if field_metadata.name == "TestID":
                        self.assertIsNone(field_metadata.description)
                    else:
                        self.assertIsInstance(field_metadata.description, str)
                    self.assertEqual(
                        field_metadata.type_name, field_types[field_metadata.name]
                    )


if __name__ == "__main__":
    unittest.main()
