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
    INSTRUCTIONS = """
    You are a deterministic shortest-path solver for a directed graph.

    Input:
    - start_node: the start node ID
    - target_node: the destination node ID
    - route_graph: either a GeoJSON FeatureCollection or a CompactRouteGraph

    Graph rules:
    1. A feature with geometry.type == "Point" is a node.
    2. Use Point properties.id as the node ID.
    3. Point coordinates are [x, y].
    4. A feature containing properties.startid and properties.endid is a directed edge.
    5. An edge can only be traversed from startid to endid.
    6. Every pair of consecutive nodes in the returned path must have a valid directed edge.

    CompactRouteGraph rules:
    1. nodes contains objects with id, x, and y.
    2. edges contains directed objects with from, to, and precomputed weight.
    3. Traverse a compact edge only from from to to.
    4. Use the supplied weight directly; do not recalculate it.

    Distance rules:
    1. All current edge cost values are 0.
    2. Calculate each edge weight using the coordinates of its start and end nodes.
    3. Use this Euclidean distance formula:
    sqrt((start_x - end_x)^2 + (start_y - end_y)^2)
    4. The total path distance is the sum of all edge weights.

    Find the valid directed path from start_node to target_node with the minimum
    total distance.

    Validation before returning:
    - The path must not be empty.
    - The first node must equal start_node.
    - The last node must equal target_node.
    - Every consecutive node pair must be connected by a directed edge.
    - Include both the start and target nodes.

    Return only the JSON object required by the provided JSON Schema.
    Do not include explanations or Markdown.
    """

    #: 작은 로컬 모델이 불필요한 GeoJSON 규칙을 처리하지 않도록 분리한 지시문.
    COMPACT_INSTRUCTIONS = """
    You are a deterministic shortest-path solver.
    route_graph is a directed weighted graph:
    - nodes is the list of valid node IDs.
    - each edge has from, to, and weight.
    - an edge can only be traversed from from to to.
    - the path cost is the sum of edge weights.

    Find the minimum-cost path for this request only.
    The returned path MUST start with start_node and MUST end with target_node.
    Every consecutive pair in the path MUST match a directed edge.
    Return only the JSON object required by the JSON Schema.
    Do not include explanations or Markdown.
    """

    #: 모든 provider가 강제해야 하는 JSON 출력 스키마.
    #: (기존 코드의 shortest_path_result 스키마와 동일)
    OUTPUT_SCHEMA = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "path": {
                "type": "array",
                "items": {"type": "integer"},
                "minItems": 1,
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
            "route_graph": raw_graph,
            "start_node": start_id,
            "target_node": target_id,
            "required_path_endpoints": {
                "first": start_id,
                "last": target_id,
            },
        }

    def instructions_for_graph(self, graph: dict) -> str:
        """Choose only the rules needed by the selected graph representation."""
        if graph.get("type") == "CompactRouteGraph":
            return self.COMPACT_INSTRUCTIONS
        return self.INSTRUCTIONS
