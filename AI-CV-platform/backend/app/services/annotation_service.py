"""Online annotation: classification labels, boxes, polygons, points.

Shapes are stored normalised (0-1) so annotations stay valid across the
original image, the preview copy and any resized pipeline input::

    {"id": "s1", "type": "bbox", "label": "NG", "points": [[x1,y1],[x2,y2]]}
    {"id": "s2", "type": "polygon", "label": "colony", "points": [[x,y], ...]}
    {"id": "s3", "type": "point", "label": "center", "points": [[x,y]]}
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import NotFoundError, ValidationError
from app.models import Annotation, ImageAsset, LabelClass, Project, new_id
from app.services import storage

SHAPE_TYPES = {"bbox", "polygon", "point"}


def _project(db: Session, project_id: str) -> Project:
    project = db.get(Project, project_id)
    if project is None:
        raise NotFoundError(f"项目不存在: {project_id}")
    return project


def list_labels(db: Session, project_id: str) -> list[LabelClass]:
    return list(
        db.execute(
            select(LabelClass)
            .where(LabelClass.project_id == project_id)
            .order_by(LabelClass.order_index)
        ).scalars().all()
    )


def add_label(db: Session, project_id: str, name: str, color: str | None = None) -> LabelClass:
    _project(db, project_id)
    name = (name or "").strip()
    if not name:
        raise ValidationError("类别名称不能为空")
    existing = db.execute(
        select(LabelClass).where(LabelClass.project_id == project_id, LabelClass.name == name)
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    count = len(list_labels(db, project_id))
    palette = ["#38bdf8", "#a78bfa", "#fbbf24", "#f472b6", "#4ade80", "#f87171", "#22d3ee"]
    label = LabelClass(
        project_id=project_id, name=name, color=color or palette[count % len(palette)],
        order_index=count,
    )
    db.add(label)
    return label


def delete_label(db: Session, project_id: str, label_id: str) -> None:
    label = db.get(LabelClass, label_id)
    if label is None or label.project_id != project_id:
        raise NotFoundError(f"类别不存在: {label_id}")
    db.delete(label)


def get_annotation(db: Session, image_id: str) -> Annotation | None:
    return db.execute(
        select(Annotation).where(Annotation.image_id == image_id)
    ).scalar_one_or_none()


def _validate_shapes(shapes: list[dict] | None) -> list[dict]:
    result: list[dict] = []
    for raw in shapes or []:
        shape_type = raw.get("type")
        if shape_type not in SHAPE_TYPES:
            raise ValidationError(f"不支持的标注类型: {shape_type}")
        points = raw.get("points") or []
        if shape_type == "bbox" and len(points) != 2:
            raise ValidationError("bbox 需要 2 个点（左上、右下）")
        if shape_type == "polygon" and len(points) < 3:
            raise ValidationError("polygon 至少需要 3 个点")
        if shape_type == "point" and len(points) != 1:
            raise ValidationError("point 需要 1 个点")
        cleaned = [[max(0.0, min(1.0, float(p[0]))), max(0.0, min(1.0, float(p[1])))] for p in points]
        result.append(
            {
                "id": raw.get("id") or new_id()[:8],
                "type": shape_type,
                "label": raw.get("label") or "",
                "points": cleaned,
            }
        )
    return result


def save_annotation(
    db: Session,
    project_id: str,
    image_id: str,
    label: str | None = None,
    shapes: list[dict] | None = None,
    reviewed: bool | None = None,
    note: str | None = None,
) -> Annotation:
    _project(db, project_id)
    asset = db.get(ImageAsset, image_id)
    if asset is None or asset.project_id != project_id:
        raise NotFoundError(f"图像不存在: {image_id}")

    annotation = get_annotation(db, image_id)
    if annotation is None:
        annotation = Annotation(project_id=project_id, image_id=image_id)
        db.add(annotation)

    if label is not None:
        annotation.label = label or None
        if label:
            add_label(db, project_id, label)
    if shapes is not None:
        annotation.shapes = _validate_shapes(shapes)
        for shape in annotation.shapes:
            if shape["label"]:
                add_label(db, project_id, shape["label"])
    if reviewed is not None:
        annotation.reviewed = reviewed
    if note is not None:
        annotation.note = note
    db.flush()
    return annotation


def bulk_label(db: Session, project_id: str, image_ids: list[str], label: str) -> int:
    add_label(db, project_id, label)
    for image_id in image_ids:
        save_annotation(db, project_id, image_id, label=label)
    return len(image_ids)


def delete_annotation(db: Session, image_id: str) -> None:
    annotation = get_annotation(db, image_id)
    if annotation is not None:
        db.delete(annotation)


def to_dict(annotation: Annotation | None) -> dict | None:
    if annotation is None:
        return None
    return {
        "imageId": annotation.image_id,
        "label": annotation.label,
        "shapes": annotation.shapes or [],
        "reviewed": annotation.reviewed,
        "note": annotation.note,
        "updatedAt": annotation.updated_at,
    }


# -- import / export -----------------------------------------------------
def export_dataset(db: Session, project_id: str, fmt: str = "coco") -> dict:
    """Export annotations as COCO or YOLO (returned inline and written to disk)."""
    project = _project(db, project_id)
    assets = db.execute(
        select(ImageAsset).where(ImageAsset.project_id == project_id)
    ).scalars().all()
    labels = [label.name for label in list_labels(db, project_id)]
    if fmt == "yolo":
        payload = _export_yolo(assets, labels)
    elif fmt == "coco":
        payload = _export_coco(project.name, assets, labels)
    elif fmt == "classification":
        payload = _export_classification(assets)
    else:
        raise ValidationError(f"不支持的导出格式: {fmt}")

    out_dir = storage.project_dir(project_id) / "annotations"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{fmt}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"format": fmt, "path": str(path), "labels": labels, "data": payload}


def _export_coco(project_name: str, assets: list[ImageAsset], labels: list[str]) -> dict:
    categories = [{"id": index + 1, "name": name} for index, name in enumerate(labels)]
    category_ids = {name: index + 1 for index, name in enumerate(labels)}
    images: list[dict] = []
    annotations: list[dict] = []
    annotation_id = 1
    for image_index, asset in enumerate(assets, start=1):
        images.append(
            {
                "id": image_index,
                "file_name": asset.filename,
                "width": asset.width,
                "height": asset.height,
            }
        )
        if asset.annotation is None:
            continue
        for shape in asset.annotation.shapes or []:
            points = [[p[0] * asset.width, p[1] * asset.height] for p in shape["points"]]
            if shape["type"] == "bbox":
                (x1, y1), (x2, y2) = points
                x, y = min(x1, x2), min(y1, y2)
                w, h = abs(x2 - x1), abs(y2 - y1)
                segmentation: list[list[float]] = []
            elif shape["type"] == "polygon":
                xs = [p[0] for p in points]
                ys = [p[1] for p in points]
                x, y = min(xs), min(ys)
                w, h = max(xs) - x, max(ys) - y
                segmentation = [[coord for point in points for coord in point]]
            else:
                continue
            annotations.append(
                {
                    "id": annotation_id,
                    "image_id": image_index,
                    "category_id": category_ids.get(shape["label"], 1),
                    "bbox": [round(x, 2), round(y, 2), round(w, 2), round(h, 2)],
                    "area": round(w * h, 2),
                    "iscrowd": 0,
                    "segmentation": segmentation,
                }
            )
            annotation_id += 1
    return {
        "info": {"description": project_name, "version": "1.0"},
        "images": images,
        "categories": categories,
        "annotations": annotations,
    }


def _export_yolo(assets: list[ImageAsset], labels: list[str]) -> dict:
    class_ids = {name: index for index, name in enumerate(labels)}
    files: dict[str, str] = {}
    for asset in assets:
        if asset.annotation is None:
            continue
        lines: list[str] = []
        for shape in asset.annotation.shapes or []:
            if shape["type"] != "bbox":
                continue
            (x1, y1), (x2, y2) = shape["points"]
            cx, cy = (x1 + x2) / 2.0, (y1 + y2) / 2.0
            w, h = abs(x2 - x1), abs(y2 - y1)
            class_id = class_ids.get(shape["label"], 0)
            lines.append(f"{class_id} {cx:.6f} {cy:.6f} {w:.6f} {h:.6f}")
        if lines:
            files[f"{asset.filename.rsplit('.', 1)[0]}.txt"] = "\n".join(lines)
    return {"names": labels, "labels": files}


def _export_classification(assets: list[ImageAsset]) -> dict:
    return {
        "items": [
            {"file": asset.filename, "label": asset.annotation.label, "split": asset.split}
            for asset in assets
            if asset.annotation is not None and asset.annotation.label
        ]
    }


def import_annotations(db: Session, project_id: str, payload: dict[str, Any], fmt: str) -> dict:
    """Import COCO / YOLO / classification annotations, matched by file name."""
    _project(db, project_id)
    assets = {
        asset.filename: asset
        for asset in db.execute(
            select(ImageAsset).where(ImageAsset.project_id == project_id)
        ).scalars().all()
    }
    stems = {name.rsplit(".", 1)[0]: asset for name, asset in assets.items()}
    imported = 0
    skipped = 0

    if fmt == "coco":
        categories = {c["id"]: c["name"] for c in payload.get("categories", [])}
        by_image: dict[int, list[dict]] = {}
        for annotation in payload.get("annotations", []):
            by_image.setdefault(annotation["image_id"], []).append(annotation)
        for image in payload.get("images", []):
            asset = assets.get(image.get("file_name")) or stems.get(
                str(image.get("file_name", "")).rsplit(".", 1)[0]
            )
            if asset is None:
                skipped += 1
                continue
            width = float(image.get("width") or asset.width or 1)
            height = float(image.get("height") or asset.height or 1)
            shapes = []
            for annotation in by_image.get(image["id"], []):
                x, y, w, h = annotation.get("bbox", [0, 0, 0, 0])
                shapes.append(
                    {
                        "type": "bbox",
                        "label": categories.get(annotation.get("category_id"), "object"),
                        "points": [[x / width, y / height], [(x + w) / width, (y + h) / height]],
                    }
                )
            save_annotation(db, project_id, asset.id, shapes=shapes)
            imported += 1
    elif fmt == "yolo":
        names = payload.get("names") or []
        for filename, content in (payload.get("labels") or {}).items():
            asset = stems.get(str(filename).rsplit(".", 1)[0])
            if asset is None:
                skipped += 1
                continue
            shapes = []
            for line in str(content).splitlines():
                parts = line.split()
                if len(parts) < 5:
                    continue
                class_id, cx, cy, w, h = int(parts[0]), *(float(v) for v in parts[1:5])
                label = names[class_id] if class_id < len(names) else f"class_{class_id}"
                shapes.append(
                    {
                        "type": "bbox",
                        "label": label,
                        "points": [[cx - w / 2, cy - h / 2], [cx + w / 2, cy + h / 2]],
                    }
                )
            save_annotation(db, project_id, asset.id, shapes=shapes)
            imported += 1
    elif fmt == "classification":
        for item in payload.get("items", []):
            asset = assets.get(item.get("file")) or stems.get(
                str(item.get("file", "")).rsplit(".", 1)[0]
            )
            if asset is None:
                skipped += 1
                continue
            save_annotation(db, project_id, asset.id, label=item.get("label"))
            imported += 1
    else:
        raise ValidationError(f"不支持的导入格式: {fmt}")

    return {"imported": imported, "skipped": skipped}
