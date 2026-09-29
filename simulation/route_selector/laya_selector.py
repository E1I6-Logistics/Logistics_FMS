"""Hugging Face Laya checkpoint를 CUDA로 직접 실행하는 경로 후보 선택기."""

from __future__ import annotations

import gc
import os
import threading
import time
from collections.abc import Callable, Mapping
from typing import Any

from .registry import RouteSelector

AgentLoader = Callable[..., Any]


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


class LayaSelector(RouteSelector):
    """단일 multilingual checkpoint로 choice, score, noul 질문을 처리한다.

    모델은 첫 요청 때 한 번만 불러온다. Jetson의 제한된 통합 메모리를 위해
    Laya Router나 복수 checkpoint를 사용하지 않으며, 모든 추론을 lock으로
    직렬화해 동시에 여러 CUDA forward가 메모리를 점유하지 않게 한다.
    """

    name = "laya"
    ROUTE_INSTRUCTIONS = (
        "Select the valid route with the smallest total distance. "
        "Return the candidate ID only through the choice answer."
    )

    def __init__(
        self,
        model: str | None = None,
        device: str | None = None,
        max_length: int | None = None,
        require_cuda: bool | None = None,
        hf_token: str | None = None,
        loader: AgentLoader | None = None,
    ) -> None:
        self.model = model or os.getenv(
            "LAYA_HF_MODEL", "convaiinnovations/laya-multilingual"
        )
        self.device = device or os.getenv("LAYA_DEVICE", "cuda:0")
        self.max_length = int(
            max_length
            if max_length is not None
            else os.getenv("LAYA_MAX_LENGTH", "1024")
        )
        if not 1 <= self.max_length <= 8192:
            raise ValueError("LAYA_MAX_LENGTH는 1 이상 8192 이하여야 합니다.")
        self.require_cuda = (
            require_cuda
            if require_cuda is not None
            else _environment_flag("LAYA_REQUIRE_CUDA", True)
        )
        self.hf_token = hf_token if hf_token is not None else os.getenv("HF_TOKEN")
        self._loader = loader or self._load_laya_agent
        self._agent: Any | None = None
        self._lock = threading.Lock()
        self.last_inference: dict[str, Any] | None = None
        self.last_load_duration_seconds: float | None = None

    @staticmethod
    def _load_laya_agent(**kwargs: Any) -> Any:
        # TensorFlow 탐색은 Jetson에서 불필요한 메모리 사용이나 import 교착을
        # 만들 수 있으므로 Laya/PyTorch를 import하기 전에 비활성화한다.
        os.environ.setdefault("USE_TF", "0")
        try:
            import laya
        except ImportError as error:
            raise RuntimeError(
                "Hugging Face Laya 실행 패키지가 없습니다. "
                "JetPack용 CUDA PyTorch를 먼저 설치한 뒤 "
                "'python -m pip install -r "
                "simulation/requirements-laya-jetson.txt'를 실행하세요."
            ) from error
        return laya.load(**kwargs)

    def _ensure_agent(self) -> tuple[Any, float]:
        if self._agent is not None:
            return self._agent, 0.0
        started = time.perf_counter()
        agent = self._loader(
            model_id_or_path=self.model,
            device=self.device,
            token=self.hf_token,
        )
        load_seconds = time.perf_counter() - started
        actual_device = str(getattr(agent, "device", "unknown"))
        if self.require_cuda and not actual_device.startswith("cuda"):
            self._close_agent(agent)
            raise RuntimeError(
                "Laya가 CUDA에 올라가지 않았습니다: "
                f"requested={self.device}, actual={actual_device}. "
                "JetPack용 CUDA PyTorch 설치와 "
                "torch.cuda.is_available()을 확인하세요."
            )
        self._agent = agent
        self.last_load_duration_seconds = load_seconds
        return agent, load_seconds

    def decide(
        self,
        state: str | dict[str, Any] | list[Any],
        questions: Mapping[str, dict[str, Any]],
    ) -> dict[str, Any]:
        """질문 묶음을 Hugging Face Laya의 단일 forward로 처리한다."""
        if not questions:
            raise ValueError("질문은 한 개 이상이어야 합니다.")
        request = {"state": state, "questions": dict(questions)}
        with self._lock:
            total_started = time.perf_counter()
            agent, load_seconds = self._ensure_agent()
            fallback_before = int(getattr(agent, "cpu_fallback_count", 0))
            eval_started = time.perf_counter()
            response = agent.predict(
                state,
                dict(questions),
                max_len=self.max_length,
            )
            eval_seconds = time.perf_counter() - eval_started
            total_seconds = time.perf_counter() - total_started
            fallback_after = int(getattr(agent, "cpu_fallback_count", 0))
            actual_device = str(getattr(agent, "device", "unknown"))
            precision = str(getattr(agent, "dtype", "unknown")).removeprefix(
                "torch."
            )
            if self.require_cuda and fallback_after > fallback_before:
                raise RuntimeError(
                    "CUDA 메모리 부족으로 Laya가 이번 요청을 CPU에서 처리했습니다. "
                    "입력 길이·질문 수를 줄이거나 다른 프로세스의 메모리를 확보하세요."
                )

        if not isinstance(response, dict):
            raise RuntimeError("Hugging Face Laya 응답이 dict 형식이 아닙니다.")
        answers = response.get("answers")
        if not isinstance(answers, dict):
            raise RuntimeError("Hugging Face Laya 응답에 answers 객체가 없습니다.")
        runtime = {
            "device": actual_device,
            "precision": precision,
            "max_length": self.max_length,
            "cpu_fallback_count": fallback_after,
        }
        self.last_inference = {
            "request": request,
            "response": response,
            "runtime": runtime,
            "load_duration_seconds": load_seconds,
            "eval_duration_seconds": eval_seconds,
            "total_duration_seconds": total_seconds,
        }
        return {
            "answers": answers,
            "model": response.get("model", self.model),
            "routing": response.get("routing"),
            "usage": response.get("usage"),
            "state_truncated": response.get("state_truncated"),
            "total_duration_seconds": total_seconds,
            "load_duration_seconds": load_seconds,
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
            raise RuntimeError(f"Laya가 알 수 없는 후보를 선택했습니다: {choice}")
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
        """모델과 CUDA cache를 해제해 다른 Jetson 프로세스에 메모리를 돌려준다."""
        with self._lock:
            if self._agent is None:
                return
            self._close_agent(self._agent)
            self._agent = None
            gc.collect()
            try:
                import torch

                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
            except ImportError:
                pass

    @staticmethod
    def _close_agent(agent: Any) -> None:
        exit_method = getattr(agent, "__exit__", None)
        if callable(exit_method):
            exit_method(None, None, None)

    @staticmethod
    def _answer(
        common: dict[str, Any], question_id: str, expected_type: str
    ) -> dict[str, Any]:
        try:
            answer = common["answers"][question_id]
        except (KeyError, TypeError) as error:
            raise RuntimeError(
                f"Laya 응답에 answers.{question_id}가 없습니다."
            ) from error
        if answer.get("type") not in (None, expected_type):
            raise RuntimeError(
                f"Laya 응답 타입 불일치: {answer.get('type')} != {expected_type}"
            )
        return answer

    @staticmethod
    def _metadata(common: dict[str, Any]) -> dict[str, Any]:
        return {key: value for key, value in common.items() if key != "answers"}
