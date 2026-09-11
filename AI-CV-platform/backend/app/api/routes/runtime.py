"""Runtime (User Mode) endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.schemas import RuntimeParamsRequest, RuntimeStartRequest
from app.services import runtime_service

router = APIRouter(prefix="/projects/{project_id}/runtime", tags=["runtime"])


@router.get("")
def status(project_id: str, history: int = 30, db: Session = Depends(get_db)) -> dict:
    result = runtime_service.status(db, project_id, history)
    db.commit()
    return result


@router.post("/start")
def start(project_id: str, payload: RuntimeStartRequest, db: Session = Depends(get_db)) -> dict:
    result = runtime_service.start(db, project_id, payload.source, payload.intervalMs, payload.deviceId)
    db.commit()
    return result


@router.post("/stop")
def stop(project_id: str, db: Session = Depends(get_db)) -> dict:
    result = runtime_service.stop(db, project_id)
    db.commit()
    return result


@router.post("/trigger")
def trigger(project_id: str, deviceId: str | None = None, db: Session = Depends(get_db)) -> dict:
    record = runtime_service.inspect_once(db, project_id, deviceId)
    db.commit()
    return {"record": record, "status": runtime_service.status(db, project_id)}


@router.post("/params")
def update_params(project_id: str, payload: RuntimeParamsRequest, db: Session = Depends(get_db)) -> dict:
    params = runtime_service.update_user_params(db, project_id, payload.values)
    db.commit()
    return {"userParams": params}


@router.post("/params/reset")
def reset_params(project_id: str, db: Session = Depends(get_db)) -> dict:
    params = runtime_service.reset_user_params(db, project_id)
    db.commit()
    return {"userParams": params}


@router.post("/reset")
def reset_statistics(project_id: str, db: Session = Depends(get_db)) -> dict:
    result = runtime_service.reset_statistics(db, project_id)
    db.commit()
    return result
