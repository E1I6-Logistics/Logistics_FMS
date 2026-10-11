"""Run the six V2 route-generation conditions as a separate experiment matrix."""

from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from simulation.evaluation.benchmark import load_and_validate_config, run_benchmark


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MATRIX = Path(__file__).with_name("route_generation_v2_matrix.json")
RESULTS_ROOT = Path(__file__).with_name("benchmark_results")
COMPARABLE_SETTING_KEYS = (
    "temperature",
    "seed",
    "num_ctx",
    "num_predict",
    "timeout_seconds",
    "realtime_deadline_seconds",
    "max_attempts",
    "repeats",
    "warmups_per_model",
    "keep_alive",
)


def _sha256_json(value: Any) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def resolve_experiment_configs(
    matrix_path: Path, directory: Path, *, settings_overrides: dict[str, int] | None = None
) -> list[Path]:
    """Expand one shared V2 matrix into six reproducible benchmark configs."""
    matrix = json.loads(matrix_path.read_text(encoding="utf-8"))
    required_names = {
        "direct_no_rag",
        "direct_graph_retrieval",
        "cot_no_rag",
        "cot_graph_retrieval",
        "iterative_full_graph_only",
        "iterative_neighbor_context",
    }
    names = {experiment["name"] for experiment in matrix["experiments"]}
    if names != required_names:
        raise ValueError(f"V2 experiment names mismatch: {sorted(names)}")

    # 원본 설정은 보존하고 실제 실행 설정과 비교 해시에 출력 예산 변경을 반영한다.
    overrides = settings_overrides or {}
    for key, value in overrides.items():
        if key not in {"num_predict", "timeout_seconds"} or type(value) is not int or value <= 0:
            raise ValueError(f"invalid settings override: {key}={value!r}")
    common_settings = {**matrix["settings"], **overrides}
    if common_settings["num_predict"] >= common_settings["num_ctx"]:
        raise ValueError("num_predict must be smaller than num_ctx to leave room for input")
    conditions = {
        "graph_sha256": matrix["graph"]["sha256"],
        "models": matrix["models"],
        "cases": matrix["cases"],
        "settings": {
            key: common_settings[key] for key in COMPARABLE_SETTING_KEYS
        },
    }
    condition_hash = _sha256_json(conditions)
    paths = []
    for experiment in matrix["experiments"]:
        prompt = experiment["prompt"]
        settings = {
            **common_settings,
            "response_format": experiment["response_format"],
            "execution_strategy": experiment["execution_strategy"],
        }
        if experiment["execution_strategy"] == "iterative_chain":
            settings["max_chain_steps"] = int(
                experiment.get("max_chain_steps", matrix["graph"]["node_count"])
            )
        config = {
            "benchmark_id": f"{matrix['matrix_id']}--{experiment['name']}",
            "description": experiment["description"],
            "graph": matrix["graph"],
            "models": matrix["models"],
            "cases": matrix["cases"],
            "settings": settings,
            "retrieval": experiment["retrieval"],
            "neighbor_context": experiment.get(
                "neighbor_context", {"enabled": False, "policy": "none"}
            ),
            "prompt": prompt,
            "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
            "experiment_mode": experiment["experiment_mode"],
            "comparison_condition_sha256": condition_hash,
            "matrix_id": matrix["matrix_id"],
        }
        path = directory / f"{experiment['name']}.json"
        _write_json(path, config)
        paths.append(path)
    return paths


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--matrix", type=Path, default=DEFAULT_MATRIX)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--only", action="append", default=[])
    parser.add_argument(
        "--model", action="append", default=[],
        help="run only this configured model; may be repeated",
    )
    parser.add_argument(
        "--check", action="store_true", help="Ollama 호출 없이 6조건을 검증"
    )
    parser.add_argument("--num-predict", type=int, help="override output token budget")
    parser.add_argument("--timeout-seconds", type=int, help="override request timeout")
    args = parser.parse_args()
    settings_overrides = {
        key: value for key, value in {
            "num_predict": args.num_predict,
            "timeout_seconds": args.timeout_seconds,
        }.items() if value is not None
    }
    matrix_path = args.matrix.resolve()

    if args.check:
        with tempfile.TemporaryDirectory() as temporary:
            config_paths = resolve_experiment_configs(
                matrix_path, Path(temporary) / "configs", settings_overrides=settings_overrides
            )
            rows = []
            for config_path in config_paths:
                prepared = load_and_validate_config(config_path)
                rows.append(
                    {
                        "name": config_path.stem,
                        "mode": prepared["config"]["experiment_mode"],
                        "retrieval": prepared["config"]["retrieval"]["enabled"],
                        "condition_sha256": prepared[
                            "comparison_condition_sha256"
                        ],
                        "graph_sha256": prepared["graph_sha256"],
                        "cases": len(prepared["cases"]),
                        "num_predict": prepared["config"]["settings"]["num_predict"],
                        "timeout_seconds": prepared["config"]["settings"]["timeout_seconds"],
                    }
                )
            if len({row["condition_sha256"] for row in rows}) != 1:
                raise ValueError("V2 six conditions do not share comparison conditions")
            print(json.dumps(rows, ensure_ascii=False, indent=2))
            print("V2 6조건 검증 완료: Ollama에는 요청하지 않았습니다.")
        return 0

    output = args.output or (
        RESULTS_ROOT / f"v2-matrix-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    )
    output = output.resolve()
    if output.exists() and any(output.iterdir()):
        raise FileExistsError(f"V2 output directory is not empty: {output}")
    output.mkdir(parents=True, exist_ok=True)
    config_paths = resolve_experiment_configs(
        matrix_path, output / "configs", settings_overrides=settings_overrides
    )
    selected = set(args.only)
    if selected:
        known = {path.stem for path in config_paths}
        unknown = selected.difference(known)
        if unknown:
            raise ValueError(f"unknown --only condition: {sorted(unknown)}")
        config_paths = [path for path in config_paths if path.stem in selected]

    manifest = {
        "matrix_file": str(matrix_path),
        "matrix_sha256": hashlib.sha256(matrix_path.read_bytes()).hexdigest(),
        "started_at": datetime.now(timezone.utc).isoformat(),
        "status": "running",
        "conditions": [path.stem for path in config_paths],
        "model_filter": args.model or None,
        "settings_overrides": settings_overrides,
    }
    _write_json(output / "matrix_manifest.json", manifest)
    for config_path in config_paths:
        print(f"V2 condition 시작: {config_path.stem}", flush=True)
        run_benchmark(
            config_path,
            output / config_path.stem,
            model_names=set(args.model) or None,
        )
    manifest.update(
        status="complete",
        finished_at=datetime.now(timezone.utc).isoformat(),
    )
    _write_json(output / "matrix_manifest.json", manifest)
    print(f"V2 matrix 결과 폴더: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
