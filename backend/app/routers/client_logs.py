from __future__ import annotations

import logging

from fastapi import APIRouter, Response, status

from ..schemas.client_log import ClientLog


router = APIRouter(prefix="/api/client-logs", tags=["client-logs"])
logger = logging.getLogger("fms.frontend")


@router.post("", status_code=status.HTTP_204_NO_CONTENT)
async def receive_client_log(payload: ClientLog) -> Response:
    log_method = logger.error if payload.level == "error" else logger.warning
    safe_details = {
        key: value.replace("\n", " ") if isinstance(value, str) else value
        for key, value in payload.details.items()
    }
    log_method(
        "event=%s client_time=%s url=%s message=%s details=%s",
        payload.event,
        payload.client_time or "unknown",
        payload.url or "unknown",
        payload.message.replace("\n", " "),
        safe_details,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
