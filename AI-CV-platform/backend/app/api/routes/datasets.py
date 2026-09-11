"""Dataset endpoints: import, browse, split, image assets."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, File, Query, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.errors import NotFoundError
from app.schemas import AutoSplitRequest, ImageIdsRequest, ImportFolderRequest, SplitRequest
from app.services import annotation_service, dataset_service, diagnostics, storage
from app.utils.imageio import fit_within, histogram, load_image

router = APIRouter(tags=["dataset"])


def _asset_dict(asset, annotation=None) -> dict:
    return {
        "id": asset.id,
        "projectId": asset.project_id,
        "filename": asset.filename,
        "width": asset.width,
        "height": asset.height,
        "channels": asset.channels,
        "sizeBytes": asset.size_bytes,
        "format": asset.image_format,
        "split": asset.split,
        "source": asset.source,
        "meta": asset.meta or {},
        "createdAt": asset.created_at,
        "thumbUrl": f"/api/images/{asset.id}/thumb",
        "previewUrl": f"/api/images/{asset.id}/preview",
        "rawUrl": f"/api/images/{asset.id}/raw",
        "annotation": annotation_service.to_dict(annotation or asset.annotation),
    }


@router.get("/projects/{project_id}/images")
def list_images(
    project_id: str,
    page: int = 1,
    pageSize: int = Query(default=60, ge=1, le=500),
    split: str | None = None,
    label: str | None = None,
    annotated: bool | None = None,
    search: str | None = None,
    source: str | None = None,
    db: Session = Depends(get_db),
) -> dict:
    assets, total = dataset_service.list_images(
        db, project_id, page=page, page_size=pageSize, split=split, label=label,
        annotated=annotated, search=search, source=source,
    )
    return {
        "images": [_asset_dict(asset) for asset in assets],
        "total": total,
        "page": page,
        "pageSize": pageSize,
    }


@router.post("/projects/{project_id}/images", status_code=201)
async def upload_images(
    project_id: str,
    files: list[UploadFile] = File(...),
    split: str = "unassigned",
    db: Session = Depends(get_db),
) -> dict:
    created: list[dict] = []
    failed: list[dict] = []
    for upload in files:
        data = await upload.read()
        try:
            asset = dataset_service.import_bytes(
                db, project_id, upload.filename or "image.png", data, split=split
            )
            created.append(_asset_dict(asset))
        except Exception as exc:  # noqa: BLE001 - report per-file, keep importing
            failed.append({"filename": upload.filename, "error": str(exc)})
    db.commit()
    return {"imported": len(created), "images": created, "failed": failed}


@router.post("/projects/{project_id}/images/import-folder", status_code=201)
def import_folder(
    project_id: str, payload: ImportFolderRequest, db: Session = Depends(get_db)
) -> dict:
    assets = dataset_service.import_folder(
        db, project_id, Path(payload.path).expanduser(), payload.recursive, payload.limit
    )
    db.commit()
    return {"imported": len(assets), "images": [_asset_dict(asset) for asset in assets]}


@router.post("/projects/{project_id}/images/delete")
def delete_images(project_id: str, payload: ImageIdsRequest, db: Session = Depends(get_db)) -> dict:
    deleted = dataset_service.delete_images(db, project_id, payload.imageIds)
    db.commit()
    return {"deleted": deleted}


@router.post("/projects/{project_id}/images/split")
def set_split(project_id: str, payload: SplitRequest, db: Session = Depends(get_db)) -> dict:
    updated = dataset_service.set_split(db, project_id, payload.imageIds, payload.split)
    db.commit()
    return {"updated": updated}


@router.post("/projects/{project_id}/images/auto-split")
def auto_split(project_id: str, payload: AutoSplitRequest, db: Session = Depends(get_db)) -> dict:
    result = dataset_service.auto_split(db, project_id, payload.train, payload.val, payload.seed)
    db.commit()
    return {"split": result}


@router.get("/projects/{project_id}/dataset/stats")
def dataset_stats(project_id: str, db: Session = Depends(get_db)) -> dict:
    return dataset_service.statistics(db, project_id)


@router.get("/images/{image_id}")
def get_image(image_id: str, db: Session = Depends(get_db)) -> dict:
    asset = dataset_service.get_image(db, image_id)
    return _asset_dict(asset)


def _file_response(path: Path, filename: str) -> FileResponse:
    if not path.exists():
        raise NotFoundError(f"文件不存在: {filename}")
    return FileResponse(path, filename=filename)


@router.get("/images/{image_id}/raw")
def image_raw(image_id: str, db: Session = Depends(get_db)) -> FileResponse:
    asset = dataset_service.get_image(db, image_id)
    return _file_response(storage.abs_path(asset.project_id, asset.rel_path), asset.filename)


@router.get("/images/{image_id}/preview")
def image_preview(image_id: str, db: Session = Depends(get_db)) -> FileResponse:
    asset = dataset_service.get_image(db, image_id)
    rel = asset.preview_path or asset.rel_path
    return _file_response(storage.abs_path(asset.project_id, rel), asset.filename)


@router.get("/images/{image_id}/thumb")
def image_thumb(image_id: str, db: Session = Depends(get_db)) -> FileResponse:
    asset = dataset_service.get_image(db, image_id)
    rel = asset.thumb_path or asset.preview_path or asset.rel_path
    return _file_response(storage.abs_path(asset.project_id, rel), asset.filename)


@router.get("/images/{image_id}/histogram")
def image_histogram(
    image_id: str, bins: int = Query(default=256, ge=8, le=256), db: Session = Depends(get_db)
) -> dict:
    asset = dataset_service.get_image(db, image_id)
    image = load_image(dataset_service.image_source_path(asset))
    return histogram(image, bins=bins)


@router.get("/images/{image_id}/pixels")
def image_pixels(
    image_id: str,
    x: int = Query(ge=0),
    y: int = Query(ge=0),
    size: int = Query(default=1, ge=1, le=64),
    db: Session = Depends(get_db),
) -> dict:
    """Pixel probe: value at (x, y) plus the mean of a small neighbourhood."""
    asset = dataset_service.get_image(db, image_id)
    image = load_image(storage.abs_path(asset.project_id, asset.rel_path))
    height, width = image.shape[:2]
    x = min(max(0, x), width - 1)
    y = min(max(0, y), height - 1)
    half = size // 2
    patch = image[max(0, y - half):y + half + 1, max(0, x - half):x + half + 1]
    pixel = image[y, x]
    if image.ndim == 2:
        value = {"gray": int(pixel)}
        mean = {"gray": round(float(patch.mean()), 2)}
    else:
        blue, green, red = (int(v) for v in pixel[:3])
        value = {"r": red, "g": green, "b": blue}
        mean = {
            "b": round(float(patch[..., 0].mean()), 2),
            "g": round(float(patch[..., 1].mean()), 2),
            "r": round(float(patch[..., 2].mean()), 2),
        }
    return {"x": x, "y": y, "size": size, "value": value, "neighborhoodMean": mean,
            "width": width, "height": height}


@router.get("/images/{image_id}/diagnose")
def image_diagnose(image_id: str, db: Session = Depends(get_db)) -> dict:
    asset = dataset_service.get_image(db, image_id)
    image = fit_within(load_image(dataset_service.image_source_path(asset)), 1024)
    result = diagnostics.analyze(image).to_dict()
    result["imageId"] = image_id
    result["filename"] = asset.filename
    return result
