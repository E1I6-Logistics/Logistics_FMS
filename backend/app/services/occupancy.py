"""그래프 좌표와 물리 노드·통로 자원 간의 변환. ROS 및 mock 의존성 없음."""

import math

from .reservation import node_key, edge_key
from .route_graph import locate_current_node


def locate_occupancy(graph, nodes, x: float, y: float, *, tolerance_m: float = 1e-6):
    """좌표 이동 후 그래프 위 점유를 판정한다. 방향별 edge ID는 유지한다."""
    if not math.isfinite(tolerance_m) or tolerance_m <= 0:
        raise ValueError("점유 판정 허용 오차는 유한한 양수여야 합니다.")
    if not all(math.isfinite(value) for value in (x, y)):
        raise ValueError("좌표는 유한한 값이어야 합니다.")
    node = locate_current_node(nodes, x, y, tolerance_m=tolerance_m)
    if node is not None:
        return node, None

    matches = {}
    for feature in graph["features"]:
        props = feature.get("properties") or {}
        if "startid" not in props or "endid" not in props:
            continue
        start, end = str(props["startid"]), str(props["endid"])
        ax, ay = nodes[start]
        bx, by = nodes[end]
        dx, dy = bx - ax, by - ay
        length_squared = dx * dx + dy * dy
        if length_squared == 0:
            continue
        fraction = ((x - ax) * dx + (y - ay) * dy) / length_squared
        if not 0 < fraction < 1:
            continue
        if math.hypot(x - ax - fraction * dx, y - ay - fraction * dy) <= tolerance_m:
            matches.setdefault(tuple(sorted((start, end))), str(props["id"]))

    if len(matches) != 1:
        raise ValueError("좌표의 점유 노드 또는 통로를 확정할 수 없습니다.")
    return None, next(iter(matches.values()))


def occupied_resource(robot, graph):
    if robot["occupied_node"] is not None:
        return node_key(robot["occupied_node"])
    for feature in graph["features"]:
        props = feature.get("properties") or {}
        if (str(props.get("id")) == robot["occupied_edge"]
                and "startid" in props and "endid" in props):
            return edge_key(props["startid"], props["endid"])
    raise ValueError("실제 점유 위치를 확인할 수 없습니다.")
