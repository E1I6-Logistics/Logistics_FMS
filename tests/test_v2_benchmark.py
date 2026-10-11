"""V2 행렬의 6조건과 공통 비교 조건을 확인한다."""

import json
import tempfile
import unittest
from pathlib import Path

from simulation.evaluation.benchmark import load_and_validate_config
from simulation.evaluation.v2_benchmark import (
    DEFAULT_MATRIX,
    resolve_experiment_configs,
)


class V2BenchmarkTest(unittest.TestCase):
    # Direct·CoT Graph Retrieval과 Iterative Neighbor Context를 포함한 6조건을 확인한다.
    def test_resolves_six_conditions_with_one_common_hash(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = resolve_experiment_configs(DEFAULT_MATRIX, Path(directory))
            configs = [json.loads(path.read_text()) for path in paths]

        self.assertEqual(len(configs), 6)
        self.assertEqual(len({item["comparison_condition_sha256"] for item in configs}), 1)
        self.assertEqual(sum(item["retrieval"]["enabled"] for item in configs), 2)
        self.assertEqual(
            sum(item["neighbor_context"]["enabled"] for item in configs), 1
        )
        self.assertEqual(
            {item["graph"]["model_input_format"] for item in configs},
            {"CompactAdjacencyGraph"},
        )

    # 고정 10쌍을 사용하고 반복 규칙·지시문을 최종 인접 선택 시험과 통일한다.
    def test_iterative_policy_matches_final_benchmark(self):
        from simulation.services.iterative_route_policy import NEXT_NODE_INSTRUCTIONS
        with tempfile.TemporaryDirectory() as directory:
            configs = [json.loads(p.read_text()) for p in resolve_experiment_configs(DEFAULT_MATRIX, Path(directory))]
        for config in configs:
            self.assertEqual(len(config["cases"]), 10)
            self.assertEqual(len({(c["start"], c["goal"]) for c in config["cases"]}), 10)
            self.assertEqual(config["case_selection"]["case_count"], 10)
            self.assertTrue(all(c["goal"] in range(7) and c["start"] != c["goal"] for c in config["cases"]))
            self.assertEqual(config["case_selection"]["route_seed"], 20260928)
            self.assertEqual(config["settings"]["repeats"], 5)
            if config["settings"]["execution_strategy"] == "iterative_chain":
                self.assertEqual(config["prompt"], NEXT_NODE_INSTRUCTIONS)
                self.assertEqual(config["settings"]["max_chain_steps"], 26)
                self.assertEqual(config["settings"]["iterative_policy"]["candidate_scope"], "neighbors")
                self.assertEqual(config["settings"]["iterative_policy"]["max_visits_per_node"], 2)

    # Graph Retrieval 쌍은 같은 프롬프트·모델·경로에서 Graph 입력만 바꾸는지 확인한다.
    def test_graph_retrieval_pair_changes_only_retrieval_input(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = resolve_experiment_configs(DEFAULT_MATRIX, Path(directory))
            configs = {path.stem: json.loads(path.read_text()) for path in paths}

        for prefix in ("direct", "cot"):
            plain = configs[f"{prefix}_no_rag"]
            retrieved = configs[f"{prefix}_graph_retrieval"]
            self.assertEqual(plain["prompt_sha256"], retrieved["prompt_sha256"])
            self.assertEqual(plain["models"], retrieved["models"])
            self.assertEqual(plain["cases"], retrieved["cases"])
            self.assertNotEqual(plain["retrieval"], retrieved["retrieval"])

    # Iterative Neighbor Context는 전체 Graph를 유지하고 정확 조회 정책만 켠다.
    def test_iterative_neighbor_context_keeps_full_graph_for_each_case(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = resolve_experiment_configs(DEFAULT_MATRIX, Path(directory))
            path_by_name = {path.stem: path for path in paths}
            plain = load_and_validate_config(
                path_by_name["iterative_full_graph_only"]
            )
            context = load_and_validate_config(
                path_by_name["iterative_neighbor_context"]
            )

        self.assertFalse(plain["config"]["neighbor_context"]["enabled"])
        self.assertEqual(
            context["config"]["neighbor_context"]["policy"],
            "exact_current_node_adjacency_each_step",
        )
        self.assertEqual(plain["compact_graph"], context["compact_graph"])
        for case in context["cases"]:
            self.assertEqual(case["model_graph"], context["compact_graph"])
            self.assertFalse(case["retrieval"]["enabled"])


    # 출력 예산 확대 시 원본·프롬프트는 유지하고 실제 설정과 비교 해시만 바뀌는지 확인한다.
    def test_output_budget_overrides_are_recorded_without_changing_prompts(self):
        before = DEFAULT_MATRIX.read_bytes()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            normal = resolve_experiment_configs(DEFAULT_MATRIX, root / "normal")
            expanded = resolve_experiment_configs(
                DEFAULT_MATRIX, root / "expanded",
                settings_overrides={"num_predict": 2048, "timeout_seconds": 600},
            )
            for a, b in zip(normal, expanded):
                old, new = json.loads(a.read_text()), json.loads(b.read_text())
                self.assertEqual(new["settings"]["num_predict"], 2048)
                self.assertEqual(new["settings"]["timeout_seconds"], 600)
                self.assertEqual(old["prompt_sha256"], new["prompt_sha256"])
                self.assertEqual(old["graph"], new["graph"])
                self.assertEqual(old["cases"], new["cases"])
                self.assertNotEqual(old["comparison_condition_sha256"], new["comparison_condition_sha256"])
                load_and_validate_config(b)
        self.assertEqual(DEFAULT_MATRIX.read_bytes(), before)

    # 무제한 출력·음수·입력 공간 없는 예산을 실행 전에 거부한다.
    def test_invalid_budget_overrides_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            for overrides in (
                {"num_predict": -1}, {"num_predict": 0},
                {"timeout_seconds": 0}, {"num_predict": 4096},
            ):
                with self.subTest(overrides=overrides), self.assertRaises(ValueError):
                    resolve_experiment_configs(
                        DEFAULT_MATRIX, Path(directory), settings_overrides=overrides
                    )


if __name__ == "__main__":
    unittest.main()
