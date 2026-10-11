# 타입 힌트 지연 평가 기능 사용
from __future__ import annotations

# 여러 자료형 허용을 위한 Union 타입 사용
from typing import Literal, Union

# API 요청 및 응답 데이터 검증용 Pydantic 모델 사용
from pydantic import BaseModel, model_validator


# ============================================================
# 좌표 기반 이동
# ============================================================

# 좌표 기반 이동 요청 데이터 구조 생성
class GoalCoordinateRequest(BaseModel):

    # 이동 대상 Robot ID 사용
    robot_id: str

    # 목표 X 좌표 사용
    target_x: float

    # 목표 Y 좌표 사용
    target_y: float


# ============================================================
# Node 기반 이동
# ============================================================

# Route Graph Node 기반 이동 요청 데이터 구조 생성
class GoalNodeRequest(BaseModel):

    robot_id: str

    # 숫자 또는 문자열 형식 Node ID 사용
    node_id: Union[int, str]


    driving_mode: Literal["standard", "llm"] = "standard"
    selector: Literal["ollama", "laya", "kev"] | None = None
    model: str | None = None

    @model_validator(mode="after")
    def require_llm_model(self):
        # LLM 요청의 모델 누락을 기본 알고리즘 주행으로 처리하지 않는다.
        if self.driving_mode == "llm" and (not self.selector or not self.model or not self.model.strip()):
            raise ValueError("LLM 주행에는 selector와 model이 필요합니다.")
        return self


# 모델 경로 미리보기 요청
class LlmRoutePreviewRequest(BaseModel):
    robot_id: str
    node_id: Union[int, str]
    selector: Literal["ollama", "laya", "kev"]
    model: str


# ============================================================
# 정지
# ============================================================

# Robot 정지 요청 데이터 구조 생성
class StopRequest(BaseModel):

    robot_id: str
