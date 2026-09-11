"""离线种类识别：优先 EfficientNet-B0 自有权重，其次 YOLO。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image

from preprocess import PreparedImage, bgr_to_rgb, prepare
from taxonomy import EFFNET_WEIGHTS, RAW_DIR, YOLO_WEIGHTS, load_species


@dataclass
class Prediction:
    species_name: str
    species_id: str
    confidence: float
    ranking: list[tuple[str, float]]
    backend: str
    roi_rgb: np.ndarray
    note: str = ""


_YOLO_MODEL = None
_YOLO_PATH: Path | None = None


def default_weights() -> Path:
    if EFFNET_WEIGHTS.exists():
        return EFFNET_WEIGHTS
    return YOLO_WEIGHTS


def _is_effnet(path: Path) -> bool:
    if path.suffix == ".onnx" and "effnet" in path.name:
        return True
    try:
        import torch

        ckpt = torch.load(path, map_location="cpu", weights_only=False)
        return isinstance(ckpt, dict) and ckpt.get("arch") == "efficientnet_b0"
    except Exception:
        return False


def _load_yolo(weights: Path):
    global _YOLO_MODEL, _YOLO_PATH
    if not weights.exists():
        return None
    if _YOLO_MODEL is None or _YOLO_PATH != weights.resolve():
        from ultralytics import YOLO

        _YOLO_MODEL = YOLO(str(weights))
        _YOLO_PATH = weights.resolve()
    return _YOLO_MODEL


def _yolo_ranking(roi_rgb: np.ndarray, weights: Path) -> list[tuple[str, float]]:
    model = _load_yolo(weights)
    assert model is not None
    results = model.predict(source=Image.fromarray(roi_rgb), verbose=False)
    probs = results[0].probs
    names = results[0].names
    scores = probs.data.cpu().numpy()
    ranking = [(names[i], float(scores[i])) for i in range(len(names))]
    ranking.sort(key=lambda item: item[1], reverse=True)
    return ranking


def resolve_image(path: str) -> Path:
    candidate = Path(path)
    if candidate.exists():
        return candidate
    hits = list(RAW_DIR.rglob(path)) if RAW_DIR.exists() else []
    if hits:
        return hits[0]
    raise FileNotFoundError(f"找不到图片: {path}")


def predict_image(
    path: str,
    prepared: PreparedImage | None = None,
    weights: Path | None = None,
) -> Prediction:
    species = load_species()
    image_path = resolve_image(path)
    prepared = prepared or prepare(str(image_path))
    roi_rgb = bgr_to_rgb(prepared.roi_bgr)
    id_map = {item.name: item.id for item in species}
    weight_path = Path(weights) if weights is not None else default_weights()

    if weight_path.exists() and _is_effnet(weight_path):
        from effnet import predict_roi

        ranking = predict_roi(roi_rgb, weight_path)
        top_name, top_p = ranking[0]
        return Prediction(
            species_name=top_name,
            species_id=id_map.get(top_name, top_name),
            confidence=float(top_p),
            ranking=ranking,
            backend=f"EfficientNet-B0 · {weight_path.name}",
            roi_rgb=roi_rgb,
        )

    if weight_path.exists() and _load_yolo(weight_path) is not None:
        ranking = _yolo_ranking(roi_rgb, weight_path)
        top_name, top_p = ranking[0]
        return Prediction(
            species_name=top_name,
            species_id=id_map.get(top_name, top_name),
            confidence=float(top_p),
            ranking=ranking,
            backend=f"YOLO 离线 · {weight_path.name}",
            roi_rgb=roi_rgb,
        )

    return Prediction(
        species_name="未识别",
        species_id="unknown",
        confidence=0.0,
        ranking=[(item.name, 0.0) for item in species],
        backend="无本地权重",
        roi_rgb=roi_rgb,
        note="没有 EfficientNet 或 YOLO 权重。先 python src/train_effnet.py。",
    )


if __name__ == "__main__":
    import argparse
    import json
    import sys

    root = Path(__file__).resolve().parents[1]
    if str(root / "src") not in sys.path:
        sys.path.insert(0, str(root / "src"))

    parser = argparse.ArgumentParser(description="离线识别一张密封袋谷物照片")
    parser.add_argument("image")
    parser.add_argument(
        "--weights",
        default=None,
        help="默认优先 models/grain_effnet.pt，否则 grain_yolo.pt",
    )
    args = parser.parse_args()
    result = predict_image(
        args.image,
        weights=Path(args.weights) if args.weights else None,
    )
    print(
        json.dumps(
            {
                "species": result.species_name,
                "confidence": round(result.confidence, 4),
                "backend": result.backend,
                "ranking": [[n, round(p, 4)] for n, p in result.ranking[:5]],
                "note": result.note,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
