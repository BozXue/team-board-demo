"""用 torchvision EfficientNet-B0 微调密封袋谷物种类。数据复用 data/yolo。"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

import torch
from torch import nn
from torch.utils.data import DataLoader, WeightedRandomSampler
from torchvision.datasets import ImageFolder
from tqdm import tqdm

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from effnet import (  # noqa: E402
    build_model,
    eval_transforms,
    pick_device,
    train_transforms,
)
from taxonomy import EFFNET_WEIGHTS, MODEL_DIR, YOLO_DATA_DIR  # noqa: E402


def _class_weights(dataset: ImageFolder) -> torch.Tensor:
    counts = Counter(dataset.targets)
    n_class = len(dataset.classes)
    freq = torch.tensor([counts[i] for i in range(n_class)], dtype=torch.float32)
    return (freq.sum() / freq).clone()


def _sampler(dataset: ImageFolder) -> WeightedRandomSampler:
    counts = Counter(dataset.targets)
    w = [1.0 / counts[y] for y in dataset.targets]
    return WeightedRandomSampler(w, num_samples=len(w), replacement=True)


@torch.no_grad()
def evaluate(model: nn.Module, loader: DataLoader, device: torch.device, n_class: int) -> tuple[float, list[float]]:
    model.eval()
    correct = 0
    total = 0
    per_correct = [0] * n_class
    per_total = [0] * n_class
    for images, labels in loader:
        images = images.to(device)
        labels = labels.to(device)
        pred = model(images).argmax(dim=1)
        correct += int((pred == labels).sum().item())
        total += labels.numel()
        for label, p in zip(labels.tolist(), pred.tolist()):
            per_total[label] += 1
            if p == label:
                per_correct[label] += 1
    acc = correct / max(total, 1)
    per_acc = [c / t if t else 0.0 for c, t in zip(per_correct, per_total)]
    return acc, per_acc


def main() -> None:
    parser = argparse.ArgumentParser(description="EfficientNet-B0 微调：密封袋谷物种类")
    parser.add_argument("--data", default=str(YOLO_DATA_DIR))
    parser.add_argument("--epochs", type=int, default=25)
    parser.add_argument("--imgsz", type=int, default=384)
    parser.add_argument("--batch", type=int, default=16)
    parser.add_argument("--patience", type=int, default=8)
    args = parser.parse_args()

    data = Path(args.data)
    train_dir = data / "train"
    val_dir = data / "val"
    if not train_dir.exists():
        raise SystemExit(f"没有 {train_dir}。先运行 python src/train.py 生成粮面切片，或把照片放进该目录。")

    device = pick_device()
    train_set = ImageFolder(str(train_dir), transform=train_transforms(args.imgsz))
    val_set = ImageFolder(str(val_dir), transform=eval_transforms(args.imgsz))
    classes = list(train_set.classes)
    print(f"device={device}  类别 {classes}")
    print(f"train {len(train_set)}  val {len(val_set)}")

    train_loader = DataLoader(
        train_set,
        batch_size=args.batch,
        sampler=_sampler(train_set),
        num_workers=0,
        drop_last=False,
    )
    val_loader = DataLoader(val_set, batch_size=args.batch, shuffle=False, num_workers=0)

    model = build_model(len(classes), pretrained=True).to(device)
    backbone_params = list(model.features.parameters())
    head_params = list(model.classifier.parameters())
    optimizer = torch.optim.AdamW(
        [
            {"params": backbone_params, "lr": 1e-4},
            {"params": head_params, "lr": 1e-3},
        ],
        weight_decay=0.01,
    )
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=args.epochs)
    criterion = nn.CrossEntropyLoss(weight=_class_weights(train_set).to(device))

    best_acc = -1.0
    stale = 0
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    history: list[dict] = []

    for epoch in range(1, args.epochs + 1):
        model.train()
        running = 0.0
        seen = 0
        for images, labels in tqdm(train_loader, desc=f"{epoch}/{args.epochs}", leave=False):
            images = images.to(device)
            labels = labels.to(device)
            optimizer.zero_grad(set_to_none=True)
            loss = criterion(model(images), labels)
            loss.backward()
            optimizer.step()
            running += float(loss.item()) * labels.size(0)
            seen += labels.size(0)
        scheduler.step()
        val_acc, per_acc = evaluate(model, val_loader, device, len(classes))
        train_loss = running / max(seen, 1)
        per = " ".join(f"{name}:{acc:.3f}" for name, acc in zip(classes, per_acc))
        print(f"epoch {epoch:02d}  loss {train_loss:.4f}  val_acc {val_acc:.4f}  {per}")
        history.append({"epoch": epoch, "train_loss": train_loss, "val_acc": val_acc})

        if val_acc > best_acc + 1e-6:
            best_acc = val_acc
            stale = 0
            torch.save(
                {
                    "arch": "efficientnet_b0",
                    "imgsz": args.imgsz,
                    "classes": classes,
                    "model": model.state_dict(),
                    "val_acc": val_acc,
                },
                EFFNET_WEIGHTS,
            )
        else:
            stale += 1
            if stale >= args.patience:
                print(f"早停：{args.patience} 轮无提升，最佳 val_acc={best_acc:.4f}")
                break

    meta = MODEL_DIR / "grain_effnet.json"
    meta.write_text(
        json.dumps(
            {
                "arch": "efficientnet_b0",
                "imgsz": args.imgsz,
                "classes": {str(i): name for i, name in enumerate(classes)},
                "best_val_acc": best_acc,
                "weights": EFFNET_WEIGHTS.name,
                "history": history,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"已保存 {EFFNET_WEIGHTS}  最佳验证 {best_acc:.4f}")
    print("识别：python src/infer.py 照片.jpg --weights models/grain_effnet.pt")


if __name__ == "__main__":
    main()
