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
        self.client = OpenAI(
            timeout=float(os.getenv("LLM_TIMEOUT_SECONDS", "60"))
        )

    def compute_shortest_path(
        self,
        raw_graph: dict,
        start_id: int,
        target_id: int,
    ) -> dict:
        llm_input = self.build_llm_input(raw_graph, start_id, target_id)

        response = self.client.responses.create(
            model=self.model,
            instructions=self.instructions_for_graph(raw_graph),
            input=json.dumps(llm_input, ensure_ascii=False, separators=(",", ":")),
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
