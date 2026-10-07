"""Resolve one explicit or environment-selected route graph path."""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def resolve_graph_path(
    explicit: Path | None = None,
    *,
    fallback: Path | None = None,
) -> Path:
    """Resolve CLI path first, then LLM_ROUTE_GRAPH, then the caller fallback."""
    if explicit is not None:
        return explicit.expanduser().resolve()
    configured = os.getenv("LLM_ROUTE_GRAPH")
    if configured:
        selected = Path(configured).expanduser()
        if selected.is_absolute():
            return selected.resolve()
        if selected.parts and selected.parts[0] == "routes":
            return (ROOT / selected).resolve()
        return (ROOT / "routes" / selected).resolve()
    if fallback is None:
        fallback = ROOT / "routes" / "test.geojson"
    return fallback.expanduser().resolve()
