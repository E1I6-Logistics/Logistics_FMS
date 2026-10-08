from fastapi import APIRouter, HTTPException
from fastapi.concurrency import run_in_threadpool

from ..schemas.order import CreateOrderRequest
from ..services.order_manager import order_manager
from ..services.mode_service import mode_manager

router = APIRouter(prefix="/api/orders", tags=["orders"])


@router.post("")
async def create_order(payload: CreateOrderRequest):
    try:
        required_path = None
        if payload.driving_mode == "llm":
            if mode_manager.mode != "real":
                raise ValueError("주문 LLM 주행은 현재 실제 로봇에서만 지원합니다.")
            if payload.selector is None or payload.model is None:
                raise ValueError("주문에 사용할 경로 선택기와 모델을 선택하세요.")
            # Model inference may take seconds; keep the API event loop responsive.
            preview = await run_in_threadpool(
                order_manager.preview_first_leg,
                payload.robot_id,
                payload.items.model_dump(),
                payload.selector,
                payload.model,
            )
            required_path = preview["path"]
            if mode_manager.mode != "real":
                raise ValueError("모드가 변경되어 주문을 등록하지 않았습니다.")
        return order_manager.create_order(
            robot_id=payload.robot_id,
            items=payload.items.model_dump(),
            total_quantity=payload.total_quantity,
            workstation_node=payload.workstation_node,
            driving_mode=payload.driving_mode,
            selector=payload.selector,
            model=payload.model,
            first_required_path=required_path,
        )

    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"주문 LLM 경로 생성 실패: {exc}") from exc
