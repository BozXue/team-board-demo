"""AI inference nodes.

Classification and tile-wise texture mapping run on the platform's own
LBP+SVM models (trained from the annotation module). Detection and
segmentation are declared here as reserved interfaces so a Pipeline can be
designed around them before the model service lands.
"""

from __future__ import annotations

from typing import Any

import cv2
import numpy as np

from app.core.errors import NotImplementedFeature, ValidationError
from app.engine.algorithms import texture as tex
from app.engine.base import Node, NodeContext
from app.engine.registry import register
from app.engine.types import Judgement, ParamSpec, PortSpec, PortType, Value
from app.utils.imageio import to_uint8

_MODEL_PARAM = ParamSpec(
    "model_id", "str", "", label="模型",
    description="模型库中的模型 ID（模型页面可训练/导入）",
)


@register
class AiClassify(Node):
    type = "ai_classify"
    label = "Classification"
    category = "AI"
    description = (
        "图像分类推理。支持平台训练的 LBP+SVM，以及导入的 ONNX 分类模型"
        "（YOLO-cls / EfficientNet）。选中 .pt 时会自动改用同名的 .onnx。"
        "ok_classes 中的类别判为 OK，可直接接 OK/NG。"
    )
    tags = ("ai", "classification", "分类")
    inputs = (PortSpec("image", PortType.IMAGE, "图像"),)
    outputs = (
        PortSpec("result", PortType.RESULT, "判定"),
        PortSpec("confidence", PortType.VALUE, "置信度"),
    )
    params = (
        _MODEL_PARAM,
        ParamSpec("ok_classes", "str", "", label="OK 类别",
                  description="逗号分隔；留空表示所有类别都判 OK（仅输出类别）", level="business"),
        ParamSpec("min_confidence", "float", 0.0, label="最低置信度", min=0.0, max=1.0, step=0.01,
                  level="business", description="低于该置信度判为 NG（需人工确认）"),
    )

    def process(self, inputs: dict[str, Any], params: dict[str, Any], ctx: NodeContext) -> dict[str, Any]:
        from app.services.model_service import predict_image

        image = self.require_image(inputs)
        label, confidence, classes = predict_image(params["model_id"], image)
        ok_classes = [c.strip() for c in params["ok_classes"].split(",") if c.strip()]
        ok = (not ok_classes or label in ok_classes) and confidence >= params["min_confidence"]
        ctx.log(f"分类={label} 置信度={confidence:.3f} 候选={classes}")
        return {
            "result": Judgement(
                verdict="OK" if ok else "NG",
                reason=f"分类结果 {label}（置信度 {confidence:.2f}）",
                measurements={"class": label, "confidence": round(confidence, 4)},
            ),
            "confidence": Value(confidence, "confidence", ""),
        }


@register
class AiTextureMap(Node):
    type = "ai_texture_map"
    label = "Texture Map (分块分类)"
    category = "AI"
    description = (
        "分块纹理分类：按 tile 网格逐块推理，输出类别彩色图和所选类别的掩膜。"
        "对应 iPSC 七类形态（单细胞/中致密/全致密/死细胞/分化/碎片/背景）。"
    )
    tags = ("ai", "texture", "分块", "ipsc")
    inputs = (PortSpec("image", PortType.IMAGE, "图像"),)
    outputs = (
        PortSpec("image", PortType.IMAGE, "类别图"),
        PortSpec("mask", PortType.MASK, "目标类别掩膜"),
        PortSpec("ratio", PortType.VALUE, "目标类别占比"),
    )
    params = (
        _MODEL_PARAM,
        ParamSpec("tile", "int", tex.TILE_SIZE, label="分块大小", min=16, max=512, unit="px"),
        ParamSpec("stride", "int", 0, label="步长", min=0, max=512, unit="px",
                  description="0 表示等于分块大小（不重叠）"),
        ParamSpec("target_classes", "str", "", label="目标类别",
                  description="逗号分隔，用于生成掩膜与占比；留空取第一个类别", level="business"),
    )

    def process(self, inputs: dict[str, Any], params: dict[str, Any], ctx: NodeContext) -> dict[str, Any]:
        from app.services.model_service import predict_tiles

        gray = self.as_gray(self.require_image(inputs))
        tile = params["tile"]
        stride = params["stride"] or tile
        label_grid, classes = predict_tiles(params["model_id"], gray, tile, stride)
        targets = [c.strip() for c in params["target_classes"].split(",") if c.strip()]
        if not targets:
            targets = classes[:1]
        target_ids = {classes.index(c) for c in targets if c in classes}

        color_map = _class_color_map(len(classes))
        color_grid = color_map[np.clip(label_grid, 0, len(classes) - 1)]
        visual = cv2.resize(color_grid, (gray.shape[1], gray.shape[0]), interpolation=cv2.INTER_NEAREST)

        selected = np.isin(label_grid, list(target_ids)).astype(np.uint8) * 255
        mask = cv2.resize(selected, (gray.shape[1], gray.shape[0]), interpolation=cv2.INTER_NEAREST)
        ratio = float(np.count_nonzero(selected)) / float(selected.size) * 100.0
        ctx.log(f"分块网格 {label_grid.shape}，目标类别 {targets} 占比 {ratio:.2f}%")
        return {
            "image": visual,
            "mask": mask,
            "ratio": Value(ratio, "target_class_ratio", "%"),
        }


def _class_color_map(count: int) -> np.ndarray:
    base = np.array(
        [
            [60, 60, 60], [200, 120, 60], [80, 190, 120], [70, 70, 230],
            [200, 200, 70], [180, 90, 200], [120, 180, 220], [40, 140, 240],
        ],
        dtype=np.uint8,
    )
    if count <= len(base):
        return base[:max(1, count)]
    extra = np.random.default_rng(7).integers(40, 230, size=(count - len(base), 3), dtype=np.uint8)
    return np.vstack([base, extra])


@register
class AiAnomalyDetect(Node):
    type = "ai_anomaly_detect"
    label = "Anomaly Detection"
    category = "AI"
    description = (
        "无监督异常检测：用局部统计残差定位与邻域显著不同的区域，"
        "无需缺陷样本即可上线；后续可替换为 PatchCore 等模型。"
    )
    tags = ("ai", "anomaly", "异常检测")
    inputs = (PortSpec("image", PortType.IMAGE, "图像"),)
    outputs = (
        PortSpec("heatmap", PortType.IMAGE, "异常热力图"),
        PortSpec("mask", PortType.MASK, "异常掩膜"),
        PortSpec("score", PortType.VALUE, "异常分数"),
    )
    params = (
        ParamSpec("method", "enum", "residual", label="方法",
                  options=["residual", "texture_zscore"],
                  description="residual=与局部均值的偏差；texture_zscore=局部纹理强度异常"),
        ParamSpec("window", "int", 31, label="邻域窗口", min=3, max=501, step=2),
        ParamSpec("sensitivity", "float", 3.0, label="灵敏度", min=0.5, max=10.0, step=0.1,
                  level="business", description="等价于 k·σ 阈值，越小越灵敏"),
        ParamSpec("min_area", "float", 20.0, label="最小异常面积", min=0.0, max=1e9, unit="px²",
                  level="business"),
    )

    def process(self, inputs: dict[str, Any], params: dict[str, Any], ctx: NodeContext) -> dict[str, Any]:
        gray = self.as_gray(self.require_image(inputs)).astype(np.float32)
        window = self.odd(params["window"], 3)
        if params["method"] == "residual":
            smooth = cv2.blur(gray, (window, window))
            residual = np.abs(gray - smooth)
        else:
            residual = tex.local_std(gray.astype(np.uint8), window)
            residual = np.abs(residual - residual.mean())
        sigma = float(residual.std()) or 1.0
        score_map = residual / sigma
        mask = (score_map > params["sensitivity"]).astype(np.uint8) * 255
        if params["min_area"] > 0:
            mask = tex.remove_small_objects(mask, int(params["min_area"]))
        score = float(score_map.max())
        ctx.log(f"异常分数 max={score:.2f}, 异常像素 {int(np.count_nonzero(mask))}")
        return {
            "heatmap": to_uint8(score_map),
            "mask": mask,
            "score": Value(score, "anomaly_score", "σ"),
        }


@register
class AiDetect(Node):
    type = "ai_detect"
    label = "Detection (预留)"
    category = "AI"
    description = (
        "目标检测推理节点（YOLO/ONNX）。接口已按标准 Node 契约预留，"
        "模型服务接入后即可执行，无需修改流程结构。"
    )
    tags = ("ai", "detection", "检测", "预留")
    inputs = (PortSpec("image", PortType.IMAGE, "图像"),)
    outputs = (PortSpec("regions", PortType.REGIONS, "检测框"),)
    params = (
        _MODEL_PARAM,
        ParamSpec("conf_threshold", "float", 0.35, label="置信度阈值", min=0.0, max=1.0, step=0.01,
                  level="business"),
        ParamSpec("iou_threshold", "float", 0.45, label="NMS IoU", min=0.0, max=1.0, step=0.01),
        ParamSpec("device", "enum", "cpu", label="推理设备", options=["cpu", "cuda"]),
    )

    def process(self, inputs: dict[str, Any], params: dict[str, Any], ctx: NodeContext) -> dict[str, Any]:
        raise NotImplementedFeature(
            "检测模型推理为 P1 能力：请在模型库导入 ONNX/YOLO 模型后启用（接口已预留）"
        )


@register
class AiSegment(Node):
    type = "ai_segment"
    label = "Segmentation (预留)"
    category = "AI"
    description = "语义/实例分割推理节点，接口预留，输出掩膜可直接接入测量与判定。"
    tags = ("ai", "segmentation", "分割", "预留")
    inputs = (PortSpec("image", PortType.IMAGE, "图像"),)
    outputs = (PortSpec("mask", PortType.MASK, "分割掩膜"),)
    params = (
        _MODEL_PARAM,
        ParamSpec("threshold", "float", 0.5, label="概率阈值", min=0.0, max=1.0, step=0.01,
                  level="business"),
        ParamSpec("device", "enum", "cpu", label="推理设备", options=["cpu", "cuda"]),
    )

    def process(self, inputs: dict[str, Any], params: dict[str, Any], ctx: NodeContext) -> dict[str, Any]:
        raise NotImplementedFeature(
            "分割模型推理为 P1 能力：接口已预留，接入模型服务后可直接运行"
        )


@register
class AiRegionClassify(Node):
    type = "ai_region_classify"
    label = "Region Classify"
    category = "AI"
    description = "对已分割出的每个区域裁剪后分类，实现“先定位再判型”的混合流程。"
    tags = ("ai", "classification", "区域分类")
    inputs = (
        PortSpec("image", PortType.IMAGE, "图像"),
        PortSpec("regions", PortType.REGIONS, "区域"),
    )
    outputs = (
        PortSpec("regions", PortType.REGIONS, "带类别的区域"),
        PortSpec("result", PortType.RESULT, "判定"),
    )
    params = (
        _MODEL_PARAM,
        ParamSpec("ng_classes", "str", "", label="NG 类别", level="business",
                  description="逗号分隔；命中任一类别即判 NG"),
    )

    def process(self, inputs: dict[str, Any], params: dict[str, Any], ctx: NodeContext) -> dict[str, Any]:
        from app.engine.types import Regions
        from app.services.model_service import predict_image

        image = self.as_gray(self.require_image(inputs))
        regions = inputs.get("regions")
        if not isinstance(regions, Regions):
            raise ValidationError("Region Classify 需要 Regions 输入")
        ng_classes = {c.strip() for c in params["ng_classes"].split(",") if c.strip()}
        hits: list[str] = []
        for region in regions.items:
            x, y, w, h = region.bbox
            patch = image[y:y + max(1, h), x:x + max(1, w)]
            if patch.size == 0:
                continue
            label, confidence, _ = predict_image(params["model_id"], patch)
            region.extra["class"] = label
            region.extra["confidence"] = round(confidence, 4)
            if label in ng_classes:
                hits.append(label)
        ok = not hits
        return {
            "regions": regions,
            "result": Judgement(
                verdict="OK" if ok else "NG",
                reason="无异常类别" if ok else f"命中异常类别: {', '.join(sorted(set(hits)))}",
                measurements={"ng_region_count": len(hits)},
            ),
        }


@register
class AiPreAnnotate(Node):
    type = "ai_pre_annotate"
    label = "Pre-Annotate (预留)"
    category = "AI"
    description = "AI 预标注：用已有模型对未标注图像生成候选标注供人工修正（P1）。"
    tags = ("ai", "annotation", "预标注", "预留")
    inputs = (PortSpec("image", PortType.IMAGE, "图像"),)
    outputs = (PortSpec("regions", PortType.REGIONS, "候选标注"),)
    params = (_MODEL_PARAM,)

    def process(self, inputs: dict[str, Any], params: dict[str, Any], ctx: NodeContext) -> dict[str, Any]:
        raise NotImplementedFeature(
            "批量预标注仍为预留。交互式 SAM 请到数据页使用「SAM」工具（点选/框选）。"
        )
