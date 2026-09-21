"""Load ROS control only when real robots are enabled."""
from __future__ import annotations

from ..config import ROBOT_MODE


if ROBOT_MODE == "real":
    from .ros_gateway import ros_gateway
else:
    class _InactiveRosGateway:
        active = False

        @staticmethod
        def status_snapshot() -> dict[str, object]:
            return {"active": False, "node": None, "robots": []}

    ros_gateway = _InactiveRosGateway()
