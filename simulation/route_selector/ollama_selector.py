"""Ollama adapter for the common route-choice selector interface."""

from __future__ import annotations

import time
from typing import Any, Mapping

from simulation.llm_providers.ollama_provider import OllamaPathProvider

from .registry import RouteSelector


class OllamaSelector(RouteSelector):
    """Ask an Ollama generation model to choose one provided option."""

    name = "ollama"
    ROUTE_INSTRUCTIONS = (
        "Select the valid route option with the smallest directed total weight."
    )

    def __init__(self, provider: OllamaPathProvider | None = None) -> None:
        self.provider = provider or OllamaPathProvider()
        self.model = self.provider.model
        self.last_inference: dict[str, Any] | None = None
        self._runtime: dict[str, Any] | None = None

    def select_choice(
        self,
        state: str | dict[str, Any],
        candidates: Mapping[str, str],
        instructions: str,
        *,
        question_id: str = "decision",
    ) -> dict[str, Any]:
        if len(candidates) < 2:
            raise ValueError("후보는 두 개 이상이어야 합니다.")
        candidate_ids = list(candidates)
        output_schema = {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "choice": {"type": "string", "enum": candidate_ids},
            },
            "required": ["choice"],
        }
        system_instructions = (
            "You are a deterministic decision selector. Read the supplied state and "
            "criteria, then return exactly one criteria ID through the JSON schema. "
            "Do not invent an option. Do not return explanations or Markdown."
        )
        payload = {
            "question_id": question_id,
            "state": state,
            "instructions": instructions,
            "criteria": dict(candidates),
        }
        started = time.perf_counter()
        response = self.provider.request_structured(
            instructions=system_instructions,
            payload=payload,
            output_schema=output_schema,
        )
        wall_seconds = time.perf_counter() - started
        choice = str(response.get("choice", ""))
        if choice not in candidates:
            raise RuntimeError(f"Ollama가 알 수 없는 후보를 선택했습니다: {choice}")

        inference = self.provider.last_inference or {}
        raw = inference.get("response") or {}
        runtime = self._runtime_metadata()
        self.last_inference = {**inference, "runtime": runtime}
        return {
            "choice": choice,
            "confidence": None,
            "probabilities": {},
            "model": self.model,
            "routing": None,
            "usage": {
                "prompt_tokens": raw.get("prompt_eval_count"),
                "output_tokens": raw.get("eval_count"),
            },
            "total_duration_seconds": _nanoseconds_to_seconds(
                raw.get("total_duration")
            ) or wall_seconds,
            "load_duration_seconds": _nanoseconds_to_seconds(
                raw.get("load_duration")
            ),
            "eval_duration_seconds": _nanoseconds_to_seconds(
                raw.get("eval_duration")
            ),
            "runtime": runtime,
            "raw": raw,
        }

    def select_route(
        self,
        state: str | dict[str, Any],
        candidates: Mapping[str, str],
    ) -> dict[str, Any]:
        return self.select_choice(
            state,
            candidates,
            self.ROUTE_INSTRUCTIONS,
            question_id="route",
        )

    def release(self) -> None:
        """Ollama owns model lifetime, so only local diagnostics are cleared."""
        self.last_inference = None

    def _runtime_metadata(self) -> dict[str, Any]:
        """Read Ollama model placement once after the model becomes resident."""
        if self._runtime is not None:
            return self._runtime
        client = getattr(self.provider, "client", None)
        if client is None or not hasattr(client, "ps"):
            self._runtime = {}
            return self._runtime
        try:
            response = client.ps()
            payload = (
                response.model_dump(mode="json")
                if hasattr(response, "model_dump")
                else dict(response)
            )
            loaded = next(
                (
                    item for item in payload.get("models", [])
                    if item.get("name") == self.model
                    or item.get("model") == self.model
                ),
                None,
            )
            if loaded is None:
                self._runtime = {}
                return self._runtime
            size = int(loaded.get("size") or 0)
            size_vram = int(loaded.get("size_vram") or 0)
            if size_vram <= 0:
                device = "cpu"
            elif size > 0 and size_vram >= size * 0.95:
                device = "cuda"
            else:
                device = "mixed"
            details = loaded.get("details") or {}
            self._runtime = {
                "device": device,
                "precision": details.get("quantization_level"),
                "size_bytes": size,
                "size_vram_bytes": size_vram,
                "vram_fraction": size_vram / size if size else None,
            }
        except Exception as error:
            self._runtime = {"device": "unknown", "error": str(error)}
        return self._runtime


def _nanoseconds_to_seconds(value: Any) -> float | None:
    if value is None:
        return None
    return float(value) / 1_000_000_000
