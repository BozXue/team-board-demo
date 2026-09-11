"""AI Copilot endpoints: diagnose, plan, apply, ask."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.schemas import CopilotApplyRequest, CopilotAskRequest, CopilotPlanRequest
from app.services.copilot import service as copilot_service

router = APIRouter(prefix="/projects/{project_id}/copilot", tags=["copilot"])


@router.get("/diagnose")
def diagnose(project_id: str, imageId: str | None = None, sample: int = 4,
             db: Session = Depends(get_db)) -> dict:
    return copilot_service.diagnose_project(db, project_id, imageId, sample)


@router.post("/plan")
def plan(project_id: str, payload: CopilotPlanRequest, db: Session = Depends(get_db)) -> dict:
    result = copilot_service.plan_pipeline(
        db, project_id, payload.text, payload.imageId, payload.useLlm
    )
    db.commit()
    return result


@router.post("/apply")
def apply_plan(project_id: str, payload: CopilotApplyRequest, db: Session = Depends(get_db)) -> dict:
    result = copilot_service.apply_plan(db, project_id, payload.graph, payload.taskType)
    db.commit()
    return result


@router.post("/ask")
def ask(project_id: str, payload: CopilotAskRequest, db: Session = Depends(get_db)) -> dict:
    result = copilot_service.answer(
        db, project_id, payload.question, payload.nodeType, payload.params
    )
    db.commit()
    return result


@router.get("/history")
def history(project_id: str, limit: int = 40, db: Session = Depends(get_db)) -> dict:
    return {"messages": copilot_service.history(db, project_id, limit)}


@router.delete("/history")
def clear_history(project_id: str, db: Session = Depends(get_db)) -> dict:
    removed = copilot_service.clear_history(db, project_id)
    db.commit()
    return {"removed": removed}
