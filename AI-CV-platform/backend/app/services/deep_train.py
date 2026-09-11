"""Deep classifiers: EfficientNet-B0 and YOLO-cls, trained on project annotations.

These are optional backends. The platform stays usable without torch; the
Models page lists them as unavailable until the extra packages are installed.
Trained weights are exported to ONNX so the existing classify node can run them.
"""

from __future__ import annotations

import importlib.util
import shutil
from pathlib import Path
from typing import Any

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.errors import ValidationError
from app.models import Annotation, ImageAsset, ModelAsset, new_id
from app.services import dataset_service, storage
from app.utils.imageio import load_image, save_jpeg, to_bgr

MIN_DEEP_SAMPLES = 8
IMAGENET_MEAN = (0.485, 0.456, 0.406)
IMAGENET_STD = (0.229, 0.224, 0.225)


def _has(module: str) -> bool:
    return importlib.util.find_spec(module) is not None


def trainer_catalog() -> list[dict[str, Any]]:
    torch_ok = _has("torch") and _has("torchvision")
    yolo_ok = torch_ok and _has("ultralytics")
    return [
        {
            "id": "lbp_svm",
            "name": "LBP + SVM",
            "family": "classical",
            "available": True,
            "hint": "纹理特征 + 支持向量机，无需 GPU，几十张图就能训。",
        },
        {
            "id": "efficientnet",
            "name": "EfficientNet-B0",
            "family": "deep",
            "available": torch_ok,
            "hint": "适合袋装物料、外观分类。训练后导出 ONNX，流程里可直接推理。"
            + ("" if torch_ok else " 未安装 PyTorch：在后端执行 pip install torch torchvision"),
        },
        {
            "id": "yolo",
            "name": "YOLO 分类",
            "family": "deep",
            "available": yolo_ok,
            "hint": "Ultralytics YOLO-cls（默认 yolo11n-cls）。训练后导出 ONNX。"
            + ("" if yolo_ok else " 未安装 ultralytics：pip install ultralytics torch"),
        },
    ]


def materialize_dataset(
    db: Session, project_id: str, dest: Path, splits: list[str] | None = None
) -> dict[str, Any]:
    """Write labelled crops into ``dest/train|val/<class>/`` for ImageFolder / YOLO."""
    query = (
        select(ImageAsset, Annotation)
        .join(Annotation, Annotation.image_id == ImageAsset.id)
        .where(ImageAsset.project_id == project_id)
    )
    if splits:
        query = query.where(ImageAsset.split.in_(splits))
    rows = db.execute(query).all()
    items: list[tuple[np.ndarray, str, str]] = []
    for asset, annotation in rows:
        path = dataset_service.image_source_path(asset, prefer_preview=True)
        try:
            image = to_bgr(load_image(path))
        except Exception:
            continue
        height, width = image.shape[:2]
        split = asset.split if asset.split in {"train", "val"} else "train"
        shapes = [s for s in (annotation.shapes or []) if s.get("label")]
        used = False
        for shape in shapes:
            points = np.array(shape["points"], dtype=np.float32)
            xs = np.clip(points[:, 0] * width, 0, width - 1)
            ys = np.clip(points[:, 1] * height, 0, height - 1)
            x0, x1 = int(xs.min()), int(xs.max())
            y0, y1 = int(ys.min()), int(ys.max())
            if x1 - x0 < 12 or y1 - y0 < 12:
                continue
            items.append((image[y0:y1, x0:x1], str(shape["label"]), split))
            used = True
        if not used and annotation.label:
            items.append((image, str(annotation.label), split))

    if len({label for _, label, _ in items}) < 2 or len(items) < MIN_DEEP_SAMPLES:
        raise ValidationError(
            f"深度模型训练样本不足：当前 {len(items)} 张 / "
            f"{len({label for _, label, _ in items})} 类，至少需要 {MIN_DEEP_SAMPLES} 张、2 个类别"
        )

    if not any(split == "val" for _, _, split in items):
        by_label: dict[str, list[int]] = {}
        for index, (_, label, _) in enumerate(items):
            by_label.setdefault(label, []).append(index)
        val_ids: set[int] = set()
        for indexes in by_label.values():
            take = max(1, len(indexes) // 5)
            val_ids.update(indexes[-take:])
        items = [
            (image, label, "val" if index in val_ids else "train")
            for index, (image, label, _) in enumerate(items)
        ]

    if dest.exists():
        shutil.rmtree(dest)
    counts: dict[str, int] = {}
    for index, (image, label, split) in enumerate(items):
        folder = dest / split / label
        folder.mkdir(parents=True, exist_ok=True)
        save_jpeg(folder / f"{index:05d}.jpg", image, quality=90)
        counts[label] = counts.get(label, 0) + 1
    return {
        "classes": sorted({label for _, label, _ in items}),
        "counts": counts,
        "sampleCount": len(items),
        "train": sum(1 for *_, split in items if split == "train"),
        "val": sum(1 for *_, split in items if split == "val"),
    }


def _register(
    db: Session,
    project_id: str,
    name: str,
    classes: list[str],
    onnx_src: Path,
    imgsz: int,
    metrics: dict,
    meta: dict,
    pt_src: Path | None = None,
) -> ModelAsset:
    model_id = new_id()
    settings.models_dir.mkdir(parents=True, exist_ok=True)
    rel = f"{model_id}.onnx"
    shutil.copy2(onnx_src, settings.models_dir / rel)
    extra = dict(meta)
    if pt_src and pt_src.exists():
        pt_rel = f"{model_id}.pt"
        shutil.copy2(pt_src, settings.models_dir / pt_rel)
        extra["weightsPt"] = pt_rel
    asset = ModelAsset(
        id=model_id,
        project_id=project_id,
        name=name,
        task="classification",
        framework="onnx",
        rel_path=rel,
        classes=classes,
        input_size=imgsz,
        metrics=metrics,
        meta=extra,
    )
    db.add(asset)
    db.flush()
    return asset


def train_efficientnet(
    db: Session,
    project_id: str,
    name: str | None = None,
    splits: list[str] | None = None,
    epochs: int = 8,
    imgsz: int = 384,
    batch: int = 8,
) -> ModelAsset:
    if not (_has("torch") and _has("torchvision")):
        raise ValidationError("未安装 PyTorch。请在后端执行：pip install torch torchvision")

    import torch
    from torch import nn
    from torch.utils.data import DataLoader
    from torchvision import transforms as T
    from torchvision.datasets import ImageFolder
    from torchvision.models import EfficientNet_B0_Weights, efficientnet_b0

    work = storage.run_cache_dir("train", new_id())
    stats = materialize_dataset(db, project_id, work / "data", splits)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    train_tf = T.Compose([
        T.RandomResizedCrop(imgsz, scale=(0.7, 1.0)),
        T.RandomHorizontalFlip(),
        T.ColorJitter(0.15, 0.15, 0.1),
        T.ToTensor(),
        T.Normalize(IMAGENET_MEAN, IMAGENET_STD),
    ])
    eval_tf = T.Compose([
        T.Resize(imgsz),
        T.CenterCrop(imgsz),
        T.ToTensor(),
        T.Normalize(IMAGENET_MEAN, IMAGENET_STD),
    ])
    train_set = ImageFolder(str(work / "data" / "train"), transform=train_tf)
    val_dir = work / "data" / "val"
    val_set = ImageFolder(str(val_dir), transform=eval_tf) if val_dir.exists() else None
    classes = list(train_set.classes)

    try:
        weights = EfficientNet_B0_Weights.IMAGENET1K_V1
    except Exception:
        weights = None
    model = efficientnet_b0(weights=weights)
    model.classifier[1] = nn.Linear(model.classifier[1].in_features, len(classes))
    model.to(device)

    loader = DataLoader(train_set, batch_size=max(1, batch), shuffle=True, num_workers=0)
    val_loader = DataLoader(val_set, batch_size=max(1, batch), shuffle=False, num_workers=0) if val_set else None
    optimizer = torch.optim.AdamW(
        [
            {"params": model.features.parameters(), "lr": 1e-4},
            {"params": model.classifier.parameters(), "lr": 1e-3},
        ],
        weight_decay=0.01,
    )
    criterion = nn.CrossEntropyLoss()
    best_acc = -1.0
    best_path = work / "best.pt"
    history: list[dict] = []

    for epoch in range(1, max(1, epochs) + 1):
        model.train()
        running = 0.0
        seen = 0
        for images, labels in loader:
            images, labels = images.to(device), labels.to(device)
            optimizer.zero_grad()
            loss = criterion(model(images), labels)
            loss.backward()
            optimizer.step()
            running += float(loss.item()) * labels.size(0)
            seen += int(labels.size(0))
        acc = 0.0
        if val_loader:
            model.eval()
            correct = total = 0
            with torch.no_grad():
                for images, labels in val_loader:
                    pred = model(images.to(device)).argmax(1).cpu()
                    correct += int((pred == labels).sum())
                    total += int(labels.numel())
            acc = correct / max(total, 1)
        history.append({"epoch": epoch, "loss": round(running / max(seen, 1), 4), "valAcc": round(acc, 4)})
        if acc >= best_acc:
            best_acc = acc
            torch.save({"model": model.state_dict(), "classes": classes, "imgsz": imgsz,
                        "arch": "efficientnet_b0"}, best_path)

    model.load_state_dict(torch.load(best_path, map_location="cpu", weights_only=False)["model"])
    model.cpu().eval()
    onnx_path = work / "model.onnx"
    dummy = torch.randn(1, 3, imgsz, imgsz)
    torch.onnx.export(model, dummy, str(onnx_path), input_names=["images"], output_names=["logits"],
                      opset_version=17, dynamo=False)
    return _register(
        db, project_id,
        name or f"EfficientNet-B0 ({len(classes)} 类)",
        classes, onnx_path, imgsz,
        {"sampleCount": stats["sampleCount"], "train": stats["train"], "val": stats["val"],
         "valAccuracy": round(float(best_acc), 4), "epochs": epochs},
        {"arch": "efficientnet_b0", "device": str(device), "history": history[-8:],
         "counts": stats.get("counts", {})},
        pt_src=best_path,
    )


def train_yolo(
    db: Session,
    project_id: str,
    name: str | None = None,
    splits: list[str] | None = None,
    epochs: int = 8,
    imgsz: int = 384,
    batch: int = 8,
    base: str = "yolo11n-cls.pt",
) -> ModelAsset:
    if not _has("ultralytics"):
        raise ValidationError("未安装 Ultralytics。请在后端执行：pip install ultralytics torch")

    from ultralytics import YOLO

    work = storage.run_cache_dir("train", new_id())
    stats = materialize_dataset(db, project_id, work / "data", splits)
    model = YOLO(base)
    model.train(
        data=str(work / "data"),
        epochs=max(1, epochs),
        imgsz=imgsz,
        batch=max(1, batch),
        project=str(work / "runs"),
        name="cls",
        exist_ok=True,
        verbose=False,
        pretrained=True,
    )
    best = work / "runs" / "cls" / "weights" / "best.pt"
    if not best.exists():
        raise ValidationError("YOLO 训练结束但没有找到 best.pt")
    trained = YOLO(str(best))
    names = trained.names
    classes = [names[i] for i in sorted(names)] if isinstance(names, dict) else list(names)
    exported = trained.export(format="onnx", imgsz=imgsz, simplify=True, dynamic=False)
    onnx_path = Path(str(exported))
    metrics = {"sampleCount": stats["sampleCount"], "train": stats["train"], "val": stats["val"],
               "epochs": epochs}
    top1 = None
    try:
        top1 = float(trained.trainer.metrics.get("metrics/accuracy_top1", 0))
    except Exception:
        top1 = None
    if top1:
        metrics["valAccuracy"] = round(top1, 4)
    return _register(
        db, project_id,
        name or f"YOLO-cls ({len(classes)} 类)",
        classes, onnx_path, imgsz, metrics,
        {"arch": "yolo-cls", "base": base, "frameworkTrain": "ultralytics"},
        pt_src=best,
    )
