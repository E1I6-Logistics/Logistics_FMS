"""모델 없이 V2 다음 노드 반복 선택과 실패 기록을 검증한다."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from simulation.evaluation.selector_iterative_route_benchmark import (
    _prepare,
    _run_route,
    _resolve_model_specs,
    _summarize,
    load_iterative_config,
    run_benchmark,
    run_configured_benchmarks,
)


class _OracleSelector:
    """복수 후보 단계에서 정답 다음 노드를 반환한다."""

    name = "laya"
    model = "fake-oracle"

    def __init__(self):
        self.calls = 0
        self.states = []
        self.candidate_sets = []

    def select_choice(self, state, candidates, _instructions, *, question_id):
        self.calls += 1
        self.states.append(state)
        self.candidate_sets.append(dict(candidates))
        choice = {0: "node_1"}[state["current_node"]]
        if choice not in candidates:
            raise AssertionError(f"missing candidate: {choice}")
        return {
            "choice": choice,
            "confidence": 0.9,
            "answer_confidence": 0.9,
            "probabilities": {
                key: (0.9 if key == choice else 0.1) for key in candidates
            },
            "state_truncated": False,
            "usage": {"input_tokens": 120},
            "total_duration_seconds": 0.01,
            "eval_duration_seconds": 0.008,
            "runtime": {"device": "cuda:0"},
        }


class _InvalidEdgeSelector:
    """전체 노드 후보에서 실제 간선이 아닌 노드를 골라 검증 실패를 만든다."""

    name = "kev"
    model = "fake-invalid"

    def select_choice(self, _state, _candidates, _instructions, *, question_id):
        return {
            "choice": "node_3",
            "answer_confidence": 0.8,
            "probabilities": {"node_3": 0.8},
        }


def _fixture():
    return {
        "compact_graph": {
            "type": "CompactAdjacencyGraph",
            "directed": True,
            "nodes": [0, 1, 2],
            "adjacency": {
                "0": [
                    {"to": 1, "weight": 1.0},
                    {"to": 2, "weight": 3.0},
                ],
                "1": [{"to": 2, "weight": 1.0}],
                "2": [],
            },
        },
        "points": {0: (0.0, 0.0), 1: (1.0, 0.0), 2: (2.0, 0.0)},
        "edges": [(0, 1, 1.0), (0, 2, 3.0), (1, 2, 1.0)],
        "edge_weights": {(0, 1): 1.0, (0, 2): 3.0, (1, 2): 1.0},
        "nodes": [0, 1, 2],
    }


class SelectorIterativeRouteBenchmarkTest(unittest.TestCase):
    # 같은 seed는 동일한 5개 경로를 만들고 Start·Docking 집합은 겹치지 않아야 한다.
    def test_random_cases_are_reproducible_disjoint_and_target_docking_nodes(self):
        first = _prepare(case_count=5, route_seed=20261006)
        second = _prepare(case_count=5, route_seed=20261006)
        first_pairs = [
            (case["start"], case["target"]) for case in first["cases"]
        ]
        second_pairs = [
            (case["start"], case["target"]) for case in second["cases"]
        ]
        starts = {start for start, _target in first_pairs}
        targets = {target for _start, target in first_pairs}

        self.assertEqual(first_pairs, second_pairs)
        self.assertEqual(len(first_pairs), 5)
        self.assertEqual(len(starts), 5)
        self.assertEqual(len(targets), 5)
        self.assertTrue(starts.isdisjoint(targets))
        self.assertTrue(targets.issubset(set(range(7))))
        self.assertTrue(
            all(case["expected_path"][0] == case["start"] for case in first["cases"])
        )
        self.assertTrue(
            all(case["expected_path"][-1] == case["target"] for case in first["cases"])
        )

    # 올바른 다음 노드를 두 번 고르면 최단 경로와 거리까지 일치해야 한다.
    def test_oracle_selector_reaches_exact_route(self):
        selector = _OracleSelector()
        result = _run_route(
            selector,
            _fixture(),
            {
                "start": 0,
                "target": 2,
                "expected_path": [0, 1, 2],
                "expected_distance": 2.0,
            },
            "neighbors",
            0.15,
        )

        self.assertIsNone(result["error"])
        self.assertEqual(result["path"], [0, 1, 2])
        self.assertTrue(result["exact_path_match"])
        self.assertTrue(result["distance_match"])
        self.assertEqual(result["api_call_count"], 1)
        self.assertEqual(selector.calls, 1)
        self.assertFalse(result["steps"][0]["forced_step"])
        self.assertTrue(result["steps"][1]["forced_step"])
        self.assertFalse(result["steps"][1]["model_called"])
        self.assertTrue(result["full_graph_input_preserved"])

    # 기본 모드는 available_edges의 Node만 Laya·Kev·Ollama choice 후보로 사용한다.
    def test_default_mode_builds_criteria_from_available_edges(self):
        selector = _OracleSelector()
        prepared = _fixture()
        prepared["nodes"].append(3)
        prepared["points"][3] = (3.0, 0.0)
        prepared["compact_graph"]["nodes"].append(3)
        prepared["compact_graph"]["adjacency"]["3"] = []

        result = _run_route(
            selector,
            prepared,
            {
                "start": 0,
                "target": 2,
                "expected_path": [0, 1, 2],
                "expected_distance": 2.0,
            },
            "neighbors",
            0.15,
        )

        self.assertIsNone(result["error"])
        self.assertEqual(
            selector.states[0]["available_edges"],
            [
                {"node": 1, "weight": 1},
                {"node": 2, "weight": 3},
            ],
        )
        self.assertEqual(
            selector.candidate_sets[0],
            {"node_1": "Node 1", "node_2": "Node 2"},
        )
        self.assertNotIn("node_3", selector.candidate_sets[0])

    # Context 모드는 criteria를 바꾸지 않고 available_edges만 추가해야 한다.
    def test_neighbor_context_changes_only_state_context(self):
        base_selector = _OracleSelector()
        context_selector = _OracleSelector()
        case = {
            "start": 0,
            "target": 2,
            "expected_path": [0, 1, 2],
            "expected_distance": 2.0,
        }

        base = _run_route(
            base_selector, _fixture(), case, "all", 0.15, "full_graph_only"
        )
        context = _run_route(
            context_selector, _fixture(), case, "all", 0.15, "neighbor_context"
        )

        self.assertNotIn("available_edges", base_selector.states[0])
        self.assertEqual(
            context_selector.states[0]["available_edges"],
            [
                {"node": 1, "weight": 1},
                {"node": 2, "weight": 3},
            ],
        )
        self.assertEqual(
            base["steps"][0]["candidates"],
            context["steps"][0]["candidates"],
        )
        self.assertEqual(base["context_mode"], "full_graph_only")
        self.assertEqual(context["context_mode"], "neighbor_context")

    # 직전 Node는 available_edges와 criteria에서 제외해 즉시 왕복을 막는다.
    def test_immediate_previous_node_is_not_a_candidate(self):
        selector = _OracleSelector()
        prepared = _fixture()
        prepared["compact_graph"]["adjacency"]["1"] = [
            {"to": 0, "weight": 1.0},
            {"to": 2, "weight": 1.0},
        ]
        prepared["edges"].append((1, 0, 1.0))
        prepared["edge_weights"][(1, 0)] = 1.0

        result = _run_route(
            selector,
            prepared,
            {
                "start": 0,
                "target": 2,
                "expected_path": [0, 1, 2],
                "expected_distance": 2.0,
            },
            "neighbors",
            0.15,
            "neighbor_context",
            max_steps=6,
        )

        self.assertIsNone(result["error"])
        self.assertEqual(result["path"], [0, 1, 2])
        self.assertEqual(result["steps"][1]["previous_node"], 0)
        self.assertEqual(result["steps"][1]["candidates"], {"node_2": "Node 2"})
        self.assertEqual(
            result["steps"][1]["available_edges"],
            [{"node": 2, "weight": 1}],
        )

    # 직전 Node가 아니면 과거 방문 Node로 돌아간 뒤 Target에 도착할 수 있다.
    def test_older_revisit_is_recorded_and_route_can_reach_target(self):
        class _ScriptedSelector:
            name = "kev"
            model = "fake-revisit"

            def __init__(self):
                self.choices = iter(["node_1", "node_0", "node_3"])

            def select_choice(self, _state, candidates, _instructions, *, question_id):
                choice = next(self.choices)
                if choice not in candidates:
                    raise AssertionError(f"missing candidate: {choice}")
                return {
                    "choice": choice,
                    "answer_confidence": 0.8,
                    "probabilities": {key: (0.8 if key == choice else 0.2) for key in candidates},
                }

        prepared = {
            "compact_graph": {
                "type": "CompactAdjacencyGraph",
                "directed": True,
                "nodes": [0, 1, 2, 3],
                "adjacency": {
                    "0": [{"to": 1, "weight": 1.0}, {"to": 3, "weight": 4.0}],
                    "1": [{"to": 0, "weight": 1.0}, {"to": 2, "weight": 1.0}],
                    "2": [{"to": 0, "weight": 1.0}, {"to": 3, "weight": 1.0}],
                    "3": [],
                },
            },
            "points": {0: (0.0, 0.0), 1: (1.0, 0.0), 2: (2.0, 0.0), 3: (3.0, 0.0)},
            "edges": [
                (0, 1, 1.0), (0, 3, 4.0), (1, 0, 1.0),
                (1, 2, 1.0), (2, 0, 1.0), (2, 3, 1.0),
            ],
            "edge_weights": {
                (0, 1): 1.0, (0, 3): 4.0, (1, 0): 1.0,
                (1, 2): 1.0, (2, 0): 1.0, (2, 3): 1.0,
            },
            "nodes": [0, 1, 2, 3],
        }

        result = _run_route(
            _ScriptedSelector(),
            prepared,
            {
                "start": 0,
                "target": 3,
                "expected_path": [0, 1, 2, 3],
                "expected_distance": 3.0,
            },
            "neighbors",
            0.15,
            "neighbor_context",
            max_steps=8,
        )

        self.assertIsNone(result["error"])
        self.assertEqual(result["path"], [0, 1, 2, 0, 3])
        self.assertTrue(result["valid_path"])
        self.assertTrue(result["has_revisit"])
        self.assertFalse(result["non_revisiting_valid_path"])
        self.assertGreater(result["step_excess"], 0)
        self.assertEqual(result["revisit_count"], 1)
        self.assertTrue(result["steps"][2]["revisited"])

    # 삼각형 순환도 동일 방향 Edge를 두 번째 사용하기 전에 중단한다.
    def test_triangle_cycle_stops_before_reusing_directed_edge(self):
        class _MustNotRunSelector:
            name = "laya"

            def select_choice(self, *args, **kwargs):
                raise AssertionError("단일 후보 순환에서는 selector를 호출하면 안 됩니다.")

        prepared = {
            "compact_graph": {
                "type": "CompactAdjacencyGraph",
                "directed": True,
                "nodes": [0, 1, 2, 3],
                "adjacency": {
                    "0": [{"to": 1, "weight": 1.0}],
                    "1": [{"to": 2, "weight": 1.0}],
                    "2": [{"to": 0, "weight": 1.0}],
                    "3": [],
                },
            },
            "points": {0: (0.0, 0.0), 1: (1.0, 0.0), 2: (2.0, 0.0), 3: (3.0, 0.0)},
            "edges": [(0, 1, 1.0), (1, 2, 1.0), (2, 0, 1.0)],
            "edge_weights": {(0, 1): 1.0, (1, 2): 1.0, (2, 0): 1.0},
            "nodes": [0, 1, 2, 3],
        }

        result = _run_route(
            _MustNotRunSelector(),
            prepared,
            {
                "start": 0,
                "target": 3,
                "expected_path": [0, 1, 2, 3],
                "expected_distance": 3.0,
            },
            "neighbors",
            0.15,
            "neighbor_context",
            max_steps=4,
        )

        self.assertEqual(result["path"], [0, 1, 2, 0])
        self.assertEqual(result["revisit_count"], 1)
        self.assertEqual(result["used_edge_count"], 3)
        self.assertEqual(result["max_node_visit_count"], 2)
        self.assertGreaterEqual(result["cycle_prevented_count"], 1)
        self.assertIn("순환 방지 조건", result["error"])

    # 일반 후보가 없으면 아직 사용하지 않은 역방향 Edge로 한 번 복귀할 수 있다.
    def test_unused_reverse_edge_is_allowed_as_backtrack(self):
        class _MustNotRunSelector:
            name = "laya"

            def select_choice(self, *args, **kwargs):
                raise AssertionError("단일 후보 backtrack에서는 selector를 호출하면 안 됩니다.")

        prepared = {
            "compact_graph": {
                "type": "CompactAdjacencyGraph",
                "directed": True,
                "nodes": [0, 1, 2],
                "adjacency": {
                    "0": [{"to": 1, "weight": 1}],
                    "1": [{"to": 0, "weight": 1}],
                    "2": [],
                },
            },
            "points": {0: (0.0, 0.0), 1: (1.0, 0.0), 2: (2.0, 0.0)},
            "edges": [(0, 1, 1.0), (1, 0, 1.0)],
            "edge_weights": {(0, 1): 1.0, (1, 0): 1.0},
            "nodes": [0, 1, 2],
        }

        result = _run_route(
            _MustNotRunSelector(),
            prepared,
            {
                "start": 0,
                "target": 2,
                "expected_path": [0, 1, 2],
                "expected_distance": 2.0,
            },
            "neighbors",
            0.15,
            max_steps=4,
        )

        self.assertEqual(result["path"], [0, 1, 0])
        self.assertEqual(result["backtrack_step_count"], 1)
        self.assertTrue(result["steps"][1]["backtrack_allowed"])
        self.assertTrue(result["steps"][1]["backtrack"])
        self.assertIn("순환 방지 조건", result["error"])


    # 전체 노드 모드에서 없는 간선을 고르면 첫 실패 단계와 원인을 남겨야 한다.
    def test_invalid_edge_choice_is_recorded(self):
        prepared = _fixture()
        prepared["nodes"].append(3)
        prepared["points"][3] = (3.0, 0.0)
        prepared["compact_graph"]["nodes"].append(3)
        prepared["compact_graph"]["adjacency"]["3"] = []
        result = _run_route(
            _InvalidEdgeSelector(),
            prepared,
            {
                "start": 0,
                "target": 2,
                "expected_path": [0, 1, 2],
                "expected_distance": 2.0,
            },
            "all",
            0.15,
        )
        summary = _summarize([{"selector_name": "kev", **result}])

        self.assertEqual(result["failed_step"], 1)
        self.assertEqual(result["invalid_edge_count"], 1)
        self.assertFalse(result["steps"][0]["accepted"])
        self.assertIn("존재하지 않는 방향성 edge", result["error"])
        self.assertEqual(summary["state_truncation_unreported_trial_count"], 0)

    # 단일 후보는 모델 오류로 처리하지 않고 API 호출 없는 강제 이동으로 기록한다.
    def test_single_candidate_is_forced_without_selector_call(self):
        class _MustNotRunSelector:
            name = "laya"

            def select_choice(self, *args, **kwargs):
                raise AssertionError("단일 후보에서 selector를 호출하면 안 됩니다.")

        prepared = _fixture()
        prepared["compact_graph"]["adjacency"]["0"] = [
            {"to": 1, "weight": 1.0}
        ]
        prepared["edges"] = [(0, 1, 1.0), (1, 2, 1.0)]
        prepared["edge_weights"] = {(0, 1): 1.0, (1, 2): 1.0}
        result = _run_route(
            _MustNotRunSelector(),
            prepared,
            {
                "start": 0,
                "target": 2,
                "expected_path": [0, 1, 2],
                "expected_distance": 2.0,
            },
            "neighbors",
            0.15,
        )
        summary = _summarize([{"selector_name": "laya", **result}])

        self.assertIsNone(result["error"])
        self.assertEqual(result["api_call_count"], 0)
        self.assertEqual(summary["forced_step_count"], 2)
        self.assertEqual(summary["model_decision_step_count"], 0)
        self.assertEqual(summary["state_truncation_unreported_trial_count"], 0)
        self.assertIsNone(summary["step_realtime_met_rate"])
        self.assertTrue(all(step["forced_step"] for step in result["steps"]))


    # 정수 weight 맵을 명시하면 모델 입력에서도 정수 표현을 유지해야 한다.
    def test_explicit_integer_graph_is_used(self):
        prepared = _prepare(
            graph_path=Path("routes/test_int.geojson"),
            case_count=1,
            route_seed=20260928,
        )

        self.assertEqual(prepared["graph_path"].name, "test_int.geojson")
        self.assertEqual(
            prepared["compact_graph"]["adjacency"]["0"],
            [{"to": 1, "weight": 38}, {"to": 18, "weight": 43}],
        )

    # all-pairs는 12개 Node에서 도킹 0~6과 동일한 7쌍을 제외한 77쌍이다.
    def test_all_pairs_generates_every_start_to_docking_pair(self):
        prepared = _prepare(
            graph_path=Path("routes/test_int.geojson"),
            case_mode="all-pairs",
        )

        pairs = {(case["start"], case["target"]) for case in prepared["cases"]}
        self.assertEqual(len(pairs), 77)
        self.assertTrue(all(start != target for start, target in pairs))
        self.assertTrue(all(target in range(7) for _start, target in pairs))
        self.assertIsNone(prepared["route_seed"])

    # 서버·checkpoint 사전 점검 실패는 trial이 아니라 benchmark 실패로 기록한다.
    def test_preflight_failure_marks_manifest_failed(self):
        class _UnavailableSelector:
            name = "kev"
            model = "kev-4b"

            def _ensure_runtime(self):
                raise RuntimeError("checkpoint mismatch")

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "result"
            with self.assertRaisesRegex(RuntimeError, "checkpoint mismatch"):
                run_benchmark(
                    output,
                    repeats=1,
                    warmups=0,
                    case_count=1,
                    route_seed=20260928,
                    graph_path=Path("routes/test_int.geojson"),
                    selector=_UnavailableSelector(),
                    progress=False,
                )
            manifest = json.loads((output / "manifest.json").read_text())
            self.assertEqual(manifest["status"], "failed")
            self.assertEqual(manifest["failure_stage"], "selector_preflight")
            self.assertIn("checkpoint mismatch", manifest["failure"])
            self.assertIn("instructions_sha256", manifest["settings"])


    # JSON 설정은 Graph hash와 공통 옵션을 검증하고 모델별 최종 설정을 만든다.
    def test_iterative_ollama_config_resolves_selected_models(self):
        resolved = load_iterative_config(
            Path("simulation/evaluation/selector_iterative_benchmark.json"),
            ["qwen3:4b", "phi4:14b"],
        )

        self.assertEqual(resolved["graph_path"].name, "test_int.geojson")
        self.assertEqual(
            [model["name"] for model in resolved["models"]],
            ["qwen3:4b", "phi4:14b"],
        )
        self.assertFalse(resolved["models"][0]["think"])
        self.assertEqual(resolved["models"][0]["options"]["num_ctx"], 4096)
        self.assertEqual(resolved["models"][1]["options"]["num_predict"], 512)

    # JSON에 없는 모델명은 조용히 건너뛰지 않고 실행 전에 오류로 막는다.
    def test_iterative_ollama_config_rejects_unknown_model(self):
        with self.assertRaisesRegex(ValueError, "not present in config"):
            load_iterative_config(
                Path("simulation/evaluation/selector_iterative_benchmark.json"),
                ["missing:model"],
            )

    # 다중 모델 실행기는 모델별 하위 결과와 상위 matrix manifest를 만든다.
    def test_configured_runner_writes_matrix_and_model_results(self):
        class _FirstCandidateSelector:
            name = "ollama"
            model = "fake:model"

            def select_choice(
                self, _state, candidates, _instructions, *, question_id
            ):
                return {"choice": next(iter(candidates)), "probabilities": {}}

            def release(self):
                pass

        graph_path = Path("routes/test_int.geojson")
        graph_hash = __import__("hashlib").sha256(graph_path.read_bytes()).hexdigest()
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            config_path = temporary / "config.json"
            config_path.write_text(
                json.dumps(
                    {
                        "graph": {"path": str(graph_path), "sha256": graph_hash},
                        "ollama_defaults": {
                            "options": {"num_ctx": 4096, "num_predict": 512}
                        },
                        "models": [{"name": "fake:model"}],
                        "settings": {
                            "case_mode": "random",
                            "case_count": 1,
                            "route_seed": 20260928,
                            "candidate_scope": "neighbors",
                            "context_mode": "neighbor_context",
                            "repeats": 1,
                            "warmups": 0,
                            "max_steps": 1,
                            "deadline_seconds": 0.15,
                        },
                    }
                ),
                encoding="utf-8",
            )
            output = temporary / "output"
            with patch(
                "simulation.evaluation.selector_iterative_route_benchmark."
                "_build_configured_ollama_selector",
                return_value=_FirstCandidateSelector(),
            ):
                matrix = run_configured_benchmarks(
                    config_path, output, progress=False
                )

            self.assertEqual(matrix["status"], "complete")
            self.assertTrue(
                (output / "selector_iterative_matrix_manifest.json").is_file()
            )
            self.assertTrue((output / "fake-model" / "manifest.json").is_file())

    # 모델 항목의 options는 공통값 중 필요한 값만 안전하게 덮어쓴다.
    def test_model_options_override_defaults(self):
        models = _resolve_model_specs(
            {
                "ollama_defaults": {
                    "timeout_seconds": 120,
                    "options": {"num_ctx": 4096, "num_predict": 512},
                },
                "models": [
                    {"name": "small", "options": {"num_ctx": 2048}},
                ],
            }
        )

        self.assertEqual(models[0]["options"], {"num_ctx": 2048, "num_predict": 512})
        self.assertEqual(models[0]["timeout_seconds"], 120)



if __name__ == "__main__":
    unittest.main()
