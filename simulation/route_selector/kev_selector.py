"""공식 Kev runtime의 TypeSafe 호환 API를 사용하는 경로 후보 선택기."""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from typing import Any

from .registry import RouteSelector

PostTransport = Callable[[str, dict[str, Any], dict[str, str], float], dict[str, Any]]
GetTransport = Callable[[str, dict[str, str], float], dict[str, Any]]

# KEV_MODEL은 실험 결과에 남길 모델 이름이다. Kev 서버의 실제 API 별칭은
# 두 checkpoint 모두 kev-latest이므로 요청 시 아래 설정으로 변환한다.
_KEV_MODELS: dict[str, dict[str, str]] = {
    "kev-08b": {"api_model": "kev-latest", "run": "jaredpalmer/kev-0.8b"},
    "kev-4b": {"api_model": "kev-latest", "run": "jaredpalmer/kev-4b"},
}
_KEV_MODEL_ALIASES = {
    "kev-0.8b": "kev-08b",
}


def _environment_flag(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name}은 true 또는 false여야 합니다: {value!r}")


class KevSelector(RouteSelector):
    """Kev의 choice, score, noul API를 호출하고 CUDA 실행을 확인한다."""

    name = "kev"
    ROUTE_INSTRUCTIONS = (
        "Select the valid route with the smallest total distance. "
        "Return the candidate ID only through the choice answer."
    )

    def __init__(
        self,
        model: str | None = None,
        host: str | None = None,
        timeout_seconds: float | None = None,
        api_key: str | None = None,
        require_cuda: bool | None = None,
        transport: PostTransport | None = None,
        metadata_transport: GetTransport | None = None,
    ) -> None:
        requested_model = model or os.getenv("KEV_MODEL", "kev-08b")
        self.model = _KEV_MODEL_ALIASES.get(requested_model, requested_model)
        if self.model not in _KEV_MODELS:
            available = ", ".join(sorted(_KEV_MODELS))
            raise ValueError(
                f"알 수 없는 KEV_MODEL: {self.model!r} (사용 가능: {available})"
            )
        model_config = _KEV_MODELS[self.model]
        self.api_model = model_config["api_model"]
        self.expected_run = model_config["run"]
        self.host = (
            host or os.getenv("KEV_HOST", "http://127.0.0.1:8011")
        ).rstrip("/")
        self.timeout_seconds = float(
            timeout_seconds
            if timeout_seconds is not None
            else os.getenv("KEV_TIMEOUT_SECONDS", "60")
        )
        self.api_key = api_key if api_key is not None else os.getenv("KEV_API_KEY")
        self.require_cuda = (
            require_cuda
            if require_cuda is not None
            else _environment_flag("KEV_REQUIRE_CUDA", True)
        )
        self._transport = transport or self._http_post
        self._metadata_transport = metadata_transport or self._http_get
        self._runtime: dict[str, Any] | None = None
        self.last_inference: dict[str, Any] | None = None

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _ensure_runtime(self) -> dict[str, Any]:
        if self._runtime is not None:
            return self._runtime
        response = self._metadata_transport(
            f"{self.host}/v1/models", self._headers(), self.timeout_seconds
        )
        models = response.get("models")
        if not isinstance(models, list) or not models:
            raise RuntimeError("Kev /v1/models 응답에 모델 정보가 없습니다.")
        runtime = next(
            (item for item in models if item.get("name") == self.api_model),
            None,
        )
        if runtime is None:
            raise RuntimeError(
                "Kev /v1/models에 필요한 API 모델이 없습니다: "
                f"{self.api_model!r}"
            )
        actual_run = str(runtime.get("run", "")).split("@", 1)[0]
        if actual_run != self.expected_run:
            raise RuntimeError(
                f"KEV_MODEL={self.model}과 실행 중인 checkpoint가 다릅니다: "
                f"expected_run={self.expected_run}, actual_run={actual_run or 'unknown'}"
            )
        device = str(runtime.get("device", "unknown"))
        if self.require_cuda and not device.startswith("cuda"):
            raise RuntimeError(
                "Kev가 CUDA에서 실행되지 않습니다: "
                f"device={device}. Kev 서버와 JetPack CUDA PyTorch를 확인하세요."
            )
        self._runtime = dict(runtime)
        return self._runtime

    def decide(
        self,
        state: str | dict[str, Any] | list[Any],
        questions: Mapping[str, dict[str, Any]],
    ) -> dict[str, Any]:
        if not questions:
            raise ValueError("질문은 한 개 이상이어야 합니다.")
        runtime = self._ensure_runtime()
        payload = {
            "model": self.api_model,
            "state": state,
            "questions": dict(questions),
        }
        started = time.perf_counter()
        response = self._transport(
            f"{self.host}/v1/systemone",
            payload,
            self._headers(),
            self.timeout_seconds,
        )
        total_seconds = time.perf_counter() - started
        answers = response.get("answers")
        if not isinstance(answers, dict):
            raise RuntimeError("Kev 응답에 answers 객체가 없습니다.")
        latency_ms = response.get("latency_ms")
        eval_seconds = float(latency_ms) / 1000 if latency_ms is not None else None
        self.last_inference = {
            "requested_model": self.model,
            "request": payload,
            "response": response,
            "runtime": runtime,
            "total_duration_seconds": total_seconds,
            "eval_duration_seconds": eval_seconds,
        }
        return {
            "answers": answers,
            "model": self.model,
            "api_model": response.get("model", self.api_model),
            "routing": None,
            "usage": response.get("usage"),
            "state_truncated": None,
            "total_duration_seconds": total_seconds,
            "load_duration_seconds": 0.0,
            "eval_duration_seconds": eval_seconds,
            "runtime": runtime,
            "raw": response,
        }

    def select_choice(
        self,
        state: str | dict[str, Any],
        candidates: Mapping[str, str],
        instructions: str,
        *,
        question_id: str = "decision",
    ) -> dict[str, Any]:
        if len(candidates) < 2:
            raise ValueError("후보는 두 개 이상이어야 합니다.")
        if any(not key or not description for key, description in candidates.items()):
            raise ValueError("모든 후보에는 비어 있지 않은 ID와 설명이 필요합니다.")
        common = self.decide(
            state,
            {
                question_id: {
                    "type": "choice",
                    "instructions": instructions,
                    "criteria": dict(candidates),
                }
            },
        )
        answer = self._answer(common, question_id, "choice")
        choice = str(answer["choice"])
        if choice not in candidates:
            raise RuntimeError(f"Kev가 알 수 없는 후보를 선택했습니다: {choice}")
        return {
            **self._metadata(common),
            "choice": choice,
            "confidence": float(answer.get("confidence", 0.0)),
            "probabilities": dict(answer.get("probabilities", {})),
        }

    def evaluate_score(
        self,
        state: str | dict[str, Any],
        levels: list[str],
        instructions: str,
        *,
        question_id: str = "score",
    ) -> dict[str, Any]:
        if not 2 <= len(levels) <= 10:
            raise ValueError("score 단계는 2개 이상 10개 이하여야 합니다.")
        common = self.decide(
            state,
            {
                question_id: {
                    "type": "score",
                    "instructions": instructions,
                    "criteria": levels,
                }
            },
        )
        answer = self._answer(common, question_id, "score")
        return {
            **self._metadata(common),
            "score": float(answer["score"]),
            "confidence": float(answer.get("confidence", 0.0)),
            "legend": dict(answer.get("legend", {})),
            "probabilities": dict(answer.get("probabilities", {})),
        }

    def evaluate_noul(
        self,
        state: str | dict[str, Any],
        instructions: str,
        *,
        criteria: Mapping[str, str] | None = None,
        question_id: str = "noul",
    ) -> dict[str, Any]:
        question: dict[str, Any] = {
            "type": "noul",
            "instructions": instructions,
        }
        if criteria is not None:
            question["criteria"] = dict(criteria)
        common = self.decide(state, {question_id: question})
        answer = self._answer(common, question_id, "noul")
        return {**self._metadata(common), "noul": float(answer["noul"])}

    def select_route(
        self,
        state: str | dict[str, Any],
        candidates: Mapping[str, str],
    ) -> dict[str, Any]:
        return self.select_choice(
            state, candidates, self.ROUTE_INSTRUCTIONS, question_id="route"
        )

    def release(self) -> None:
        """Kev 모델은 별도 서버가 소유하므로 selector에서는 연결 정보만 비운다."""
        self._runtime = None

    @staticmethod
    def _answer(
        common: dict[str, Any], question_id: str, expected_type: str
    ) -> dict[str, Any]:
        try:
            answer = common["answers"][question_id]
        except (KeyError, TypeError) as error:
            raise RuntimeError(
                f"Kev 응답에 answers.{question_id}가 없습니다."
            ) from error
        if answer.get("type") not in (None, expected_type):
            raise RuntimeError(
                f"Kev 응답 타입 불일치: {answer.get('type')} != {expected_type}"
            )
        return answer

    @staticmethod
    def _metadata(common: dict[str, Any]) -> dict[str, Any]:
        return {key: value for key, value in common.items() if key != "answers"}

    @staticmethod
    def _http_get(
        url: str, headers: dict[str, str], timeout_seconds: float
    ) -> dict[str, Any]:
        return KevSelector._request(url, headers, timeout_seconds)

    @staticmethod
    def _http_post(
        url: str,
        payload: dict[str, Any],
        headers: dict[str, str],
        timeout_seconds: float,
    ) -> dict[str, Any]:
        return KevSelector._request(url, headers, timeout_seconds, payload)

    @staticmethod
    def _request(
        url: str,
        headers: dict[str, str],
        timeout_seconds: float,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        request = urllib.request.Request(
            url,
            data=(
                json.dumps(payload, ensure_ascii=False).encode("utf-8")
                if payload is not None
                else None
            ),
            headers=headers,
            method="POST" if payload is not None else "GET",
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            body = error.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Kev HTTP {error.code}: {body}") from error
        except urllib.error.URLError as error:
            raise RuntimeError(f"Kev 서버에 연결할 수 없습니다: {url}") from error
