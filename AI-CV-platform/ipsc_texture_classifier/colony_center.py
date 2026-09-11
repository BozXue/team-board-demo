"""Segment the main cell colony in an image and locate its center.

The colony is a highly-textured region (many cell borders) sitting on a
smoother, brighter background. We therefore:
  1. compute a local-texture map (local standard deviation),
  2. threshold it (Otsu) to get textured regions,
  3. clean up with morphology and drop small scattered debris,
  4. keep the largest connected component = the colony,
  5. report its centroid, area and equivalent diameter,
  6. draw the colony outline + center marker over the original image.

Example:
    python colony_center.py --image colony.tif --out results
"""

import argparse
import csv
import os
import glob

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager


def _enable_cjk_font():
    """Use a CJK-capable font if available so Chinese sample names render."""
    available = {f.name for f in font_manager.fontManager.ttflist}
    for name in ("PingFang SC", "Heiti TC", "Songti SC", "STHeiti",
                 "Arial Unicode MS", "Hiragino Sans GB", "Microsoft YaHei",
                 "SimHei", "Noto Sans CJK SC"):
        if name in available:
            plt.rcParams["font.sans-serif"] = [name] + \
                list(plt.rcParams.get("font.sans-serif", []))
            break
    plt.rcParams["axes.unicode_minus"] = False


_enable_cjk_font()

from scipy import ndimage as ndi
from skimage.filters import threshold_otsu, gaussian
from skimage.morphology import (binary_closing, binary_opening, disk,
                                remove_small_objects, remove_small_holes)
from skimage.measure import label, regionprops, find_contours

from features import load_gray

_IMG_EXTS = (".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp")


def local_std(gray, win):
    """Local standard deviation over a square window (texture strength)."""
    g = gray.astype(np.float64)
    mean = ndi.uniform_filter(g, win)
    mean_sq = ndi.uniform_filter(g * g, win)
    var = np.clip(mean_sq - mean * mean, 0, None)
    return np.sqrt(var)


def segment_colony(gray, win=None, min_frac=0.01, smooth_sigma=None, record=None):
    """Return (mask, texture) for the largest textured colony region.

    win        : local-std window in px (default ~ 1.5% of image height).
    min_frac   : ignore textured blobs smaller than this fraction of the image.
    smooth_sigma: Gaussian smoothing of the texture map before thresholding.
    record     : optional list; if given, each intermediate step is appended
                 as a dict {"method": name, "img": array, "kind": kind} so the
                 caller can visualise the full pipeline.
    """
    H, W = gray.shape[:2]
    if win is None:
        win = max(7, int(round(0.015 * H)) | 1)   # odd-ish, scale with image
    if smooth_sigma is None:
        smooth_sigma = max(1.0, win / 3.0)

    def _log(method, img, kind):
        if record is not None:
            record.append({"method": method, "img": np.array(img), "kind": kind})

    _log("01_grayscale", gray, "gray")

    texture = local_std(gray, win)
    _log("02_local_std_texture", texture, "heat")

    texture_s = gaussian(texture, sigma=smooth_sigma, preserve_range=True)
    _log("03_gaussian_smoothed", texture_s, "heat")

    thr = threshold_otsu(texture_s)
    mask = texture_s > thr
    _log("04_otsu_threshold", mask, "mask")

    # Clean up: close gaps inside the colony, drop small debris, fill holes.
    min_size = int(min_frac * H * W)
    close_r = max(3, win // 2)
    mask = binary_closing(mask, disk(close_r))
    _log("05_binary_closing", mask, "mask")

    mask = remove_small_objects(mask, min_size=min_size)
    _log("06_remove_small_objects", mask, "mask")

    mask = remove_small_holes(mask, area_threshold=min_size)
    _log("07_remove_small_holes", mask, "mask")

    mask = binary_opening(mask, disk(max(2, close_r // 2)))
    _log("08_binary_opening", mask, "mask")

    lab = label(mask)
    if lab.max() == 0:
        _log("09_largest_component", np.zeros_like(mask), "mask")
        _log("10_fill_holes_final", np.zeros_like(mask), "mask")
        return np.zeros_like(mask), texture_s

    # Keep the largest connected component.
    props = regionprops(lab)
    biggest = max(props, key=lambda p: p.area)
    colony = lab == biggest.label
    _log("09_largest_component", colony, "mask")

    colony = ndi.binary_fill_holes(colony)
    _log("10_fill_holes_final", colony, "mask")
    return colony, texture_s


def describe(colony):
    """Return a dict of centroid/area metrics for a boolean colony mask."""
    lab = label(colony.astype(np.uint8))
    if lab.max() == 0:
        return None
    p = regionprops(lab)[0]
    cy, cx = p.centroid
    area = int(p.area)
    equiv_d = float(p.equivalent_diameter)
    H, W = colony.shape
    return {
        "center_x": round(cx, 1),
        "center_y": round(cy, 1),
        "area_px": area,
        "area_fraction_percent": round(100.0 * area / (H * W), 2),
        "equivalent_diameter_px": round(equiv_d, 1),
        "solidity": round(float(p.solidity), 3),
    }


def save_overlay(gray, colony, info, path):
    """Draw the colony outline + center marker over the original image."""
    fig, ax = plt.subplots(figsize=(10, 10 * gray.shape[0] / gray.shape[1]))
    ax.imshow(gray, cmap="gray")
    ax.set_axis_off()

    for contour in find_contours(colony.astype(float), 0.5):
        ax.plot(contour[:, 1], contour[:, 0], color="cyan", linewidth=2)

    if info is not None:
        cx, cy = info["center_x"], info["center_y"]
        ax.plot(cx, cy, "r+", markersize=22, markeredgewidth=3)
        ax.plot(cx, cy, "o", markerfacecolor="none", markeredgecolor="red",
                markersize=14, markeredgewidth=2)
        ax.set_title(
            f"center=({cx:.0f}, {cy:.0f})  "
            f"area={info['area_fraction_percent']:.1f}%  "
            f"d={info['equivalent_diameter_px']:.0f}px",
            fontsize=12)
    fig.tight_layout()
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)


# Short human-readable titles for the montage (kept separate from the file
# name, which stays as "<sample>_<method>").
_STEP_TITLES = {
    "01_grayscale": "1. Grayscale",
    "02_local_std_texture": "2. Local-std texture",
    "03_gaussian_smoothed": "3. Gaussian smoothed",
    "04_otsu_threshold": "4. Otsu threshold",
    "05_binary_closing": "5. Binary closing",
    "06_remove_small_objects": "6. Remove small objects",
    "07_remove_small_holes": "7. Fill small holes",
    "08_binary_opening": "8. Binary opening",
    "09_largest_component": "9. Largest component",
    "10_fill_holes_final": "10. Fill holes (colony)",
}


def _cmap_for(kind):
    return {"gray": "gray", "heat": "magma", "mask": "gray"}.get(kind, "gray")


def save_steps(stem, steps, gray, colony, info, steps_dir):
    """Save every pipeline step as '<sample>_<method>.png' + a montage.

    Files are named by sample + processing method, e.g.
    'EPC-D0_02_local_std_texture.png'. A combined overview grid named
    'EPC-D0_00_all_steps.png' is also written.
    """
    os.makedirs(steps_dir, exist_ok=True)

    # 1) individual step images.
    for step in steps:
        fname = os.path.join(steps_dir, f"{stem}_{step['method']}.png")
        plt.imsave(fname, step["img"], cmap=_cmap_for(step["kind"]))

    # 2) final overlay (colony outline + center) as its own named image.
    overlay_name = os.path.join(steps_dir, f"{stem}_11_overlay_center.png")
    save_overlay(gray, colony, info, overlay_name)

    # 3) montage of all steps + final overlay.
    panels = steps + [{"method": "11_overlay_center", "img": None, "kind": "overlay"}]
    n = len(panels)
    cols = 4
    rows = int(np.ceil(n / cols))
    fig, axes = plt.subplots(rows, cols, figsize=(4 * cols, 4 * rows))
    axes = np.array(axes).reshape(-1)
    for ax, panel in zip(axes, panels):
        if panel["kind"] == "overlay":
            ax.imshow(gray, cmap="gray")
            for contour in find_contours(colony.astype(float), 0.5):
                ax.plot(contour[:, 1], contour[:, 0], color="cyan", linewidth=1.5)
            if info is not None:
                ax.plot(info["center_x"], info["center_y"], "r+",
                        markersize=16, markeredgewidth=2.5)
            ax.set_title("11. Overlay + center", fontsize=11)
        else:
            ax.imshow(panel["img"], cmap=_cmap_for(panel["kind"]))
            ax.set_title(_STEP_TITLES.get(panel["method"], panel["method"]),
                         fontsize=11)
        ax.set_axis_off()
    for ax in axes[n:]:
        ax.set_axis_off()
    fig.suptitle(f"{stem} — colony segmentation pipeline", fontsize=14)
    fig.tight_layout(rect=[0, 0, 1, 0.98])
    fig.savefig(os.path.join(steps_dir, f"{stem}_00_all_steps.png"),
                dpi=150, bbox_inches="tight")
    plt.close(fig)


def process_one(image_path, out_dir, win, min_frac, steps_dir=None):
    from skimage.io import imsave
    gray = load_gray(image_path)
    record = [] if steps_dir else None
    colony, _ = segment_colony(gray, win=win, min_frac=min_frac, record=record)
    info = describe(colony)

    stem = os.path.splitext(os.path.basename(image_path))[0]
    imsave(os.path.join(out_dir, f"{stem}_colony_mask.png"),
           (colony * 255).astype(np.uint8), check_contrast=False)
    save_overlay(gray, colony, info,
                 os.path.join(out_dir, f"{stem}_colony_overlay.png"))

    if steps_dir:
        save_steps(stem, record, gray, colony, info, steps_dir)

    if info is None:
        print(f"[warn] {stem}: no colony found")
    else:
        print(f"[done] {stem}: center=({info['center_x']}, {info['center_y']}), "
              f"area={info['area_fraction_percent']}%, "
              f"d={info['equivalent_diameter_px']}px, "
              f"solidity={info['solidity']}")
    return stem, info


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--image", required=True, help="image file or a folder")
    ap.add_argument("--out", default="colony_results", help="output folder")
    ap.add_argument("--win", type=int, default=None,
                    help="local-std window in px (default auto from image size)")
    ap.add_argument("--min-frac", type=float, default=0.01,
                    help="min colony size as fraction of image (default 0.01)")
    ap.add_argument("--steps-dir", default="process_images",
                    help="folder for per-step images (default 'process_images')")
    ap.add_argument("--no-steps", action="store_true",
                    help="do not save the per-step process images")
    args = ap.parse_args()

    os.makedirs(args.out, exist_ok=True)
    steps_dir = None if args.no_steps else args.steps_dir
    if steps_dir:
        os.makedirs(steps_dir, exist_ok=True)
    if os.path.isdir(args.image):
        files = [f for f in sorted(glob.glob(os.path.join(args.image, "*")))
                 if f.lower().endswith(_IMG_EXTS)]
    else:
        files = [args.image]
    if not files:
        raise SystemExit("No images found.")

    rows = []
    for f in files:
        stem, info = process_one(f, args.out, args.win, args.min_frac,
                                 steps_dir=steps_dir)
        rows.append((stem, info))

    with open(os.path.join(args.out, "colony_centers.csv"), "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["image", "center_x", "center_y", "area_px",
                    "area_fraction_percent", "equivalent_diameter_px", "solidity"])
        for stem, info in rows:
            if info is None:
                w.writerow([stem, "", "", "", "", "", ""])
            else:
                w.writerow([stem, info["center_x"], info["center_y"],
                            info["area_px"], info["area_fraction_percent"],
                            info["equivalent_diameter_px"], info["solidity"]])
    print(f"\nResults saved to {os.path.abspath(args.out)}")
    if steps_dir:
        print(f"Per-step process images saved to {os.path.abspath(steps_dir)}")


if __name__ == "__main__":
    main()
