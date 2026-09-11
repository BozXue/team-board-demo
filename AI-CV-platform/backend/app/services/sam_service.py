"""Interactive SAM segmentation for the dedicated SAM 智能标注 page.

Point / box prompts produce a mask overlay (same interaction as the Gradio
prototype). The mask is also converted into a normalised polygon so it can
be saved as a regular Annotation shape on the Data page.
"""

from __future__ import annotations

import base64
import threading
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.errors import NotFoundError, ValidationError
from app.models import ImageAsset, ModelAsset
from app.services import dataset_service
from app.utils.imageio import encode_png, load_image, to_bgr, to_uint8

_LOCK = threading.Lock()
_MODEL: Any = None
_WEIGHTS: str | None = None

_NAMED_WEIGHTS = (
    "sam2_b.pt",
    "sam2.1_b.pt",
    "sam2_t.pt",
    "sam2_s.pt",
    "sam2_l.pt",
    "sam_b.pt",
    "mobile_sam.pt",
)
_MISSING_HINT = "未找到本地 SAM 权重。请到「模型」页上传 sam2_b.pt，不会联网下载。"


def available(db: Session | None = None, project_id: str | None = None) -> dict[str, Any]:
    try:
        import ultralytics  # noqa: F401
    except ImportError:
        return {
            "available": False,
            "hint": "未安装 ultralytics。在后端虚拟环境执行: pip install ultralytics",
        }
    path = resolve_weights(db, project_id)
    if path is None:
        return {
            "available": False,
            "weights": str(settings.models_dir / "sam2_b.pt"),
            "hint": _MISSING_HINT,
        }
    return {
        "available": True,
        "weights": str(path),
        "hint": "点选或框选后，左侧显示位置，右侧显示叠加",
    }


def _looks_like_sam(name: str, task: str = "") -> bool:
    blob = f"{name} {task}".lower()
    return "sam" in blob or task.lower() in {"segment", "segmentation"}


def resolve_weights(db: Session | None = None, project_id: str | None = None) -> Path | None:
    """Pick an existing local .pt. Never downloads."""
    models_dir = settings.models_dir
    ranked: list[Path] = []

    if db is not None:
        assets = db.execute(select(ModelAsset)).scalars().all()
        project_hits: list[Path] = []
        other_hits: list[Path] = []
        for asset in assets:
            if not asset.rel_path:
                continue
            path = models_dir / asset.rel_path
            if not path.exists() or path.suffix.lower() != ".pt":
                continue
            imported = str((asset.meta or {}).get("importedFrom") or "")
            if not _looks_like_sam(f"{asset.name} {imported}", asset.task or ""):
                continue
            if project_id and asset.project_id == project_id:
                project_hits.append(path)
            else:
                other_hits.append(path)
        ranked.extend(project_hits)
        ranked.extend(other_hits)

    if models_dir.exists():
        for name in _NAMED_WEIGHTS:
            path = models_dir / name
            if path.exists() and path not in ranked:
                ranked.append(path)
        for path in sorted(models_dir.glob("*.pt")):
            if _looks_like_sam(path.name) and path not in ranked:
                ranked.append(path)

    return ranked[0] if ranked else None


def _load_model(db: Session | None = None, project_id: str | None = None):
    global _MODEL, _WEIGHTS
    path = resolve_weights(db, project_id)
    if path is None or not path.exists():
        raise ValidationError(_MISSING_HINT)
    key = str(path.resolve())
    with _LOCK:
        if _MODEL is not None and _WEIGHTS == key:
            return _MODEL
        try:
            from ultralytics import SAM
        except ImportError as exc:
            raise ValidationError(
                "未安装 ultralytics，无法运行 SAM。请执行: pip install ultralytics"
            ) from exc
        _MODEL = SAM(key)
        _WEIGHTS = key
        return _MODEL


def _norm_to_px(points: list[list[float]], width: int, height: int) -> list[list[int]]:
    out: list[list[int]] = []
    for raw in points:
        if len(raw) < 2:
            continue
        x = int(round(float(raw[0]) * width))
        y = int(round(float(raw[1]) * height))
        out.append([max(0, min(width - 1, x)), max(0, min(height - 1, y))])
    return out


def _mask_to_polygon(mask: np.ndarray) -> list[list[float]]:
    binary = (mask > 0.5).astype(np.uint8) * 255
    height, width = binary.shape[:2]
    contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return []
    contour = max(contours, key=cv2.contourArea)
    if cv2.contourArea(contour) < 8:
        return []
    epsilon = max(1.0, 0.002 * cv2.arcLength(contour, True))
    approx = cv2.approxPolyDP(contour, epsilon, True)
    if len(approx) < 3:
        approx = contour
    pts = approx.reshape(-1, 2).astype(np.float32)
    if len(pts) > 80:
        step = int(np.ceil(len(pts) / 80))
        pts = pts[::step]
    return [
        [round(float(x) / width, 6), round(float(y) / height, 6)]
        for x, y in pts
    ]


def _overlay(image: np.ndarray, mask: np.ndarray, color=(255, 96, 16), alpha=0.55) -> np.ndarray:
    """Mask tint. ``color`` is BGR; blue stands out on yellow grain."""
    bgr = to_bgr(image).astype(np.float32)
    if mask.shape[:2] != bgr.shape[:2]:
        mask = cv2.resize(mask.astype(np.uint8), (bgr.shape[1], bgr.shape[0]), interpolation=cv2.INTER_NEAREST)
    tint = bgr.copy()
    hit = mask > 0.5
    tint[hit] = tint[hit] * (1 - alpha) + np.array(color, dtype=np.float32) * alpha
    out = tint.astype(np.uint8)
    binary = hit.astype(np.uint8) * 255
    contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if contours:
        cv2.drawContours(out, contours, -1, (255, 140, 40), 2)
    return out


def _png_data_url(image: np.ndarray) -> str:
    return "data:image/png;base64," + base64.b64encode(encode_png(image)).decode("ascii")


def _jpeg_data_url(image: np.ndarray, quality: int = 85) -> str:
    ok, buffer = cv2.imencode(".jpg", to_uint8(image), [int(cv2.IMWRITE_JPEG_QUALITY), quality])
    if not ok:
        raise ValidationError("预览图编码失败")
    return "data:image/jpeg;base64," + base64.b64encode(buffer.tobytes()).decode("ascii")


def _draw_prompts(
    bgr: np.ndarray,
    points: list[list[int]],
    labels: list[int],
    box: list[int] | None,
) -> np.ndarray:
    """Preview of clicks / box, matching the Gradio left-hand pane."""
    marked = bgr.copy()
    for (x, y), label in zip(points, labels):
        color = (50, 220, 50) if label else (40, 40, 230)
        cv2.circle(marked, (int(x), int(y)), 10, color, thickness=-1)
        cv2.circle(marked, (int(x), int(y)), 10, (0, 0, 0), thickness=2)
    if box and len(box) == 4:
        x1, y1, x2, y2 = (int(v) for v in box)
        cv2.rectangle(marked, (x1, y1), (x2, y2), (255, 160, 40), 3)
    return marked


def predict(
    db: Session,
    project_id: str,
    image_id: str,
    points: list[list[float]] | None = None,
    labels: list[int] | None = None,
    box: list[float] | None = None,
) -> dict[str, Any]:
    asset = db.get(ImageAsset, image_id)
    if asset is None or asset.project_id != project_id:
        raise NotFoundError(f"图像不存在: {image_id}")

    # Run on the preview the Data page displays so click coordinates line up.
    path = dataset_service.image_source_path(asset, prefer_preview=True)
    image = load_image(path)
    bgr = to_bgr(image)
    height, width = bgr.shape[:2]

    kwargs: dict[str, Any] = {}
    px_points = _norm_to_px(points or [], width, height)
    if px_points:
        if labels and len(labels) == len(px_points):
            px_labels = [1 if int(v) else 0 for v in labels]
        else:
            px_labels = [1] * len(px_points)
        kwargs["points"] = [px_points]
        kwargs["labels"] = [px_labels]
    if box and len(box) == 4:
        x1, y1, x2, y2 = box
        x1i, x2i = sorted([int(round(float(x1) * width)), int(round(float(x2) * width))])
        y1i, y2i = sorted([int(round(float(y1) * height)), int(round(float(y2) * height))])
        if x2i - x1i < 3 or y2i - y1i < 3:
            raise ValidationError("框太小，请拉大一些再分割")
        kwargs["bboxes"] = [[x1i, y1i, x2i, y2i]]
    if not kwargs:
        raise ValidationError("请先点选目标点或画框")

    model = _load_model(db, project_id)
    results = model.predict(bgr, verbose=False, **kwargs)
    if not results or results[0].masks is None or results[0].masks.data is None:
        raise ValidationError("SAM 没有产生掩膜，请换个点或换个框再试")
    mask = results[0].masks.data[0]
    if hasattr(mask, "cpu"):
        mask = mask.cpu().numpy()
    mask = np.squeeze(np.asarray(mask))
    if mask.ndim != 2:
        raise ValidationError("SAM 掩膜格式异常")
    if mask.shape != (height, width):
        mask = cv2.resize(mask.astype(np.float32), (width, height), interpolation=cv2.INTER_LINEAR)

    polygon = _mask_to_polygon(mask)
    if len(polygon) < 3:
        raise ValidationError("掩膜太碎，换一个更靠近目标的点或框")

    overlay = _overlay(bgr, mask)
    binary = (mask > 0.5).astype(np.uint8) * 255
    prompt_box = kwargs.get("bboxes", [[]])[0] if "bboxes" in kwargs else None
    marked = _draw_prompts(bgr, px_points, kwargs.get("labels", [[]])[0] if px_points else [], prompt_box)
    ys, xs = np.where(mask > 0.5)
    bbox = None
    if xs.size:
        bbox = [
            round(float(xs.min()) / width, 6),
            round(float(ys.min()) / height, 6),
            round(float(xs.max()) / width, 6),
            round(float(ys.max()) / height, 6),
        ]
    return {
        "polygon": polygon,
        "box": bbox,
        "area": int(np.count_nonzero(mask > 0.5)),
        "markedPng": _jpeg_data_url(marked),
        "overlayPng": _jpeg_data_url(overlay),
        "maskPng": _png_data_url(binary),
        "width": width,
        "height": height,
    }
