"""Feature extraction: intensity histogram + Local Binary Pattern (LBP).

Each patch is described by a 1D feature vector that concatenates:
  - a normalized intensity histogram (brightness distribution), and
  - one normalized uniform-LBP histogram per configured scale (texture).

The vector length is fixed regardless of patch size, so patches of
slightly different sizes still produce comparable descriptors.
"""

import numpy as np
from skimage.color import rgb2gray
from skimage.feature import local_binary_pattern

try:
    import tifffile
    _HAS_TIFFFILE = True
except Exception:
    _HAS_TIFFFILE = False

from skimage.io import imread as _sk_imread

import config


def load_gray(path):
    """Load an image from disk and return a 2D uint8 grayscale array."""
    img = None
    if _HAS_TIFFFILE and str(path).lower().endswith((".tif", ".tiff")):
        img = tifffile.imread(str(path))
    if img is None:
        img = _sk_imread(str(path))

    img = np.asarray(img)

    # Drop a leading singleton axis, e.g. (1, H, W).
    if img.ndim == 3 and img.shape[0] in (1,) and img.shape[-1] not in (3, 4):
        img = img[0]
    if img.ndim == 3 and img.shape[0] not in (3, 4) and img.shape[-1] not in (3, 4):
        # Z-stack: collapse with a maximum-intensity projection.
        img = img.max(axis=0)

    # Colour image: ignore any alpha channel before converting to gray.
    if img.ndim == 3 and img.shape[-1] in (3, 4):
        img = rgb2gray(img[..., :3])

    img = _to_uint8(img)
    return img


def _to_uint8(img):
    """Scale any numeric image to uint8 [0, 255]."""
    img = np.asarray(img)
    if img.dtype == np.uint8:
        return img
    img = img.astype(np.float64)
    lo, hi = float(img.min()), float(img.max())
    if hi <= 1.0 and lo >= 0.0:
        img = img * 255.0
    elif hi > lo:
        img = (img - lo) / (hi - lo) * 255.0
    else:
        img = np.zeros_like(img)
    return np.clip(img, 0, 255).astype(np.uint8)


def intensity_histogram(gray, bins=None):
    """Normalized brightness histogram over the 0-255 range."""
    if bins is None:
        bins = config.INTENSITY_BINS
    hist, _ = np.histogram(gray, bins=bins, range=(0, 256))
    hist = hist.astype(np.float64)
    total = hist.sum()
    if total > 0:
        hist /= total
    return hist


def lbp_histogram(gray, P, R, method=None):
    """Normalized uniform-LBP histogram for one (P, R) scale."""
    if method is None:
        method = config.LBP_METHOD
    lbp = local_binary_pattern(gray, P, R, method=method)
    n_bins = P + 2
    hist, _ = np.histogram(lbp, bins=n_bins, range=(0, n_bins))
    hist = hist.astype(np.float64)
    total = hist.sum()
    if total > 0:
        hist /= total
    return hist


def extract_features(gray):
    """Build the full feature vector for a single grayscale patch."""
    gray = _to_uint8(gray)
    parts = [intensity_histogram(gray)]
    for P, R in config.LBP_SCALES:
        parts.append(lbp_histogram(gray, P, R))
    return np.concatenate(parts).astype(np.float32)


def feature_names():
    """Human-readable names for each feature dimension (for debugging)."""
    names = [f"int_hist_{i}" for i in range(config.INTENSITY_BINS)]
    for P, R in config.LBP_SCALES:
        names += [f"lbp_P{P}_R{R}_{i}" for i in range(P + 2)]
    return names
