"""Reproduce the versioned Ollama route-generation benchmark.

The benchmark computes ground truth with the shared route service, asks each
configured Ollama model for the same routes, and stores raw and derived data.
It never sends a robot command and does not require FastAPI, ROS 2, or Zenoh.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import platform
import subprocess
import sys
import time
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, median
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from simulation.llm_providers.ollama_provider import OllamaPathProvider
from simulation.services.route_service import (
    build_compact_route_graph,
    build_route_inputs,
    plan_route,
    validate_and_calculate_path_distance,
)

DEFAULT_CONFIG = Path(__file__).with_name("route_generation_benchmark.json")
DEFAULT_RESULTS_DIR = Path(__file__).with_name("benchmark_results")
ProviderFactory = Callable[[dict, dict, str], Any]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _json_dump(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _append_jsonl(path: Path, value: dict) -> None:
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(value, ensure_ascii=False) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def _read_jsonl(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _git(*arguments: str) -> str | None:
    try:
        return subprocess.check_output(
            ["git", *arguments], cwd=ROOT, text=True, stderr=subprocess.DEVNULL
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def _command_output(command: list[str]) -> str | None:
    try:
        return subprocess.check_output(
            command, text=True, stderr=subprocess.STDOUT, timeout=10
        ).strip()
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return None


def _runtime_metadata(host: str) -> dict:
    """Capture enough environment data to compare PC and Jetson runs."""
    metadata = {
        "platform": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "python": sys.version,
        "ollama_version": _command_output(["ollama", "--version"]),
        "nvidia_smi": _command_output(
            [
                "nvidia-smi",
                "--query-gpu=name,driver_version,memory.total",
                "--format=csv,noheader",
            ]
        ),
        "lscpu": _command_output(["lscpu"]),
    }
    for source, field in (
        (Path("/proc/meminfo"), "memory_info"),
        (Path("/etc/nv_tegra_release"), "jetson_release"),
    ):
        try:
            metadata[field] = source.read_text(encoding="utf-8").strip()
        except OSError:
            metadata[field] = None
    try:
        with urllib.request.urlopen(f"{host.rstrip('/')}/api/tags", timeout=10) as response:
            metadata["ollama_tags"] = json.load(response)
    except Exception as error:  # The first actual request will report full details.
        metadata["ollama_tags_error"] = f"{type(error).__name__}: {error}"
    return metadata


def load_and_validate_config(config_path: Path) -> dict:
    """Validate the frozen graph, baselines, and experiment dimensions."""
    config_path = config_path.resolve()
    config = json.loads(config_path.read_text(encoding="utf-8"))
    graph_config = config["graph"]
    graph_path = (ROOT / graph_config["path"]).resolve()
    if not graph_path.is_relative_to(ROOT):
        raise ValueError("benchmark graph must be inside the repository")
    graph_bytes = graph_path.read_bytes()
    graph_hash = _sha256_bytes(graph_bytes)
    if graph_hash != graph_config["sha256"]:
        raise ValueError(
            "graph SHA-256 mismatch: "
            f"expected {graph_config['sha256']}, got {graph_hash}"
        )
    graph = json.loads(graph_bytes)
    points, edges = build_route_inputs(graph)
    if len(points) != graph_config["node_count"]:
        raise ValueError("graph node count does not match the benchmark config")
    if len(edges) != graph_config["directed_edge_count"]:
        raise ValueError("graph edge count does not match the benchmark config")

    validated_cases = []
    for case in config["cases"]:
        baseline = plan_route(str(case["start"]), str(case["goal"]), graph)
        path = [int(node) for node in baseline["node_ids"]]
        if path != case["expected_path"]:
            raise ValueError(
                f"baseline path changed for {case['start']}->{case['goal']}: {path}"
            )
        if not math.isclose(
            baseline["cost"], case["expected_distance"], rel_tol=1e-12, abs_tol=1e-12
        ):
            raise ValueError(
                f"baseline distance changed for {case['start']}->{case['goal']}"
            )
        validated_cases.append({**case, "baseline": baseline})

    settings = config["settings"]
    for field in ("repeats", "warmups_per_model", "max_attempts"):
        if int(settings[field]) < 1:
            raise ValueError(f"{field} must be at least 1")
    if not config.get("models"):
        raise ValueError("at least one model is required")
    if not config.get("prompt", "").strip():
        raise ValueError("the benchmark prompt must not be empty")
    prompt_hash = _sha256_bytes(config["prompt"].encode("utf-8"))
    if prompt_hash != config["prompt_sha256"]:
        raise ValueError(
            "prompt SHA-256 mismatch: "
            f"expected {config['prompt_sha256']}, got {prompt_hash}"
        )

    return {
        "config": config,
        "config_path": config_path,
        "config_sha256": _sha256_bytes(config_path.read_bytes()),
        "graph": graph,
        "graph_path": graph_path,
        "graph_sha256": graph_hash,
        "points": points,
        "edges": edges,
        "compact_graph": build_compact_route_graph(graph, graph_path.name),
        "cases": validated_cases,
    }


def _default_provider_factory(model: dict, settings: dict, prompt: str):
    options = {
        "temperature": settings["temperature"],
        "seed": settings["seed"],
        "num_ctx": settings["num_ctx"],
        "num_predict": settings["num_predict"],
    }
    return OllamaPathProvider(
        model=model["name"],
        host=os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434"),
        timeout_seconds=float(settings["timeout_seconds"]),
        options=options,
        keep_alive=settings["keep_alive"],
        think=model.get("think"),
        instructions=prompt,
    )


def _is_timeout(error: Exception) -> bool:
    text = f"{type(error).__name__} {error}".lower()
    return isinstance(error, TimeoutError) or "timeout" in text or "timed out" in text


def _run_trial(
    provider: Any,
    model_name: str,
    case: dict,
    repeat: int,
    prepared: dict,
) -> dict:
    settings = prepared["config"]["settings"]
    start, goal = int(case["start"]), int(case["goal"])
    answer = None
    validated_path = None
    recalculated_distance = None
    attempts = []

    for attempt_number in range(1, int(settings["max_attempts"]) + 1):
        started = time.perf_counter()
        attempt = {
            "attempt": attempt_number,
            "json_response_success": False,
            "valid_path": False,
            "timed_out": False,
        }
        try:
            answer = provider.compute_shortest_path(
                prepared["compact_graph"], start, goal
            )
            attempt["json_response_success"] = isinstance(answer, dict)
            validated_path, recalculated_distance = validate_and_calculate_path_distance(
                prepared["points"], prepared["edges"], answer["path"], start, goal
            )
            attempt["valid_path"] = True
        except Exception as error:
            attempt.update(
                timed_out=_is_timeout(error),
                error_type=type(error).__name__,
                error_message=str(error),
            )
        finally:
            attempt["response_time_seconds"] = round(
                time.perf_counter() - started, 6
            )
            inference = getattr(provider, "last_inference", None)
            if inference is not None:
                attempt["inference"] = inference
            attempts.append(attempt)
        if attempt["valid_path"]:
            break

    baseline_path = case["expected_path"]
    baseline_distance = float(case["expected_distance"])
    total_time = sum(item["response_time_seconds"] for item in attempts)
    valid = validated_path is not None and recalculated_distance is not None
    reported_distance = (
        answer.get("reported_total_distance") if isinstance(answer, dict) else None
    )
    distance_error = (
        abs(recalculated_distance - baseline_distance) if valid else None
    )
    reported_error = (
        abs(float(reported_distance) - recalculated_distance)
        if valid and isinstance(reported_distance, (int, float))
        else None
    )
    compact_input = json.dumps(
        {
            "route_graph": prepared["compact_graph"],
            "start_node": start,
            "target_node": goal,
            "required_path_endpoints": {"first": start, "last": goal},
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )
    input_characters = len(prepared["config"]["prompt"] + compact_input)
    return {
        "trial_id": f"{model_name}|{start}|{goal}|{repeat}",
        "timestamp": _utc_now(),
        "task": "path_generation",
        "provider": "ollama",
        "model": model_name,
        "repeat": repeat,
        "input": {
            "start_node": start,
            "target_node": goal,
            "route_graph_file": prepared["graph_path"].name,
            "route_graph_sha256": prepared["graph_sha256"],
            "compact_graph": prepared["compact_graph"],
        },
        "baseline": {
            "path": baseline_path,
            "recalculated_total_distance": baseline_distance,
        },
        "llm": {
            "path": answer.get("path") if isinstance(answer, dict) else None,
            "reported_total_distance": reported_distance,
            "recalculated_total_distance": recalculated_distance,
        },
        "metrics": {
            "json_response_success": any(
                item["json_response_success"] for item in attempts
            ),
            "valid_path": valid,
            "shortest_path_match": valid and validated_path == baseline_path,
            "shortest_distance_match": valid
            and math.isclose(
                recalculated_distance, baseline_distance, rel_tol=1e-9, abs_tol=1e-9
            ),
            "absolute_distance_error": distance_error,
            "reported_distance_error": reported_error,
            "response_time_seconds": round(total_time, 6),
            "realtime_deadline_seconds": settings["realtime_deadline_seconds"],
            "meets_realtime_deadline": valid
            and total_time <= settings["realtime_deadline_seconds"],
            "timed_out": any(item["timed_out"] for item in attempts),
            "first_attempt_success": bool(attempts[0]["valid_path"]),
            "retry_success": len(attempts) > 1 and bool(attempts[-1]["valid_path"]),
            "attempt_count": len(attempts),
            "input_character_count": input_characters,
            "estimated_input_tokens": math.ceil(input_characters / 4),
        },
        "attempts": attempts,
    }


def _rate(rows: list[dict], name: str) -> float:
    return sum(bool(row["metrics"].get(name)) for row in rows) / len(rows)


def _mean_optional(values: list[float | None]) -> float | None:
    present = [value for value in values if value is not None]
    return mean(present) if present else None


def write_exports(output: Path) -> dict:
    """Regenerate JSON and CSV summaries from the durable trial JSONL."""
    rows = _read_jsonl(output / "trials.jsonl")
    by_model: dict[str, list[dict]] = defaultdict(list)
    by_route: dict[tuple[str, int, int], list[dict]] = defaultdict(list)
    for row in rows:
        by_model[row["model"]].append(row)
        by_route[
            (row["model"], row["input"]["start_node"], row["input"]["target_node"])
        ].append(row)

    model_rows = []
    for model, group in sorted(by_model.items()):
        response_times = [item["metrics"]["response_time_seconds"] for item in group]
        model_rows.append(
            {
                "model": model,
                "trial_count": len(group),
                "json_response_success_rate": _rate(group, "json_response_success"),
                "valid_path_rate": _rate(group, "valid_path"),
                "shortest_path_match_rate": _rate(group, "shortest_path_match"),
                "shortest_distance_match_rate": _rate(
                    group, "shortest_distance_match"
                ),
                "mean_absolute_distance_error": _mean_optional(
                    [item["metrics"]["absolute_distance_error"] for item in group]
                ),
                "mean_response_time_seconds": mean(response_times),
                "median_response_time_seconds": median(response_times),
                "timeout_rate": _rate(group, "timed_out"),
                "realtime_deadline_success_rate": _rate(
                    group, "meets_realtime_deadline"
                ),
                "first_attempt_success_rate": _rate(
                    group, "first_attempt_success"
                ),
                "retry_success_rate": _rate(group, "retry_success"),
                "mean_input_character_count": mean(
                    item["metrics"]["input_character_count"] for item in group
                ),
                "mean_estimated_input_tokens": mean(
                    item["metrics"]["estimated_input_tokens"] for item in group
                ),
            }
        )

    route_rows = []
    for (model, start, goal), group in sorted(by_route.items()):
        route_rows.append(
            {
                "model": model,
                "start_node": start,
                "target_node": goal,
                "trial_count": len(group),
                "valid_path_rate": _rate(group, "valid_path"),
                "shortest_path_match_rate": _rate(group, "shortest_path_match"),
                "shortest_distance_match_rate": _rate(
                    group, "shortest_distance_match"
                ),
                "mean_response_time_seconds": mean(
                    item["metrics"]["response_time_seconds"] for item in group
                ),
            }
        )

    summary = {
        "generated_at": _utc_now(),
        "trial_count": len(rows),
        "models": model_rows,
        "routes": route_rows,
    }
    _json_dump(output / "summary.json", summary)
    _write_csv(output / "model_summary.csv", model_rows)
    _write_csv(output / "route_summary.csv", route_rows)
    latency_rows = [
        {
            "trial_id": row["trial_id"],
            "model": row["model"],
            "start_node": row["input"]["start_node"],
            "target_node": row["input"]["target_node"],
            "repeat": row["repeat"],
            "response_time_seconds": row["metrics"]["response_time_seconds"],
            "valid_path": row["metrics"]["valid_path"],
            "shortest_distance_match": row["metrics"][
                "shortest_distance_match"
            ],
            "timed_out": row["metrics"]["timed_out"],
            "meets_realtime_deadline": row["metrics"][
                "meets_realtime_deadline"
            ],
        }
        for row in rows
    ]
    _write_csv(output / "latency_samples.csv", latency_rows)
    return summary


def _write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def run_benchmark(
    config_path: Path,
    output: Path,
    *,
    resume: bool = False,
    provider_factory: ProviderFactory | None = None,
    runtime_metadata: dict | None = None,
    progress: bool = True,
) -> dict:
    """Run or resume every configured model/case/repeat combination."""
    prepared = load_and_validate_config(config_path)
    config = prepared["config"]
    output = output.resolve()
    manifest_path = output / "manifest.json"
    if resume:
        if not manifest_path.is_file():
            raise FileNotFoundError(f"resume manifest not found: {manifest_path}")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest["config_sha256"] != prepared["config_sha256"]:
            raise ValueError("resume config differs from the original run")
        if manifest["graph_sha256"] != prepared["graph_sha256"]:
            raise ValueError("resume graph differs from the original run")
        manifest["status"] = "running"
        manifest["resumed_at"] = _utc_now()
    else:
        if output.exists() and any(output.iterdir()):
            raise FileExistsError(f"new run directory is not empty: {output}")
        output.mkdir(parents=True, exist_ok=True)
        host = os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434")
        manifest = {
            "benchmark_id": config["benchmark_id"],
            "status": "running",
            "started_at": _utc_now(),
            "reference_commit": config["reference_commit"],
            "executed_branch": _git("branch", "--show-current"),
            "executed_commit": _git("rev-parse", "HEAD"),
            "working_tree_dirty": bool(_git("status", "--porcelain")),
            "config_file": prepared["config_path"].name,
            "config_sha256": prepared["config_sha256"],
            "graph_file": str(prepared["graph_path"].relative_to(ROOT)),
            "graph_sha256": prepared["graph_sha256"],
            "prompt_sha256": _sha256_bytes(config["prompt"].encode("utf-8")),
            "settings": config["settings"],
            "models": config["models"],
            "cases": config["cases"],
            "runtime": runtime_metadata
            if runtime_metadata is not None
            else _runtime_metadata(host),
            "scope": "LLM route comparison only; no robot commands",
        }
    _json_dump(manifest_path, manifest)

    factory = provider_factory or _default_provider_factory
    existing_trials = {
        row["trial_id"] for row in _read_jsonl(output / "trials.jsonl")
    }
    warmups = _read_jsonl(output / "warmups.jsonl")
    completed_warmups = {
        (row["model"], int(row["warmup"])) for row in warmups
    }
    repeats = int(config["settings"]["repeats"])
    warmup_count = int(config["settings"]["warmups_per_model"])

    for model in config["models"]:
        provider = factory(model, config["settings"], config["prompt"])
        first_case = prepared["cases"][0]
        for warmup_number in range(1, warmup_count + 1):
            if (model["name"], warmup_number) in completed_warmups:
                continue
            started = time.perf_counter()
            row = {
                "timestamp": _utc_now(),
                "model": model["name"],
                "warmup": warmup_number,
                "start_node": first_case["start"],
                "target_node": first_case["goal"],
            }
            try:
                row["answer"] = provider.compute_shortest_path(
                    prepared["compact_graph"],
                    first_case["start"],
                    first_case["goal"],
                )
                row["success"] = True
            except Exception as error:
                row.update(
                    success=False,
                    error_type=type(error).__name__,
                    error_message=str(error),
                )
            row["response_time_seconds"] = round(
                time.perf_counter() - started, 6
            )
            inference = getattr(provider, "last_inference", None)
            if inference is not None:
                row["inference"] = inference
            _append_jsonl(output / "warmups.jsonl", row)

        for case in prepared["cases"]:
            for repeat in range(1, repeats + 1):
                trial_id = (
                    f"{model['name']}|{case['start']}|{case['goal']}|{repeat}"
                )
                if trial_id in existing_trials:
                    continue
                row = _run_trial(
                    provider, model["name"], case, repeat, prepared
                )
                _append_jsonl(output / "trials.jsonl", row)
                existing_trials.add(trial_id)
                write_exports(output)
                if progress:
                    print(
                        json.dumps(
                            {
                                "model": model["name"],
                                "route": f"{case['start']}->{case['goal']}",
                                "repeat": repeat,
                                "valid": row["metrics"]["valid_path"],
                                "shortest": row["metrics"][
                                    "shortest_distance_match"
                                ],
                                "seconds": row["metrics"][
                                    "response_time_seconds"
                                ],
                            },
                            ensure_ascii=False,
                        ),
                        flush=True,
                    )

    summary = write_exports(output)
    expected_trials = len(config["models"]) * len(config["cases"]) * repeats
    manifest.update(
        status="complete" if summary["trial_count"] == expected_trials else "incomplete",
        finished_at=_utc_now(),
        expected_trial_count=expected_trials,
        completed_trial_count=summary["trial_count"],
        warmup_count=len(_read_jsonl(output / "warmups.jsonl")),
        output_files=[
            "manifest.json",
            "warmups.jsonl",
            "trials.jsonl",
            "summary.json",
            "model_summary.csv",
            "route_summary.csv",
            "latency_samples.csv",
        ],
    )
    _json_dump(manifest_path, manifest)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument(
        "--output",
        type=Path,
        help="new result directory (default: timestamp under benchmark_results)",
    )
    parser.add_argument(
        "--resume",
        type=Path,
        metavar="DIRECTORY",
        help="resume an interrupted result directory",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="validate graph, baselines, and config without contacting Ollama",
    )
    args = parser.parse_args()
    try:
        prepared = load_and_validate_config(args.config)
        if args.check:
            print(
                json.dumps(
                    {
                        "benchmark_id": prepared["config"]["benchmark_id"],
                        "graph_sha256": prepared["graph_sha256"],
                        "node_count": len(prepared["points"]),
                        "directed_edge_count": len(prepared["edges"]),
                        "models": [
                            model["name"] for model in prepared["config"]["models"]
                        ],
                        "cases": [
                            {
                                "start": case["start"],
                                "goal": case["goal"],
                                "path": case["expected_path"],
                                "distance": case["expected_distance"],
                            }
                            for case in prepared["cases"]
                        ],
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            print("검증 완료: Ollama에는 요청하지 않았습니다.")
            return 0
        if args.resume and args.output:
            parser.error("--resume and --output cannot be used together")
        output = args.resume or args.output
        if output is None:
            output = DEFAULT_RESULTS_DIR / datetime.now().strftime("%Y%m%d_%H%M%S")
        manifest = run_benchmark(
            args.config, output, resume=args.resume is not None
        )
        print(f"결과 폴더: {output.resolve()}")
        print(
            f"완료: {manifest['completed_trial_count']}/"
            f"{manifest['expected_trial_count']} trials"
        )
        return 0 if manifest["status"] == "complete" else 1
    except Exception as error:
        print(f"benchmark failed ({type(error).__name__}): {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
