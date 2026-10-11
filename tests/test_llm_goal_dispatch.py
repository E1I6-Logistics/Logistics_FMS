"""Route dispatch must not move a robot on invalid or stale LLM output."""

import asyncio
import importlib.util
import sys
import types
import unittest
from unittest.mock import patch

from fastapi import HTTPException
from pydantic import ValidationError

from backend.app.schemas.command import GoalNodeRequest, StopRequest


# A test host without ROS 2 can still check the HTTP dispatch path.
if importlib.util.find_spec("action_msgs") is None:
    action = types.ModuleType("action_msgs")
    action.msg = types.ModuleType("action_msgs.msg")
    action.msg.GoalStatus = types.SimpleNamespace(STATUS_SUCCEEDED=4)
    sys.modules["action_msgs"] = action
    sys.modules["action_msgs.msg"] = action.msg

from backend.app.routers import commands


class GoalDispatchTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        commands._llm_requests.clear()
        patches = [
            patch.object(commands, "scenario_manager"),
            patch.object(commands, "mode_manager", types.SimpleNamespace(mode="simulation")),
            patch.object(commands, "_preview_start_node", return_value="0"),
            patch.object(commands, "load_route_graph", return_value={"map": 1}),
        ]
        for item in patches:
            item.start()
            self.addCleanup(item.stop)

    async def test_standard_request_keeps_algorithm_dispatch(self):
        with patch.object(commands, "navigate_to_node", return_value={"success": True}) as dispatch:
            await commands.send_node_goal(GoalNodeRequest(robot_id="robot1", node_id=3))
        dispatch.assert_called_once_with("robot1", 3, "simulation")

    async def test_validated_path_reaches_reservation(self):
        with patch("backend.app.services.llm_route_preview.preview_llm_route", return_value={"path": ["0", "2", "3"]}), patch.object(
            commands, "navigate_to_node", return_value={"success": True}
        ) as dispatch:
            result = await commands.send_node_goal(GoalNodeRequest(
                robot_id="robot1", node_id=3, driving_mode="llm", selector="laya", model="test"
            ))
        dispatch.assert_called_once_with("robot1", 3, "simulation", required_path=["0", "2", "3"])
        self.assertEqual(result["llm_preview"]["path"], ["0", "2", "3"])
        self.assertFalse(commands._llm_requests)

    async def test_http_request_drives_simulation_to_target(self):
        from backend.app.services.mock_data import MockFmsStore
        from backend.app.services.reservation import ReservationTable
        from tests.test_fixed_route_reservation import graph, robot
        from backend.app.services.pathfinding import DistanceAStar

        test_graph = graph()
        nodes = DistanceAStar(test_graph).nodes
        def get_node(node_id):
            x, y = nodes[str(node_id)]
            return {"id": str(node_id), "x": x, "y": y}

        with patch("backend.app.services.mock_data.get_node", side_effect=get_node), patch(
            "backend.app.services.mock_data.load_route_graph", return_value=test_graph
        ), patch("backend.app.services.mock_data.monotonic", return_value=1):
            store = MockFmsStore(ReservationTable())
            store._robots = {"robot1": robot()}
            store._traffic._robots = store._robots
            with patch("backend.app.services.mock_data.mock_fms", store), patch.object(
                commands, "load_route_graph", return_value=test_graph
            ), patch("backend.app.services.llm_route_preview.preview_llm_route", return_value={"path": ["0", "2", "3"]}):
                result = await commands.send_node_goal(GoalNodeRequest(
                    robot_id="robot1", node_id=3, driving_mode="llm", selector="laya", model="test"
                ))
                self.assertEqual(result["route"]["node_ids"], ["0", "2", "3"])
                for step in range(1, 300):
                    store.advance_simulation(.1, now=1+step*.1)
                    if store._robots["robot1"]["goal_node"] is None:
                        break
                self.assertEqual(store._robots["robot1"]["occupied_node"], "3")

    async def test_real_mode_dispatches_the_same_path(self):
        commands.mode_manager.mode = "real"
        with patch("backend.app.services.llm_route_preview.preview_llm_route", return_value={"path": ["0", "2", "3"]}), patch.object(
            commands, "navigate_to_node", return_value={"status": "PROCESSING"}
        ) as dispatch:
            await commands.send_node_goal(GoalNodeRequest(
                robot_id="robot1", node_id=3, driving_mode="llm", selector="kev", model="kev-08b"
            ))
        dispatch.assert_called_once_with("robot1", 3, "real", required_path=["0", "2", "3"])

    async def test_invalid_route_does_not_dispatch(self):
        with patch("backend.app.services.llm_route_preview.preview_llm_route", side_effect=ValueError("invalid_edge")), patch.object(
            commands, "navigate_to_node"
        ) as dispatch:
            with self.assertRaises(HTTPException) as error:
                await commands.send_node_goal(GoalNodeRequest(
                    robot_id="robot1", node_id=3, driving_mode="llm", selector="laya", model="test"
                ))
        self.assertEqual(error.exception.status_code, 400)
        dispatch.assert_not_called()

    async def test_stop_during_inference_prevents_late_departure(self):
        ready, finish = asyncio.Event(), asyncio.Event()

        async def infer(*args, **kwargs):
            ready.set()
            await finish.wait()
            return {"path": ["0", "2", "3"]}

        with patch.object(commands, "run_in_threadpool", side_effect=infer), patch.object(
            commands, "navigate_to_node"
        ) as dispatch, patch("backend.app.services.mock_data.mock_fms.stop_robot", return_value={}):
            task = asyncio.create_task(commands.send_node_goal(GoalNodeRequest(
                robot_id="robot1", node_id=3, driving_mode="llm", selector="laya", model="test"
            )))
            await ready.wait()
            await commands.stop_robot(StopRequest(robot_id="robot1"))
            finish.set()
            with self.assertRaises(HTTPException) as error:
                await task
        self.assertEqual(error.exception.status_code, 409)
        dispatch.assert_not_called()

    async def test_changed_graph_prevents_dispatch(self):
        with patch.object(commands, "load_route_graph", side_effect=[{"map": 1}, {"map": 2}]), patch(
            "backend.app.services.llm_route_preview.preview_llm_route", return_value={"path": ["0", "3"]}
        ), patch.object(commands, "navigate_to_node") as dispatch:
            with self.assertRaises(HTTPException) as error:
                await commands.send_node_goal(GoalNodeRequest(
                    robot_id="robot1", node_id=3, driving_mode="llm", selector="laya", model="test"
                ))
        self.assertEqual(error.exception.status_code, 409)
        dispatch.assert_not_called()

    def test_llm_request_requires_model(self):
        with self.assertRaises(ValidationError):
            GoalNodeRequest(robot_id="robot1", node_id=3, driving_mode="llm")


if __name__ == "__main__":
    unittest.main()
