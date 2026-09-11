"""粮面颜色 + 纹理特征。样本量少时用随机森林，不依赖 GPU。"""

from __future__ import annotations

import cv2
import numpy as np


FEATURE_NAMES = [
    "hue_mean",
    "hue_std",
    "sat_mean",
    "val_mean",
    "val_std",
    "yellow_ratio",
    "red_ratio",
    "edge_density",
    "grain_median_area",
    "grain_aspect",
    "laplacian_var",
]


def extract_features(roi_bgr: np.ndarray) -> np.ndarray:
    hsv = cv2.cvtColor(roi_bgr, cv2.COLOR_BGR2HSV)
    h, s, v = cv2.split(hsv)
    gray = cv2.cvtColor(roi_bgr, cv2.COLOR_BGR2GRAY)

    yellow = ((h >= 15) & (h <= 40) & (s > 40) & (v > 60)).mean()
    red = (((h <= 10) | (h >= 170)) & (s > 40) & (v > 40)).mean()

    edges = cv2.Canny(gray, 50, 150)
    edge_density = float(edges.mean() / 255.0)

    blur = cv2.GaussianBlur(gray, (5, 5), 0)
    _, binary = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    # 籽粒通常比缝隙亮或暗，两种都试，取轮廓更合理的一侧
    binary_inv = cv2.bitwise_not(binary)
    median_area, aspect = _blob_stats(binary, roi_bgr.size)
    median_area_inv, aspect_inv = _blob_stats(binary_inv, roi_bgr.size)
    if median_area_inv > median_area:
        median_area, aspect = median_area_inv, aspect_inv

    lap_var = float(cv2.Laplacian(gray, cv2.CV_64F).var())

    return np.array(
        [
            float(h.mean()),
            float(h.std()),
            float(s.mean()),
            float(v.mean()),
            float(v.std()),
            float(yellow),
            float(red),
            edge_density,
            median_area,
            aspect,
            lap_var,
        ],
        dtype=np.float32,
    )


def _blob_stats(binary: np.ndarray, image_pixels: int) -> tuple[float, float]:
    contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    min_area = image_pixels * 0.00015
    max_area = image_pixels * 0.04
    areas: list[float] = []
    aspects: list[float] = []
    for contour in contours:
        area = cv2.contourArea(contour)
        if area < min_area or area > max_area:
            continue
        _, _, w, h = cv2.boundingRect(contour)
        if min(w, h) == 0:
            continue
        areas.append(float(area))
        aspects.append(max(w, h) / min(w, h))
    if not areas:
        return 0.0, 1.0
    return float(np.median(areas) / image_pixels * 1e4), float(np.median(aspects))
