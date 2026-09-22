"""ROS/Zenoh Mock Fleet와 선택적 LLM 경로 비교의 진입점.

실행 흐름은 두 가지다. 목표 인자를 주면 FMS API에 명령만 보내고 종료한다.
인자 없이 실행하면 Zenoh 목표를 받는 시뮬레이터가 시작되며, 그때
LLM_PROVIDER가 설정되어 있으면 코드 경로와 LLM 경로를 비교한다.
"""

import rclpy
from rclpy.node import Node
from geometry_msgs.msg import PoseStamped
import time
import math
import json
import zenoh
import argparse
from pathlib import Path
import struct
import os
import sys
from urllib import error as url_error
from urllib import request as url_request

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.services.route_graph import (
    load_route_graph,
    node_lookup,
)
from backend.app.services.route_planner import plan_route

# 벤더별 API 호출은 llm_providers에 맡긴다. Mock Fleet은 코드 경로를
# baseline으로 넘기고, 비교 결과를 로그에 남기는 역할만 담당한다.
if __package__:
    from .llm_route_comparison import compare_path_with_llm
else:
    from llm_route_comparison import compare_path_with_llm

ROBOT_IDS = ("robot1", "robot2", "robot3")
INITIAL_POINT_IDS = {"robot1": 0, "robot2": 1, "robot3": 2}
ROBOT_SPEED = 0.25
TELEMETRY_PERIOD = 0.3

# 1. 공통 route_graph가 읽은 GeoJSON을 LLM 검증과 로봇 보간에 필요한
# points/edges 형식으로 바꾼다. 별도의 그래프 파일을 다시 읽지 않는다.
def build_route_inputs(graph):
    points = {
        int(node_id): (
            float(feature["geometry"]["coordinates"][0]),
            float(feature["geometry"]["coordinates"][1]),
        )
        for node_id, feature in node_lookup(graph).items()
    }
    edges = []
    for feature in graph.get("features", []):
        properties = feature.get("properties") or {}
        if properties.get("startid") is not None and properties.get("endid") is not None:
            edges.append(
                (
                    int(properties["startid"]),
                    int(properties["endid"]),
                    float(properties.get("cost", 0.0)),
                )
            )

    if not points:
        raise ValueError("Route graph에 Point 노드가 없습니다.")
    return points, edges

def plan_node_path(graph, start_id, target_id):
    """2. 공통 플래너의 최단 경로를 기존 정수 node path 형식으로 변환한다.

    이 결과가 로봇 이동 경로이자 LLM 비교의 baseline이다.
    """
    route = plan_route(str(start_id), str(target_id), graph)
    return [int(node_id) for node_id in route["node_ids"]]


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
        self.route_graph = load_route_graph()
        self.points, self.edges = build_route_inputs(self.route_graph)
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
            path = plan_node_path(self.route_graph, start_id, target_id)

            # 3. 초기 목표가 지정된 경우 코드 경로를 먼저 구한 뒤 LLM과 비교한다.
            # 일반 CLI의 목표 인자 경로는 main()에서 API 전송 후 종료하므로
            # 이 분기는 FleetSimulatorNode를 직접 생성할 때만 실행된다.
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
        """4. 코드 경로와 LLM 경로를 비교하는 보조 실험을 실행한다.

        주행 경로는 바꾸지 않지만 현재는 동기 호출이라 LLM 응답만큼
        목표 반영이 늦어질 수 있다.
        """

        # LLM_PROVIDER가 없으면 API 호출·비교·JSONL 저장을 건너뛴다.
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
            # 비교는 주행 제어에 관여하지 않는다. 모델/네트워크 오류가 나도
            # 앞서 코드로 계산한 경로에 따른 이동은 그대로 진행한다.
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
        new_path = plan_node_path(
            self.route_graph,
            current_point_id,
            target_point_id,
        )

        # 새 Zenoh 목표도 같은 순서다: 코드 경로 계산 → 선택적 LLM 비교
        # → 실제 로봇 상태에 코드 경로 반영. LLM 결과로 경로를 바꾸지 않는다.
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

    # CLI 목표 인자는 FMS에 명령만 전달한다. 이 경로는 아래 Node를 만들지 않아
    # 이 파일의 LLM 비교도 실행하지 않는다. 웹의 simulation_gateway 경로는 별개다.
    # 실제 로봇/시뮬레이션 분기는 Backend 현재 모드가 담당한다.
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
