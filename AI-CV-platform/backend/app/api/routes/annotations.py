"""Online annotation endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.schemas import AnnotationImport, AnnotationSave, BulkLabelRequest, LabelCreate, SamPredictRequest
from app.services import annotation_service, sam_service

router = APIRouter(prefix="/projects/{project_id}", tags=["annotation"])


@router.get("/labels")
def list_labels(project_id: str, db: Session = Depends(get_db)) -> dict:
    labels = annotation_service.list_labels(db, project_id)
    return {
        "labels": [
            {"id": label.id, "name": label.name, "color": label.color, "order": label.order_index}
            for label in labels
        ]
    }


@router.post("/labels", status_code=201)
def create_label(project_id: str, payload: LabelCreate, db: Session = Depends(get_db)) -> dict:
    label = annotation_service.add_label(db, project_id, payload.name, payload.color)
    db.commit()
    return {"id": label.id, "name": label.name, "color": label.color}


@router.delete("/labels/{label_id}", status_code=204)
def delete_label(project_id: str, label_id: str, db: Session = Depends(get_db)) -> Response:
    annotation_service.delete_label(db, project_id, label_id)
    db.commit()
    return Response(status_code=204)


@router.get("/annotations/{image_id}")
def get_annotation(project_id: str, image_id: str, db: Session = Depends(get_db)) -> dict:
    return {"annotation": annotation_service.to_dict(annotation_service.get_annotation(db, image_id))}


@router.put("/annotations")
def save_annotation(project_id: str, payload: AnnotationSave, db: Session = Depends(get_db)) -> dict:
    annotation = annotation_service.save_annotation(
        db,
        project_id,
        payload.imageId,
        label=payload.label,
        shapes=payload.shapes,
        reviewed=payload.reviewed,
        note=payload.note,
    )
    db.commit()
    return {"annotation": annotation_service.to_dict(annotation)}


@router.post("/annotations/bulk-label")
def bulk_label(project_id: str, payload: BulkLabelRequest, db: Session = Depends(get_db)) -> dict:
    count = annotation_service.bulk_label(db, project_id, payload.imageIds, payload.label)
    db.commit()
    return {"updated": count}


@router.delete("/annotations/{image_id}", status_code=204)
def delete_annotation(project_id: str, image_id: str, db: Session = Depends(get_db)) -> Response:
    annotation_service.delete_annotation(db, image_id)
    db.commit()
    return Response(status_code=204)


@router.get("/annotations/export/{fmt}")
def export_annotations(project_id: str, fmt: str, db: Session = Depends(get_db)) -> dict:
    return annotation_service.export_dataset(db, project_id, fmt)


@router.get("/sam/status")
def sam_status(project_id: str, db: Session = Depends(get_db)) -> dict:
    return sam_service.available(db, project_id)


@router.post("/sam/predict")
def sam_predict(project_id: str, payload: SamPredictRequest, db: Session = Depends(get_db)) -> dict:
    return sam_service.predict(
        db,
        project_id,
        payload.imageId,
        points=payload.points,
        labels=payload.labels,
        box=payload.box,
    )


@router.post("/annotations/import")
def import_annotations(
    project_id: str, payload: AnnotationImport, db: Session = Depends(get_db)
) -> dict:
    result = annotation_service.import_annotations(db, project_id, payload.data, payload.format)
    db.commit()
    return result
