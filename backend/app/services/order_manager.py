from uuid import uuid4

from .fleet_manager import fleet_manager
from ..models.robot import RobotState
from ..schemas.robot import normalize_robot_id
from ..ros2.ros_gateway import ros_gateway
from .mqtt_manager import mqtt_manager


class OrderManager:

    # 주문 품목을 보고 방문해야 하는 Pickup Node 계산
    def get_pickup_nodes(self, items: dict[str, int]) -> list[str]:

        pickup_nodes = []

        # A 또는 B가 하나라도 있으면 Node 5 방문
        if items.get("A", 0) > 0 or items.get("B", 0) > 0:
            pickup_nodes.append("5")

        # C 또는 D가 하나라도 있으면 Node 6 방문
        if items.get("C", 0) > 0 or items.get("D", 0) > 0:
            pickup_nodes.append("6")

        return pickup_nodes

    def create_order(
        self,
        robot_id: str,
        items: dict[str, int],
        total_quantity: int,
        workstation_node: str,
    ) -> dict:

        # R-01 -> robot1
        robot_id = normalize_robot_id(robot_id)

        # FleetManager에서 Robot 객체 조회
        robot = fleet_manager.get_robot(robot_id)

        if robot is None:
            raise ValueError(f"Robot을 찾을 수 없습니다: {robot_id}")

        if not robot.connected:
            raise ValueError(f"Robot이 연결되어 있지 않습니다: {robot_id}")

        if robot.state != RobotState.IDLE:
            raise ValueError(
                f"Robot이 작업 가능한 상태가 아닙니다: " f"{robot_id} ({robot.state.value})"
            )

        # 작업대는 Node 3 또는 Node 4만 허용
        workstation_node = str(workstation_node)

        if workstation_node not in ["3", "4"]:
            raise ValueError(f"지원하지 않는 작업대 Node입니다: {workstation_node}")

        # 주문 수량 검증
        calculated_total = sum(items.values())

        if calculated_total <= 0:
            raise ValueError("주문 수량은 1개 이상이어야 합니다.")

        if calculated_total != total_quantity:
            raise ValueError(
                f"주문 총 수량이 일치하지 않습니다: "
                f"total_quantity={total_quantity}, "
                f"calculated_total={calculated_total}"
            )

        # 주문 ID 생성
        order_id = str(uuid4())

        # 주문 품목에 따라 필요한 Pickup Node 계산
        pickup_nodes = self.get_pickup_nodes(items)

        # Robot 객체에 주문 저장
        robot.assign_order(
            order_id=order_id,
            items=items,
            total_quantity=total_quantity,
            pickup_nodes=pickup_nodes,
            workstation_node=workstation_node,
        )

        # 첫 번째 Pickup Node로 이동
        first_pickup_node = pickup_nodes[0]

        print(f"[ORDER] {robot_id} 첫 Pickup 이동: " f"Node {first_pickup_node}")
        ros_gateway.navigate_to_node(robot_id=robot_id, node_id=first_pickup_node)

        print()
        print("==============================")
        print("[ORDER] New order")
        print("==============================")
        print("robot_id =", robot_id)
        print("order_id =", order_id)
        print("items =", items)
        print("total_quantity =", total_quantity)
        print("pickup_nodes =", pickup_nodes)
        print("workstation_node =", workstation_node)
        print("state =", robot.state.value)
        print("==============================")

        return {
            "order_id": order_id,
            "robot_id": robot_id,
            "items": items,
            "total_quantity": total_quantity,
            "pickup_nodes": pickup_nodes,
            "workstation_node": workstation_node,
            "status": robot.state.value,
        }

    def move_to_next_destination(self, robot_id: str) -> None:
        robot = fleet_manager.get_robot(robot_id)

        if robot is None:
            return

        # 현재 Pickup 완료
        robot.order_pickup_index += 1

        # 아직 방문할 Pickup이 남아 있음
        if robot.order_pickup_index < len(robot.order_pickup_nodes):
            next_node = robot.order_pickup_nodes[robot.order_pickup_index]
            print(f"[ORDER] {robot_id} 다음 Pickup 이동: " f"Node {next_node}")
            ros_gateway.navigate_to_node(robot_id=robot_id, node_id=next_node)

            return

        # Pickup을 전부 완료했으면 작업대로 이동
        workstation_node = robot.order_workstation_node

        if workstation_node is None:
            raise ValueError("작업대 Node가 지정되어 있지 않습니다.")

        print(f"[ORDER] {robot_id} Pickup 완료 → " f"작업대 Node {workstation_node} 이동")
        ros_gateway.navigate_to_node(robot_id=robot_id, node_id=workstation_node)

    def on_mqtt_result(self, omx, data) -> None:
        job_id = data.get("job_id")
        success = data.get("success", False)

        print(
            f"[ORDER] MQTT Result: " f"omx={omx.omx_id}, " f"job_id={job_id}, " f"success={success}"
        )

        # 해당 주문을 수행 중인 Robot 찾기
        target_robot = None

        for robot in fleet_manager.get_all_robots():
            if robot.order_id == job_id:
                target_robot = robot
                break

        if target_robot is None:
            print(f"[ORDER] MQTT Result에 해당하는 " f"Robot을 찾을 수 없습니다: {job_id}")
            return

        # OMX 작업 실패
        if not success:
            target_robot.set_state(RobotState.PAUSED)
            return

        # 작업대 OMX 작업까지 완료
        if target_robot.current_node == target_robot.order_workstation_node:
            print(f"[ORDER] 작업대 작업 완료: " f"{target_robot.robot_id}")

            # 아직 주문정보는 지우지 않음
            # 이후 복귀 로직 연결 예정
            return

        # Pickup OMX 작업 완료
        # 다음 Pickup 또는 작업대로 이동
        self.move_to_next_destination(target_robot.robot_id)


order_manager = OrderManager()
mqtt_manager.set_result_callback(order_manager.on_mqtt_result)
