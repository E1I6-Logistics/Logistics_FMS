"""Ollama 없이 반복 벤치마크의 실행·저장·재개 구조를 검증한다."""

from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from simulation.evaluation import benchmark
from simulation.evaluation.benchmark import (
    DEFAULT_CONFIG,
    load_and_validate_config,
    run_benchmark,
)


class _MockProvider:
    """Ollama 호출 없이 벤치마크 반복·저장 구조만 검증"""

    answers = {
        (0, 6): [0, 3, 4, 6],
        (1, 12): [1, 4, 6, 13, 12],
        (2, 10): [2, 5, 4, 6, 10],
        (0, 4): [0, 3, 4],
        (7, 2): [7, 8, 9, 10, 6, 4, 5, 2],
    }

    def __init__(self, model: str, calls: list[tuple[str, int, int]]):
        self.model = model
        self.calls = calls
        self.last_inference = None

    def compute_shortest_path(self, _graph: dict, start: int, goal: int) -> dict:
        self.calls.append((self.model, start, goal))
        path = self.answers[(start, goal)]
        self.last_inference = {
            "request": {"model": self.model, "start": start, "goal": goal},
            "response": {"message": {"content": json.dumps({"path": path})}},
        }
        return {"path": path, "reported_total_distance": 0.0}


class RouteGenerationBenchmarkTest(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.output = Path(self.temporary_directory.name) / "run"
        self.calls: list[tuple[str, int, int]] = []

    def provider_factory(self, model: dict, _settings: dict, _prompt: str):
        return _MockProvider(model["name"], self.calls)

    def test_frozen_graph_and_ground_truth_match(self):
        prepared = load_and_validate_config(DEFAULT_CONFIG)

        self.assertEqual(len(prepared["points"]), 14)
        self.assertEqual(len(prepared["edges"]), 28)
        self.assertEqual(
            prepared["config"]["prompt_sha256"],
            "53276490f7224be85126a1576d519d132566193b9bd7fec7d32b4e38f4cbfe44",
        )
        self.assertEqual(
            [case["expected_path"] for case in prepared["cases"]],
            [
                [0, 3, 4, 6],
                [1, 4, 6, 13, 12],
                [2, 5, 4, 6, 10],
            ],
        )

    def test_v3_has_ten_representative_models_and_five_routes(self):
        config_path = DEFAULT_CONFIG.with_name("route_generation_benchmark_v3.json")
        prepared = load_and_validate_config(config_path)

        self.assertEqual(
            [model["name"] for model in prepared["config"]["models"]],
            [
                "qwen3:0.6b",
                "deepseek-r1:1.5b",
                "llama3.2:3b",
                "qwen3:4b",
                "gemma3:4b",
                "llama3.1:8b",
                "mistral-nemo:12b",
                "gemma3:12b",
                "deepseek-r1:14b",
                "phi4:14b",
            ],
        )
        self.assertEqual(len(prepared["cases"]), 5)
        self.assertEqual(prepared["config"]["settings"]["repeats"], 5)
        self.assertEqual(
            [len(case["expected_path"]) for case in prepared["cases"]],
            [3, 4, 5, 5, 8],
        )

    def test_mock_run_writes_expected_matrix_and_exports(self):
        manifest = run_benchmark(
            DEFAULT_CONFIG,
            self.output,
            provider_factory=self.provider_factory,
            runtime_metadata={"test": "mock"},
            progress=False,
        )

        warmups = self._read_jsonl("warmups.jsonl")
        trials = self._read_jsonl("trials.jsonl")
        summary = json.loads(
            (self.output / "summary.json").read_text(encoding="utf-8")
        )
        self.assertEqual(len(warmups), 5)
        self.assertEqual(len(trials), 45)
        self.assertEqual(len(self.calls), 50)
        self.assertEqual(summary["trial_count"], 45)
        self.assertEqual(manifest["status"], "complete")
        self.assertEqual(manifest["completed_trial_count"], 45)
        self.assertTrue(
            all(row["metrics"]["shortest_distance_match"] for row in trials)
        )
        self.assertEqual(
            {row["trial_count"] for row in summary["models"]}, {9}
        )

        for filename in (
            "model_summary.csv",
            "route_summary.csv",
            "latency_samples.csv",
            "trial_samples.csv",
        ):
            self.assertTrue((self.output / filename).is_file())
        with (self.output / "latency_samples.csv").open(
            encoding="utf-8-sig", newline=""
        ) as stream:
            self.assertEqual(len(list(csv.DictReader(stream))), 45)

        with (self.output / "trial_samples.csv").open(
            encoding="utf-8-sig", newline=""
        ) as stream:
            rows = list(csv.DictReader(stream))
        self.assertEqual(len(rows), 45)
        self.assertIn("shortest_distance_match", rows[0])
        self.assertIn("llm_recalculated_distance", rows[0])

    def test_v3_mock_run_writes_complete_250_trial_matrix(self):
        """모델 10개 × 경로 5개 × 5회 실행의 결과 구조를 확인한다."""
        config_path = DEFAULT_CONFIG.with_name("route_generation_benchmark_v3.json")
        manifest = run_benchmark(
            config_path,
            self.output,
            provider_factory=self.provider_factory,
            runtime_metadata={"test": "mock-v3"},
            progress=False,
        )

        summary = json.loads(
            (self.output / "summary.json").read_text(encoding="utf-8")
        )
        self.assertEqual(manifest["warmup_count"], 10)
        self.assertEqual(manifest["expected_trial_count"], 250)
        self.assertEqual(manifest["completed_trial_count"], 250)
        self.assertEqual(summary["trial_count"], 250)
        self.assertEqual(len(summary["models"]), 10)
        self.assertEqual(len(summary["routes"]), 50)
        self.assertEqual(
            {row["trial_count"] for row in summary["models"]}, {25}
        )
        with (self.output / "trial_samples.csv").open(
            encoding="utf-8-sig", newline=""
        ) as stream:
            self.assertEqual(len(list(csv.DictReader(stream))), 250)

    def test_export_results_cli_rebuilds_csv_without_provider_calls(self):
        run_benchmark(
            DEFAULT_CONFIG,
            self.output,
            provider_factory=self.provider_factory,
            runtime_metadata={"test": "mock"},
            progress=False,
        )
        initial_call_count = len(self.calls)
        for filename in (
            "summary.json",
            "model_summary.csv",
            "route_summary.csv",
            "latency_samples.csv",
            "trial_samples.csv",
        ):
            (self.output / filename).unlink()

        with patch(
            "sys.argv",
            ["benchmark", "--export-results", str(self.output)],
        ):
            self.assertEqual(benchmark.main(), 0)

        self.assertEqual(len(self.calls), initial_call_count)
        for filename in (
            "summary.json",
            "model_summary.csv",
            "route_summary.csv",
            "latency_samples.csv",
            "trial_samples.csv",
        ):
            self.assertTrue((self.output / filename).is_file())

    def test_resume_skips_completed_warmups_and_trials(self):
        run_benchmark(
            DEFAULT_CONFIG,
            self.output,
            provider_factory=self.provider_factory,
            runtime_metadata={"test": "mock"},
            progress=False,
        )
        initial_call_count = len(self.calls)

        manifest = run_benchmark(
            DEFAULT_CONFIG,
            self.output,
            resume=True,
            provider_factory=self.provider_factory,
            runtime_metadata={"ignored": True},
            progress=False,
        )

        self.assertEqual(len(self.calls), initial_call_count)
        self.assertEqual(len(self._read_jsonl("warmups.jsonl")), 5)
        self.assertEqual(len(self._read_jsonl("trials.jsonl")), 45)
        self.assertEqual(manifest["status"], "complete")

    def _read_jsonl(self, filename: str) -> list[dict]:
        return [
            json.loads(line)
            for line in (self.output / filename)
            .read_text(encoding="utf-8")
            .splitlines()
            if line.strip()
        ]


if __name__ == "__main__":
    unittest.main()
