"""Contour extraction and geometric properties."""

from __future__ import annotations

import cv2
import numpy as np

from app.engine.types import Region, Regions


def regions_from_mask(
    mask: np.ndarray,
    intensity: np.ndarray | None = None,
    external_only: bool = True,
    min_area: float = 0.0,
) -> Regions:
    binary = (mask > 0).astype(np.uint8)
    mode = cv2.RETR_EXTERNAL if external_only else cv2.RETR_LIST
    contours, _ = cv2.findContours(binary, mode, cv2.CHAIN_APPROX_SIMPLE)
    items: list[Region] = []
    for contour in contours:
        area = float(cv2.contourArea(contour))
        if area < min_area or len(contour) < 3:
            continue
        items.append(region_from_contour(len(items), contour, area, binary, intensity))
    items.sort(key=lambda r: r.area, reverse=True)
    for index, region in enumerate(items):
        region.index = index
    return Regions(items=items, shape=(binary.shape[0], binary.shape[1]))


def region_from_contour(
    index: int,
    contour: np.ndarray,
    area: float,
    binary: np.ndarray,
    intensity: np.ndarray | None = None,
) -> Region:
    perimeter = float(cv2.arcLength(contour, True))
    x, y, w, h = cv2.boundingRect(contour)
    moments = cv2.moments(contour)
    if moments["m00"] > 1e-9:
        cx = moments["m10"] / moments["m00"]
        cy = moments["m01"] / moments["m00"]
    else:
        cx, cy = x + w / 2.0, y + h / 2.0
    hull_area = float(cv2.contourArea(cv2.convexHull(contour))) or area
    circularity = 4.0 * np.pi * area / (perimeter ** 2) if perimeter > 0 else 0.0
    mean_intensity = None
    if intensity is not None:
        patch = intensity[y:y + h, x:x + w]
        patch_mask = binary[y:y + h, x:x + w] > 0
        if patch.size and patch_mask.any():
            if patch.ndim == 3:
                patch = cv2.cvtColor(patch, cv2.COLOR_BGR2GRAY)
            mean_intensity = float(patch[patch_mask].mean())
    return Region(
        index=index,
        area=area,
        centroid=(cx, cy),
        bbox=(x, y, w, h),
        contour=contour.reshape(-1, 2),
        perimeter=perimeter,
        circularity=float(min(1.5, circularity)),
        solidity=float(min(1.0, area / hull_area)) if hull_area else 0.0,
        aspect_ratio=float(w / h) if h else 1.0,
        equivalent_diameter=float(np.sqrt(4.0 * area / np.pi)),
        mean_intensity=mean_intensity,
    )


def major_axis_length(contour: np.ndarray) -> float:
    """Longest side of the minimum-area rectangle (a robust length proxy)."""
    points = np.asarray(contour, dtype=np.float32).reshape(-1, 2)
    if len(points) < 3:
        return 0.0
    (_, _), (w, h), _ = cv2.minAreaRect(points)
    return float(max(w, h))


def orientation_deg(contour: np.ndarray) -> float:
    points = np.asarray(contour, dtype=np.float32).reshape(-1, 2)
    if len(points) < 5:
        return 0.0
    (_, _), (w, h), angle = cv2.minAreaRect(points)
    if w < h:
        angle += 90.0
    return float(angle % 180.0)


def mask_from_regions(regions: Regions) -> np.ndarray:
    canvas = np.zeros(regions.shape, dtype=np.uint8)
    contours = [np.asarray(r.contour, dtype=np.int32).reshape(-1, 1, 2) for r in regions.items]
    if contours:
        cv2.drawContours(canvas, contours, -1, 255, thickness=cv2.FILLED)
    return canvas
