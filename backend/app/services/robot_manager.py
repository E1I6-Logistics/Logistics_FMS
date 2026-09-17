# 타입 힌트 지연 평가 기능 사용
from __future__ import annotations

# Robot 상태 수신 시간 관리 기능 사용
from datetime import (
    datetime,
    timezone,
)

# 여러 ROS Callback 간 Robot 상태 동시 접근 보호 기능 사용
from threading import RLock
from typing import Optional

from ..config import (
    ROBOT_COUNT,
    ROBOT_OFFLINE_TIMEOUT_SEC,
)

from ..models.robot import (
    Robot,
)

from ..schemas.robot import (
    normalize_robot_id,
)


# 전체 Robot 객체 생성 및 상태 관리 기능
class RobotManager:

    # RobotManager 초기 상태 생성
    def __init__(
        self,
    ) -> None:

        # Robot 상태 동시 접근 보호용 재진입 Lock 생성
        self._lock = (
            RLock()
        )

        # robot_id 기준 Robot 객체 저장소 생성
        self.robots: dict[
            str,
            Robot,
        ] = {}

        # 설정된 Robot 수만큼 Robot 객체 생성
        for index in range(
            1,
            ROBOT_COUNT + 1,
        ):

            robot_id = (
                f"robot{index}"
            )

            self.robots[robot_id] = Robot(robot_id=robot_id)

    # ========================================================
    # 내부 공통 처리
    # ========================================================

    # 상태 수신 시 마지막 수신 시간 및 ONLINE 상태 갱신 기능
    def _touch(
        self,
        robot: Robot,
    ) -> None:

        robot.last_update = (
            datetime.now(
                timezone.utc
            )
        )

        robot.connection_state = ("ONLINE")

        if robot.status == "OFFLINE":
            robot.status = "IDLE"

    # ========================================================
    # Get
    # ========================================================

    # robot_id 기준 Robot 객체 조회 기능
    def get(
        self,
        robot_id: str,
    ) -> Robot:

        # 입력 robot_id를 내부 표준 형식으로 변환
        backend_id = (
            normalize_robot_id(
                robot_id
            )
        )

        with self._lock:

            robot = (
                self.robots.get(
                    backend_id
                )
            )

            if robot is None:

                raise KeyError(
                    "Unknown robot: "
                    f"{backend_id}"
                )

            return robot

    # ========================================================
    # AMCL
    # map 기준 위치
    # ========================================================

    # AMCL 기반 Map 좌표 위치 갱신 기능
    def update_map_pose(
        self,
        robot_id: str,
        x: float,
        y: float,
        yaw: float,
    ) -> None:

        with self._lock:

            robot = self.get(
                robot_id
            )

            robot.x = float(x)
            robot.y = float(y)
            robot.yaw = float(yaw)

            # 현재 위치 정보 출처를 AMCL로 설정
            robot.pose_source = (
                "AMCL"
            )

            robot.map_pose_received = (
                True
            )

            self._touch(
                robot
            )

    # ========================================================
    # Odom
    # ========================================================

    # Odom 위치 및 속도 상태 갱신 기능
    def update_odom(
        self,
        robot_id: str,
        x: float,
        y: float,
        yaw: float,
        linear_velocity: float,
        angular_velocity: float,
    ) -> None:

        with self._lock:

            robot = self.get(
                robot_id
            )

            robot.odom_x = (
                float(x)
            )

            robot.odom_y = (
                float(y)
            )

            robot.odom_yaw = (
                float(yaw)
            )

            robot.linear_velocity = (
                float(
                    linear_velocity
                )
            )

            robot.angular_velocity = (
                float(
                    angular_velocity
                )
            )

            # 아직 AMCL map pose를
            # 한 번도 못 받았다면
            # odom을 임시 위치로 사용
            # AMCL 위치 미수신 시 Odom 위치를 임시 위치로 사용
            if not robot.map_pose_received:

                robot.x = (
                    robot.odom_x
                )

                robot.y = (
                    robot.odom_y
                )

                robot.yaw = (
                    robot.odom_yaw
                )

                robot.pose_source = (
                    "ODOM"
                )

            self._touch(
                robot
            )

    # ========================================================
    # BatteryState
    # ========================================================

    # BatteryState 기반 배터리 상태 갱신 기능
    def update_battery(
        self,
        robot_id: str,
        percentage: Optional[float],
        voltage: Optional[float],
        current: Optional[float],
        status: str,
    ) -> None:

        with self._lock:

            robot = self.get(
                robot_id
            )

            if percentage is not None:

                robot.battery = (
                    float(percentage)
                )

            robot.battery_voltage = (
                voltage
            )

            robot.battery_current = (
                current
            )

            robot.battery_status = (
                status
            )

            self._touch(
                robot
            )

    # ========================================================
    # TurtleBot3 SensorState
    # ========================================================

    # TurtleBot3 SensorState 기반 센서 상태 갱신 기능
    def update_sensor_state(
        self,
        robot_id: str,
        *,
        bumper: int,
        cliff: float,
        sonar: float,
        illumination: float,
        led: int,
        button: int,
        torque: bool,
        left_encoder: int,
        right_encoder: int,
        battery: float,
    ) -> None:

        with self._lock:

            robot = self.get(
                robot_id
            )

            robot.bumper = int(
                bumper
            )

            robot.cliff = float(
                cliff
            )

            robot.sonar = float(
                sonar
            )

            robot.illumination = (
                float(
                    illumination
                )
            )

            robot.led = int(
                led
            )

            robot.button = int(
                button
            )

            robot.torque = bool(
                torque
            )

            robot.left_encoder = (
                int(
                    left_encoder
                )
            )

            robot.right_encoder = (
                int(
                    right_encoder
                )
            )

            robot.sensor_battery = (
                float(
                    battery
                )
            )

            self._touch(
                robot
            )

    # ========================================================
    # Navigation
    # ========================================================

    # Nav2 주행 상태 및 결과 정보 갱신 기능
    def update_navigation(
        self,
        robot_id: str,
        *,
        navigation_state: str,
        goal_reached: Optional[
            bool
        ] = None,
        distance_remaining: Optional[
            float
        ] = None,
        status: Optional[
            str
        ] = None,
        error_code: Optional[
            str
        ] = None,
        error_message: Optional[
            str
        ] = None,
    ) -> None:

        with self._lock:

            robot = self.get(
                robot_id
            )

            robot.navigation_state = (
                navigation_state
            )

            if goal_reached is not None:

                robot.goal_reached = (
                    goal_reached
                )

            if (
                distance_remaining
                is not None
            ):

                robot.distance_remaining = (
                    float(
                        distance_remaining
                    )
                )

            if status is not None:

                robot.status = status

            robot.error_code = (
                error_code
            )

            robot.error_message = (
                error_message
            )

            self._touch(
                robot
            )

    # ========================================================
    # Offline 판단
    # ========================================================

    # 마지막 상태 수신 시간 기준 Robot ONLINE/OFFLINE 판단 기능
    def update_connection_states(
        self,
    ) -> None:

        now = datetime.now(
            timezone.utc
        )

        with self._lock:

            for robot in (
                self.robots.values()
            ):

                if (
                    robot.last_update
                    is None
                ):

                    robot.connection_state = (
                        "OFFLINE"
                    )

                    continue

                # 마지막 상태 수신 후 경과 시간 계산
                elapsed = (
                    now
                    - robot.last_update
                ).total_seconds()

                if (
                    elapsed
                    > ROBOT_OFFLINE_TIMEOUT_SEC
                ):

                    robot.connection_state = (
                        "OFFLINE"
                    )

                    robot.status = (
                        "OFFLINE"
                    )

    # ========================================================
    # Snapshot
    # ========================================================

    # 특정 Robot 현재 상태 사전 생성 기능
    def snapshot(
        self,
        robot_id: str,
    ) -> dict:

        self.update_connection_states()

        with self._lock:

            return (
                self.get(
                    robot_id
                ).to_dict()
            )

    # 전체 Robot 현재 상태 목록 생성 기능
    def snapshots(
        self,
    ) -> list[dict]:

        self.update_connection_states()

        with self._lock:

            return [
                robot.to_dict()
                for robot
                in self.robots.values()
            ]


# 전체 애플리케이션에서 공유할 RobotManager 객체 생성
robot_manager = (
    RobotManager()
)