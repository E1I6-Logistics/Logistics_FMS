"""
[플러그인] Ollama 로컬 모델 기반 최단경로 계산기.

"모델 후보 5종" 중 "오픈소스 로컬" / "오픈소스 경량" 두 자리를
이 클래스 하나로 커버한다 — OLLAMA_MODEL 값만 무거운 모델(예: qwen3-vl)과
가벼운 모델(예: gemma3)로 바꿔가며 쓰면 된다.

사전 준비:
    pip install ollama
    ollama pull qwen3-vl      # 또는: ollama pull gemma3
    ollama serve              # 로컬 서버가 떠 있어야 함 (백그라운드 실행)

⚠️ 로컬 실행이라 API 키/결제는 필요 없지만, 모델을 최초 1회 pull할 때
   용량(수 GB)과 GPU 메모리를 미리 확인해두는 게 좋다.
"""

from __future__ import annotations

import json

import ollama

from .base import LLMPathProvider


class OllamaPathProvider(LLMPathProvider):
    name = "ollama"

    def __init__(self, model: str | None = None, host: str | None = None):
        import os

        self.model = model or self._require_env("OLLAMA_MODEL")
        # host를 안 주면 ollama 기본값(http://localhost:11434)을 그대로 사용
        self.client = ollama.Client(host=host or os.getenv("OLLAMA_HOST"))

    def compute_shortest_path(
        self,
        raw_graph: dict,
        start_id: int,
        target_id: int,
    ) -> dict:
        llm_input = self.build_llm_input(raw_graph, start_id, target_id)

        response = self.client.chat(
            model=self.model,
            messages=[
                {"role": "system", "content": self.INSTRUCTIONS},
                {
                    "role": "user",
                    "content": json.dumps(llm_input, ensure_ascii=False),
                },
            ],
            # Ollama는 JSON Schema를 format 파라미터에 직접 전달한다.
            format=self.OUTPUT_SCHEMA,
        )

        content = response["message"]["content"]
        if not content:
            raise RuntimeError("LLM 응답이 비어 있습니다.")

        return json.loads(content)
