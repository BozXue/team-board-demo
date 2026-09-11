"""Image loading / encoding helpers.

Loading is deliberately tolerant: industrial and microscopy sources produce
16-bit TIFFs, Z-stacks, RGBA PNGs and huge BMPs, and all of them must end up
as an 8-bit BGR/gray array the node library can rely on.
"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

SUPPORTED_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp"}


def to_uint8(image: np.ndarray) -> np.ndarray:
    """Scale any numeric array into uint8 [0, 255]."""
    image = np.asarray(image)
    if image.dtype == np.uint8:
        return image
    if image.dtype == bool:
        return (image.astype(np.uint8)) * 255
    data = image.astype(np.float64)
    lo, hi = float(np.nanmin(data)), float(np.nanmax(data))
    if hi <= 1.0 and lo >= 0.0:
        data = data * 255.0
    elif hi > lo:
        data = (data - lo) / (hi - lo) * 255.0
    else:
        data = np.zeros_like(data)
    return np.clip(np.nan_to_num(data), 0, 255).astype(np.uint8)


def load_image(path: str | Path) -> np.ndarray:
    """Load an image as uint8 gray (HxW) or BGR (HxWx3)."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(str(path))

    image: np.ndarray | None = None
    if path.suffix.lower() in {".tif", ".tiff"}:
        try:
            import tifffile

            image = np.asarray(tifffile.imread(str(path)))
        except Exception:
            image = None
    if image is None:
        # np.fromfile keeps non-ASCII paths working on every platform.
        buffer = np.fromfile(str(path), dtype=np.uint8)
        image = cv2.imdecode(buffer, cv2.IMREAD_UNCHANGED)
    if image is None:
        raise ValueError(f"无法解码图像: {path.name}")

    image = np.asarray(image)
    if image.ndim == 3 and image.shape[0] == 1 and image.shape[-1] not in (3, 4):
        image = image[0]
    if image.ndim == 3 and image.shape[0] not in (3, 4) and image.shape[-1] not in (3, 4):
        # Z-stack: maximum intensity projection, as in the iPSC prototype.
        image = image.max(axis=0)
    if image.ndim == 3 and image.shape[-1] == 4:
        image = cv2.cvtColor(to_uint8(image), cv2.COLOR_BGRA2BGR)
    if image.ndim == 3 and image.shape[-1] == 2:
        image = image[..., 0]
    return to_uint8(image)


def to_bgr(image: np.ndarray) -> np.ndarray:
    image = to_uint8(image)
    if image.ndim == 2:
        return cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
    return image


def to_gray(image: np.ndarray) -> np.ndarray:
    image = to_uint8(image)
    if image.ndim == 3:
        return cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    return image


def encode_png(image: np.ndarray) -> bytes:
    ok, buffer = cv2.imencode(".png", to_uint8(image))
    if not ok:
        raise ValueError("PNG 编码失败")
    return buffer.tobytes()


def save_png(path: str | Path, image: np.ndarray) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(encode_png(image))
    return path


def save_jpeg(path: str | Path, image: np.ndarray, quality: int = 88) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    ok, buffer = cv2.imencode(".jpg", to_uint8(image), [int(cv2.IMWRITE_JPEG_QUALITY), quality])
    if not ok:
        raise ValueError("JPEG 编码失败")
    path.write_bytes(buffer.tobytes())
    return path


def fit_within(image: np.ndarray, max_side: int) -> np.ndarray:
    """Downscale so the longest side is at most ``max_side`` (never upscales)."""
    h, w = image.shape[:2]
    longest = max(h, w)
    if longest <= max_side:
        return image
    scale = max_side / float(longest)
    return cv2.resize(
        image, (max(1, int(round(w * scale))), max(1, int(round(h * scale)))),
        interpolation=cv2.INTER_AREA,
    )


def heatmap(image: np.ndarray, colormap: int = cv2.COLORMAP_MAGMA) -> np.ndarray:
    return cv2.applyColorMap(to_uint8(image), colormap)


def histogram(image: np.ndarray, bins: int = 256) -> dict:
    """Per-channel histogram plus basic statistics (Viewer 像素信息面板)."""
    image = to_uint8(image)
    if image.ndim == 2:
        channels = {"gray": image}
    else:
        channels = {"blue": image[..., 0], "green": image[..., 1], "red": image[..., 2]}
    out: dict = {"bins": bins, "channels": {}}
    for name, data in channels.items():
        counts, _ = np.histogram(data, bins=bins, range=(0, 256))
        out["channels"][name] = counts.astype(int).tolist()
    gray = to_gray(image)
    out["stats"] = {
        "min": int(gray.min()),
        "max": int(gray.max()),
        "mean": round(float(gray.mean()), 2),
        "std": round(float(gray.std()), 2),
        "width": int(image.shape[1]),
        "height": int(image.shape[0]),
        "channels": 1 if image.ndim == 2 else int(image.shape[2]),
    }
    return out
