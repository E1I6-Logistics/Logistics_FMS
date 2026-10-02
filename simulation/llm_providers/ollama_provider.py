"""Ollama local-model shortest-path provider."""

from __future__ import annotations

import json
import os
from typing import Any

import ollama

from .base import LLMPathProvider


class OllamaPathProvider(LLMPathProvider):
    name = "ollama"

    def __init__(
        self,
        model: str | None = None,
        host: str | None = None,
        *,
        timeout_seconds: float | None = None,
        options: dict[str, Any] | None = None,
        keep_alive: str = "5m",
        think: bool | None = None,
        instructions: str | None = None,
        output_schema: dict[str, Any] | None = None,
    ):
        self.model = model or self._require_env("OLLAMA_MODEL")
        self.options = options or {
            "temperature": 0,
            "seed": 20260928,
            "num_ctx": 4096,
            "num_predict": 512,
        }
        self.keep_alive = keep_alive
        self.think = think
        self.instructions = instructions
        self.output_schema = output_schema or self.OUTPUT_SCHEMA
        self.client = ollama.Client(
            host=host or os.getenv("OLLAMA_HOST"),
            timeout=(
                timeout_seconds
                if timeout_seconds is not None
                else float(os.getenv("LLM_TIMEOUT_SECONDS", "60"))
            ),
        )
        self.last_inference = None

    def _response_diagnostics(
        self, raw: dict[str, Any], requested_think: bool | None
    ) -> dict[str, Any]:
        """Record ignored think control and exhausted output budgets."""
        message = raw.get("message") or {}
        content = message.get("content") or ""
        thinking = message.get("thinking") or ""
        done_reason = raw.get("done_reason")
        return {
            "requested_think": requested_think,
            "thinking_observed": bool(thinking.strip()),
            "thinking_character_count": len(thinking),
            "content_character_count": len(content),
            "done_reason": done_reason,
            "prompt_eval_count": raw.get("prompt_eval_count"),
            "eval_count": raw.get("eval_count"),
            "output_budget": self.options.get("num_predict"),
            "output_budget_exhausted": done_reason == "length",
            "think_control_ignored": requested_think is False
            and bool(thinking.strip()),
        }

    def request_structured(
        self,
        *,
        instructions: str,
        payload: dict[str, Any],
        output_schema: dict[str, Any],
    ) -> dict[str, Any]:
        """Make one schema-constrained request for either benchmark strategy."""
        self.last_inference = None
        request = dict(
            model=self.model,
            messages=[
                {"role": "system", "content": instructions},
                {
                    "role": "user",
                    "content": json.dumps(
                        payload, ensure_ascii=False, separators=(",", ":")
                    ),
                },
            ],
            format=output_schema,
            options=self.options,
            stream=False,
            keep_alive=self.keep_alive,
        )
        if self.think is not None:
            request["think"] = self.think
        elif self.model.startswith("qwen3:"):
            request["think"] = False

        response = self.client.chat(**request)
        raw = (
            response.model_dump(mode="json")
            if hasattr(response, "model_dump")
            else dict(response)
        )
        diagnostics = self._response_diagnostics(raw, request.get("think"))
        self.last_inference = {
            "request": request,
            "response": raw,
            "diagnostics": diagnostics,
        }
        content = response["message"]["content"]
        if not content:
            raise RuntimeError(
                "LLM 최종 응답이 비어 있습니다: "
                f"model={self.model}, done_reason={diagnostics['done_reason']}, "
                f"eval_count={diagnostics['eval_count']}, "
                f"num_predict={diagnostics['output_budget']}, "
                f"thinking_observed={diagnostics['thinking_observed']}. "
                "done_reason=length이면 모델이 최종 JSON 전에 출력 예산을 "
                "소진한 것입니다."
            )
        return json.loads(content)

    def compute_shortest_path(
        self,
        raw_graph: dict,
        start_id: int,
        target_id: int,
    ) -> dict:
        """Request a complete path in one API call."""
        return self.request_structured(
            instructions=self.instructions or self.instructions_for_graph(raw_graph),
            payload=self.build_llm_input(raw_graph, start_id, target_id),
            output_schema=self.output_schema,
        )
