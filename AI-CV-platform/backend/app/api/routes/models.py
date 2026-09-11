"""Model repository: list, train (LBP+SVM), import, delete, download."""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, Response, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.schemas import TrainRequest
from app.services import model_service
from app.services.deep_train import trainer_catalog

router = APIRouter(tags=["models"])


@router.get("/models")
def list_models(projectId: str | None = None, db: Session = Depends(get_db)) -> dict:
    return {"models": model_service.list_models(db, projectId)}


@router.get("/models/trainers")
def list_trainers() -> dict:
    return {"trainers": trainer_catalog()}


@router.get("/projects/{project_id}/models/samples")
def training_samples(project_id: str, splits: str | None = None, db: Session = Depends(get_db)) -> dict:
    """Preview what the trainer would use, before spending time on training."""
    parsed = [item.strip() for item in splits.replace("，", ",").split(",")] if splits else None
    parsed = [item for item in (parsed or []) if item] or None
    patches, labels, stats = model_service.collect_samples(db, project_id, parsed)
    distribution: dict[str, int] = {}
    for label in labels:
        distribution[label] = distribution.get(label, 0) + 1
    return {
        "sampleCount": len(patches),
        "classes": sorted(distribution),
        "distribution": distribution,
        "stats": stats,
        "trainable": len(patches) >= 4 and len(distribution) >= 2,
    }


@router.post("/projects/{project_id}/models/train", status_code=201)
def train_model(project_id: str, payload: TrainRequest, db: Session = Depends(get_db)) -> dict:
    model = model_service.train_classifier(
        db, project_id, name=payload.name, splits=payload.splits,
        kernel=payload.kernel, c_value=payload.c, arch=payload.arch,
        epochs=payload.epochs, imgsz=payload.imgsz, batch=payload.batch,
        yolo_base=payload.yoloBase,
    )
    db.commit()
    return model_service.to_dict(model)


@router.post("/models/import", status_code=201)
async def import_model(
    file: UploadFile = File(...),
    name: str = Form(""),
    task: str = Form("classification"),
    projectId: str | None = Form(None),
    db: Session = Depends(get_db),
) -> dict:
    data = await file.read()
    model = model_service.import_model(
        db, projectId, name, file.filename or "model.joblib", data, task=task
    )
    db.commit()
    return model_service.to_dict(model)


@router.delete("/models/{model_id}", status_code=204)
def delete_model(model_id: str, db: Session = Depends(get_db)) -> Response:
    model_service.delete_model(db, model_id)
    db.commit()
    return Response(status_code=204)


@router.get("/models/{model_id}/download")
def download_model(model_id: str, db: Session = Depends(get_db)) -> FileResponse:
    path = model_service.export_model_path(db, model_id)
    return FileResponse(path, filename=path.name)
