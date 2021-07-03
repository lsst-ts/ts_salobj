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

import itertools
import logging
import unittest

from lsst.ts import salobj


class QueueCapacityCheckerTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.log = logging.getLogger()

    def test_constructor(self) -> None:
        for queue_len, expected_warn_thresholds in (
            (10, (5, 9, 10)),
            (19, (5, 17, 19)),
            (20, (5, 10, 18, 20)),
            (100, (10, 50, 90, 100)),
        ):
            with self.subTest(queue_len=queue_len):
                qlc = salobj.topics.read_topic.QueueCapacityChecker(
                    descr="test", log=self.log, queue_len=queue_len
                )
                self.assertEqual(qlc.warn_thresholds, expected_warn_thresholds)

        for invalid_len in (-1, 0, 1, 9):
            with self.subTest(invalid_len=invalid_len):
                with self.assertRaises(ValueError):
                    salobj.topics.read_topic.QueueCapacityChecker(
                        descr="test", log=self.log, queue_len=invalid_len
                    )

    def test_check_nitems(self) -> None:
        """Test the check_nitems method, going from all possible
        initial states to all possible final states.
        """
        for queue_len in (10, 33, 100):
            nthresh = 3 if queue_len < 20 else 4
            # ``start_index`` and ``end_index`` are indices into
            # warning_thresholds that specify the initial and final warning
            # thresholds (and associated reset thresholds).
            # ``use_min`` specifies whether to call ``check_nitems``
            # with the minimum (True) or maximum (False) value of ``nitems``
            # that should cause the desired transition.
            for start_index, end_index, use_min in itertools.product(
                range(nthresh + 1), range(nthresh + 1), (False, True)
            ):
                with self.subTest(
                    queue_len=queue_len, start_index=start_index, end_index=end_index
                ):
                    if end_index == start_index:
                        # This case is handled by check_nochange_values
                        continue
                    qlc = self.make_checker(queue_len, start_index)
                    self.assertEqual(len(qlc.warn_thresholds), nthresh)
                    self.check_nochange_values(qlc)

                    if end_index > start_index:
                        continue
                        # Warn of an increase
                        if use_min:
                            nitems = qlc.warn_thresholds[end_index - 1]
                        elif end_index == nthresh:
                            # There is only one valid value of nitems
                            # and it is covered by use_min True
                            continue
                        else:
                            nitems = qlc.warn_thresholds[end_index] - 1
                        expected_log_level = (
                            logging.WARNING if end_index < nthresh else logging.ERROR
                        )
                        with self.assertLogs(logger=qlc.log, level=expected_log_level):
                            did_log = qlc.check_nitems(nitems)
                        self.assertTrue(did_log)
                        if end_index == nthresh:
                            expected_warn_threshold = None
                        else:
                            expected_warn_threshold = qlc.warn_thresholds[end_index]
                        self.assertEqual(qlc.warn_threshold, expected_warn_threshold)
                        expected_reset_threshold = (
                            qlc.warn_thresholds[end_index - 1] // 2
                        )
                        self.assertEqual(qlc.reset_threshold, expected_reset_threshold)
                    else:
                        # Reset to a lower warning level
                        if use_min:
                            if end_index > 0:
                                nitems = (qlc.warn_thresholds[end_index - 1] // 2) + 1
                            else:
                                nitems = 0
                        else:
                            nitems = qlc.warn_thresholds[end_index] // 2
                        did_log = qlc.check_nitems(nitems)
                        self.assertFalse(did_log)
                        expected_warn_threshold = qlc.warn_thresholds[end_index]
                        self.assertEqual(qlc.warn_threshold, expected_warn_threshold)
                        if end_index > 0:
                            expected_reset_threshold = (
                                qlc.warn_thresholds[end_index - 1] // 2
                            )
                        else:
                            expected_reset_threshold = None
                        self.assertEqual(qlc.reset_threshold, expected_reset_threshold)

    def make_checker(
        self, queue_len: int, warn_index: int
    ) -> salobj.topics.read_topic.QueueCapacityChecker:
        """Make a QueueCapacityChecker with specified warn_threshold.

        Parameters
        ----------
        queue_len : `int`
            Queue length. Must be >= 10.
        warn_index : `int`
            Initial warn_threshold is ``warn_thresholds[warn_index]``,
            or `None` if ``warn_index == len(warn_thresholds)``.
            then the initial warn_threshold is `None`
        """
        qlc = salobj.topics.read_topic.QueueCapacityChecker(
            descr="test", log=self.log, queue_len=queue_len
        )
        self.assertIsNone(qlc.reset_threshold)
        self.assertEqual(qlc.warn_threshold, qlc.warn_thresholds[0])
        nthresh = len(qlc.warn_thresholds)
        if warn_index > 0:
            nitems = qlc.warn_thresholds[warn_index - 1]
            expected_log_level = (
                logging.WARNING if warn_index < nthresh else logging.ERROR
            )
            with self.assertLogs(logger=qlc.log, level=expected_log_level):
                did_log = qlc.check_nitems(nitems)
            self.assertTrue(did_log)

            if warn_index == nthresh:
                expected_warn_threshold = None
            else:
                expected_warn_threshold = qlc.warn_thresholds[warn_index]
            self.assertEqual(qlc.warn_threshold, expected_warn_threshold)

            expected_reset_threshold = qlc.warn_thresholds[warn_index - 1] // 2
            self.assertEqual(qlc.reset_threshold, expected_reset_threshold)
        return qlc

    def check_nochange_values(
        self, queue_len_checker: salobj.topics.read_topic.QueueCapacityChecker
    ) -> None:
        """Check that calling `check_nitems` does nothing for the full range
        of values that should not change anything.
        """
        min_len = (
            0
            if queue_len_checker.reset_threshold is None
            else queue_len_checker.reset_threshold + 1
        )
        max_len = (
            queue_len_checker.queue_len
            if queue_len_checker.warn_threshold is None
            else queue_len_checker.warn_threshold
        )
        for n in range(min_len, max_len):
            self.assertFalse(queue_len_checker.check_nitems(n))


if __name__ == "__main__":
    unittest.main()
