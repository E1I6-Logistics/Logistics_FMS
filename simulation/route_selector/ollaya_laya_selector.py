"""Ollaya의 로컬 Laya 모델을 이용한 경로 후보 선택기."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from typing import Any

from .base import RouteSelector

Transport = Callable[[str, dict[str, Any], dict[str, str], float], dict[str, Any]]


class OllayaLayaSelector(RouteSelector):
    """Ollaya `/api/decide`에 후보 선택 질문을 전달한다."""

    name = "ollaya_laya"

    def __init__(
        self,
        model: str | None = None,
        host: str | None = None,
        timeout_seconds: float | None = None,
        api_key: str | None = None,
        transport: Transport | None = None,
    ) -> None:
        self.model = model or os.getenv("OLLAYA_MODEL", "laya")
        self.host = (host or os.getenv("OLLAYA_HOST", "http://127.0.0.1:11435")).rstrip("/")
        self.timeout_seconds = float(
            timeout_seconds
            if timeout_seconds is not None
            else os.getenv("OLLAYA_TIMEOUT_SECONDS", "10")
        )
        self.api_key = api_key if api_key is not None else os.getenv("OLLAYA_API_KEY")
        self._transport = transport or self._http_post
        self.last_inference: dict[str, Any] | None = None

    def select_route(
        self,
        state: str | dict[str, Any],
        candidates: Mapping[str, str],
    ) -> dict[str, Any]:
        if len(candidates) < 2:
            raise ValueError("경로 후보는 두 개 이상이어야 합니다.")
        if any(not key or not description for key, description in candidates.items()):
            raise ValueError("모든 후보에는 비어 있지 않은 ID와 설명이 필요합니다.")

        payload = {
            "model": self.model,
            "state": state,
            "questions": {
                "route": {
                    "type": "choice",
                    "instructions": (
                        "Select the valid route with the smallest total distance. "
                        "Return the candidate ID only through the choice answer."
                    ),
                    "criteria": dict(candidates),
                }
            },
        }
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        response = self._transport(
            f"{self.host}/api/decide",
            payload,
            headers,
            self.timeout_seconds,
        )
        self.last_inference = {"request": payload, "response": response}

        try:
            answer = response["answers"]["route"]
            choice = str(answer["choice"])
        except (KeyError, TypeError) as error:
            raise RuntimeError("Ollaya 응답에 answers.route.choice가 없습니다.") from error
        if choice not in candidates:
            raise RuntimeError(f"Ollaya가 알 수 없는 후보를 선택했습니다: {choice}")

        return {
            "choice": choice,
            "confidence": float(answer.get("confidence", 0.0)),
            "probabilities": dict(answer.get("probabilities", {})),
            "model": response.get("model", self.model),
            "routing": response.get("routing"),
            "total_duration_seconds": self._nanoseconds_to_seconds(
                response.get("total_duration")
            ),
            "load_duration_seconds": self._nanoseconds_to_seconds(
                response.get("load_duration")
            ),
            "eval_duration_seconds": self._nanoseconds_to_seconds(
                response.get("eval_duration")
            ),
            "raw": response,
        }

    @staticmethod
    def _nanoseconds_to_seconds(value: Any) -> float | None:
        if value is None:
            return None
        return float(value) / 1_000_000_000

    @staticmethod
    def _http_post(
        url: str,
        payload: dict[str, Any],
        headers: dict[str, str],
        timeout_seconds: float,
    ) -> dict[str, Any]:
        request = urllib.request.Request(
            url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            body = error.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Ollaya HTTP {error.code}: {body}") from error
        except urllib.error.URLError as error:
            raise RuntimeError(f"Ollaya 서버에 연결할 수 없습니다: {url}") from error
