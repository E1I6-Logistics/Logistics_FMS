"""개별 명령과 시나리오가 공유하는 기존 모드별 이동/정지 호출."""

def navigate_to_node(robot_id, node_id, mode):
    if mode == "simulation":
        from .mock_data import mock_fms
        result = mock_fms.navigate_to_node(robot_id, node_id)
    elif mode == "real":
        from ..ros2.ros_gateway import ros_gateway
        result = ros_gateway.navigate_to_node(robot_id, node_id)
    else:
        raise ValueError("지원하지 않는 운용 모드")
    return dict(result, mode=mode)


def stop_robot(robot_id, mode):
    if mode == "simulation":
        from .mock_data import mock_fms
        return mock_fms.stop_robot(robot_id)
    from ..ros2.ros_gateway import ros_gateway
    return ros_gateway.emergency_stop(robot_id)
