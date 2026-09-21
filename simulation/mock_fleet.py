import rclpy
from rclpy.node import Node
from geometry_msgs.msg import PoseStamped
import time
import math
import json
import zenoh
import argparse
import heapq
from pathlib import Path
import struct
import os
from urllib import error as url_error
from urllib import request as url_request

# LLM 제공자별 API 코드는 llm_providers에 두고,
# mock_fleet에서는 공통 비교 함수만 호출한다.
if __package__:
    from .llm_route_comparison import compare_path_with_llm
else:
    from llm_route_comparison import compare_path_with_llm

ROUTE_GRAPH_PATH = Path(__file__).resolve().parents[1] / "routes" / "test.geojson"
ROBOT_IDS = ("robot1", "robot2", "robot3")
INITIAL_POINT_IDS = {"robot1": 0, "robot2": 1, "robot3": 2}
ROBOT_SPEED = 0.25
TELEMETRY_PERIOD = 0.3

#Geojson 맵 points, edges 파싱
def load_route_graph():
    with ROUTE_GRAPH_PATH.open("r", encoding="utf-8") as route_file:
        graph = json.load(route_file)

    points = {}
    edges = []
    for feature in graph.get("features", []):
        geometry = feature.get("geometry", {})
        properties = feature.get("properties", {})
        if geometry.get("type") == "Point":
            point_id = int(properties["id"])
            coordinates = geometry["coordinates"]
            points[point_id] = (float(coordinates[0]), float(coordinates[1]))
        elif properties.get("startid") is not None and properties.get("endid") is not None:
            edges.append(
                (
                    int(properties["startid"]),
                    int(properties["endid"]),
                    float(properties.get("cost", 0.0)),
                )
            )

    if not points:
        raise ValueError(f"Route graph에 Point 노드가 없습니다: {ROUTE_GRAPH_PATH}")
    return points, edges

#Node, Edge, 시작 Node, 도착 Node 를 통한 최단거리 루트 추출
def shortest_path(points, edges, start_id, target_id):
    if start_id not in points or target_id not in points:
        raise ValueError(f"존재하지 않는 Point id입니다: {start_id}, {target_id}")

    adjacency = {point_id: [] for point_id in points}
    for start, end, cost in edges:
        if start not in points or end not in points:
            continue
        start_x, start_y = points[start] #시작 노드 좌표
        end_x, end_y = points[end] #도착 노드
        weight = cost if cost > 0 else math.hypot(end_x - start_x, end_y - start_y)
        adjacency[start].append((end, weight))

    distances = {point_id: math.inf for point_id in points}
    previous = {}
    distances[start_id] = 0.0
    queue = [(0.0, start_id)]

    while queue:
        distance, current = heapq.heappop(queue)
        if distance > distances[current]:
            continue
        if current == target_id:
            break
        for neighbor, weight in adjacency[current]:
            candidate = distance + weight
            if candidate < distances[neighbor]:
                distances[neighbor] = candidate
                previous[neighbor] = current
                heapq.heappush(queue, (candidate, neighbor))

    if distances[target_id] == math.inf:
        raise ValueError(f"Point {start_id}에서 Point {target_id}로 가는 경로가 없습니다.")

    path = [target_id]
    while path[-1] != start_id:
        path.append(previous[path[-1]])
    path.reverse()
    return path


def parse_route_arguments(args):
    parser = argparse.ArgumentParser(description="Route graph 기반 Mock Fleet 시뮬레이터")
    parser.add_argument(
        "--robot-number",
        type=int,
        choices=(1, 2, 3),
        help="목적지를 지정할 로봇 번호 (1~3)",
    )
    parser.add_argument(
        "--point-id",
        type=int,
        help="선택한 로봇이 이동할 Route Graph Point id",
    )
    parser.add_argument(
        "--fms-url",
        default=os.getenv("FMS_API_URL", "http://127.0.0.1:8000"),
        help="현재 모드에 따라 명령을 분기할 FMS Backend URL",
    )
    parsed, ros_args = parser.parse_known_args(args)
    if (parsed.robot_number is None) != (parsed.point_id is None):
        parser.error("--robot-number와 --point-id는 함께 지정해야 합니다.")
    return parsed, ros_args


def dispatch_goal_command(fms_url, robot_number, point_id):
    """Send the same node command used by the frontend and real robots."""
    endpoint = f"{fms_url.rstrip('/')}/api/command/goal-node"
    body = json.dumps({
        "robot_id": f"robot{robot_number}",
        "node_id": point_id,
    }).encode("utf-8")
    command = url_request.Request(
        endpoint,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with url_request.urlopen(command, timeout=10) as response:
            result = json.loads(response.read().decode("utf-8"))
    except url_error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"FMS 명령 실패 ({exc.code}): {detail}") from exc
    except url_error.URLError as exc:
        raise RuntimeError(f"FMS Backend 연결 실패: {endpoint} ({exc.reason})") from exc

    print(
        "FMS 이동 명령 완료: "
        f"mode={result.get('mode', 'unknown')}, "
        f"robot={result.get('robot_id', f'robot{robot_number}')}, "
        f"node={point_id}, "
        f"status={result.get('status', 'unknown')}"
    )
    return result


def parse_goal_payload(raw_payload):
    json_bytes = raw_payload.lstrip(b"\xef\xbb\xbf \t\r\n")

    if json_bytes.startswith((b"{", b"[")):
        return json.loads(json_bytes.decode("utf-8"))

    cdr_header_size = 4
    string_length_size = 4
    minimum_cdr_size = cdr_header_size + string_length_size
    if len(raw_payload) < minimum_cdr_size:
        raise ValueError("Goal payload가 JSON 또는 유효한 ROS 2 CDR 형식이 아닙니다.")

    string_length = struct.unpack_from("<I", raw_payload, cdr_header_size)[0]
    json_start = minimum_cdr_size
    json_end = json_start + string_length
    if string_length == 0 or json_end > len(raw_payload):
        raise ValueError("ROS 2 CDR 문자열 길이가 payload 범위를 벗어났습니다.")

    json_bytes = raw_payload[json_start:json_end].rstrip(b"\x00")
    return json.loads(json_bytes.decode("utf-8"))


class FleetSimulatorNode(Node):
    def __init__(self, robot_number=None, point_id=None):
        super().__init__('fleet_simulator_node')
        self.points, self.edges = load_route_graph()
        self.route_robot_id = (
            f"robot{robot_number}" if robot_number is not None else None
        )
        self.robot_states = self.build_robot_states(point_id)
        
        # 1. Zenoh 세션 초기화 (기존 인프라 7447 포트 연동)
        conf = zenoh.Config()
        conf.insert_json5("connect/endpoints", '["tcp/127.0.0.1:7447"]')
        # conf.insert_json5("connect/endpoints", '["tcp/10.10.141.15:7447"]')
        self.zenoh_session = zenoh.open(conf)
        self.get_logger().info("-> Zenoh 세션 연결 완료 (fms-zenoh-router:7447)")
        

        # 2. 관제 시스템에서 보내는 Goal 명령 구독 (robot1/goal 예시)
        self.zenoh_session.declare_subscriber("*/goal", self.on_zenoh_goal_received)

        # 3. ROS 2 퍼블리셔 선언 (필요시 내부 ROS 2 노드들과 통신용)
        self.goal_publishers = {
            "robot1": self.create_publisher(PoseStamped, '/robot1/goal_pose', 10),
            "robot2": self.create_publisher(PoseStamped, '/robot2/goal_pose', 10),
            "robot3": self.create_publisher(PoseStamped, '/robot3/goal_pose', 10),
        }

        # 4. 주기적 텔레메트리 발행을 위한 타이머 설정 (0.3초 주기)
        self.timer = self.create_timer(TELEMETRY_PERIOD, self.publish_telemetry_callback)
        
        self.get_logger().info(
            f"-> [fleet]로봇 3대 ROS 2 시뮬레이터 노드 구동 시작 "
            f"(route={self.route_robot_id or 'none'}:{point_id if point_id is not None else '-'})"
        )

    def build_robot_states(self, route_point_id):
        states = {}
        for robot_id in ROBOT_IDS:
            start_id = INITIAL_POINT_IDS[robot_id]
            target_id = (
                route_point_id if robot_id == self.route_robot_id else start_id
            )
            path = shortest_path(self.points, self.edges, start_id, target_id)

            # 명령행에서 선택한 로봇의 초기 경로도 LLM과 비교한다.
            if robot_id == self.route_robot_id and route_point_id is not None:
                self.compare_route_with_llm(
                    robot_id,
                    start_id,
                    target_id,
                    path,
                )

            states[robot_id] = {
                "path": path,
                "segment": 0,
                "progress": 0.0,
                "status": "NAVIGATING" if len(path) > 1 else "IDLE",
                "battery": {"robot1": 95.0, "robot2": 82.5, "robot3": 45.0}[robot_id],
            }
            self.get_logger().info(
                f"[{robot_id}] Point {start_id} -> Point {target_id}, 최단 경로: {path}"
            )
        return states

    def compare_route_with_llm(
        self,
        robot_id,
        start_id,
        target_id,
        baseline_path,
    ):
        """선택된 LLM 플러그인으로 기존 최단경로 결과를 비교한다."""

        # LLM_PROVIDER가 없으면 기존 Mock Fleet과 완전히 동일하게 동작한다.
        if not os.getenv("LLM_PROVIDER"):
            return

        try:
            comparison = compare_path_with_llm(
                self.points,
                self.edges,
                start_id,
                target_id,
                baseline_path,
            )

            self.get_logger().info(
                f"[{robot_id}] LLM 경로 비교 완료: "
                f"provider={comparison['provider']}, "
                f"model={comparison['model']}, "
                f"LLM 경로={comparison['llm']['path']}, "
                f"경로 일치={comparison['comparison']['same_path']}, "
                f"거리 일치={comparison['comparison']['same_distance']}"
            )

        except Exception as exc:
            # LLM 또는 네트워크가 실패해도 기존 로봇 이동은 중단하지 않는다.
            self.get_logger().error(
                f"[{robot_id}] LLM 경로 비교 실패: {exc}"
            )

    def advance_robot(self, state):
        while state["segment"] < len(state["path"]) - 1:
            start = self.points[state["path"][state["segment"]]]
            end = self.points[state["path"][state["segment"] + 1]]
            segment_length = math.hypot(end[0] - start[0], end[1] - start[1])
            if segment_length == 0:
                state["segment"] += 1
                state["progress"] = 0.0
                continue

            state["progress"] += ROBOT_SPEED * TELEMETRY_PERIOD / segment_length
            if state["progress"] < 1.0:
                break
            state["progress"] -= 1.0
            state["segment"] += 1

        if state["segment"] >= len(state["path"]) - 1:
            state["segment"] = len(state["path"]) - 1
            state["progress"] = 0.0
            state["status"] = "IDLE"

    def robot_pose(self, state):
        point_id = state["path"][state["segment"]]
        if state["segment"] >= len(state["path"]) - 1:
            return (*self.points[point_id], 0.0)

        start = self.points[point_id]
        end = self.points[state["path"][state["segment"] + 1]]
        progress = state["progress"]
        x = start[0] + (end[0] - start[0]) * progress
        y = start[1] + (end[1] - start[1]) * progress
        yaw = math.atan2(end[1] - start[1], end[0] - start[0])
        return x, y, yaw

    def find_nearest_point_id(self, x, y):
        return min(
            self.points,
            key=lambda point_id: (self.points[point_id][0] - x) ** 2
            + (self.points[point_id][1] - y) ** 2,
        )

    def update_robot_goal(self, robot_id, target_x, target_y):
        if robot_id not in self.robot_states:
            raise ValueError(f"알 수 없는 로봇 ID입니다: {robot_id}")

        target_point_id = self.find_nearest_point_id(target_x, target_y)
        state = self.robot_states[robot_id]

        current_point_id = state["path"][state["segment"]]
        new_path = shortest_path(
            self.points,
            self.edges,
            current_point_id,
            target_point_id,
        )

        # Zenoh로 새 목표를 받은 경우에도 동일 입력으로 LLM 경로를 비교한다.
        self.compare_route_with_llm(
            robot_id,
            current_point_id,
            target_point_id,
            new_path,
        )

        state["path"] = new_path
        state["segment"] = 0
        state["progress"] = 0.0
        state["status"] = "NAVIGATING" if len(new_path) > 1 else "IDLE"

        self.get_logger().info(
            f"[{robot_id}] 목표 경로 갱신: "
            f"Point {current_point_id} -> Point {target_point_id}, "
            f"경로={new_path}"
        )

    def on_zenoh_goal_received(self, sample):
        """관제 웹에서 Zenoh로 보낸 주행 목표를 수신하여 ROS 2 토픽으로 전환"""
        try:
            topic = str(sample.key_expr)
            robot_id = topic.split('/')[0]
            payload = parse_goal_payload(sample.payload.to_bytes())
            target_x = float(payload['x'])
            target_y = float(payload['y'])            
            self.get_logger().info(f"[{robot_id}] Zenoh Goal 수신 -> X: {target_x}, Y: {target_y}")
            self.update_robot_goal(robot_id, target_x, target_y)

            # ROS 2 PoseStamped 메시지로 변환 후 내부 발행
            if robot_id in self.goal_publishers:
                msg = PoseStamped()
                msg.header.stamp = self.get_clock().now().to_msg()
                msg.header.frame_id = 'map'
                msg.pose.position.x = target_x
                msg.pose.position.y = target_y
                msg.pose.orientation.w = 1.0
                self.goal_publishers[robot_id].publish(msg)

        except Exception as e:
            self.get_logger().error(f"Goal 처리 에러: {e}")

    def publish_telemetry_callback(self):
        """3대 로봇의 궤적을 계산하여 Zenoh 텔레메트리 토픽으로 발행"""
        for robot_id, state in self.robot_states.items():
            self.advance_robot(state)
            x, y, yaw = self.robot_pose(state)
            payload = {
                "robot_id": robot_id,
                "x": round(x, 2),
                "y": round(y, 2),
                "yaw": round(yaw, 2),
                "battery": state["battery"],
                "status": state["status"],
            }
            
            # Zenoh를 통해 중앙 관제 서버로 위치 전송
            self.zenoh_session.put(f"{robot_id}/telemetry", json.dumps(payload).encode('utf-8'))

    def destroy_node(self):
        self.zenoh_session.close()
        super().destroy_node()

def main(args=None):
    route_args, ros_args = parse_route_arguments(args)

    # 목적지가 주어진 실행은 simulator를 하나 더 띄우지 않고 FMS에 명령만 전달한다.
    # 실제 로봇/시뮬레이션 분기는 프론트에서 선택한 Backend 현재 모드가 담당한다.
    if route_args.robot_number is not None:
        dispatch_goal_command(
            route_args.fms_url,
            route_args.robot_number,
            route_args.point_id,
        )
        return

    rclpy.init(args=ros_args)
    node = FleetSimulatorNode(route_args.robot_number, route_args.point_id)
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        node.get_logger().info("군집 시뮬레이터 노드 종료 중...")
    finally:
        node.destroy_node()
        rclpy.shutdown()

if __name__ == '__main__':
    main()
