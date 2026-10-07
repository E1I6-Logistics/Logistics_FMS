"""모델 없이 selector 질문 타입과 반복 벤치마크를 검증한다."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from simulation.evaluation.selector_question_types_benchmark import (
    CASES,
    CSV_FILENAME,
    SUMMARY_FILENAME,
    TRIALS_FILENAME,
    run_question_types_benchmark,
)


class SelectorQuestionTypesTest(unittest.TestCase):
    # 질문 유형 벤치마크를 변경했을 때 choice·score·noul 결과가 저장되는지 확인한다.
    def test_benchmark_exports_question_type_cases(self):
        class FakeSelector:
            name = "fake-kev"
            model = "test-model"

            def select_choice(self, *_args, **_kwargs):
                return self.result(
                    choice="red", confidence=0.9, probabilities={"red": 0.9}
                )

            def evaluate_score(self, *_args, **_kwargs):
                return self.result(
                    score=3.8,
                    confidence=0.8,
                    probabilities={"4": 0.8},
                    legend={"4": "high"},
                )

            def evaluate_noul(self, *_args, **_kwargs):
                return self.result(noul=0.95)

            @staticmethod
            def result(**values):
                return {
                    "model": "test-model",
                    "total_duration_seconds": 0.02,
                    "load_duration_seconds": 0.0,
                    "eval_duration_seconds": 0.01,
                    "runtime": {
                        "device": "cuda:0", "device_name": "Fake RTX 4070 SUPER",
                        "precision": "float16", "cpu_fallback_count": 0,
                    },
                    "raw": {},
                    **values,
                }

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "run"
            values = iter(
                value
                for index in range(16)
                for value in (float(index), float(index) + 0.1)
            )
            summary = run_question_types_benchmark(
                output,
                repeats=2,
                warmups=1,
                selector=FakeSelector(),
                clock=lambda: next(values),
                progress=False,
            )
            self.assertEqual(len(CASES), 8)
            blocked_case = next(
                case for case in CASES if case["id"] == "ko_route_blocked_noul"
            )
            self.assertEqual(blocked_case["state"]["planned_route"], [0, 10, 9, 2])
            self.assertIn(10, blocked_case["state"]["blocked_nodes"])
            self.assertEqual(
                blocked_case["state"]["route_graph"]["source_graph"],
                "test_int.geojson",
            )
            self.assertEqual(
                len(blocked_case["state"]["route_graph"]["node_coordinates"]),
                13,
            )
            self.assertEqual(
                len(blocked_case["state"]["route_graph"]["edges"]),
                30,
            )
            self.assertTrue(blocked_case["expected_boolean"])
            english_blocked_case = next(
                case for case in CASES if case["id"] == "en_route_blocked_noul"
            )
            self.assertEqual(
                english_blocked_case["state"],
                blocked_case["state"]
                | {"rule": "A route cannot be used when it contains a blocked node."},
            )
            self.assertEqual(
                english_blocked_case["instructions"],
                "Is the current route unavailable?",
            )
            self.assertTrue(english_blocked_case["expected_boolean"])
            self.assertEqual(summary["settings"]["expected_trial_count"], 16)
            self.assertEqual(summary["overall"]["correct_count"], 16)
            self.assertEqual(len(summary["groups"]), 6)
            self.assertEqual(
                len((output / TRIALS_FILENAME).read_text(encoding="utf-8").splitlines()),
                16,
            )
            self.assertTrue((output / SUMMARY_FILENAME).is_file())
            self.assertTrue((output / CSV_FILENAME).is_file())
            manifest = json.loads(
                (output / "manifest.json").read_text(encoding="utf-8")
            )
            self.assertEqual(summary["selector_name"], "fake-kev")
            self.assertEqual(manifest["selector_name"], "fake-kev")
            trials = [json.loads(line) for line in (output / TRIALS_FILENAME).read_text(encoding="utf-8").splitlines()]
            self.assertEqual({row["selector_name"] for row in trials}, {"fake-kev"})
            self.assertEqual(manifest["device"]["actual"], "cuda:0")
            self.assertEqual(manifest["device"]["kind"], "gpu")
            self.assertEqual(manifest["device"]["device_name"], "Fake RTX 4070 SUPER")


if __name__ == "__main__":
    unittest.main()
