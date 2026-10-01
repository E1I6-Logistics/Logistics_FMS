from types import SimpleNamespace

import pytest

from backend.app.models.robot import RobotState
from backend.app.services.fleet_manager import fleet_manager
from backend.app.services.order_service import order_service


@pytest.fixture
def robot():
    fleet_manager._robots.clear()
    order_service._omx_jobs.clear()
    result = fleet_manager.register_robot("robot1")
    result.set_state(RobotState.IDLE)
    yield result
    fleet_manager._robots.clear()
    order_service._omx_jobs.clear()


def test_order_rejects_more_than_five_items(robot):
    with pytest.raises(ValueError, match="5개 이하"):
        order_service.create_order(
            robot_id="robot1",
            items={"A": 3, "B": 3, "C": 0, "D": 0},
            workstation_node="3",
        )


def test_multi_pickup_workstation_and_waiting_flow(robot, monkeypatch):
    mqtt_commands = []
    navigation_commands = []
    monkeypatch.setattr(
        "backend.app.services.order_service.mqtt_manager.send_command",
        lambda omx_id, job_id, items, **kwargs: mqtt_commands.append(
            (omx_id, job_id, items, kwargs)
        ),
    )
    def fake_alignment(robot_id, node_id, purpose):
        active_robot = fleet_manager.get_robot(robot_id)
        active_robot.order_phase = f"ALIGNING_{purpose}"
        active_robot.set_state(RobotState.ALIGNING)

    monkeypatch.setattr(order_service, "_start_alignment", fake_alignment)
    monkeypatch.setattr(
        order_service,
        "_navigate",
        lambda robot_id, node_id: navigation_commands.append((robot_id, node_id)),
    )

    order = order_service.create_order(
        robot_id="robot1",
        items={"A": 1, "B": 0, "C": 2, "D": 0},
        workstation_node="3",
    )

    assert order["pickup_nodes"] == ["5", "6"]

    order_service.handle_arrival("robot1", "5")
    order_service.handle_alignment_result(
        "robot1", "5", True, {"result_code": 0}
    )
    first_job = mqtt_commands[0][1]
    assert mqtt_commands[0][0] == "omx1"
    assert mqtt_commands[0][2] == {"A": 1}
    assert mqtt_commands[0][3]["operation"] == "LOAD"

    order_service.handle_omx_progress(
        SimpleNamespace(robot_id="omx1"),
        {"job_id": first_job, "current": 1, "total": 1},
    )
    assert robot.loaded_count == 1

    order_service.handle_omx_result(
        SimpleNamespace(robot_id="omx1"),
        {"job_id": first_job, "success": True},
    )
    assert navigation_commands[-1] == ("robot1", "6")

    order_service.handle_arrival("robot1", "6")
    order_service.handle_alignment_result(
        "robot1", "6", True, {"result_code": 0}
    )
    second_job = mqtt_commands[1][1]
    assert mqtt_commands[1][0] == "omx2"
    assert mqtt_commands[1][2] == {"C": 2}

    order_service.handle_omx_result(
        SimpleNamespace(robot_id="omx2"),
        {"job_id": second_job, "success": True},
    )
    assert navigation_commands[-1] == ("robot1", "3")

    order_service.handle_arrival("robot1", "3")
    order_service.handle_alignment_result(
        "robot1", "3", True, {"result_code": 0}
    )
    unload_job = mqtt_commands[2][1]
    assert mqtt_commands[2][0] == "omx3"
    assert mqtt_commands[2][3]["operation"] == "UNLOAD"
    assert mqtt_commands[2][3]["total_count"] == 3

    order_service.handle_omx_progress(
        SimpleNamespace(robot_id="omx3"),
        {"job_id": unload_job, "current": 1, "total": 3},
    )
    assert robot.loaded_count == 2
    order_service.handle_omx_result(
        SimpleNamespace(robot_id="omx3"),
        {"job_id": unload_job, "success": True},
    )
    assert navigation_commands[-1] == ("robot1", "0")

    order_service.handle_arrival("robot1", "0")
    assert robot.order_status == "COMPLETED"
    assert robot.order_phase == "DONE"
    assert robot.state == RobotState.IDLE
