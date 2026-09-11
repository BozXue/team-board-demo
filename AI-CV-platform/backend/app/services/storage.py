"""On-disk project layout.

::

    data/projects/<project_id>/
        project.json        项目元信息（导出用，DB 之外的可读副本）
        pipeline.json       当前 Pipeline
        images/             原始图像
        thumbs/  previews/  浏览与调试用的缩放副本
        annotations/        标注导出
        results/            批量测试与生产结果
        logs/               运行日志
        models/             项目模型
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from app.core.config import settings

SUBDIRS = ("images", "thumbs", "previews", "annotations", "results", "logs", "models")


def project_dir(project_id: str) -> Path:
    return settings.projects_dir / project_id


def ensure_project_dirs(project_id: str) -> Path:
    root = project_dir(project_id)
    for name in SUBDIRS:
        (root / name).mkdir(parents=True, exist_ok=True)
    return root


def delete_project_dir(project_id: str) -> None:
    shutil.rmtree(project_dir(project_id), ignore_errors=True)


def copy_project_dir(source_id: str, target_id: str) -> None:
    source = project_dir(source_id)
    target = project_dir(target_id)
    if source.exists():
        shutil.copytree(source, target, dirs_exist_ok=True)
    ensure_project_dirs(target_id)


def abs_path(project_id: str, rel_path: str) -> Path:
    return project_dir(project_id) / rel_path


def write_project_files(project_id: str, meta: dict, graph: dict) -> None:
    """Keep the human-readable project.json / pipeline.json in sync."""
    root = ensure_project_dirs(project_id)
    (root / "project.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    (root / "pipeline.json").write_text(
        json.dumps(graph, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )


def debug_cache_dir(project_id: str, image_id: str) -> Path:
    path = settings.cache_dir / "debug" / project_id / (image_id or "none")
    path.mkdir(parents=True, exist_ok=True)
    return path


def debug_cache_url(project_id: str, image_id: str) -> str:
    return f"/api/artifacts/debug/{project_id}/{image_id or 'none'}"


def run_cache_dir(kind: str, run_id: str) -> Path:
    path = settings.cache_dir / kind / run_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def run_cache_url(kind: str, run_id: str) -> str:
    return f"/api/artifacts/{kind}/{run_id}"


def unique_name(folder: Path, filename: str) -> str:
    """Avoid clobbering an existing file with the same name."""
    candidate = Path(filename).name
    stem, suffix = Path(candidate).stem, Path(candidate).suffix
    index = 1
    while (folder / candidate).exists():
        candidate = f"{stem}_{index}{suffix}"
        index += 1
    return candidate


def dir_size_bytes(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())
