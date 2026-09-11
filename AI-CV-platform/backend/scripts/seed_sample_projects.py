"""Import every folder under ``sample_projects/`` as a platform project.

These sample trees are standalone training repos (class-named image folders,
optional ``config/classes.yaml``, optional ``models/*.onnx``). This script
turns each one into a Project: labels, labelled dataset, registered model
files, and a classification pipeline if enough samples exist.

Safe to re-run: a sample that is already a platform project is skipped.

Usage::

    python -m scripts.seed_sample_projects
    python -m scripts.seed_sample_projects --all          # every image, not per-class cap
    python -m scripts.seed_sample_projects --per-class 20
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select  # noqa: E402

from app.core.db import init_db, session_scope  # noqa: E402
from app.engine.registry import load_nodes  # noqa: E402
from app.models import ModelAsset, Project  # noqa: E402
from app.services import (  # noqa: E402
    annotation_service,
    dataset_service,
    model_service,
    project_service,
)
from app.services.templates import grain_classify_graph  # noqa: E402
from app.utils.imageio import SUPPORTED_EXTS, encode_png, fit_within, load_image  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
SAMPLE_ROOT = ROOT / "sample_projects"
SKIP_DIRS = {".venv", "node_modules", "__pycache__", ".git", "models", "src", "config"}
SPLIT_NAMES = {"train", "val", "valid", "test"}
MODEL_EXTS = {".onnx", ".pt", ".joblib", ".pkl"}
DEFAULT_PER_CLASS = 40
MAX_SIDE = 1280


def _existing(db, name: str) -> Project | None:
    return db.execute(select(Project).where(Project.name == name)).scalar_one_or_none()


def discover_samples(root: Path) -> list[Path]:
    if not root.is_dir():
        return []
    found: list[Path] = []
    for path in sorted(root.iterdir()):
        if not path.is_dir() or path.name.startswith(".") or path.name in SKIP_DIRS:
            continue
        if (path / "README.md").exists() or (path / "data").is_dir() or (path / "rawdata").is_dir():
            found.append(path)
    return found


def project_title(sample_dir: Path) -> str:
    readme = sample_dir / "README.md"
    if readme.exists():
        for line in readme.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith("# "):
                return line[2:].strip()
    return sample_dir.name


def project_description(sample_dir: Path) -> str:
    readme = sample_dir / "README.md"
    if not readme.exists():
        return f"从 sample_projects/{sample_dir.name} 导入"
    lines = [
        line.strip()
        for line in readme.read_text(encoding="utf-8", errors="replace").splitlines()
        if line.strip() and not line.startswith("#") and not line.startswith("```")
    ]
    return (lines[0] if lines else f"从 sample_projects/{sample_dir.name} 导入")[:400]


def class_aliases(sample_dir: Path) -> dict[str, str]:
    """Map folder names / aliases onto the Chinese display label."""
    mapping: dict[str, str] = {}
    yaml_path = sample_dir / "config" / "classes.yaml"
    if not yaml_path.exists():
        return mapping
    current: str | None = None
    for line in yaml_path.read_text(encoding="utf-8", errors="replace").splitlines():
        name_match = re.match(r"\s+name:\s*(.+)$", line)
        if name_match:
            current = name_match.group(1).strip().strip("\"'")
            mapping[current] = current
            continue
        id_match = re.match(r"\s+id:\s*(\S+)$", line)
        if id_match and current:
            mapping[id_match.group(1).strip()] = current
            continue
        alias_match = re.match(r"\s+aliases:\s*\[(.*)\]\s*$", line)
        if alias_match and current:
            for raw in alias_match.group(1).split(","):
                alias = raw.strip().strip("\"'")
                if alias:
                    mapping[alias] = current
    return mapping


def resolve_label(folder_name: str, aliases: dict[str, str]) -> str:
    if folder_name in aliases:
        return aliases[folder_name]
    lowered = folder_name.lower()
    for key, label in aliases.items():
        if key.lower() == lowered:
            return label
    return folder_name


def labeled_images(sample_dir: Path, aliases: dict[str, str]) -> list[tuple[Path, str, str]]:
    """(path, label, split) from conventional class-folder layouts."""
    found: list[tuple[Path, str, str]] = []

    def add_tree(root: Path, default_split: str) -> None:
        if not root.is_dir():
            return
        for class_dir in sorted(p for p in root.iterdir() if p.is_dir()):
            if class_dir.name.startswith(".") or class_dir.name in SKIP_DIRS:
                continue
            split = default_split
            label = resolve_label(class_dir.name, aliases)
            for path in sorted(class_dir.rglob("*")):
                if path.is_file() and path.suffix.lower() in SUPPORTED_EXTS:
                    found.append((path, label, split))

    for split in ("train", "val", "test"):
        add_tree(sample_dir / "data" / split, "val" if split == "val" else split)
        add_tree(sample_dir / "data" / "yolo" / split, "val" if split == "val" else split)

    if found:
        return found

    raw_root = sample_dir / "rawdata"
    if not raw_root.is_dir():
        return found
    for class_dir in sorted(p for p in raw_root.rglob("*") if p.is_dir()):
        if class_dir.name.startswith(".") or class_dir.name in SKIP_DIRS:
            continue
        files = [
            p for p in class_dir.iterdir()
            if p.is_file() and p.suffix.lower() in SUPPORTED_EXTS
        ]
        if not files:
            continue
        label = resolve_label(class_dir.name, aliases)
        for path in sorted(files):
            found.append((path, label, "train"))
    return found


def classify_graph(model_id: str) -> dict:
    return grain_classify_graph(model_id)


def import_models(db, project_id: str, sample_dir: Path) -> int:
    models_dir = sample_dir / "models"
    if not models_dir.is_dir():
        return 0
    imported = 0
    for path in sorted(models_dir.iterdir()):
        if not path.is_file() or path.suffix.lower() not in MODEL_EXTS:
            continue
        sidecar = path.with_suffix(".json")
        classes: list[str] = []
        metrics: dict = {}
        payload: dict = {}
        if sidecar.exists():
            try:
                payload = json.loads(sidecar.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                payload = {}
            raw_classes = payload.get("classes") or {}
            if isinstance(raw_classes, dict):
                classes = [str(v) for _, v in sorted(raw_classes.items(), key=lambda kv: str(kv[0]))]
            elif isinstance(raw_classes, list):
                classes = [str(v) for v in raw_classes]
            if payload.get("best_val_acc") is not None:
                metrics["valAccuracy"] = payload["best_val_acc"]
        imgsz = None
        extra_meta: dict = {"sourceDir": str(path.relative_to(sample_dir))}
        if sidecar.exists():
            extra_meta["arch"] = payload.get("arch") or payload.get("task")
            if payload.get("imgsz"):
                imgsz = int(payload["imgsz"])
        asset = model_service.import_model(
            db, project_id, path.stem, path.name, path.read_bytes(),
            task="classification", classes=classes, input_size=imgsz, meta=extra_meta,
        )
        if metrics:
            asset.metrics = {**(asset.metrics or {}), **metrics}
        imported += 1
        print(f"    模型 {path.name} -> {asset.framework} ({asset.id})")
    return imported


def seed_one(sample_dir: Path, per_class: int | None, train: bool) -> str | None:
    name = project_title(sample_dir)
    aliases = class_aliases(sample_dir)
    images = labeled_images(sample_dir, aliases)
    if not images:
        print(f"[skip] {sample_dir.name}: 没有找到按类别分好的图像")
        return None

    with session_scope() as db:
        existing = _existing(db, name)
        if existing is not None:
            print(f"[skip] 项目已存在: {name} ({existing.id})")
            return existing.id

        labels = sorted({label for _, label, _ in images})
        project = project_service.create_project(
            db,
            name=name,
            description=project_description(sample_dir),
            template_id="blank",
            requirement="识别图像所属类别（来自 sample_projects 的已标注样本）。",
            labels=labels,
        )
        project.task_type = "classification"
        project.meta = {**(project.meta or {}), "source": str(sample_dir.relative_to(ROOT))}
        project_id = project.id

        taken: dict[str, int] = {}
        imported = 0
        skipped = 0
        for path, label, split in images:
            if per_class is not None and taken.get(label, 0) >= per_class:
                skipped += 1
                continue
            try:
                image = fit_within(load_image(path), MAX_SIDE)
            except Exception as exc:  # noqa: BLE001
                print(f"    [warn] 读图失败 {path.name}: {exc}")
                continue
            filename = f"{label}_{path.stem}.png"
            payload = encode_png(image)
            asset = dataset_service.import_bytes(
                db, project_id, filename, payload,
                source="folder", split=split,
                meta={"origin": str(path.relative_to(sample_dir)), "class": label},
            )
            annotation_service.save_annotation(db, project_id, asset.id, label=label)
            taken[label] = taken.get(label, 0) + 1
            imported += 1
        n_models = import_models(db, project_id, sample_dir)
        onnx_models = list(
            db.execute(
                select(ModelAsset).where(
                    ModelAsset.project_id == project_id,
                    ModelAsset.framework == "onnx",
                )
            ).scalars().all()
        )
        onnx = next((item for item in onnx_models if "yolo" in item.name.lower()), None) or (
            onnx_models[0] if onnx_models else None
        )
        if onnx is not None:
            project_service.save_graph(db, project_id, classify_graph(onnx.id))
            print(f"    已把 ONNX {onnx.name} ({onnx.id}) 接到谷物分类流程")
        print(
            f"[ok] {name} ({project_id}) 导入 {imported} 张"
            + (f"，另跳过 {skipped} 张（每类上限 {per_class}）" if skipped else "")
            + f"，类别 {taken}，外部模型 {n_models} 个"
        )

    if train:
        with session_scope() as db:
            try:
                model = model_service.train_classifier(
                    db, project_id, name=f"{sample_dir.name} LBP+SVM",
                )
                existing = db.get(Project, project_id)
                has_graph = bool(existing and (existing.graph or {}).get("nodes"))
                if not has_graph:
                    project_service.save_graph(db, project_id, classify_graph(model.id))
                print(
                    f"    已训练 {model.name} cv={ (model.metrics or {}).get('cvAccuracy') }"
                    + ("（流程已使用 ONNX，未覆盖）" if has_graph else "，并接到 AI 分类节点")
                )
            except Exception as exc:  # noqa: BLE001
                print(f"    [warn] 未训练平台分类器：{exc}")
    return project_id


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=str(SAMPLE_ROOT), help="sample_projects 根目录")
    parser.add_argument("--per-class", type=int, default=DEFAULT_PER_CLASS,
                        help="每类最多导入多少张；0 表示全部")
    parser.add_argument("--all", action="store_true", help="导入全部图像（忽略 --per-class）")
    parser.add_argument("--train", action="store_true", help="额外训练 LBP+SVM；已有 ONNX 时默认只接 ONNX")
    args = parser.parse_args()

    load_nodes()
    init_db()
    root = Path(args.root)
    samples = discover_samples(root)
    if not samples:
        print(f"[warn] {root} 下没有可导入的示例项目")
        return

    per_class = None if args.all or args.per_class <= 0 else args.per_class
    print(f"发现 {len(samples)} 个示例：{', '.join(p.name for p in samples)}")
    for sample_dir in samples:
        seed_one(sample_dir, per_class=per_class, train=args.train)


if __name__ == "__main__":
    main()
