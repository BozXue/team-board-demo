"""Batch test endpoints: run, progress, results, metrics, error reflow."""

from __future__ import annotations

import csv
import io

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.schemas import BatchStartRequest, ReflowRequest
from app.services import batch_service
from app.services.copilot import service as copilot_service

router = APIRouter(tags=["batch"])


@router.post("/projects/{project_id}/batch", status_code=201)
def start_batch(project_id: str, payload: BatchStartRequest, db: Session = Depends(get_db)) -> dict:
    run = batch_service.start_run(
        db,
        project_id,
        split=payload.split,
        limit=payload.limit,
        ng_labels=payload.ngLabels,
        full_resolution=payload.fullResolution,
        save_previews=payload.savePreviews,
    )
    return batch_service.run_summary(db, run)


@router.get("/projects/{project_id}/batch")
def list_batches(project_id: str, limit: int = 20, db: Session = Depends(get_db)) -> dict:
    return {"runs": batch_service.list_runs(db, project_id, limit)}


@router.get("/batch/{run_id}")
def get_batch(run_id: str, db: Session = Depends(get_db)) -> dict:
    run = batch_service.get_run(db, run_id)
    summary = batch_service.run_summary(db, run)
    if run.status in {"finished", "failed", "cancelled"}:
        summary["metrics"] = {**summary["metrics"], **batch_service.compute_metrics(db, run_id)}
    return summary


@router.get("/batch/{run_id}/results")
def batch_results(
    run_id: str,
    verdict: str | None = None,
    outcome: str | None = None,
    page: int = 1,
    pageSize: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
) -> dict:
    results, total = batch_service.list_results(
        db, run_id, verdict=verdict, outcome=outcome, page=page, page_size=pageSize
    )
    return {"results": results, "total": total, "page": page, "pageSize": pageSize}


@router.post("/batch/{run_id}/cancel")
def cancel_batch(run_id: str) -> dict:
    return {"cancelled": batch_service.cancel_run(run_id)}


@router.post("/batch/{run_id}/reflow")
def reflow(run_id: str, payload: ReflowRequest, db: Session = Depends(get_db)) -> dict:
    result = batch_service.reflow_errors(db, run_id, payload.split, payload.resultIds)
    db.commit()
    return result


@router.get("/batch/{run_id}/advice")
def batch_advice(run_id: str, db: Session = Depends(get_db)) -> dict:
    run = batch_service.get_run(db, run_id)
    summary = batch_service.run_summary(db, run)
    results, _ = batch_service.list_results(db, run_id, page=1, page_size=500)
    advice = copilot_service.debug_advice(db, run.project_id, summary, results)
    db.commit()
    return advice


@router.get("/batch/{run_id}/export.csv")
def export_csv(run_id: str, db: Session = Depends(get_db)) -> StreamingResponse:
    run = batch_service.get_run(db, run_id)
    results, _ = batch_service.list_results(db, run_id, page=1, page_size=100000)
    measurement_keys = sorted({k for r in results for k in (r["measurements"] or {})})

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        ["image", "verdict", "gt_label", "outcome", "duration_ms", "error", *measurement_keys]
    )
    for result in results:
        writer.writerow(
            [
                result["imageName"], result["verdict"], result["gtLabel"] or "",
                result["outcome"] or "", result["durationMs"], result["error"] or "",
                *[(result["measurements"] or {}).get(key, "") for key in measurement_keys],
            ]
        )
    buffer.seek(0)
    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="batch_{run.id}.csv"'},
    )
