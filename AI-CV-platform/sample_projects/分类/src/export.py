"""把微调后的 YOLO 权重导出成可离线拷贝的文件。

自有权重：models/grain_yolo.pt
再导出：  models/grain_yolo.onnx  （工控机 / 无 Ultralytics 源码时用）
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from taxonomy import EFFNET_WEIGHTS, MODEL_DIR, YOLO_WEIGHTS  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="导出自有分类权重（pt → onnx）")
    parser.add_argument("--weights", default=None, help="默认 grain_effnet.pt，否则 grain_yolo.pt")
    parser.add_argument("--imgsz", type=int, default=384)
    parser.add_argument("--format", default="onnx", choices=["onnx", "torchscript"])
    args = parser.parse_args()

    src = Path(args.weights) if args.weights else (EFFNET_WEIGHTS if EFFNET_WEIGHTS.exists() else YOLO_WEIGHTS)
    if not src.exists():
        raise SystemExit(f"没有找到权重 {src}。先运行 python src/train_effnet.py")

    import torch

    ckpt = None
    try:
        ckpt = torch.load(src, map_location="cpu", weights_only=False)
    except Exception:
        ckpt = None

    if isinstance(ckpt, dict) and ckpt.get("arch") == "efficientnet_b0":
        from effnet import export_onnx

        dest = MODEL_DIR / "grain_effnet.onnx"
        export_onnx(src, dest, imgsz=int(ckpt.get("imgsz", args.imgsz)))
        meta = MODEL_DIR / "grain_effnet.json"
        payload = json.loads(meta.read_text(encoding="utf-8")) if meta.exists() else {}
        payload.update(
            {
                "arch": "efficientnet_b0",
                "weights_pt": src.name,
                "weights_export": dest.name,
                "classes": {str(i): n for i, n in enumerate(ckpt["classes"])},
            }
        )
        meta.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"自有权重 {src} ({src.stat().st_size / 1e6:.1f} MB)")
        print(f"离线导出 {dest} ({dest.stat().st_size / 1e6:.1f} MB)")
        return

    from ultralytics import YOLO

    model = YOLO(str(src))
    names = model.names
    print(f"加载 {src}  ·  类别 {list(names.values())}")

    exported = model.export(
        format=args.format,
        imgsz=args.imgsz,
        keras=False,
        optimize=False,
        half=False,
        dynamic=False,
        simplify=True,
        opset=12,
    )
    exported_path = Path(str(exported))
    dest = MODEL_DIR / f"grain_yolo.{'onnx' if args.format == 'onnx' else 'torchscript'}"
    if exported_path.resolve() != dest.resolve():
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(exported_path, dest)

    meta = MODEL_DIR / "grain_yolo.json"
    meta.write_text(
        json.dumps(
            {
                "task": "classify",
                "imgsz": args.imgsz,
                "classes": names,
                "weights_pt": str(YOLO_WEIGHTS.name),
                "weights_export": dest.name,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"自有权重 {src} ({src.stat().st_size / 1e6:.1f} MB)")
    print(f"离线导出 {dest} ({dest.stat().st_size / 1e6:.1f} MB)")
    print(f"类别表   {meta}")
    print("拷到另一台机器时带上这两个文件即可，推理不再下载 yolo11n-cls.pt。")


if __name__ == "__main__":
    main()
