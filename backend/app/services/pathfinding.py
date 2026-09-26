from dataclasses import dataclass
import heapq
import math

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

    def plan(self, start, end, speed_mps=0.5):
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