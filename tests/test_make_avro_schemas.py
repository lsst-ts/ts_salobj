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
from lsst.ts import xml


class MakeAvroSchemasTestCase(unittest.TestCase):
    def check_result(self, result_json: str, components: list[str]) -> None:
        result = json.loads(result_json)
        assert isinstance(result, dict)
        assert result.keys() == set(components)
        for component, topics in result.items():
            component_info = salobj.ComponentInfo(name=component, topic_subname="")
            all_sal_topic_names = {
                topic_info.sal_name for topic_info in component_info.topics.values()
            }
            assert topics.keys() == all_sal_topic_names
            for topic_info in component_info.topics.values():
                assert topics[topic_info.sal_name] == topic_info.make_avro_schema()

    def test_one_topic(self) -> None:
        for component in ["Test", "Script", "MTMount"]:
            with self.subTest(component=component):
                proc = self.run_make_avro_schemas(args=[component])
                self.check_result(result_json=proc.stdout, components=[component])

    def test_multiple_topics(self) -> None:
        components = ["ATDome", "MTM1M3", "FiberSpectrograph"]
        proc = self.run_make_avro_schemas(args=components)
        self.check_result(result_json=proc.stdout, components=components)

    def test_all(self) -> None:
        proc = self.run_make_avro_schemas(args=["--all"])
        result = json.loads(proc.stdout)
        assert result.keys() == set(xml.subsystems)

    def test_all_with_exclude(self) -> None:
        excludes = ["ATDome", "MTM1M3", "FiberSpectrograph"]
        expected_components = set(xml.subsystems) - set(excludes)

        proc = self.run_make_avro_schemas(args=["--all", "--exclude"] + excludes)
        result = json.loads(proc.stdout)
        assert result.keys() == expected_components

        bad_exclude = "NoSuchComponent"
        proc = self.run_make_avro_schemas(args=["--all", "--exclude", bad_exclude])
        assert proc.returncode != 0
        assert bad_exclude in str(proc.stderr)

    def test_errors(self) -> None:
        bad_option = "--nosucharg"
        proc = self.run_make_avro_schemas(args=[bad_option])
        assert proc.returncode != 0
        assert bad_option in str(proc.stderr)

        bad_component = "NoSuchComponent"
        proc = self.run_make_avro_schemas(args=[bad_component])
        assert proc.returncode != 0
        assert bad_component in str(proc.stderr)

    def test_exclude(self) -> None:
        components = ["ATDome", "MTM1M3", "FiberSpectrograph"]
        for excludes in (
            ["MTM1M3"],
            ["ATDome", "MTM1M3"],
            components,
        ):
            with self.subTest(excludes=excludes):
                expected_components = set(components) - set(excludes)
                exclude_args = ["--exclude"] + excludes
                proc = self.run_make_avro_schemas(args=components + exclude_args)
                result = json.loads(proc.stdout)
                assert result.keys() == expected_components

        bad_exclude = "NoSuchComponent"
        proc = self.run_make_avro_schemas(args=components + ["--exclude", bad_exclude])
        assert proc.returncode != 0
        assert bad_exclude in str(proc.stderr)

    def run_make_avro_schemas(self, args: list[str]) -> subprocess.CompletedProcess:
        """Run make_avro_schemas with a specific lists of components.

        Parameters
        ----------
        args : `list`[`str`]
            Component names or other command-line arguments.

        Returns
        -------
        result : subprocess.CompletedProcess
            The result of subprocess.run. The ``stdout`` attribute
            will have a json string containing the schemas,
            if generated, and ``stderr`` will start with a log message
            and then have error messages, if any.
        """
        return subprocess.run(["make_avro_schemas"] + args, capture_output=True)
