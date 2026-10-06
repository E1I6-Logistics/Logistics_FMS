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


if __name__ == "__main__":
    unittest.main()
