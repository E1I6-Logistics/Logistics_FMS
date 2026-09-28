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
        self.client = ollama.Client(
            host=host or os.getenv("OLLAMA_HOST"),
            timeout=float(os.getenv("LLM_TIMEOUT_SECONDS", "60")),
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
        options = {'temperature': 0, 'seed': 20260928, 'num_ctx': 4096, 'num_predict': 512}
        request = dict(
            model=self.model,
            messages=[
                {"role": "system", "content": self.instructions_for_graph(raw_graph)},
                {
                    "role": "user",
                    "content": json.dumps(
                        llm_input, ensure_ascii=False, separators=(",", ":")
                    ),
                },
            ],
            # Ollama는 JSON Schema를 format 파라미터에 직접 전달한다.
            format=self.OUTPUT_SCHEMA,
            options=options,
            stream=False,
            keep_alive='5m',
        )
        if self.model.startswith('qwen3:'):
            request['think'] = False
        response = self.client.chat(**request)
        raw = response.model_dump(mode='json') if hasattr(response, 'model_dump') else dict(response)
        self.last_inference = {'request': request, 'response': raw}

        content = response["message"]["content"]
        if not content:
            raise RuntimeError("LLM 응답이 비어 있습니다.")

        return json.loads(content)
