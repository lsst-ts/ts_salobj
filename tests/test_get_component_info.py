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

import json
import subprocess
import unittest

from lsst.ts import salobj


class GetComponentInfoTestCase(unittest.TestCase):
    def check_result(self, result_json: str, name: str) -> None:
        result = json.loads(result_json)
        assert isinstance(result, dict)
        assert result.keys() == {"topics", "field_enums", "global_enums"}
        topics = result["topics"]
        component_info = salobj.ComponentInfo(name=name, topic_subname="")
        all_sal_topic_names = {
            topic_info.sal_name for topic_info in component_info.topics.values()
        }
        assert topics.keys() == all_sal_topic_names
        for topic_info in component_info.topics.values():
            topic_info_dict = topics[topic_info.sal_name]
            assert topic_info_dict.keys() == {"avro_schema", "array_fields"}
            assert topic_info_dict["avro_schema"] == topic_info.make_avro_schema()
            assert topic_info_dict["array_fields"] == topic_info.array_fields

        # Checke nums for Test. Do not check the other components
        # at this level of detail, because their enums may change.
        if name == "Test":
            assert result["field_enums"] == [
                [
                    "Test_logevent_scalars",
                    "int0",
                    ["Int0Enum_One", "Int0Enum_Two", "Int0Enum_Three"],
                ],
                [
                    "Test_logevent_arrays",
                    "int0",
                    [
                        "Int0ValueEnum_Zero=0",
                        "Int0ValueEnum_Two=2",
                        "Int0ValueEnum_Four=04",
                        "Int0ValueEnum_Five=0x05",
                    ],
                ],
            ]
            assert result["global_enums"] == [
                ["Enum", ["One", "Two", "Three"]],
                ["ValueEnum", ["Zero=0", "Two=2", "Four=04", "Five=0x05"]],
            ]

    def test_operation(self) -> None:
        for name in ["Test", "Script", "MTMount"]:
            with self.subTest(name=name):
                proc = self.run_get_component_info(args=[name])
                self.check_result(result_json=proc.stdout, name=name)

    def test_errors(self) -> None:
        bad_option = "--badoption"
        proc = self.run_get_component_info(args=["Test", bad_option])
        assert proc.returncode != 0
        assert bad_option in str(proc.stderr)

        bad_name = "NoSuchComponent"
        proc = self.run_get_component_info(args=[bad_name])
        assert proc.returncode != 0
        assert bad_name in str(proc.stderr)

        too_many_components = ["Test", "Script"]
        proc = self.run_get_component_info(args=too_many_components)
        assert proc.returncode != 0
        # The first extra component name should show up in the error message.
        assert too_many_components[1] in str(proc.stderr)

    def run_get_component_info(self, args: list[str]) -> subprocess.CompletedProcess:
        """Run get_component_info with specified arguments.

        Parameters
        ----------
        args : `list`[`str`]
            Command-line arguments.

        Returns
        -------
        result : subprocess.CompletedProcess
            The result of subprocess.run. The ``stdout`` attribute
            will have a json string containing the schemas,
            if generated, and ``stderr`` will start with a log message
            and then have error messages, if any.
        """
        return subprocess.run(["get_component_info"] + args, capture_output=True)
