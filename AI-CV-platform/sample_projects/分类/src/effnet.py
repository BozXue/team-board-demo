"""EfficientNet-B0 密封袋种类分类：BSD 协议，权重完全自有。"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import torch
from PIL import Image
from torch import nn
from torchvision import transforms as T
from torchvision.models import EfficientNet_B0_Weights, efficientnet_b0

IMAGENET_MEAN = (0.485, 0.456, 0.406)
IMAGENET_STD = (0.229, 0.224, 0.225)


def pick_device() -> torch.device:
    if torch.cuda.is_available():
        return torch.device("cuda")
    if torch.backends.mps.is_available():
        return torch.device("mps")
    return torch.device("cpu")


def build_model(num_classes: int, pretrained: bool = True) -> nn.Module:
    weights = EfficientNet_B0_Weights.IMAGENET1K_V1 if pretrained else None
    model = efficientnet_b0(weights=weights)
    in_features = model.classifier[1].in_features
    model.classifier[1] = nn.Linear(in_features, num_classes)
    return model


def train_transforms(imgsz: int) -> T.Compose:
    return T.Compose(
        [
            T.RandomResizedCrop(imgsz, scale=(0.7, 1.0)),
            T.RandomHorizontalFlip(),
            T.ColorJitter(brightness=0.15, contrast=0.15, saturation=0.1),
            T.ToTensor(),
            T.Normalize(IMAGENET_MEAN, IMAGENET_STD),
        ]
    )


def eval_transforms(imgsz: int) -> T.Compose:
    return T.Compose(
        [
            T.Resize(imgsz),
            T.CenterCrop(imgsz),
            T.ToTensor(),
            T.Normalize(IMAGENET_MEAN, IMAGENET_STD),
        ]
    )


_CACHE: tuple[Path, nn.Module, list[str], int] | None = None


def load_checkpoint(path: Path, device: torch.device | None = None) -> tuple[nn.Module, list[str], int]:
    global _CACHE
    device = device or pick_device()
    resolved = path.resolve()
    if _CACHE is not None and _CACHE[0] == resolved:
        model, classes, imgsz = _CACHE[1], _CACHE[2], _CACHE[3]
        return model, classes, imgsz
    ckpt = torch.load(path, map_location=device, weights_only=False)
    classes = list(ckpt["classes"])
    imgsz = int(ckpt.get("imgsz", 384))
    model = build_model(len(classes), pretrained=False)
    model.load_state_dict(ckpt["model"])
    model.to(device)
    model.eval()
    _CACHE = (resolved, model, classes, imgsz)
    return model, classes, imgsz


def predict_roi(
    roi_rgb: np.ndarray,
    path: Path,
    device: torch.device | None = None,
) -> list[tuple[str, float]]:
    device = device or pick_device()
    model, classes, imgsz = load_checkpoint(path, device)
    image = Image.fromarray(roi_rgb)
    tensor = eval_transforms(imgsz)(image).unsqueeze(0).to(device)
    with torch.no_grad():
        logits = model(tensor)
        probs = torch.softmax(logits, dim=1)[0].cpu().numpy()
    ranking = [(classes[i], float(probs[i])) for i in range(len(classes))]
    ranking.sort(key=lambda item: item[1], reverse=True)
    return ranking


def export_onnx(weights: Path, dest: Path, imgsz: int = 384) -> Path:
    device = torch.device("cpu")
    model, _classes, ckpt_imgsz = load_checkpoint(weights, device)
    imgsz = ckpt_imgsz or imgsz
    dummy = torch.randn(1, 3, imgsz, imgsz)
    dest.parent.mkdir(parents=True, exist_ok=True)
    torch.onnx.export(
        model,
        dummy,
        str(dest),
        input_names=["images"],
        output_names=["logits"],
        opset_version=17,
        dynamo=False,
    )
    return dest
