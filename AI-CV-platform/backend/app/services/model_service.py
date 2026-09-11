"""Model service: train / import / inference for classical classifiers.

Phase 5 of the plan starts with inference plus light training, deliberately
avoiding a GPU training platform. The trainer here consumes exactly what the
annotation module produces (image labels or labelled boxes) and produces the
LBP+SVM model the iPSC prototype planned, so the data loop closes end to end.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cv2
import joblib
import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.errors import NotFoundError, ValidationError
from app.engine.algorithms import texture as tex
from app.models import Annotation, ImageAsset, ModelAsset, new_id
from app.services import dataset_service
from app.utils.imageio import load_image, to_bgr, to_gray

_CACHE: dict[str, "LoadedModel"] = {}
_LOCK = threading.Lock()
MIN_PATCH = 12
IMAGENET_MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
IMAGENET_STD = np.array([0.229, 0.224, 0.225], dtype=np.float32)


@dataclass
class LoadedModel:
    kind: str
    classes: list[str]
    estimator: Any = None
    session: Any = None
    input_name: str = "images"
    output_name: str = "output0"
    imgsz: int = 64
    preprocess: str = "lbp"


def list_models(db: Session, project_id: str | None = None) -> list[dict]:
    query = select(ModelAsset).order_by(ModelAsset.created_at.desc())
    if project_id:
        query = query.where(
            (ModelAsset.project_id == project_id) | (ModelAsset.project_id.is_(None))
        )
    return [to_dict(model) for model in db.execute(query).scalars().all()]


def to_dict(model: ModelAsset) -> dict:
    return {
        "id": model.id,
        "projectId": model.project_id,
        "name": model.name,
        "task": model.task,
        "framework": model.framework,
        "classes": model.classes or [],
        "inputSize": model.input_size,
        "metrics": model.metrics or {},
        "meta": model.meta or {},
        "createdAt": model.created_at,
        "available": bool(model.rel_path and (settings.models_dir / model.rel_path).exists()),
    }


def get_model(db: Session, model_id: str) -> ModelAsset:
    model = db.get(ModelAsset, model_id)
    if model is None:
        raise NotFoundError(f"模型不存在: {model_id}")
    return model


def delete_model(db: Session, model_id: str) -> None:
    model = get_model(db, model_id)
    if model.rel_path:
        (settings.models_dir / model.rel_path).unlink(missing_ok=True)
    with _LOCK:
        _CACHE.pop(model_id, None)
    db.delete(model)


# -- training ------------------------------------------------------------
def collect_samples(db: Session, project_id: str, splits: list[str] | None = None) -> tuple[list[np.ndarray], list[str], dict]:
    """Gather labelled patches:每个 bbox/polygon 标注一个样本，否则整图一个样本。"""
    query = (
        select(ImageAsset, Annotation)
        .join(Annotation, Annotation.image_id == ImageAsset.id)
        .where(ImageAsset.project_id == project_id)
    )
    if splits:
        query = query.where(ImageAsset.split.in_(splits))
    rows = db.execute(query).all()

    patches: list[np.ndarray] = []
    labels: list[str] = []
    stats = {"images": 0, "fromShapes": 0, "fromImageLabel": 0, "skipped": 0}

    for asset, annotation in rows:
        path = dataset_service.image_source_path(asset, prefer_preview=True)
        try:
            gray = to_gray(load_image(path))
        except Exception:  # noqa: BLE001
            stats["skipped"] += 1
            continue
        stats["images"] += 1
        height, width = gray.shape[:2]

        shapes = [s for s in (annotation.shapes or []) if s.get("label")]
        used_shape = False
        for shape in shapes:
            points = np.array(shape["points"], dtype=np.float32)
            xs = np.clip(points[:, 0] * width, 0, width - 1)
            ys = np.clip(points[:, 1] * height, 0, height - 1)
            x0, x1 = int(xs.min()), int(xs.max())
            y0, y1 = int(ys.min()), int(ys.max())
            if x1 - x0 < MIN_PATCH or y1 - y0 < MIN_PATCH:
                continue
            patches.append(gray[y0:y1, x0:x1])
            labels.append(shape["label"])
            used_shape = True
            stats["fromShapes"] += 1
        if not used_shape and annotation.label:
            patches.append(gray)
            labels.append(annotation.label)
            stats["fromImageLabel"] += 1
    return patches, labels, stats


def train_classifier(
    db: Session,
    project_id: str,
    name: str | None = None,
    splits: list[str] | None = None,
    kernel: str = "rbf",
    c_value: float = 10.0,
    arch: str = "lbp_svm",
    epochs: int = 8,
    imgsz: int = 384,
    batch: int = 8,
    yolo_base: str = "yolo11n-cls.pt",
) -> ModelAsset:
    arch = (arch or "lbp_svm").strip().lower()
    if arch in {"efficientnet", "efficientnet_b0", "effnet"}:
        from app.services.deep_train import train_efficientnet

        return train_efficientnet(
            db, project_id, name=name, splits=splits, epochs=epochs, imgsz=imgsz, batch=batch,
        )
    if arch in {"yolo", "yolo_cls", "yolo-cls"}:
        from app.services.deep_train import train_yolo

        return train_yolo(
            db, project_id, name=name, splits=splits, epochs=epochs, imgsz=imgsz,
            batch=batch, base=yolo_base,
        )
    if arch not in {"lbp_svm", "svm", "lbp"}:
        raise ValidationError(f"不支持的训练架构: {arch}（可选 lbp_svm / efficientnet / yolo）")
    return _train_lbp_svm(db, project_id, name=name, splits=splits, kernel=kernel, c_value=c_value)


def _train_lbp_svm(
    db: Session,
    project_id: str,
    name: str | None = None,
    splits: list[str] | None = None,
    kernel: str = "rbf",
    c_value: float = 10.0,
) -> ModelAsset:
    from sklearn.model_selection import cross_val_score
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler
    from sklearn.svm import SVC

    patches, labels, stats = collect_samples(db, project_id, splits)
    unique = sorted(set(labels))
    if len(patches) < 4 or len(unique) < 2:
        raise ValidationError(
            f"训练样本不足：当前 {len(patches)} 个样本 / {len(unique)} 个类别，"
            "至少需要 2 个类别、4 个已标注样本（可在数据页做分类或框选标注）"
        )

    features = np.stack([tex.extract_features(patch) for patch in patches])
    targets = np.array(labels)
    model = make_pipeline(
        StandardScaler(),
        SVC(kernel=kernel, C=c_value, probability=True, class_weight="balanced"),
    )

    metrics: dict[str, Any] = {"sampleCount": int(len(patches)), **stats}
    folds = min(5, int(np.bincount(np.unique(targets, return_inverse=True)[1]).min()))
    if folds >= 2:
        scores = cross_val_score(model, features, targets, cv=folds)
        metrics["cvAccuracy"] = round(float(scores.mean()), 4)
        metrics["cvStd"] = round(float(scores.std()), 4)
        metrics["cvFolds"] = int(folds)
    model.fit(features, targets)
    metrics["trainAccuracy"] = round(float(model.score(features, targets)), 4)

    model_id = new_id()
    rel_path = f"{model_id}.joblib"
    settings.models_dir.mkdir(parents=True, exist_ok=True)
    joblib.dump({"model": model, "classes": unique, "featureDim": int(features.shape[1])},
                settings.models_dir / rel_path)

    asset = ModelAsset(
        id=model_id,
        project_id=project_id,
        name=name or f"LBP+SVM 分类器 ({len(unique)} 类)",
        task="classification",
        framework="sklearn",
        rel_path=rel_path,
        classes=unique,
        input_size=tex.TILE_SIZE,
        metrics=metrics,
        meta={
            "features": "intensity_histogram + multi-scale uniform LBP",
            "featureDim": int(features.shape[1]),
            "lbpScales": [list(s) for s in tex.LBP_SCALES],
            "kernel": kernel,
            "C": c_value,
        },
    )
    db.add(asset)
    db.flush()
    return asset


def import_model(db: Session, project_id: str | None, name: str, filename: str, data: bytes,
                 task: str = "classification", classes: list[str] | None = None,
                 input_size: int | None = None, meta: dict | None = None) -> ModelAsset:
    """Register an external model file. Runtime support depends on the task."""
    suffix = Path(filename).suffix.lower()
    if suffix == ".pt" and "sam" in filename.lower() and task in ("classification", ""):
        task = "segmentation"
    model_id = new_id()
    rel_path = f"{model_id}{suffix}"
    settings.models_dir.mkdir(parents=True, exist_ok=True)
    (settings.models_dir / rel_path).write_bytes(data)
    framework = {".joblib": "sklearn", ".pkl": "sklearn", ".onnx": "onnx", ".pt": "pytorch"}.get(
        suffix, "unknown"
    )
    extra = {"importedFrom": filename, "sizeBytes": len(data), **(meta or {})}
    asset = ModelAsset(
        id=model_id,
        project_id=project_id,
        name=name or filename,
        task=task,
        framework=framework,
        rel_path=rel_path,
        classes=classes or [],
        input_size=int(input_size or 64),
        metrics={},
        meta=extra,
    )
    db.add(asset)
    db.flush()
    return asset


# -- inference -----------------------------------------------------------
def _onnx_sibling(db: Session, asset: ModelAsset) -> ModelAsset | None:
    """A .pt file is the training artefact; the runnable copy is the .onnx of the same name."""
    query = select(ModelAsset).where(
        ModelAsset.framework == "onnx",
        ModelAsset.name == asset.name,
    )
    if asset.project_id:
        query = query.where(ModelAsset.project_id == asset.project_id)
    return db.execute(query).scalars().first()


def _preprocess_kind(asset: ModelAsset, output_name: str) -> str:
    meta = asset.meta or {}
    arch = str(meta.get("arch") or asset.name or "").lower()
    if "effnet" in arch or "efficientnet" in arch or output_name == "logits":
        return "imagenet"
    return "yolo"


def _letterbox(bgr: np.ndarray, size: int, pad: int = 114) -> np.ndarray:
    height, width = bgr.shape[:2]
    scale = size / max(height, width)
    new_h, new_w = max(1, int(round(height * scale))), max(1, int(round(width * scale)))
    resized = cv2.resize(bgr, (new_w, new_h), interpolation=cv2.INTER_LINEAR)
    canvas = np.full((size, size, 3), pad, dtype=np.uint8)
    top, left = (size - new_h) // 2, (size - new_w) // 2
    canvas[top:top + new_h, left:left + new_w] = resized
    return canvas


def _center_crop(bgr: np.ndarray, size: int) -> np.ndarray:
    height, width = bgr.shape[:2]
    scale = size / min(height, width)
    resized = cv2.resize(
        bgr,
        (max(1, int(round(width * scale))), max(1, int(round(height * scale)))),
        interpolation=cv2.INTER_LINEAR,
    )
    rh, rw = resized.shape[:2]
    y0, x0 = max(0, (rh - size) // 2), max(0, (rw - size) // 2)
    return resized[y0:y0 + size, x0:x0 + size]


def _nchw(rgb: np.ndarray, imagenet: bool) -> np.ndarray:
    blob = rgb.astype(np.float32) / 255.0
    if imagenet:
        blob = (blob - IMAGENET_MEAN) / IMAGENET_STD
    return np.transpose(blob, (2, 0, 1))[None]


def _as_probs(raw: np.ndarray) -> np.ndarray:
    vec = np.asarray(raw, dtype=np.float32).reshape(-1)
    total = float(np.sum(vec))
    if vec.min() >= 0 and abs(total - 1.0) < 0.08:
        return vec
    shifted = vec - float(vec.max())
    exp = np.exp(shifted)
    return exp / max(float(exp.sum()), 1e-9)


def _load_onnx(path: Path, asset: ModelAsset) -> LoadedModel:
    try:
        import onnxruntime as ort
    except ImportError as exc:
        raise ValidationError("未安装 onnxruntime，无法运行 ONNX 分类模型") from exc
    session = ort.InferenceSession(str(path), providers=["CPUExecutionProvider"])
    inp = session.get_inputs()[0]
    out = session.get_outputs()[0]
    shape = [dim for dim in inp.shape if isinstance(dim, int) and dim > 0]
    imgsz = int(asset.input_size) if asset.input_size and asset.input_size > 64 else 384
    if len(shape) >= 4:
        imgsz = int(shape[-1])
    classes = list(asset.classes or [])
    if not classes:
        classes = [str(index) for index in range(int(out.shape[-1] or 0) or 0)]
    return LoadedModel(
        kind="onnx",
        classes=classes,
        session=session,
        input_name=inp.name,
        output_name=out.name,
        imgsz=imgsz,
        preprocess=_preprocess_kind(asset, out.name),
    )


def _load(model_id: str) -> LoadedModel:
    if not model_id:
        raise ValidationError("未选择模型：请在节点参数中填写模型 ID（模型页面可训练或导入）")
    with _LOCK:
        cached = _CACHE.get(model_id)
    if cached is not None:
        return cached

    from app.core.db import session_scope

    with session_scope() as db:
        asset = db.get(ModelAsset, model_id)
        if asset is None:
            raise NotFoundError(f"模型不存在: {model_id}")
        path = settings.models_dir / asset.rel_path
        if asset.framework == "pytorch":
            sibling = _onnx_sibling(db, asset)
            if sibling is None:
                raise ValidationError(
                    f"模型 {asset.name} 是 PyTorch 权重（.pt），平台用 ONNX 推理。"
                    "请在节点里改选同名的 .onnx，或重新导入对应的 onnx 文件。"
                )
            path = settings.models_dir / sibling.rel_path
            asset = sibling
        if not path.exists():
            raise NotFoundError(f"模型文件缺失: {path.name}")
        if asset.framework == "sklearn" or path.suffix.lower() in {".joblib", ".pkl"}:
            bundle = joblib.load(path)
            loaded = LoadedModel(
                kind="sklearn",
                classes=list(bundle.get("classes") or asset.classes or []),
                estimator=bundle["model"],
            )
        elif asset.framework == "onnx" or path.suffix.lower() == ".onnx":
            loaded = _load_onnx(path, asset)
        else:
            raise ValidationError(
                f"模型 {asset.name} 的推理后端 {asset.framework} 尚未接入（接口已预留）"
            )

    with _LOCK:
        _CACHE[model_id] = loaded
    return loaded


def _predict_onnx(loaded: LoadedModel, image: np.ndarray) -> tuple[str, float, list[str]]:
    bgr = to_bgr(image)
    if loaded.preprocess == "imagenet":
        patch = _center_crop(bgr, loaded.imgsz)
        rgb = cv2.cvtColor(patch, cv2.COLOR_BGR2RGB)
        blob = _nchw(rgb, imagenet=True)
    else:
        patch = _letterbox(bgr, loaded.imgsz)
        rgb = cv2.cvtColor(patch, cv2.COLOR_BGR2RGB)
        blob = _nchw(rgb, imagenet=False)
    raw = loaded.session.run([loaded.output_name], {loaded.input_name: blob})[0]
    probs = _as_probs(raw)
    if loaded.classes and len(loaded.classes) != len(probs):
        classes = loaded.classes[: len(probs)] or [str(i) for i in range(len(probs))]
    else:
        classes = loaded.classes or [str(i) for i in range(len(probs))]
    index = int(np.argmax(probs))
    return str(classes[index]), float(probs[index]), list(classes)


def predict_image(model_id: str, image: np.ndarray) -> tuple[str, float, list[str]]:
    loaded = _load(model_id)
    if loaded.kind == "onnx":
        return _predict_onnx(loaded, image)
    model = loaded.estimator
    classes = loaded.classes
    patch = to_gray(image)
    if min(patch.shape[:2]) < MIN_PATCH:
        scale = MIN_PATCH / max(1, min(patch.shape[:2]))
        patch = cv2.resize(patch, None, fx=scale, fy=scale, interpolation=cv2.INTER_LINEAR)
    features = tex.extract_features(patch).reshape(1, -1)
    label = str(model.predict(features)[0])
    confidence = 1.0
    if hasattr(model, "predict_proba"):
        probabilities = model.predict_proba(features)[0]
        confidence = float(probabilities.max())
    return label, confidence, classes


def predict_tiles(model_id: str, gray: np.ndarray, tile: int, stride: int) -> tuple[np.ndarray, list[str]]:
    """Classify every tile; returns a label-index grid and the class list."""
    loaded = _load(model_id)
    patch_size = max(MIN_PATCH, int(tile))
    stride = max(1, int(stride))
    height, width = gray.shape[:2]
    positions = list(tex.tile_positions((height, width), patch_size, stride))
    if not positions:
        raise ValidationError("图像尺寸小于分块大小")
    classes = loaded.classes
    index_of = {name: index for index, name in enumerate(classes)}
    rows = len({y for y, _ in positions})
    cols = len({x for _, x in positions})

    if loaded.kind == "onnx":
        labels = []
        color = to_bgr(gray)
        for y, x in positions:
            name, _, _ = _predict_onnx(loaded, color[y:y + patch_size, x:x + patch_size])
            labels.append(index_of.get(name, 0))
        return np.array(labels, dtype=np.int32).reshape(rows, cols), classes

    model = loaded.estimator
    features = np.stack([
        tex.extract_features(to_gray(gray)[y:y + patch_size, x:x + patch_size]) for y, x in positions
    ])
    predictions = model.predict(features)
    grid = np.array([index_of.get(str(p), 0) for p in predictions], dtype=np.int32)
    return grid.reshape(rows, cols), classes


def export_model_path(db: Session, model_id: str) -> Path:
    model = get_model(db, model_id)
    path = settings.models_dir / model.rel_path
    if not path.exists():
        raise NotFoundError("模型文件不存在")
    return path
