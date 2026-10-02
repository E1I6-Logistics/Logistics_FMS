"""mock JSON을 읽어서 테스트 입력으로 변환"""

import json
from pathlib import Path

from simulation.services.route_service import build_route_inputs


MOCK_DIR = Path(__file__).resolve().parent / "mock"


def load_graph():
    return json.loads((MOCK_DIR / "route_graph.geojson").read_text(encoding="utf-8"))


def load_responses():
    return json.loads((MOCK_DIR / "llm_responses.json").read_text(encoding="utf-8"))


def route_inputs():
    # 비교 테스트도 서비스가 해석한 최종 edge weight를 그대로 사용한다.
    return build_route_inputs(load_graph())
