"""Texture algorithms ported from the iPSC prototype.

``local_std`` / ``segment_textured_region`` reproduce
``ipsc_texture_classifier/colony_center.py`` and ``features.py``, re-expressed
with OpenCV so they run at platform speed, and split so the pipeline engine can
expose each step as its own node.
"""

from __future__ import annotations

import cv2
import numpy as np

# iPSC prototype defaults (config.py): 32-bin intensity histogram + 2 LBP scales.
INTENSITY_BINS = 32
LBP_SCALES: tuple[tuple[int, int], ...] = ((8, 1), (16, 2))
LBP_METHOD = "uniform"
TILE_SIZE = 64
TEXTURE_CLASSES = (
    "single_cells",
    "medium_compaction",
    "full_compaction",
    "dead_cells",
    "differentiated_cells",
    "debris",
    "background",
)


def resolve_window(height: int, window: int | None = None) -> int:
    """Default local-std window: ~1.5% of image height, odd, at least 7 px."""
    if window:
        window = int(window)
        return window if window % 2 == 1 else window + 1
    return max(7, int(round(0.015 * height)) | 1)


def local_std(gray: np.ndarray, window: int | None = None) -> np.ndarray:
    """Local standard deviation over a square window (texture strength)."""
    window = resolve_window(gray.shape[0], window)
    data = gray.astype(np.float32)
    mean = cv2.boxFilter(data, -1, (window, window), normalize=True,
                         borderType=cv2.BORDER_REFLECT)
    mean_sq = cv2.boxFilter(data * data, -1, (window, window), normalize=True,
                            borderType=cv2.BORDER_REFLECT)
    variance = np.clip(mean_sq - mean * mean, 0, None)
    return np.sqrt(variance)


def remove_small_objects(mask: np.ndarray, min_size: int) -> np.ndarray:
    """Drop connected components smaller than ``min_size`` pixels."""
    binary = (mask > 0).astype(np.uint8)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(binary, connectivity=8)
    out = np.zeros_like(binary)
    for index in range(1, count):
        if stats[index, cv2.CC_STAT_AREA] >= min_size:
            out[labels == index] = 1
    return out * 255


def remove_small_holes(mask: np.ndarray, area_threshold: int) -> np.ndarray:
    """Fill background holes smaller than ``area_threshold`` pixels."""
    inverted = (mask == 0).astype(np.uint8)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(inverted, connectivity=8)
    out = (mask > 0).astype(np.uint8)
    for index in range(1, count):
        if stats[index, cv2.CC_STAT_AREA] < area_threshold:
            out[labels == index] = 1
    return out * 255


def fill_holes(mask: np.ndarray) -> np.ndarray:
    """Fill every enclosed hole of a binary mask."""
    binary = (mask > 0).astype(np.uint8)
    contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    out = np.zeros_like(binary)
    cv2.drawContours(out, contours, -1, 1, thickness=cv2.FILLED)
    return out * 255


def largest_component(mask: np.ndarray) -> np.ndarray:
    binary = (mask > 0).astype(np.uint8)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(binary, connectivity=8)
    if count <= 1:
        return np.zeros_like(binary)
    areas = stats[1:, cv2.CC_STAT_AREA]
    best = int(np.argmax(areas)) + 1
    return ((labels == best).astype(np.uint8)) * 255


def disk_kernel(radius: int) -> np.ndarray:
    radius = max(1, int(radius))
    size = radius * 2 + 1
    return cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (size, size))


def segment_textured_region(
    gray: np.ndarray,
    window: int | None = None,
    min_frac: float = 0.01,
    smooth_sigma: float | None = None,
    keep_largest: bool = True,
    steps: list[dict] | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """Return ``(mask, texture)`` for the dominant textured region.

    Direct port of the prototype's 10-step colony pipeline: local-std texture →
    Otsu → closing → drop debris → fill holes → opening → largest component.
    """
    height, width = gray.shape[:2]
    window = resolve_window(height, window)
    if smooth_sigma is None or smooth_sigma <= 0:
        smooth_sigma = max(1.0, window / 3.0)

    def record(name: str, image: np.ndarray, kind: str) -> None:
        if steps is not None:
            steps.append({"method": name, "image": image, "kind": kind})

    record("01_grayscale", gray, "gray")

    texture = local_std(gray, window)
    record("02_local_std_texture", texture, "heat")

    texture_s = cv2.GaussianBlur(texture, (0, 0), smooth_sigma)
    record("03_gaussian_smoothed", texture_s, "heat")

    scaled = cv2.normalize(texture_s, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)
    _, mask = cv2.threshold(scaled, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    record("04_otsu_threshold", mask, "mask")

    min_size = int(min_frac * height * width)
    close_radius = max(3, window // 2)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, disk_kernel(close_radius))
    record("05_binary_closing", mask, "mask")

    mask = remove_small_objects(mask, min_size)
    record("06_remove_small_objects", mask, "mask")

    mask = remove_small_holes(mask, min_size)
    record("07_remove_small_holes", mask, "mask")

    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, disk_kernel(max(2, close_radius // 2)))
    record("08_binary_opening", mask, "mask")

    if keep_largest:
        mask = largest_component(mask)
    record("09_largest_component", mask, "mask")

    mask = fill_holes(mask)
    record("10_fill_holes_final", mask, "mask")
    return mask, texture_s


def describe_mask(mask: np.ndarray) -> dict | None:
    """Centroid / area / solidity metrics, matching the prototype's CSV."""
    binary = (mask > 0).astype(np.uint8)
    contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    if not contours:
        return None
    contour = max(contours, key=cv2.contourArea)
    area = float(np.count_nonzero(binary))
    if area <= 0:
        return None
    moments = cv2.moments(binary, binaryImage=True)
    cx = moments["m10"] / moments["m00"]
    cy = moments["m01"] / moments["m00"]
    hull = cv2.convexHull(contour)
    hull_area = float(cv2.contourArea(hull)) or area
    height, width = binary.shape
    return {
        "center_x": round(float(cx), 1),
        "center_y": round(float(cy), 1),
        "area_px": int(area),
        "area_fraction_percent": round(100.0 * area / (height * width), 2),
        "equivalent_diameter_px": round(float(np.sqrt(4.0 * area / np.pi)), 1),
        "solidity": round(min(1.0, area / hull_area), 3),
        "contour": contour.reshape(-1, 2),
    }


def intensity_histogram(gray: np.ndarray, bins: int = INTENSITY_BINS) -> np.ndarray:
    hist, _ = np.histogram(gray, bins=bins, range=(0, 256))
    hist = hist.astype(np.float64)
    total = hist.sum()
    if total > 0:
        hist /= total
    return hist


def lbp_histogram(gray: np.ndarray, points: int, radius: int) -> np.ndarray:
    from skimage.feature import local_binary_pattern

    lbp = local_binary_pattern(gray, points, radius, method=LBP_METHOD)
    n_bins = points + 2
    hist, _ = np.histogram(lbp, bins=n_bins, range=(0, n_bins))
    hist = hist.astype(np.float64)
    total = hist.sum()
    if total > 0:
        hist /= total
    return hist


def extract_features(gray: np.ndarray) -> np.ndarray:
    """Intensity histogram + multi-scale uniform LBP (58-D by default)."""
    parts = [intensity_histogram(gray)]
    for points, radius in LBP_SCALES:
        parts.append(lbp_histogram(gray, points, radius))
    return np.concatenate(parts).astype(np.float32)


def feature_names() -> list[str]:
    names = [f"int_hist_{i}" for i in range(INTENSITY_BINS)]
    for points, radius in LBP_SCALES:
        names += [f"lbp_P{points}_R{radius}_{i}" for i in range(points + 2)]
    return names


def tile_positions(shape: tuple[int, int], tile: int, stride: int | None = None):
    """Yield ``(y, x)`` origins of the tiles covering an image."""
    stride = stride or tile
    height, width = shape[:2]
    for y in range(0, max(1, height - tile + 1), stride):
        for x in range(0, max(1, width - tile + 1), stride):
            yield y, x
