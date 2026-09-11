"""Dataset management: import, browse, split, delete."""

from __future__ import annotations

import random
from pathlib import Path

import numpy as np
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.errors import NotFoundError, ValidationError
from app.models import Annotation, ImageAsset, Project
from app.services import storage
from app.utils.imageio import SUPPORTED_EXTS, fit_within, load_image, save_jpeg


def _project(db: Session, project_id: str) -> Project:
    project = db.get(Project, project_id)
    if project is None:
        raise NotFoundError(f"项目不存在: {project_id}")
    return project


def import_bytes(
    db: Session,
    project_id: str,
    filename: str,
    data: bytes,
    source: str = "upload",
    split: str = "unassigned",
    meta: dict | None = None,
) -> ImageAsset:
    """Store one uploaded image and register it in the dataset."""
    _project(db, project_id)
    suffix = Path(filename).suffix.lower()
    if suffix not in SUPPORTED_EXTS:
        raise ValidationError(f"不支持的图像格式: {suffix or filename}（支持 {', '.join(sorted(SUPPORTED_EXTS))}）")

    root = storage.ensure_project_dirs(project_id)
    safe_name = storage.unique_name(root / "images", filename)
    target = root / "images" / safe_name
    target.write_bytes(data)

    try:
        image = load_image(target)
    except Exception as exc:  # noqa: BLE001
        target.unlink(missing_ok=True)
        raise ValidationError(f"图像无法解码: {filename} ({exc})") from exc

    asset = ImageAsset(
        project_id=project_id,
        filename=safe_name,
        rel_path=f"images/{safe_name}",
        width=int(image.shape[1]),
        height=int(image.shape[0]),
        channels=1 if image.ndim == 2 else int(image.shape[2]),
        size_bytes=len(data),
        image_format=suffix.lstrip("."),
        split=split,
        source=source,
        meta=meta or {},
    )
    db.add(asset)
    db.flush()
    _write_derivatives(project_id, asset, image)
    db.add(asset)
    return asset


def import_path(
    db: Session, project_id: str, path: Path, source: str = "upload", split: str = "unassigned"
) -> ImageAsset:
    return import_bytes(db, project_id, path.name, path.read_bytes(), source=source, split=split)


def import_folder(
    db: Session, project_id: str, folder: Path, recursive: bool = False, limit: int = 500
) -> list[ImageAsset]:
    if not folder.exists() or not folder.is_dir():
        raise ValidationError(f"目录不存在: {folder}")
    pattern = "**/*" if recursive else "*"
    files = sorted(
        p for p in folder.glob(pattern) if p.is_file() and p.suffix.lower() in SUPPORTED_EXTS
    )
    assets: list[ImageAsset] = []
    for path in files[:limit]:
        assets.append(import_path(db, project_id, path, source="folder"))
    return assets


def _write_derivatives(project_id: str, asset: ImageAsset, image: np.ndarray) -> None:
    """Thumbnail for the browser grid, preview for the Viewer."""
    root = storage.project_dir(project_id)
    thumb = fit_within(image, settings.thumbnail_side)
    save_jpeg(root / "thumbs" / f"{asset.id}.jpg", thumb, quality=80)
    asset.thumb_path = f"thumbs/{asset.id}.jpg"

    preview = fit_within(image, settings.max_preview_side)
    save_jpeg(root / "previews" / f"{asset.id}.jpg", preview, quality=90)
    asset.preview_path = f"previews/{asset.id}.jpg"


def list_images(
    db: Session,
    project_id: str,
    page: int = 1,
    page_size: int = 60,
    split: str | None = None,
    label: str | None = None,
    annotated: bool | None = None,
    search: str | None = None,
    source: str | None = None,
) -> tuple[list[ImageAsset], int]:
    _project(db, project_id)
    query = select(ImageAsset).where(ImageAsset.project_id == project_id)
    count_query = select(func.count(ImageAsset.id)).where(ImageAsset.project_id == project_id)

    if split and split != "all":
        query = query.where(ImageAsset.split == split)
        count_query = count_query.where(ImageAsset.split == split)
    if source and source != "all":
        query = query.where(ImageAsset.source == source)
        count_query = count_query.where(ImageAsset.source == source)
    if search:
        pattern = f"%{search}%"
        query = query.where(ImageAsset.filename.like(pattern))
        count_query = count_query.where(ImageAsset.filename.like(pattern))
    if label:
        query = query.join(Annotation).where(Annotation.label == label)
        count_query = count_query.join(Annotation).where(Annotation.label == label)
    elif annotated is True:
        query = query.join(Annotation)
        count_query = count_query.join(Annotation)
    elif annotated is False:
        annotated_ids = select(Annotation.image_id).where(Annotation.project_id == project_id)
        query = query.where(ImageAsset.id.not_in(annotated_ids))
        count_query = count_query.where(ImageAsset.id.not_in(annotated_ids))

    total = db.execute(count_query).scalar_one()
    page = max(1, page)
    rows = db.execute(
        query.order_by(ImageAsset.created_at, ImageAsset.filename)
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).scalars().all()
    return list(rows), int(total)


def get_image(db: Session, image_id: str) -> ImageAsset:
    asset = db.get(ImageAsset, image_id)
    if asset is None:
        raise NotFoundError(f"图像不存在: {image_id}")
    return asset


def delete_images(db: Session, project_id: str, image_ids: list[str]) -> int:
    assets = db.execute(
        select(ImageAsset).where(
            ImageAsset.project_id == project_id, ImageAsset.id.in_(image_ids)
        )
    ).scalars().all()
    root = storage.project_dir(project_id)
    for asset in assets:
        for rel in (asset.rel_path, asset.thumb_path, asset.preview_path):
            if rel:
                (root / rel).unlink(missing_ok=True)
        db.delete(asset)
    return len(assets)


def set_split(db: Session, project_id: str, image_ids: list[str], split: str) -> int:
    if split not in {"unassigned", "train", "val", "test"}:
        raise ValidationError(f"非法的数据集划分: {split}")
    assets = db.execute(
        select(ImageAsset).where(
            ImageAsset.project_id == project_id, ImageAsset.id.in_(image_ids)
        )
    ).scalars().all()
    for asset in assets:
        asset.split = split
    return len(assets)


def auto_split(
    db: Session, project_id: str, train: float = 0.7, val: float = 0.2, seed: int = 42
) -> dict:
    """Random Train/Val/Test split; the remainder goes to test."""
    if train + val > 1.0:
        raise ValidationError("train + val 不能大于 1")
    assets = db.execute(
        select(ImageAsset).where(ImageAsset.project_id == project_id)
    ).scalars().all()
    ids = [a.id for a in assets]
    random.Random(seed).shuffle(ids)
    n = len(ids)
    n_train = int(n * train)
    n_val = int(n * val)
    groups = {
        "train": ids[:n_train],
        "val": ids[n_train:n_train + n_val],
        "test": ids[n_train + n_val:],
    }
    lookup = {a.id: a for a in assets}
    for split, members in groups.items():
        for image_id in members:
            lookup[image_id].split = split
    return {split: len(members) for split, members in groups.items()}


def statistics(db: Session, project_id: str) -> dict:
    _project(db, project_id)
    rows = db.execute(
        select(ImageAsset.split, func.count(ImageAsset.id))
        .where(ImageAsset.project_id == project_id)
        .group_by(ImageAsset.split)
    ).all()
    by_split = {split: int(count) for split, count in rows}

    label_rows = db.execute(
        select(Annotation.label, func.count(Annotation.id))
        .where(Annotation.project_id == project_id)
        .group_by(Annotation.label)
    ).all()
    by_label = {(label or "未分类"): int(count) for label, count in label_rows}

    total = int(db.execute(
        select(func.count(ImageAsset.id)).where(ImageAsset.project_id == project_id)
    ).scalar_one())
    annotated = int(db.execute(
        select(func.count(Annotation.id)).where(Annotation.project_id == project_id)
    ).scalar_one())
    shapes = db.execute(
        select(Annotation.shapes).where(Annotation.project_id == project_id)
    ).scalars().all()
    shape_count = sum(len(s or []) for s in shapes)

    return {
        "total": total,
        "annotated": annotated,
        "unannotated": max(0, total - annotated),
        "shapeCount": shape_count,
        "bySplit": by_split,
        "byLabel": by_label,
        "diskBytes": storage.dir_size_bytes(storage.project_dir(project_id)),
    }


def image_source_path(asset: ImageAsset, prefer_preview: bool = True) -> Path:
    """Path used for pipeline execution.

    Large industrial frames are executed on the preview copy by default so the
    debug loop stays interactive; batch/runtime can ask for the original.
    """
    root = storage.project_dir(asset.project_id)
    if prefer_preview and asset.preview_path and (root / asset.preview_path).exists():
        return root / asset.preview_path
    return root / asset.rel_path
