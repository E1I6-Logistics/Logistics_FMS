from dataclasses import dataclass
import heapq
import math
from .reservation import node_key, edge_key

# decorator
@dataclass(frozen=True)
class PathResult:
    route: tuple[str, ...]
    total_distance_m: float
    estimated_travel_time_s: float
    speed_mps: float

    def to_dict(self):
        return dict(route=list(self.route), total_distance_m=self.total_distance_m,
                    estimated_travel_time_s=self.estimated_travel_time_s,
                    speed_mps=self.speed_mps, algorithm='astar_distance')

class DistanceAStar:
    def __init__(self, graph):
        self.nodes = {}
        for feature in graph['features']:
            geometry = feature.get('geometry') or {}
            if geometry.get('type') != 'Point':
                continue

            node = str(feature['properties']['id'])
            coords = geometry.get('coordinates', [])
            if len(coords) <2 or node in self.nodes:
                raise ValueError('노드 좌표 누락 또는 중복 ID')
            
            point = tuple(float(v) for v in coords[:2])
            if not all(math.isfinite(v) for v in point):
                raise ValueError('노드 좌표는 유한한 값이어야 한다.')

            self.nodes[node] = point

        if not self.nodes:
            raise ValueError('그래프에 노드가 없습니다.')
        
        self.edges = {node: [] for node in self.nodes}
        for feature in graph['features']:
            props = feature.get('properties') or {}
            if 'startid' not in props and 'endid' not in props:
                continue

            start,end = str(props.get('startid')), str(props.get('endid'))
            if start not in self.nodes or end not in self.nodes:
                raise ValueError('엣지가 존재하지 않는 노드를 참조합니다.')
            
            self.edges[start].append((end, math.dist(self.nodes[start], self.nodes[end])))

    def plan(self, start, end, speed_mps=0.025):
        start, end = str(start), str(end)
        if start not in self.nodes or end not in self.nodes:
            raise ValueError('출발 또는 목적지 노드가 존재하지 않습니다.')
        if not math.isfinite(speed_mps) or speed_mps <= 0:
            raise ValueError('속도는 유한한 양수여야 합니다.')
        
        heuristic = lambda node: math.dist(self.nodes[node], self.nodes[end])
        queue = [(heuristic(start), 0.0, start)]
        distances = {start: 0.0}
        previous = {}
        while queue:
            _, cost, node = heapq.heappop(queue)
            if cost > distances[node]:
                continue

            if node == end:
                route = [end]
                while route[-1] != start:
                    route.append(previous[route[-1]])
                return PathResult(tuple(reversed(route)), cost, cost / speed_mps, speed_mps)

            for neighbor, weight in self.edges[node]:
                candidate = cost + weight
                if candidate < distances.get(neighbor, math.inf):
                    distances[neighbor] = candidate
                    previous[neighbor] = node
                    heapq.heappush(queue, (candidate + heuristic(neighbor), candidate, neighbor))

        raise ValueError('방향성 그래프에서 도달 가능한 경로가 없습니다.')

    # 다른 로봇의 예약을 기준으로 가장 이른 도착 경로를 탐색. 시간 기준
    # blocked: 노드·통로별로 사용할 수 없는 시간 구간 -> 안전 여유가 반영된 기존 예약과 실제 점유를 전달.
    # 구간 중간 출발은 허용 방향별 끝점을 모두 비교
    def plan_timed(self, end, position, current_node, occupied_edge=None, *,
                   blocked, now, speed_mps, safety_margin, allowed_edges=None):
        end = str(end)
        if end not in self.nodes:
            raise ValueError('목적지 노드가 존재하지 않습니다.')
        if (not all(math.isfinite(v) for v in (now, speed_mps, safety_margin, *position))
                or now < 0 or speed_mps <= 0 or safety_margin <= 0 or len(position) != 2):
            raise ValueError('시간·속도·안전 여유·좌표가 올바르지 않습니다.')
        if current_node is not None:
            current_node = str(current_node)
            if current_node not in self.nodes or math.dist(position, self.nodes[current_node]) > 1e-6:
                raise ValueError('현재 노드와 실제 위치가 일치하지 않습니다.')
        elif occupied_edge is None or any(n not in self.nodes for n in occupied_edge):
            raise ValueError('구간 중간 출발에는 점유 통로가 필요합니다.')

        margin = safety_margin
        intervals = {}
        for node in self.nodes:
            cursor, safe = 0.0, []
            for start, finish in sorted(blocked.get(node_key(node), ())):
                lower, upper = max(0.0, start - margin), finish + margin
                if lower + margin > start:
                    lower = math.nextafter(lower, -math.inf)
                if math.isfinite(upper) and upper - margin < finish:
                    upper = math.nextafter(upper, math.inf)
                if upper <= cursor:
                    continue
                if lower > cursor:
                    safe.append((cursor, lower))
                cursor = max(cursor, upper)
            if math.isfinite(cursor):
                safe.append((cursor, math.inf))
            intervals[node] = safe

        # 특정 다음 구간의 가장 빠른 출발 계산
        def earliest(arrival, source_end, target_interval, resource, duration, on_edge=False):
            lower, upper = target_interval
            departure = max(arrival, lower - duration)
            if departure + duration < lower:
                departure = math.nextafter(departure, math.inf)
            for start, finish in sorted(blocked.get(resource, ())):
                occupied_from = now if on_edge else departure
                if occupied_from - margin < finish and start < departure + duration + margin:
                    # 이미 점유 중인 통로에서 다른 예약을 가로질러 기다릴 수 없다.
                    if on_edge or not math.isfinite(finish):
                        return None
                    departure = finish + margin
                    if departure - margin < finish:
                        departure = math.nextafter(departure, math.inf)
            reached = departure + duration
            if (not math.isfinite(reached) or departure > source_end
                    or reached < lower or reached > upper):
                return None
            return departure, reached

        best, parents, seeds, queue = {}, {}, {}, []

        # 직선 이동 시간은 대기나 우회를 제외한 예상치 -> 목적지에 빨리 도착할 가능성이 높은 상태부터 검사
        def push(state, arrival):
            heuristic = math.dist(self.nodes[state[0]], self.nodes[end]) / speed_mps
            heapq.heappush(queue, (arrival + heuristic, arrival, state))

        if current_node is not None:
            for i, (lower, upper) in enumerate(intervals[current_node]):
                if lower <= now <= upper:
                    state = (current_node, i)
                    best[state] = now
                    seeds[state] = ([current_node], [])
                    push(state, now)
                    break
        else:
            # 양 끝점을 후보로 확인
            a, b = occupied_edge
            for previous, endpoint in ((a, b), (b, a)):
                if not any(neighbor == endpoint for neighbor, _ in self.edges[previous]):
                    continue
                if allowed_edges is not None and (previous, endpoint) not in allowed_edges:
                    continue
                duration = math.dist(position, self.nodes[endpoint]) / speed_mps
                for i, interval in enumerate(intervals[endpoint]):
                    move = earliest(now, math.inf, interval, edge_key(a, b), duration, True)
                    if move is None:
                        continue
                    departure, arrival = move
                    state = (endpoint, i)
                    if arrival < best.get(state, math.inf):
                        best[state] = arrival
                        seeds[state] = ([previous, endpoint], [departure])
                        push(state, arrival)

        while queue:
            _, arrival, state = heapq.heappop(queue)
            if arrival != best[state]:
                continue
            node, interval_index = state
            source_end = intervals[node][interval_index][1]
            # 목적지에서 계속 정차할 수 있는 구간에 도착해야 완료다.
            if node == end and source_end == math.inf:
                suffix, departures = [], []
                while state in parents:
                    suffix.append(state[0])
                    state, departure = parents[state]
                    departures.append(departure)
                prefix, initial_departures = seeds[state]
                return {
                    'node_ids': prefix + list(reversed(suffix)),
                    'segment_departures': initial_departures + list(reversed(departures)),
                }
            for neighbor, distance in self.edges[node]:
                if allowed_edges is not None and (node, neighbor) not in allowed_edges:
                    continue
                for i, interval in enumerate(intervals[neighbor]):
                    move = earliest(arrival, source_end, interval, edge_key(node, neighbor),
                                    distance / speed_mps)
                    if move is None:
                        continue
                    departure, reached = move
                    successor = (neighbor, i)
                    if reached < best.get(successor, math.inf):
                        best[successor] = reached
                        parents[successor] = (state, departure)
                        push(successor, reached)
        return None
