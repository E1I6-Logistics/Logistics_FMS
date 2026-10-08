from uuid import uuid4
from time import strftime

from .fleet_manager import fleet_manager
from .scenario_service import scenario_manager
from ..models.robot import RobotState
from ..schemas.robot import normalize_robot_id
from ..ros2.ros_gateway import ros_gateway, NODE_OMX_MAP, CHARGING_STATION_NODES
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

    @scenario_manager.protect_command
    def create_order(
        self,
        robot_id: str,
        items: dict[str, int],
        total_quantity: int,
        workstation_node: str,
    ) -> dict:
        with ros_gateway._navigation.lock:
            return self._create_order_locked(robot_id, items, total_quantity, workstation_node)

    def _create_order_locked(
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

        if robot.state == RobotState.EMERGENCY_STOP:
            raise ValueError(f"비상정지를 해제한 뒤 새 주문을 요청해야 합니다: {robot_id}")

        # 작업대는 Node 3 또는 Node 4만 허용
        workstation_node = str(workstation_node)

        if workstation_node not in ["3", "4"]:
            raise ValueError(f"지원하지 않는 작업대 Node입니다: {workstation_node}")

        # 주문 수량 검증
        if any(quantity < 0 for quantity in items.values()):
            raise ValueError("주문 품목 수량은 음수일 수 없습니다.")
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
        first_pickup_node = pickup_nodes[0]
        # 새 주문을 위해 기존 작업을 취소하기 전에 첫 이동 가능 여부부터 확인한다.
        ros_gateway._validate_navigation_request(robot_id, first_pickup_node)

        def start_order():
            # 이전 동작의 종료가 확인된 뒤에만 새 주문과 첫 이동을 실행한다.
            robot.assign_order(
                order_id=order_id,
                items=items,
                total_quantity=total_quantity,
                pickup_nodes=pickup_nodes,
                workstation_node=workstation_node,
            )
            try:
                ros_gateway.navigate_to_node(
                    robot_id=robot_id, node_id=first_pickup_node, _order_step=True)
            except (ValueError, RuntimeError):
                robot.clear_order()
                if robot.state == RobotState.TASK_ASSIGNED:
                    robot.set_state(RobotState.IDLE)
                raise

        if robot.state == RobotState.IDLE and robot.order_id is None:
            start_order()
        else:
            ros_gateway.cancel_current_work(robot_id, start_order)

        print(f"[{strftime('%H:%M:%S')}] [ORDER] new order robot={robot_id} "
              f"order_id={order_id} items={items} total={total_quantity} "
              f"pickup_nodes={pickup_nodes} workstation={workstation_node} "
              f"state={robot.state.value}", flush=True)

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
            print(f"[{strftime('%H:%M:%S')}] [ORDER] robot={robot_id} "
                  f"next pickup={next_node}", flush=True)
            ros_gateway.navigate_to_node(robot_id=robot_id, node_id=next_node, _order_step=True)

            return

        # Pickup을 전부 완료했으면 작업대로 이동
        workstation_node = robot.order_workstation_node

        if workstation_node is None:
            raise ValueError("작업대 Node가 지정되어 있지 않습니다.")

        print(f"[{strftime('%H:%M:%S')}] [ORDER] robot={robot_id} "
              f"pickup complete, workstation={workstation_node}", flush=True)
        ros_gateway.navigate_to_node(
            robot_id=robot_id, node_id=workstation_node, _order_step=True)

    def on_mqtt_result(self, omx, data) -> None:
        # MQTT thread의 늦은 결과가 정지/새 주문의 상태 변경과 교차하지 않게 한다.
        with ros_gateway._navigation.lock:
            self._handle_mqtt_result(omx, data)

    def _handle_mqtt_result(self, omx, data) -> None:
        job_id = data.get("job_id")
        success = data.get("success", False)

        print(f"[{strftime('%H:%M:%S')}] [ORDER RESULT] omx={omx.omx_id} "
              f"job_id={job_id} success={success}", flush=True)

        # 해당 주문을 수행 중인 Robot 찾기
        target_robot = None

        for robot in fleet_manager.get_all_robots():
            if robot.order_id == job_id:
                target_robot = robot
                break

        if target_robot is None:
            print(f"[{strftime('%H:%M:%S')}] [ORDER RESULT] "
                  f"matching robot not found: job_id={job_id}", flush=True)
            return

        # 이전 단계나 다른 OMX의 늦은 Result로 현재 주문을 진행시키지 않는다.
        if (target_robot.state != RobotState.WAITING
                or target_robot.current_node is None
                or omx.omx_id != NODE_OMX_MAP.get(target_robot.current_node)):
            print(f"[{strftime('%H:%M:%S')}] [ORDER RESULT] ignored stale result "
                  f"robot={target_robot.robot_id} omx={omx.omx_id} "
                  f"node={target_robot.current_node} state={target_robot.state.value} "
                  f"connected={target_robot.connected} "
                  f"expected_omx={NODE_OMX_MAP.get(target_robot.current_node)}", flush=True)
            return

        # OMX 작업 실패
        if not success:
            target_robot.set_state(RobotState.PAUSED)
            return

        # 작업대 OMX 작업까지 완료
        if target_robot.current_node == target_robot.order_workstation_node:
            print(f"[{strftime('%H:%M:%S')}] [ORDER] workstation work complete: "
                  f"robot={target_robot.robot_id}", flush=True)

            station_node = CHARGING_STATION_NODES.get(target_robot.robot_id)
            if station_node is None:
                target_robot.set_state(RobotState.PAUSED)
                print(f"[{strftime('%H:%M:%S')}] [ORDER ERROR] robot={target_robot.robot_id} "
                      "charging station not assigned", flush=True)
                return

            try:
                # 주문 완료 후에는 담당 스테이션 Node까지만 이동한다. PrecisionDock은 실행하지 않는다.
                ros_gateway._validate_navigation_request(target_robot.robot_id, station_node)
                target_robot.clear_order()
                ros_gateway.navigate_to_node(
                    robot_id=target_robot.robot_id, node_id=station_node, _order_step=True)
                print(f"[{strftime('%H:%M:%S')}] [ORDER] robot={target_robot.robot_id} "
                      f"return to station node={station_node} without docking", flush=True)
            except (ValueError, RuntimeError) as exc:
                target_robot.set_state(RobotState.PAUSED)
                print(f"[{strftime('%H:%M:%S')}] [ORDER ERROR] robot={target_robot.robot_id} "
                      f"station_return_failed={exc!r}", flush=True)
            return

        # Pickup OMX 작업 완료
        # 다음 Pickup 또는 작업대로 이동
        try:
            self.move_to_next_destination(target_robot.robot_id)
        except (ValueError, RuntimeError) as exc:
            target_robot.set_state(RobotState.PAUSED)
            print(f"[{strftime('%H:%M:%S')}] [ORDER ERROR] robot={target_robot.robot_id} "
                  f"next_destination_failed={exc!r}", flush=True)


order_manager = OrderManager()
mqtt_manager.set_result_callback(order_manager.on_mqtt_result)
