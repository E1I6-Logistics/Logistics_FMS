from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from ..services.scenario_service import load_config, scenario_manager

router = APIRouter(prefix="/api/scenarios", tags=["scenarios"])


class RunScenario(BaseModel):
    name: str


@router.get("")
async def list_scenarios():
    try:
        return [{"name": s["name"], "description": s["description"]}
                for s in load_config()["scenarios"]]
    except ValueError as exc:
        raise HTTPException(400, detail=str(exc)) from exc


@router.post("/run", status_code=202)
async def run_scenario(payload: RunScenario):
    try:
        return scenario_manager.start(payload.name)
    except ValueError as exc:
        raise HTTPException(409, detail=str(exc)) from exc


@router.get("/status")
async def scenario_status():
    return scenario_manager.status()
