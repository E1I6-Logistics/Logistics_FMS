"""시나리오의 Mock 시작 위치 복원. 실제 실행 경로에서는 import하지 않는다."""
import math
from backend.app.services.mock_data import mock_fms


def placement(robots, specs, nodes):
    """빈 노드부터 배치. 서로 자리가 바뀌었으면 여유 노드를 임시로 사용한다."""
    positions = {r["robot_id"]: next((n for n, xy in nodes.items()
                 if math.dist((r["x"], r["y"]), xy) < 1e-6), None) for r in robots}
    targets = {r["id"]: str(r["start"]) for r in specs}
    pending = [rid for rid in targets if positions[rid] != targets[rid]]
    moves = []
    while pending:
        rid = next((r for r in pending if targets[r] not in positions.values()), None)
        if rid is not None:
            node = targets[rid]
            pending.remove(rid)
        else:
            rid = pending[0]
            node = next((n for n in nodes if n not in positions.values()
                         and n not in targets.values()), None)
            if node is None:
                raise ValueError("초기 배치용 빈 노드가 없습니다. 시뮬레이션을 초기화하세요.")
        moves.append((rid, node))
        positions[rid] = node
    return moves



def prepare(specs, nodes):
    with mock_fms._lock:
        robots = mock_fms.robot_snapshots("simulation")
        moves = placement(robots, specs, nodes)
        for robot in specs:
            mock_fms.stop_robot(robot["id"])
        for rid, node in moves:
            mock_fms.navigate_to_pose(rid, *nodes[node])
        for robot in specs:
            mock_fms.stop_robot(robot["id"])
