"""Frontend WebSocket connection registry without external messaging systems."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import WebSocket


logger = logging.getLogger("fms.websocket")


class ConnectionManager:
    def __init__(self) -> None:
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info(
            "event=dashboard_ws_connected connection_id=%s active=%s",
            id(websocket),
            len(self.active_connections),
        )

    def disconnect(self, websocket: WebSocket) -> None:
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
            logger.info(
                "event=dashboard_ws_disconnected connection_id=%s active=%s",
                id(websocket),
                len(self.active_connections),
            )

    async def broadcast(self, message: dict[str, Any]) -> None:
        dead: list[WebSocket] = []
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception as exc:
                logger.warning(
                    "event=dashboard_ws_send_failed connection_id=%s error=%r",
                    id(connection),
                    exc,
                )
                dead.append(connection)
        for connection in dead:
            self.disconnect(connection)


manager = ConnectionManager()
