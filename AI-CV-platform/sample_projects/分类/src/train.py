"""用 YOLO 分类模型微调密封袋谷物种类识别。

数据：data/train/<种类名>/*.jpg
默认底座：yolo11n-cls（没有检测框，整张粮面认种类）。
"""

from __future__ import annotations

import argparse
import random
import shutil
import sys
from pathlib import Path

import cv2
import torch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from preprocess import prepare  # noqa: E402
from taxonomy import (  # noqa: E402
    IMAGE_SUFFIXES,
    MODEL_DIR,
    RAW_DIR,
    TRAIN_DIR,
    VAL_DIR,
    YOLO_DATA_DIR,
    YOLO_WEIGHTS,
    folder_to_species,
)


def _list_images(folder: Path) -> list[Path]:
    if not folder.exists():
        return []
    return sorted(
        p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in IMAGE_SUFFIXES
    )


def _add_images(
    gathered: dict[str, dict[str, list[Path]]],
    name: str,
    split: str,
    images: list[Path],
) -> None:
    if not images:
        return
    gathered.setdefault(name, {"train": [], "val": []})
    existing = {p.resolve() for bucket in gathered[name].values() for p in bucket}
    for path in images:
        if path.resolve() not in existing:
            gathered[name][split].append(path)
            existing.add(path.resolve())


def _collect_by_class() -> dict[str, dict[str, list[Path]]]:
    mapping = folder_to_species()
    gathered: dict[str, dict[str, list[Path]]] = {}

    for split, root in (("train", TRAIN_DIR), ("val", VAL_DIR)):
        if not root.exists():
            continue
        for folder in sorted(p for p in root.iterdir() if p.is_dir()):
            item = mapping.get(folder.name)
            if item is None:
                print(f"跳过未登记种类: {folder.name}")
                continue
            _add_images(gathered, item.name, split, _list_images(folder))

    if RAW_DIR.exists():
        print(f"读取 rawdata: {RAW_DIR}")
        for folder in sorted(p for p in RAW_DIR.iterdir() if p.is_dir()):
            item = mapping.get(folder.name)
            if item is None:
                print(f"跳过未登记 rawdata 目录: {folder.name}")
                continue
            images = _list_images(folder)
            print(f"  {folder.name} → {item.name}: {len(images)} 张")
            _add_images(gathered, item.name, "train", images)

    return gathered


def _split_if_needed(gathered: dict[str, dict[str, list[Path]]]) -> dict[str, dict[str, list[Path]]]:
    rng = random.Random(42)
    has_val = any(item["val"] for item in gathered.values())
    if has_val:
        return gathered

    print("data/val 为空，从训练集按 8:2 划分验证集。")
    for name, splits in gathered.items():
        paths = list(splits["train"])
        rng.shuffle(paths)
        if len(paths) == 1:
            print(f"  {name} 只有 1 张，训练和验证会用同一张（仅作占位）。")
            splits["val"] = paths
            continue
        n_val = max(1, round(len(paths) * 0.2))
        splits["val"] = paths[:n_val]
        splits["train"] = paths[n_val:]
    return gathered


def _write_yolo_image(src: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    prepared = prepare(str(src))
    ok, buf = cv2.imencode(".jpg", prepared.roi_bgr, [int(cv2.IMWRITE_JPEG_QUALITY), 95])
    if not ok:
        raise RuntimeError(f"无法写出 {dest}")
    dest.write_bytes(buf.tobytes())


def build_yolo_dataset() -> Path:
    gathered = _collect_by_class()
    if len(gathered) < 2:
        raise SystemExit("至少需要两个种类、各若干张照片才能训练。放到 data/train/<种类名>/")

    gathered = _split_if_needed(gathered)
    if YOLO_DATA_DIR.exists():
        shutil.rmtree(YOLO_DATA_DIR)

    total = 0
    for name, splits in gathered.items():
        print(f"{name}: train {len(splits['train'])}  val {len(splits['val'])}")
        if len(splits["train"]) < 8:
            print(f"  警告：{name} 训练图偏少，建议至少 20 张，80 张更稳。")
        for split, paths in splits.items():
            for index, src in enumerate(paths):
                dest = YOLO_DATA_DIR / split / name / f"{src.stem}_{index:03d}.jpg"
                try:
                    _write_yolo_image(src, dest)
                    total += 1
                    if total % 50 == 0:
                        print(f"  已处理 {total} 张...")
                except Exception as exc:  # noqa: BLE001
                    print(f"  跳过 {src}: {exc}")

    if total == 0:
        raise SystemExit("没有成功写出任何训练图片。")
    return YOLO_DATA_DIR


def pick_device() -> str | int:
    if torch.cuda.is_available():
        return 0
    if torch.backends.mps.is_available():
        return "mps"
    return "cpu"


def main() -> None:
    parser = argparse.ArgumentParser(description="YOLO 分类微调：密封袋谷物种类")
    parser.add_argument("--model", default="yolo11n-cls.pt", help="底座权重，例如 yolo11n-cls.pt / yolo11s-cls.pt")
    parser.add_argument("--epochs", type=int, default=80)
    parser.add_argument("--imgsz", type=int, default=384, help="袋面纹理需要比 224 更大的输入")
    parser.add_argument("--batch", type=int, default=16)
    args = parser.parse_args()

    data_dir = build_yolo_dataset()
    MODEL_DIR.mkdir(parents=True, exist_ok=True)

    from ultralytics import YOLO

    device = pick_device()
    print(f"底座 {args.model}  ·  device={device}  ·  数据 {data_dir}")
    model = YOLO(args.model)
    results = model.train(
        data=str(data_dir),
        epochs=args.epochs,
        imgsz=args.imgsz,
        batch=args.batch,
        device=device,
        project=str(MODEL_DIR),
        name="yolo_cls",
        exist_ok=True,
        pretrained=True,
        workers=2,
        patience=20,
        plots=True,
    )

    best = Path(results.save_dir) / "weights" / "best.pt"
    if not best.exists():
        raise SystemExit(f"训练结束但没有找到 {best}")
    shutil.copy2(best, YOLO_WEIGHTS)
    print(f"已保存 {YOLO_WEIGHTS}")
    print("之后 python src/infer.py 照片.jpg 会自动用这套 YOLO 权重。")


if __name__ == "__main__":
    main()
