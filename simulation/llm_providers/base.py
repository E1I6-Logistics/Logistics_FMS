"""
LLM 경로 계산 플러그인 공통 인터페이스.

모든 벤더별 구현(OpenAI, Anthropic, Ollama 등)은 이 클래스를 상속해서
compute_shortest_path()를 구현한다. 공통 지시문·입력·출력 형식을 두어
비교 코드가 벤더별 API 차이를 알 필요가 없도록 한다.
"""

from abc import ABC, abstractmethod
from typing import Optional


class LLMPathProvider(ABC):
    """LLM 기반 최단경로 계산 플러그인의 공통 인터페이스."""

    #: 로그·JSONL 결과에 기록할 provider 이름 (예: "openai", "anthropic", "ollama")
    name: str = "base"

    @abstractmethod
    def compute_shortest_path(
        self,
        raw_graph: dict,
        start_id: int,
        target_id: int,
    ) -> dict:
        """
        LLM에 raw_graph, start_id, target_id를 전달해 경로를 계산시킨다.

        반환값은 항상 아래 스키마를 따라야 한다:
            {
                "path": [int, int, ...],
                "reported_total_distance": float,
            }

        reported_total_distance는 기록용일 뿐, 실제 검증·비교에는
        validate_and_calculate_path_distance()의 재계산값만 사용한다.
        """
        raise NotImplementedError

    #: 모든 provider가 동일하게 사용하는 시스템 지시문.
    #: (기존 request_llm_shortest_path()의 instructions 문자열 그대로)
    INSTRUCTIONS = (
        "당신은 방향성 그래프의 최단 경로 계산기입니다.\n"
        "Point feature의 properties.id를 노드 ID로 사용하세요.\n"
        "Edge feature의 properties.startid에서 "
        "properties.endid 방향으로만 이동할 수 있습니다.\n"
        "Edge의 cost가 0보다 크면 cost를 거리로 사용하세요.\n"
        "cost가 0이면 두 Point 좌표 사이의 "
        "Euclidean 거리를 사용하세요.\n"
        "주어진 시작 노드에서 도착 노드까지의 "
        "최단 경로를 직접 계산하세요."
    )

    #: 모든 provider가 강제해야 하는 JSON 출력 스키마.
    #: (기존 코드의 shortest_path_result 스키마와 동일)
    OUTPUT_SCHEMA = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "path": {
                "type": "array",
                "items": {"type": "integer"},
            },
            "reported_total_distance": {"type": "number"},
        },
        "required": ["path", "reported_total_distance"],
    }

    @staticmethod
    def _require_env(var_name: str) -> str:
        """환경변수가 없으면 즉시 명확한 에러를 낸다."""
        import os

        value = os.getenv(var_name)
        if not value:
            raise RuntimeError(f"{var_name} 환경변수가 설정되지 않았습니다.")
        return value

    def build_llm_input(
        self,
        raw_graph: dict,
        start_id: int,
        target_id: int,
    ) -> dict:
        """세 provider가 공통으로 사용하는 입력 JSON 형태."""
        return {
            "start_node": start_id,
            "target_node": target_id,
            "route_graph": raw_graph,
        }
