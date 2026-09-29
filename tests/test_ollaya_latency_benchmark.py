"""Ollaya 없이 세 질문 유형의 지연시간 집계를 검증한다."""

from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path

from simulation.evaluation.ollaya_latency_benchmark import (
    CSV_FILENAME,
    SUMMARY_FILENAME,
    TEST_CASES,
    TRIALS_FILENAME,
    run_latency_benchmark,
)


class _FakeSelector:
    model = "laya:multilingual"

    def __init__(self):
        self.calls = 0

    def select_choice(
        self, _state, candidates, _instructions, *, question_id="decision"
    ):
        self.calls += 1
        expected_by_case = {
            "intuitive": "blue",
            "reasoning": "minsu",
            "shortest_path": "route_b",
        }
        choice = expected_by_case[question_id]
        probability = 1 / len(candidates)
        return {
            "choice": choice,
            "confidence": 0.8,
            "probabilities": {key: probability for key in candidates},
            "model": "laya:multilingual",
            "routing": {"route": "multilingual"},
            "total_duration_seconds": 0.02,
            "load_duration_seconds": 0.0,
            "eval_duration_seconds": 0.015,
            "raw": {"done_reason": "decide"},
        }


class _SteppedClock:
    def __init__(self, durations):
        self.values = iter(
            value
            for index, duration in enumerate(durations)
            for value in (float(index), float(index) + duration)
        )

    def __call__(self):
        return next(self.values)


class OllayaLatencyBenchmarkTest(unittest.TestCase):
    def test_three_cases_are_measured_and_exported_separately(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            output = Path(temporary_directory) / "result"
            selector = _FakeSelector()
            # Three repeats for each of the three cases.
            durations = [0.1, 0.2, 0.3] * len(TEST_CASES)

            summary = run_latency_benchmark(
                output,
                repeats=3,
                warmups=1,
                realtime_deadline_seconds=0.15,
                selector=selector,
                clock=_SteppedClock(durations),
                progress=False,
            )

            self.assertEqual(selector.calls, 12)  # 3 warmups + 9 measured calls
            self.assertEqual(summary["settings"]["case_count"], 3)
            self.assertEqual(summary["settings"]["expected_trial_count"], 9)
            self.assertEqual(summary["overall"]["trial_count"], 9)
            self.assertEqual(summary["overall"]["correct_count"], 9)
            self.assertEqual(len(summary["cases"]), 3)
            self.assertEqual(
                {case["case_id"] for case in summary["cases"]},
                {"intuitive", "reasoning", "shortest_path"},
            )
            for case in summary["cases"]:
                self.assertEqual(case["trial_count"], 3)
                self.assertAlmostEqual(case["realtime_met_rate"], 1 / 3)
                self.assertAlmostEqual(case["wall_latency"]["median_seconds"], 0.2)

            trials = [
                json.loads(line)
                for line in (output / TRIALS_FILENAME).read_text(
                    encoding="utf-8"
                ).splitlines()
            ]
            self.assertEqual(len(trials), 9)
            self.assertEqual(
                {row["case_id"] for row in trials},
                {"intuitive", "reasoning", "shortest_path"},
            )
            self.assertTrue((output / SUMMARY_FILENAME).is_file())
            with (output / CSV_FILENAME).open(
                encoding="utf-8-sig", newline=""
            ) as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual(len(rows), 9)
            self.assertIn("case_id", rows[0])
            self.assertIn("eval_seconds", rows[0])


if __name__ == "__main__":
    unittest.main()
