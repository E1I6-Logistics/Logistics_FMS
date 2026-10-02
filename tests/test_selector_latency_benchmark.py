"""모델 없이 언어·복잡도·정답 위치별 selector 지연시간 집계를 검증한다."""

from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path

from simulation.evaluation.selector_latency_benchmark import (
    CSV_FILENAME, ROUTE_CASES, ROUTE_GRAPH_PATH, SUMMARY_FILENAME, TEST_CASES,
    TRIALS_FILENAME,
    run_latency_benchmark,
)


class _FakeSelector:
    name = "fake-laya"
    model = "laya:multilingual"

    def __init__(self):
        self.calls = 0

    def select_choice(self, _state, candidates, _instructions, *, question_id="decision"):
        self.calls += 1
        correct_values = {
            "파란색", "Blue", "민수", "Alice",
        }
        route_candidates = [
            (float(value.rsplit("distance=", 1)[1]), key)
            for key, value in candidates.items()
            if value.startswith("path=")
        ]
        choice = next(
            (key for key, value in candidates.items() if value in correct_values),
            min(route_candidates)[1] if route_candidates else next(iter(candidates)),
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
            "runtime": {
                "device": "cuda:0", "device_name": "Fake RTX 4070 SUPER",
                "precision": "float16", "cpu_fallback_count": 0,
            },
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


class SelectorLatencyBenchmarkTest(unittest.TestCase):
    # 지연시간 케이스를 변경했을 때 정답이 다섯 위치에 고르게 배치되는지 확인한다.
    def test_builds_five_options_and_moves_answer_through_every_position(self):
        self.assertEqual(ROUTE_GRAPH_PATH.name, "test.geojson")
        self.assertEqual(len(ROUTE_CASES), 5)
        self.assertEqual(len(TEST_CASES), 70)
        for language in ("ko", "en"):
            for question_type in ("intuitive", "reasoning", "shortest_path"):
                cases = [
                    case for case in TEST_CASES
                    if case["language"] == language
                    and case["question_type"] == question_type
                ]
                expected_count = 25 if question_type == "shortest_path" else 5
                self.assertEqual(len(cases), expected_count)
                self.assertEqual(
                    {case["expected_choice"] for case in cases},
                    {"option_a", "option_b", "option_c", "option_d", "option_e"},
                )
                self.assertTrue(all(len(case["candidates"]) == 5 for case in cases))
        route_cases = [case for case in TEST_CASES if case["question_type"] == "shortest_path"]
        self.assertEqual(
            {(case["start_node"], case["target_node"]) for case in route_cases},
            set(ROUTE_CASES),
        )
        self.assertTrue(
            all(
                case["state"]["route_graph"]["source_graph"] == "test.geojson"
                and case["state"]["route_graph"]["node_coordinates"]
                for case in route_cases
            )
        )

    # 지연시간 집계를 변경했을 때 모든 조건과 결과 파일이 생성되는지 확인한다.
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

            self.assertEqual(selector.calls, 154)  # fourteen warmups + 140 trials
            self.assertEqual(summary["settings"]["case_count"], 70)
            self.assertEqual(summary["settings"]["option_count"], 5)
            self.assertEqual(summary["settings"]["expected_trial_count"], 140)
            self.assertEqual(summary["overall"]["trial_count"], 140)
            self.assertEqual(summary["overall"]["correct_count"], 140)
            self.assertEqual(len(summary["groups"]), 6)
            self.assertEqual(len(summary["answer_positions"]), 5)
            self.assertEqual(len(summary["routes"]), 5)
            for group in summary["groups"]:
                expected_trials = 50 if group["question_type"] == "shortest_path" else 10
                self.assertEqual(group["trial_count"], expected_trials)
                self.assertAlmostEqual(group["realtime_met_rate"], 0.5)

            trials = [
                json.loads(line)
                for line in (output / TRIALS_FILENAME).read_text(
                    encoding="utf-8"
                ).splitlines()
            ]
            self.assertEqual(len(trials), 140)
            self.assertEqual({row["selector_name"] for row in trials}, {"fake-laya"})
            self.assertEqual({row["language"] for row in trials}, {"ko", "en"})
            self.assertTrue((output / SUMMARY_FILENAME).is_file())
            with (output / CSV_FILENAME).open(
                encoding="utf-8-sig", newline=""
            ) as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual(len(rows), 140)
            self.assertIn("answer_position", rows[0])
            self.assertIn("start_node", rows[0])
            self.assertIn("language", rows[0])
            self.assertEqual(rows[0]["selector_name"], "fake-laya")
            manifest = json.loads(
                (output / "manifest.json").read_text(encoding="utf-8")
            )
            self.assertEqual(manifest["selector_name"], "fake-laya")
            self.assertEqual(manifest["device"]["actual"], "cuda:0")
            self.assertEqual(manifest["device"]["kind"], "gpu")
            self.assertEqual(manifest["device"]["device_name"], "Fake RTX 4070 SUPER")


if __name__ == "__main__":
    unittest.main()
