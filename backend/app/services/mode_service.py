"""FMS robot operating mode shared by HTTP and WebSocket handlers."""
from __future__ import annotations

from threading import RLock
from typing import Literal

from ..config import ROBOT_MODE


RobotMode = Literal["real", "simulation"]


class RobotModeManager:
    def __init__(self, initial_mode: str) -> None:
        self._lock = RLock()
        self._mode: RobotMode = self._validate(initial_mode)

    @staticmethod
    def _validate(mode: str) -> RobotMode:
        normalized = str(mode).strip().lower()
        if normalized not in {"real", "simulation"}:
            raise ValueError("mode must be either 'real' or 'simulation'")
        return normalized  # type: ignore[return-value]

    @property
    def mode(self) -> RobotMode:
        with self._lock:
            return self._mode

    def set_mode(self, mode: str) -> RobotMode:
        normalized = self._validate(mode)
        with self._lock:
            self._mode = normalized
            return self._mode


mode_manager = RobotModeManager(ROBOT_MODE)
