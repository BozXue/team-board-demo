"""密封袋谷物种类识别界面：上传照片 → 初判 → 人工确认后写入训练集。"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

import gradio as gr
import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from infer import predict_image  # noqa: E402
from preprocess import prepare  # noqa: E402
from taxonomy import TRAIN_DIR, load_species  # noqa: E402


SPECIES = load_species()
SPECIES_NAMES = [item.name for item in SPECIES]


def _save_rgb(path: Path, rgb: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(rgb).save(path)


def classify(image: Image.Image | None):
    if image is None:
        raise gr.Error("请先上传一张密封袋俯拍照片。")

    tmp = ROOT / "models" / "_last_upload.jpg"
    tmp.parent.mkdir(parents=True, exist_ok=True)
    image.convert("RGB").save(tmp)

    prepared = prepare(str(tmp))
    result = predict_image(str(tmp), prepared=prepared)
    ranking_rows = [
        [name, f"{score:.1%}"] for name, score in result.ranking[:7]
    ]
    status = (
        f"{result.backend}  ·  预测 **{result.species_name}**  "
        f"（{result.confidence:.1%}）"
    )
    if result.note:
        status += f"\n\n{result.note}"
    return result.roi_rgb, ranking_rows, result.species_name, status


def save_labeled(image: Image.Image | None, label: str, split: str) -> str:
    if image is None:
        raise gr.Error("没有可保存的照片。")
    if label not in SPECIES_NAMES:
        raise gr.Error("请选择一个种类标签。")

    folder = ROOT / "data" / split / label
    folder.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = folder / f"{stamp}.jpg"
    image.convert("RGB").save(dest, quality=95)
    n = len(list(folder.glob("*.jpg")))
    return f"已保存到 `{dest.relative_to(ROOT)}`。该种类在 {split} 中现有 {n} 张。"


def dataset_summary() -> str:
    lines = ["当前训练集张数："]
    for name in SPECIES_NAMES:
        folder = TRAIN_DIR / name
        n = len(list(folder.glob("*"))) if folder.exists() else 0
        lines.append(f"- {name}: {n}")
    return "\n".join(lines)


with gr.Blocks(title="密封袋谷物分类") as demo:
    gr.Markdown(
        """
# 密封袋谷物种类识别

垂直俯拍、袋子展平、关掉闪光灯。先看种类对不对，确认后再存进训练集。
        """
    )
    with gr.Row():
        with gr.Column():
            photo = gr.Image(type="pil", label="密封袋照片")
            run = gr.Button("识别种类", variant="primary")
        with gr.Column():
            roi = gr.Image(type="numpy", label="检出的粮面")
            ranking = gr.Dataframe(
                headers=["种类", "置信度"],
                label="排序",
                interactive=False,
            )
            status = gr.Markdown()
            label = gr.Dropdown(SPECIES_NAMES, label="确认种类（可改）")
            split = gr.Radio(["train", "val"], value="train", label="保存到")
            save = gr.Button("保存到数据集")
            saved = gr.Markdown()
            counts = gr.Markdown(dataset_summary())

    run.click(classify, inputs=photo, outputs=[roi, ranking, label, status])
    save.click(save_labeled, inputs=[photo, label, split], outputs=saved).then(
        dataset_summary, outputs=counts
    )


if __name__ == "__main__":
    demo.launch()
