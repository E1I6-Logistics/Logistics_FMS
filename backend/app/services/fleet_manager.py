from __future__ import annotations

from ..models.robot import Robot


class FleetManager:
    def __init__(self):

        # FMS가 한 번이라도 발견한 로봇 객체 관리
        self._robots: dict[str, Robot] = {}

    def register_robot(self, robot_id: str) -> Robot:
        """
        로봇이 처음 발견되면 Robot 객체를 생성한다.
        이미 존재하는 로봇이면 기존 객체를 재사용한다.
        """

        robot = self._robots.get(robot_id)

        if robot is None:
            robot = Robot(robot_id)
            self._robots[robot_id] = robot

        robot.set_connected(True)

        return robot

    def disconnect_robot(self, robot_id: str) -> None:
        """
        연결이 끊겨도 Robot 객체는 삭제하지 않고
        OFFLINE 상태로 유지한다.
        """

        robot = self._robots.get(robot_id)

        if robot is None:
            return

        robot.set_connected(False)

    def get_robot(self, robot_id: str) -> Robot | None:
        """
        robot_id에 해당하는 Robot 객체를 반환한다.
        """

        return self._robots.get(robot_id)

    def get_all_robots(self) -> list[Robot]:
        """
        FMS가 관리하고 있는 모든 Robot 객체를 반환한다.
        """

        return list(self._robots.values())

    def is_registered(self, robot_id: str) -> bool:
        """
        Robot 객체가 FleetManager에 존재하는지 확인한다.
        """

        return robot_id in self._robots


fleet_manager = FleetManager()
