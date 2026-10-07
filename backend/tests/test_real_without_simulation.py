"""시뮬레이션 모듈 import를 차단한 실제 API/서버 수명주기 검사.

프로젝트 Python 환경과 ROS setup을 사용한다. ROS/MQTT 시작은 대체하여
로봇이나 외부 장비로 명령을 보내지 않는다.
"""
import asyncio
import importlib.util
import sys
import unittest
from unittest.mock import AsyncMock, Mock, patch


@unittest.skipUnless(importlib.util.find_spec("fastapi") and importlib.util.find_spec("rclpy"),
                     "프로젝트 Python/ROS 환경 필요")
class RealWithoutSimulationTest(unittest.IsolatedAsyncioTestCase):
    async def test_real_startup_and_endpoints_do_not_import_simulation(self):
        with patch.dict(sys.modules, {"backend.app.services.mock_data": None}):
            from backend.app import main
            from backend.app.routers import robots, connections, commands, mode
            from backend.app.schemas.command import GoalNodeRequest, GoalCoordinateRequest
            from backend.app.services.mode_service import mode_manager
            from fastapi import HTTPException
            previous = mode_manager.mode
            mode_manager.set_mode("real")
            try:
                with patch.object(main.mqtt_manager, "start"), patch.object(main.mqtt_manager, "stop"), \
                     patch.object(main.rclpy, "init"), patch.object(main.rclpy, "ok", return_value=False), \
                     patch.object(main, "FmsRosNode", return_value=Mock()), \
                     patch.object(main, "SingleThreadedExecutor", return_value=Mock()):
                    async with main.lifespan(main.app):
                        await asyncio.sleep(max(.1, main.REAL_NAVIGATION_INTERVAL_S) + .02)
                        running = {task.get_name() for task in asyncio.all_tasks()}
                        self.assertIn("mock-simulation", running)
                        self.assertIn("real-navigation", running)
                        self.assertEqual(await robots.fetch_robots(), [])
                        with patch.object(connections.zenoh_connection_manager, "connections", return_value=[]):
                            self.assertEqual(await connections.get_connections(), {"devices": []})
                        with patch.object(commands.ros_gateway, "navigate_to_node", return_value={"success": True}) as goal:
                            response = await commands.send_node_goal(GoalNodeRequest(robot_id="robot1", node_id="0"))
                            self.assertEqual(response["mode"], "real")
                            goal.assert_called_once()
                        with patch.object(mode.manager, "broadcast", new_callable=AsyncMock):
                            response = await mode.set_mode(mode.ModeRequest(mode="real"))
                            self.assertEqual(response["mode"], "real")
                        with self.assertRaises(HTTPException) as raised:
                            await commands.send_coordinate_goal(GoalCoordinateRequest(
                                robot_id="robot1", target_x=0., target_y=0.))
                        self.assertEqual(raised.exception.status_code, 400)
                        self.assertIsNone(sys.modules["backend.app.services.mock_data"])
            finally:
                mode_manager.set_mode(previous)


if __name__ == "__main__":
    unittest.main()
