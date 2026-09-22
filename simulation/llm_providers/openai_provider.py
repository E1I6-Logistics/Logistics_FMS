"""
[플러그인] OpenAI Responses API 기반 최단경로 계산기.

"모델 후보 5종" 중 "상용 저지연" / "상용 플래그십" 두 자리를
OPENAI_MODEL 값만 바꿔서 커버한다 (예: gpt-4o-mini vs gpt-4.1 등).

사전 준비:
    cp simulation/.env.example simulation/.env
    # simulation/.env의 OPENAI_API_KEY에 실제 키를 입력한다.
    # LLM_PROVIDER=openai, OPENAI_MODEL=모델 ID도 같은 파일에서 설정한다.
    python simulation/run_llm_comparison.py

registry.py가 simulation/.env를 먼저 읽는다. 동일한 환경변수가 셸에
이미 있으면 셸의 값이 우선한다. API 키는 Git에 올리지 않는다.

동작은 기존에 받은 request_llm_shortest_path()와 완전히 동일하다 —
OpenAI 전용 코드를 그대로 클래스 안으로 옮긴 것뿐이다.
"""

import json
import os

from openai import OpenAI

from .base import LLMPathProvider


class OpenAIPathProvider(LLMPathProvider):
    name = "openai"

    def __init__(self, model: str | None = None):
        self.model = model or self._require_env("OPENAI_MODEL")
        self._require_env("OPENAI_API_KEY")
        # OPENAI_API_KEY 환경변수를 자동으로 읽는다.
        self.client = OpenAI()

    def compute_shortest_path(
        self,
        raw_graph: dict,
        start_id: int,
        target_id: int,
    ) -> dict:
        llm_input = self.build_llm_input(raw_graph, start_id, target_id)

        response = self.client.responses.create(
            model=self.model,
            instructions=self.INSTRUCTIONS,
            input=json.dumps(llm_input, ensure_ascii=False),
            text={
                "format": {
                    "type": "json_schema",
                    "name": "shortest_path_result",
                    "strict": True,
                    "schema": self.OUTPUT_SCHEMA,
                }
            },
            # 이번 실험에서는 API 응답을 서버 측에 저장하지 않는다.
            store=False,
        )

        if not response.output_text:
            raise RuntimeError("LLM 응답에 output_text가 없습니다.")

        return json.loads(response.output_text)
