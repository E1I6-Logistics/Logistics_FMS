from __future__ import annotations

from dataclasses import dataclass
from math import dist, isfinite
from threading import RLock


# 노드: ("node", node_id)
# 통로: ("edge", 작은_ID, 큰_ID)
ResourceKey = tuple[str, ...]


def node_key(node_id: str | int) -> ResourceKey:
    return ("node", str(node_id))


def edge_key(start_id: str | int, end_id: str | int) -> ResourceKey:
    # 방향별 엣지 ID가 달라도 같은 물리 통로로 비교
    return ("edge", *sorted((str(start_id), str(end_id))))


@dataclass(frozen=True)
class Reservation:
    resource: ResourceKey
    robot_id: str
    navigation_id: str
    segment_index: int
    start: float
    end: float

    def __post_init__(self) -> None:
        key = self.resource

        if len(key) == 2 and key[0] == "node":
            key = node_key(key[1])
        elif len(key) == 3 and key[0] == "edge":
            key = edge_key(key[1], key[2])
        else:
            raise ValueError("예약 자원은 node 또는 edge여야 합니다.")

        object.__setattr__(self, "resource", key)

        if not self.robot_id or not self.navigation_id:
            raise ValueError("로봇 ID와 주행 요청 ID가 필요합니다.")

        if self.segment_index < 0:
            raise ValueError("구간 인덱스는 0 이상이어야 합니다.")

        if not isfinite(self.start) or self.start < 0:
            raise ValueError("시작 시각은 유한한 0 이상의 값이어야 합니다.")

        # 출발 계획이 없는 목적지 정차를 표현하기 위해 +inf 허용
        if (
            not (isfinite(self.end) or self.end == float("inf"))
            or self.end <= self.start
        ):
            raise ValueError("종료 시각은 시작 시각보다 커야 합니다.")


def overlaps(a: Reservation, b: Reservation) -> bool:
    # 한 예약의 끝과 다른 예약의 시작이 같으면 비중첩
    return a.start < b.end and b.start < a.end


class ReservationTable:
    def __init__(self) -> None:
        # 모든 로봇의 예약 검사/확정을 함께 보호
        self._lock = RLock()
        self._rows: list[Reservation] = []

    # 전체 후보 시간표를 한 번에 확정
    # True: 예약표에 충돌 없이 확정. 실제 주행 허가는 아님.
    # False: 다른 로봇의 예약과 충돌. 기존 데이터는 유지됨.
    def try_commit(self, robot_id: str, navigation_id: str, candidates: list[Reservation] | tuple[Reservation, ...]) -> bool:
        batch = tuple(candidates) # 호출자가 원본 목록을 바꿔도 검사 대상이 변하지 않도록 고정

        if not batch:
            raise ValueError("예약 후보가 비어 있습니다.")

        if any(
            row.robot_id != robot_id
            or row.navigation_id != navigation_id
            for row in batch
        ):
            raise ValueError("예약 후보의 로봇 또는 주행 요청 ID가 다릅니다.")

        with self._lock:
            existing = tuple(
                row for row in self._rows
                if row.robot_id == robot_id and row.navigation_id == navigation_id
            )
            if existing:
                if existing != batch:
                    raise ValueError("이미 확정된 시간표를 try_commit으로 덮어쓸 수 없습니다.")
                return True
            for candidate in batch:
                for row in self._rows:
                    if row.robot_id == robot_id:
                        continue
                    if candidate.resource == row.resource and overlaps(candidate, row):
                        return False
            self._rows.extend(batch)
            return True

    def snapshot(self) -> tuple[Reservation, ...]:
        with self._lock:
            return tuple(self._rows)

    # 정지 상태에서 시간표를 교체
    def replace_request(self, robot_id, navigation_id, candidates) -> bool:
        with self._lock:
            previous = self._rows
            self._rows = [row for row in previous if row.robot_id != robot_id]
            try:
                if self.try_commit(robot_id, navigation_id, candidates):
                    return True
            except Exception:
                self._rows = previous
                raise
            self._rows = previous
            return False

    # 실행 종료 및 실제 점유 보호 확인 후에만 해당 요청을 해제
    def release_request(self, robot_id: str, navigation_id: str) -> None:
        with self._lock:
            self._rows = [
                row for row in self._rows
                if not (row.robot_id == robot_id and row.navigation_id == navigation_id)
            ]


reservation_tables = {
    "real": ReservationTable(),
    "simulation": ReservationTable(),
}


def build_schedule(
    robot_id: str,
    navigation_id: str,
    node_ids: list[str],
    nodes: dict[str, tuple[float, float]],
    position: tuple[float, float],
    current_node: str | None,
    *,
    now: float,
    departure_at: float,
    speed_mps: float,
    safety_margin: float,
) -> tuple[Reservation, ...]:
    if not node_ids or any(node not in nodes for node in node_ids):
        raise ValueError("경로 노드가 비어 있거나 좌표가 없습니다.")
    if not all(isfinite(value) for value in (now, departure_at, speed_mps, safety_margin)):
        raise ValueError("시간·속도·안전 여유는 유한해야 합니다.")
    if now < 0 or departure_at < now or speed_mps <= 0 or safety_margin <= 0:
        raise ValueError("시간·속도·안전 여유의 범위가 올바르지 않습니다.")
    if len(position) != 2 or any(
        len(point) != 2 or not all(isfinite(value) for value in point)
        for point in [position, *(nodes[node] for node in node_ids)]
    ):
        raise ValueError("위치는 유한한 2차원 좌표여야 합니다.")
    if current_node is not None:
        if current_node != node_ids[0] or dist(position, nodes[current_node]) > 1e-6:
            raise ValueError("현재 노드와 실제 출발 위치가 일치하지 않습니다.")
    elif len(node_ids) < 2:
        raise ValueError("구간 중간 출발에는 통로 양 끝 노드가 필요합니다.")

    rows = []

    def add(resource, index, start, end):
        rows.append(Reservation(resource, robot_id, navigation_id, index, max(0.0, start), end))

    if len(node_ids) == 1:
        add(node_key(node_ids[0]), 0, now - safety_margin, float("inf"))
        return tuple(rows)

    if current_node is not None:
        add(node_key(current_node), 0, now - safety_margin, departure_at + safety_margin)

    entry = departure_at
    origin = position
    for index, (start, end) in enumerate(zip(node_ids, node_ids[1:])):
        arrival = entry + dist(origin, nodes[end]) / speed_mps
        if not isfinite(arrival):
            raise ValueError("예상 도착 시각이 유한하지 않습니다.")
        # 통로 중간에서 대기하면 현재 시각부터 해당 통로를 보호한다.
        occupied_from = now if index == 0 and current_node is None else entry
        add(edge_key(start, end), index, occupied_from - safety_margin, arrival + safety_margin)
        last = index == len(node_ids) - 2
        add(node_key(end), index, arrival - safety_margin,
            float("inf") if last else arrival + safety_margin)
        origin = nodes[end]
        entry = arrival

    return tuple(rows)
