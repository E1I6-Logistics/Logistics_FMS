"""Load ROS control when ROS dependencies are available."""
from __future__ import annotations

try:
    from .ros_gateway import ros_gateway
except ImportError as exc:
    class _InactiveRosGateway:
        active = False
        error = str(exc)

        @staticmethod
        def start() -> None:
            return None

        @staticmethod
        def stop() -> None:
            return None

        @staticmethod
        def status_snapshot() -> dict[str, object]:
            return {
                "active": False,
                "node": None,
                "robots": [],
                "error": _InactiveRosGateway.error,
            }

    ros_gateway = _InactiveRosGateway()
