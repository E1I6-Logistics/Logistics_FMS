"""
[플러그인] Ollama 로컬 모델 기반 최단경로 계산기.

"모델 후보 5종" 중 "오픈소스 로컬" / "오픈소스 경량" 두 자리를
이 클래스 하나로 커버한다. OLLAMA_MODEL 값만 바꿔 같은 코드로 비교한다.

사전 준비:
    cp simulation/.env.example simulation/.env
    # simulation/.env에서 LLM_PROVIDER=ollama, OLLAMA_MODEL을 설정한다.
    ollama pull gemma3:1b
    ollama serve              # 이미 서비스로 실행 중이면 생략한다.
    python simulation/run_llm_comparison.py

로컬 서버는 API 키가 필요 없다. 다른 주소의 서버를 사용하면
simulation/.env에 OLLAMA_HOST를 설정한다.
"""

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
        # host를 안 주면 ollama 기본값(http://localhost:11434)을 그대로 사용
        self.client = ollama.Client(
            host=host or os.getenv("OLLAMA_HOST"),
            timeout=(
                timeout_seconds
                if timeout_seconds is not None
                else float(os.getenv("LLM_TIMEOUT_SECONDS", "60"))
            ),
        )
        self.last_inference = None

    def compute_shortest_path(
        self,
        raw_graph: dict,
        start_id: int,
        target_id: int,
    ) -> dict:
        llm_input = self.build_llm_input(raw_graph, start_id, target_id)

        self.last_inference = None
        request = dict(
            model=self.model,
            messages=[
                {
                    "role": "system",
                    "content": self.instructions
                    or self.instructions_for_graph(raw_graph),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        llm_input, ensure_ascii=False, separators=(",", ":")
                    ),
                },
            ],
            # Ollama는 JSON Schema를 format 파라미터에 직접 전달한다.
            format=self.OUTPUT_SCHEMA,
            options=self.options,
            stream=False,
            keep_alive=self.keep_alive,
        )
        if self.think is not None:
            request["think"] = self.think
        elif self.model.startswith("qwen3:"):
            # 기존 단일 실행기의 qwen3 기본 동작을 유지한다.
            request["think"] = False
        response = self.client.chat(**request)
        raw = response.model_dump(mode='json') if hasattr(response, 'model_dump') else dict(response)
        self.last_inference = {'request': request, 'response': raw}

        content = response["message"]["content"]
        if not content:
            raise RuntimeError("LLM 응답이 비어 있습니다.")

        return json.loads(content)
