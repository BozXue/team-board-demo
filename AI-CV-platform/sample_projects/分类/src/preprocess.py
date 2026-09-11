"""密封袋照片预处理：缩小大图、去反光、切出粮面。"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

MAX_SIDE = 1600


@dataclass
class PreparedImage:
    original_bgr: np.ndarray
    deglared_bgr: np.ndarray
    roi_bgr: np.ndarray
    roi_box: tuple[int, int, int, int]


def load_bgr(path: str) -> np.ndarray:
    image = cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise FileNotFoundError(f"无法读取图片: {path}")
    return downscale(image)


def downscale(bgr: np.ndarray, max_side: int = MAX_SIDE) -> np.ndarray:
    h, w = bgr.shape[:2]
    longest = max(h, w)
    if longest <= max_side:
        return bgr
    scale = max_side / longest
    return cv2.resize(
        bgr,
        (max(1, int(w * scale)), max(1, int(h * scale))),
        interpolation=cv2.INTER_AREA,
    )


def suppress_glare(bgr: np.ndarray) -> np.ndarray:
    """塑料袋高光：高亮度、低饱和。用模糊像素替换，避免白斑主导颜色。"""
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    s = hsv[:, :, 1]
    v = hsv[:, :, 2]
    glare = (v > 230) & (s < 40)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
    mask = cv2.dilate(glare.astype(np.uint8) * 255, kernel, iterations=1)
    if int(mask.sum()) == 0:
        return bgr
    blurred = cv2.GaussianBlur(bgr, (21, 21), 0)
    return np.where(mask[..., None] > 0, blurred, bgr)


def find_grain_roi(bgr: np.ndarray) -> tuple[np.ndarray, tuple[int, int, int, int]]:
    """黑底上散落的籽粒会碎成很多连通域，取全部粮色像素的外接框。"""
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    sat = hsv[:, :, 1]
    val = hsv[:, :, 2]
    grain = (sat > 22) & (val > 45) & (val < 245)
    mask = grain.astype(np.uint8) * 255
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (15, 15))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)

    ys, xs = np.where(mask > 0)
    h, w = bgr.shape[:2]
    if xs.size < 80:
        return bgr, (0, 0, w, h)

    x0, x1 = int(xs.min()), int(xs.max())
    y0, y1 = int(ys.min()), int(ys.max())
    pad = int(0.04 * max(x1 - x0, y1 - y0, 1))
    x0 = max(0, x0 - pad)
    y0 = max(0, y0 - pad)
    x1 = min(w, x1 + pad)
    y1 = min(h, y1 + pad)
    if (x1 - x0) * (y1 - y0) < 0.04 * h * w:
        return bgr, (0, 0, w, h)
    return bgr[y0:y1, x0:x1], (x0, y0, x1 - x0, y1 - y0)


def prepare(path: str) -> PreparedImage:
    original = load_bgr(path)
    deglared = suppress_glare(original)
    roi, box = find_grain_roi(deglared)
    return PreparedImage(
        original_bgr=original,
        deglared_bgr=deglared,
        roi_bgr=roi,
        roi_box=box,
    )


def bgr_to_rgb(bgr: np.ndarray) -> np.ndarray:
    return cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
