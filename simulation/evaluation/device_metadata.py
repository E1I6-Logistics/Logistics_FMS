"""Collect device evidence shared by reproducible benchmark manifests."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any, Mapping


def _device_kind(device: str | None) -> str:
    normalized = (device or "").strip().lower()
    if normalized.startswith(("cuda", "mps", "xpu", "gpu")):
        return "gpu"
    if normalized.startswith("cpu"):
        return "cpu"
    if normalized == "mixed":
        return "mixed"
    return "unknown"


def git_metadata(root: Path) -> dict[str, Any]:
    """Record the exact source state used by a benchmark run."""
    def run(*arguments: str) -> str | None:
        try:
            return subprocess.check_output(
                ["git", *arguments], cwd=root, text=True,
                stderr=subprocess.DEVNULL,
            ).strip()
        except (OSError, subprocess.CalledProcessError):
            return None

    return {
        "branch": run("branch", "--show-current"),
        "commit": run("rev-parse", "HEAD"),
        "working_tree_dirty": bool(run("status", "--porcelain")),
    }


def selector_device_metadata(
    selector: Any, result: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    """Read the actual Laya/Kev runtime device after at least one inference."""
    runtime: Mapping[str, Any] = {}
    if isinstance(result, Mapping) and isinstance(result.get("runtime"), Mapping):
        runtime = result["runtime"]
    if not runtime:
        inference = getattr(selector, "last_inference", None)
        if isinstance(inference, Mapping) and isinstance(
            inference.get("runtime"), Mapping
        ):
            runtime = inference["runtime"]

    requested = getattr(selector, "device", None)
    actual = str(runtime.get("device", "unknown"))
    device_name = runtime.get("device_name")
    cuda_available = None
    if actual.startswith("cuda") and not device_name:
        try:
            import torch

            cuda_available = bool(torch.cuda.is_available())
            if cuda_available:
                device_name = torch.cuda.get_device_name(actual)
        except (ImportError, RuntimeError, AssertionError):
            cuda_available = False

    return {
        "source": "selector_runtime",
        "requested": requested,
        "actual": actual,
        "kind": _device_kind(actual),
        "device_name": device_name,
        "cuda_available": cuda_available,
        "precision": runtime.get("precision"),
        "cpu_fallback_count": runtime.get("cpu_fallback_count"),
    }


def ollama_model_device_metadata(
    payload: Mapping[str, Any], model_name: str
) -> dict[str, Any]:
    """Classify Ollama CPU/GPU placement from the official /api/ps fields."""
    models = payload.get("models", [])
    loaded = next(
        (
            item for item in models
            if item.get("name") == model_name or item.get("model") == model_name
        ),
        None,
    )
    if loaded is None:
        return {
            "source": "ollama_api_ps",
            "kind": "unknown",
            "error": "model was not present in /api/ps",
        }

    size = int(loaded.get("size") or 0)
    size_vram = int(loaded.get("size_vram") or 0)
    if size_vram <= 0:
        kind = "cpu"
    elif size > 0 and size_vram >= size * 0.95:
        kind = "gpu"
    else:
        kind = "mixed"
    return {
        "source": "ollama_api_ps",
        "kind": kind,
        "size_bytes": size,
        "size_vram_bytes": size_vram,
        "vram_fraction": size_vram / size if size else None,
        "details": loaded.get("details"),
    }
