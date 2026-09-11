"""Model Monitoring endpoints: how deployed pipelines are performing."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.services import monitoring_service

router = APIRouter(prefix="/monitoring", tags=["monitoring"])


@router.get("/overview")
def overview(
    hours: int = Query(default=24, ge=1, le=720),
    db: Session = Depends(get_db),
) -> dict:
    return monitoring_service.overview(db, hours=hours)


@router.get("/records")
def records(
    hours: int = Query(default=24, ge=1, le=720),
    projectId: str | None = None,
    deviceId: str | None = None,
    modelId: str | None = None,
    verdict: str | None = None,
    lowConfidence: bool = False,
    page: int = 1,
    pageSize: int = Query(default=40, ge=1, le=200),
    db: Session = Depends(get_db),
) -> dict:
    return monitoring_service.records(
        db, hours=hours, project_id=projectId, device_id=deviceId, model_id=modelId,
        verdict=verdict, low_confidence=lowConfidence, page=page, page_size=pageSize,
    )
