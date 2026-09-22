"""
[플러그인] Anthropic Claude API 기반 최단경로 계산기.

"모델 후보 5종" 중 "상용 타 벤더 저지연" 자리에 해당한다.
Claude의 Structured Outputs(JSON outputs) 기능으로 스키마를 강제한다.

사전 준비:
    pip install anthropic
    export ANTHROPIC_API_KEY="발급받은_API_KEY"
    export ANTHROPIC_MODEL="claude-sonnet-4-6"
    # ⚠️ Structured Outputs 지원 모델만 사용 가능 — 최신 지원 목록은
    #    docs.claude.com/en/docs/build-with-claude/structured-outputs 확인
"""

from __future__ import annotations

import json
import os

from anthropic import Anthropic

from .base import LLMPathProvider


class AnthropicPathProvider(LLMPathProvider):
    name = "anthropic"

    def __init__(self, model: str | None = None):
        self.model = model or self._require_env("ANTHROPIC_MODEL")
        self._require_env("ANTHROPIC_API_KEY")
        # ANTHROPIC_API_KEY 환경변수를 자동으로 읽는다.
        self.client = Anthropic(
            timeout=float(os.getenv("LLM_TIMEOUT_SECONDS", "60"))
        )

    def compute_shortest_path(
        self,
        raw_graph: dict,
        start_id: int,
        target_id: int,
    ) -> dict:
        llm_input = self.build_llm_input(raw_graph, start_id, target_id)

        response = self.client.messages.create(
            model=self.model,
            max_tokens=1024,
            system=self.instructions_for_graph(raw_graph),
            messages=[
                {
                    "role": "user",
                    "content": json.dumps(
                        llm_input, ensure_ascii=False, separators=(",", ":")
                    ),
                }
            ],
            # OpenAI의 text.format과 동일한 역할 — JSON 스키마를 강제한다.
            output_config={
                "format": {
                    "type": "json_schema",
                    "schema": self.OUTPUT_SCHEMA,
                }
            },
        )

        if not response.content or not response.content[0].text:
            raise RuntimeError("LLM 응답에 텍스트가 없습니다.")

        return json.loads(response.content[0].text)
