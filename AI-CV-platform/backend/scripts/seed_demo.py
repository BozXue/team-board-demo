"""Seed demo projects.

1. ``iPSC 克隆定位`` — imports the prototype's sample images and runs the ported
   colony pipeline, so the platform opens on a working real-data project.
2. ``表面污渍检测`` — a synthetic OK/NG dataset (uneven illumination + dark
   spots + noise) with classification labels, which makes Batch Test metrics,
   error reflow and Copilot debug advice demonstrable without customer data.

Usage::

    python -m scripts.seed_demo [--ipsc-dir /opt/AI-CV-platform/ipsc_texture_classifier]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.db import init_db, session_scope  # noqa: E402
from app.engine.registry import load_nodes  # noqa: E402
from app.models import Project  # noqa: E402
from app.services import (  # noqa: E402
    annotation_service,
    dataset_service,
    pipeline_service,
    project_service,
)
from app.utils.imageio import encode_png, fit_within  # noqa: E402
from sqlalchemy import select  # noqa: E402

IPSC_DEFAULT = Path("/opt/AI-CV-platform/ipsc_texture_classifier")


def _existing(db, name: str) -> Project | None:
    return db.execute(select(Project).where(Project.name == name)).scalar_one_or_none()


def seed_ipsc(ipsc_dir: Path, max_side: int = 2048) -> str | None:
    name = "iPSC 克隆定位（原型示例）"
    with session_scope() as db:
        if _existing(db, name):
            print(f"[skip] 项目已存在: {name}")
            return _existing(db, name).id
        project = project_service.create_project(
            db,
            name=name,
            description="移植 ipsc_texture_classifier 原型：局部纹理分割定位克隆中心并输出形态指标。",
            template_id="ipsc_colony",
            requirement="定位培养皿中 iPSC 克隆的中心位置，输出面积占比与等效直径，面积异常时报警。",
            labels=["OK", "NG"],
        )
        project_id = project.id

        images = sorted(
            p for p in ipsc_dir.glob("*")
            if p.is_file() and p.suffix.lower() in {".bmp", ".png", ".jpg", ".tif", ".tiff"}
        )
        if not images:
            print(f"[warn] 未在 {ipsc_dir} 找到样本图像")
        for path in images:
            # The prototype ships 5120x5120 BMPs; downscale on import so the demo
            # stays responsive while keeping the same texture characteristics.
            from app.utils.imageio import load_image

            image = fit_within(load_image(path), max_side)
            dataset_service.import_bytes(
                db, project_id, f"{path.stem}.png", encode_png(image),
                source="upload", split="test",
                meta={"origin": str(path), "downscaledTo": max_side},
            )
            print(f"[ok] 导入 {path.name} -> {image.shape}")
        print(f"[ok] 项目已创建: {name} ({project_id})")
        return project_id


def _synthetic_frame(rng: np.random.Generator, defects: int, size: int = 512) -> np.ndarray:
    """Bright fabric-like background with uneven illumination, noise and dark spots."""
    yy, xx = np.mgrid[0:size, 0:size].astype(np.float32)
    base = 185.0 + 25.0 * np.sin(xx / size * np.pi) - 18.0 * (yy / size)
    cx, cy = rng.uniform(0.2, 0.8, 2) * size
    base += 22.0 * np.exp(-((xx - cx) ** 2 + (yy - cy) ** 2) / (2 * (size * 0.35) ** 2))
    # Fine fabric texture: visible in the histogram but small enough that
    # morphology + the minimum-area filter can separate it from real spots.
    texture = cv2.GaussianBlur(rng.normal(0, 7, (size, size)).astype(np.float32), (0, 0), 0.8)
    image = np.clip(base + texture + rng.normal(0, 1.5, (size, size)), 0, 255).astype(np.uint8)

    for _ in range(defects):
        radius = int(rng.integers(5, 12))
        x, y = (int(v) for v in rng.integers(radius + 20, size - radius - 20, 2))
        overlay = image.copy()
        cv2.circle(overlay, (x, y), radius, int(rng.integers(30, 80)), -1)
        image = cv2.GaussianBlur(overlay, (5, 5), 0)
    return image


def seed_defect(ok_count: int = 12, ng_count: int = 8) -> str | None:
    name = "白布污渍检测（示例）"
    with session_scope() as db:
        if _existing(db, name):
            print(f"[skip] 项目已存在: {name}")
            return _existing(db, name).id
        project = project_service.create_project(
            db,
            name=name,
            description="合成样本演示数据闭环：批量测试指标、错误样本回流与 Copilot 调试建议。",
            template_id="surface_defect",
            requirement="检测白布上的黑色污点，不允许出现面积大于 50 像素的污点。",
            labels=["OK", "NG"],
        )
        project_id = project.id
        rng = np.random.default_rng(20260811)

        for index in range(ok_count):
            image = _synthetic_frame(rng, defects=0)
            asset = dataset_service.import_bytes(
                db, project_id, f"ok_{index + 1:03d}.png", encode_png(image),
                split="test", meta={"synthetic": True},
            )
            annotation_service.save_annotation(db, project_id, asset.id, label="OK")
        for index in range(ng_count):
            image = _synthetic_frame(rng, defects=int(rng.integers(1, 4)))
            asset = dataset_service.import_bytes(
                db, project_id, f"ng_{index + 1:03d}.png", encode_png(image),
                split="test", meta={"synthetic": True},
            )
            annotation_service.save_annotation(db, project_id, asset.id, label="NG")
        print(f"[ok] 项目已创建: {name} ({project_id})，{ok_count} OK / {ng_count} NG")
        return project_id


def smoke_run(project_id: str) -> None:
    """Execute the project's pipeline on its first image."""
    with session_scope() as db:
        assets, _ = dataset_service.list_images(db, project_id, page=1, page_size=1)
        if not assets:
            print("[warn] 项目没有图像，跳过试运行")
            return
        result = pipeline_service.run_debug(db, project_id, None, image_id=assets[0].id)
        print(
            f"[run] {assets[0].filename}: verdict={result['verdict']} "
            f"耗时={result['totalMs']}ms 节点={len(result['nodes'])} "
            f"错误={len(result['errors'])}"
        )
        for node_id, info in result["nodes"].items():
            flag = "x" if info["status"] != "success" else "."
            print(f"   {flag} {node_id:10s} {info['nodeType']:24s} {info['durationMs']:8.1f}ms "
                  f"{info['error'] or ''}")
        if result["measurements"]:
            print(f"   测量值: {result['measurements']}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ipsc-dir", default=str(IPSC_DEFAULT))
    parser.add_argument("--skip-run", action="store_true")
    args = parser.parse_args()

    load_nodes()
    init_db()

    ipsc_id = seed_ipsc(Path(args.ipsc_dir))
    defect_id = seed_defect()
    if not args.skip_run:
        for project_id in filter(None, (ipsc_id, defect_id)):
            smoke_run(project_id)


if __name__ == "__main__":
    main()
