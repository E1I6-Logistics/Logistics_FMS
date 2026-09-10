from dataclasses import dataclass, asdict
from typing import Any, Dict
import json


@dataclass
class RobotTelemetry:
    robot_id: str
    x: float
    y: float
    yaw: float
    battery: float
    status: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(
            self.to_dict(),
            ensure_ascii=False
        )

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RobotTelemetry":
        return cls(
            robot_id=str(data.get("robot_id", "")),
            x=float(data.get("x", 0.0)),
            y=float(data.get("y", 0.0)),
            yaw=float(data.get("yaw", 0.0)),
            battery=float(data.get("battery", 100.0)),
            status=str(data.get("status", "UNKNOWN")),
        )

    @classmethod
    def from_json(cls, raw: str) -> "RobotTelemetry":
        return cls.from_dict(json.loads(raw))


def validate_telemetry(data: Dict[str, Any]) -> bool:
    required = [
        "robot_id",
        "x",
        "y",
        "yaw",
        "battery",
        "status",
    ]

    return all(key in data for key in required)