"""Turn port payloads into something the Viewer can display."""

from __future__ import annotations

import cv2
import numpy as np

from app.engine.types import Judgement, PortType, Regions, Roi, Value
from app.utils.imageio import heatmap, to_bgr, to_gray, to_uint8

REGION_COLOR = (255, 208, 0)   # BGR - cyan/amber outline reads well on gray
CENTER_COLOR = (60, 60, 255)
ROI_COLOR = (255, 170, 40)


def render_mask(mask: np.ndarray) -> np.ndarray:
    return to_uint8(mask)


def render_roi(roi: Roi) -> np.ndarray:
    canvas = np.zeros(roi.shape, dtype=np.uint8)
    canvas[roi.mask.astype(bool)] = 255
    return canvas


def overlay_regions(base: np.ndarray, regions: Regions, draw_centers: bool = True) -> np.ndarray:
    canvas = to_bgr(base)
    if canvas.shape[:2] != tuple(regions.shape):
        canvas = cv2.resize(canvas, (regions.shape[1], regions.shape[0]))
    for region in regions.items:
        contour = np.asarray(region.contour, dtype=np.int32).reshape(-1, 1, 2)
        cv2.polylines(canvas, [contour], True, REGION_COLOR, max(1, canvas.shape[0] // 500))
        if draw_centers:
            cx, cy = int(round(region.centroid[0])), int(round(region.centroid[1]))
            size = max(4, canvas.shape[0] // 120)
            cv2.drawMarker(canvas, (cx, cy), CENTER_COLOR, cv2.MARKER_CROSS, size * 2,
                           max(1, size // 3))
    return canvas


def overlay_roi(base: np.ndarray, roi: Roi) -> np.ndarray:
    canvas = to_bgr(base)
    tinted = canvas.copy()
    tinted[roi.mask.astype(bool)] = ROI_COLOR
    canvas = cv2.addWeighted(canvas, 0.78, tinted, 0.22, 0)
    x, y, w, h = roi.bbox
    cv2.rectangle(canvas, (x, y), (x + w, y + h), ROI_COLOR, max(1, canvas.shape[0] // 500))
    return canvas


def render_heat(image: np.ndarray) -> np.ndarray:
    return heatmap(image)


def preview_for(
    value: object,
    port_type: PortType,
    base_image: np.ndarray | None = None,
) -> tuple[np.ndarray | None, str]:
    """Return ``(image, kind)`` to save as this port's preview."""
    if port_type == PortType.IMAGE and isinstance(value, np.ndarray):
        if value.ndim == 2:
            return value, "gray"
        return value, "color"
    if port_type == PortType.MASK and isinstance(value, np.ndarray):
        return render_mask(value), "mask"
    if isinstance(value, Roi):
        if base_image is not None:
            return overlay_roi(base_image, value), "overlay"
        return render_roi(value), "mask"
    if isinstance(value, Regions):
        base = base_image if base_image is not None else np.zeros(value.shape, dtype=np.uint8)
        return overlay_regions(base, value), "overlay"
    if isinstance(value, np.ndarray) and value.ndim in (2, 3):
        return value, "gray" if value.ndim == 2 else "color"
    return None, "none"


def judgement_banner(image: np.ndarray, judgement: Judgement) -> np.ndarray:
    """OK/NG stamp used by Batch Test and Runtime result thumbnails."""
    canvas = to_bgr(image)
    h, w = canvas.shape[:2]
    color = (80, 200, 120) if judgement.ok else (70, 70, 240)
    thickness = max(2, h // 200)
    cv2.rectangle(canvas, (0, 0), (w - 1, h - 1), color, thickness * 2)
    scale = max(0.6, h / 900.0 * 1.6)
    text = judgement.verdict
    (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, scale, thickness)
    pad = int(th * 0.45)
    cv2.rectangle(canvas, (thickness, thickness),
                  (thickness + tw + pad * 2, thickness + th + pad * 2), color, -1)
    cv2.putText(canvas, text, (thickness + pad, thickness + th + pad),
                cv2.FONT_HERSHEY_SIMPLEX, scale, (255, 255, 255), thickness, cv2.LINE_AA)
    return canvas


def gray_stats(image: np.ndarray) -> dict:
    gray = to_gray(image)
    return {
        "mean": round(float(gray.mean()), 2),
        "std": round(float(gray.std()), 2),
        "min": int(gray.min()),
        "max": int(gray.max()),
    }


def value_text(value: Value) -> str:
    return f"{value.name}={value.value} {value.unit}".strip()
