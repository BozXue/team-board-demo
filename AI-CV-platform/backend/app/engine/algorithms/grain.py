"""Grain-bag photo helpers ported from sample_projects/分类/src/preprocess.py."""

from __future__ import annotations

import cv2
import numpy as np


def suppress_glare(bgr: np.ndarray) -> np.ndarray:
    """Replace plastic-bag specular highlights with neighbouring blur."""
    if bgr.ndim == 2:
        bgr = cv2.cvtColor(bgr, cv2.COLOR_GRAY2BGR)
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    sat = hsv[:, :, 1]
    val = hsv[:, :, 2]
    glare = (val > 230) & (sat < 40)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
    mask = cv2.dilate(glare.astype(np.uint8) * 255, kernel, iterations=1)
    if int(np.count_nonzero(mask)) == 0:
        return bgr
    blurred = cv2.GaussianBlur(bgr, (21, 21), 0)
    return np.where(mask[..., None] > 0, blurred, bgr)


def find_grain_roi(bgr: np.ndarray) -> tuple[np.ndarray, tuple[int, int, int, int]]:
    """Crop to the coloured grain mass; fall back to the full frame."""
    if bgr.ndim == 2:
        bgr = cv2.cvtColor(bgr, cv2.COLOR_GRAY2BGR)
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    sat = hsv[:, :, 1]
    val = hsv[:, :, 2]
    grain = (sat > 22) & (val > 45) & (val < 245)
    mask = grain.astype(np.uint8) * 255
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (15, 15))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)

    ys, xs = np.where(mask > 0)
    height, width = bgr.shape[:2]
    if xs.size < 80:
        return bgr, (0, 0, width, height)

    x0, x1 = int(xs.min()), int(xs.max())
    y0, y1 = int(ys.min()), int(ys.max())
    pad = int(0.04 * max(x1 - x0, y1 - y0, 1))
    x0 = max(0, x0 - pad)
    y0 = max(0, y0 - pad)
    x1 = min(width, x1 + pad)
    y1 = min(height, y1 + pad)
    if (x1 - x0) * (y1 - y0) < 0.04 * height * width:
        return bgr, (0, 0, width, height)
    return bgr[y0:y1, x0:x1], (x0, y0, x1 - x0, y1 - y0)
