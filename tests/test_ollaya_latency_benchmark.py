"""Ollaya 없이 언어·복잡도·정답 위치별 지연시간 집계를 검증한다."""

from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path

from simulation.evaluation.ollaya_latency_benchmark import (
    CSV_FILENAME, SUMMARY_FILENAME, TEST_CASES, TRIALS_FILENAME,
    run_latency_benchmark,
)


class _FakeSelector:
    model = "laya:multilingual"

    def __init__(self):
        self.calls = 0

    def select_choice(self, _state, candidates, _instructions, *, question_id="decision"):
        self.calls += 1
        correct_values = {
            "파란색", "Blue", "민수", "Alice",
            "path=[2, 5, 4, 6, 10], distance=1.592143",
        }
        choice = next(
            (key for key, value in candidates.items() if value in correct_values),
            next(iter(candidates)),  # warmup route data uses the same correct value
        )
        return {
            "choice": choice,
            "confidence": 0.8,
            "probabilities": {key: 0.2 for key in candidates},
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
            value for index, duration in enumerate(durations)
            for value in (float(index), float(index) + duration)
        )

    def __call__(self):
        return next(self.values)


class OllayaLatencyBenchmarkTest(unittest.TestCase):
    def test_builds_five_options_and_moves_answer_through_every_position(self):
        self.assertEqual(len(TEST_CASES), 30)
        for language in ("ko", "en"):
            for question_type in ("intuitive", "reasoning", "shortest_path"):
                cases = [
                    case for case in TEST_CASES
                    if case["language"] == language
                    and case["question_type"] == question_type
                ]
                self.assertEqual(len(cases), 5)
                self.assertEqual(
                    {case["expected_choice"] for case in cases},
                    {"option_a", "option_b", "option_c", "option_d", "option_e"},
                )
                self.assertTrue(all(len(case["candidates"]) == 5 for case in cases))

    def test_all_dimensions_are_measured_and_exported(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            output = Path(temporary_directory) / "result"
            selector = _FakeSelector()
            durations = [0.1, 0.2] * len(TEST_CASES)
            summary = run_latency_benchmark(
                output, repeats=2, warmups=1,
                realtime_deadline_seconds=0.15, selector=selector,
                clock=_SteppedClock(durations), progress=False,
            )

            self.assertEqual(selector.calls, 66)  # six warmups + 60 trials
            self.assertEqual(summary["settings"]["case_count"], 30)
            self.assertEqual(summary["settings"]["option_count"], 5)
            self.assertEqual(summary["settings"]["expected_trial_count"], 60)
            self.assertEqual(summary["overall"]["trial_count"], 60)
            self.assertEqual(summary["overall"]["correct_count"], 60)
            self.assertEqual(len(summary["groups"]), 6)
            self.assertEqual(len(summary["answer_positions"]), 5)
            for group in summary["groups"]:
                self.assertEqual(group["trial_count"], 10)
                self.assertAlmostEqual(group["realtime_met_rate"], 0.5)

            trials = [
                json.loads(line)
                for line in (output / TRIALS_FILENAME).read_text(
                    encoding="utf-8"
                ).splitlines()
            ]
            self.assertEqual(len(trials), 60)
            self.assertEqual({row["language"] for row in trials}, {"ko", "en"})
            self.assertTrue((output / SUMMARY_FILENAME).is_file())
            with (output / CSV_FILENAME).open(
                encoding="utf-8-sig", newline=""
            ) as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual(len(rows), 60)
            self.assertIn("answer_position", rows[0])
            self.assertIn("language", rows[0])


if __name__ == "__main__":
    unittest.main()
