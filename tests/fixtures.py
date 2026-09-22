"""mock JSON을 읽어서 테스트 입력으로 변환"""

import json
from pathlib import Path


MOCK_DIR = Path(__file__).resolve().parent / "mock"


def load_graph():
    return json.loads((MOCK_DIR / "route_graph.geojson").read_text(encoding="utf-8"))


def load_responses():
    return json.loads((MOCK_DIR / "llm_responses.json").read_text(encoding="utf-8"))


def route_inputs():
    graph = load_graph()
    points = {
        int(feature["properties"]["id"]): tuple(feature["geometry"]["coordinates"][:2])
        for feature in graph["features"]
        if feature.get("geometry", {}).get("type") == "Point"
    }
    edges = [
        (feature["properties"]["startid"], feature["properties"]["endid"], feature["properties"]["cost"])
        for feature in graph["features"]
        if "startid" in feature.get("properties", {})
    ]
    return points, edges
