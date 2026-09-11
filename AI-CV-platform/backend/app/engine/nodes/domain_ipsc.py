"""iPSC domain nodes.

These wrap the prototype (``ipsc_texture_classifier``) as first-class pipeline
nodes: the whole 10-step colony pipeline as one node for quick results, and the
metrics/feature steps separately so they can be recombined with generic nodes.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from app.engine.algorithms import texture as tex
from app.engine.base import Node, NodeContext
from app.engine.registry import register
from app.engine.types import (
    ParamSpec,
    PortSpec,
    PortType,
    Region,
    Regions,
    Value,
)
from app.utils.imageio import to_uint8


@register
class ColonySegment(Node):
    type = "ipsc_colony_segment"
    label = "Colony Segment"
    category = "Domain"
    description = (
        "iPSC 克隆分割（原型移植）：局部标准差纹理 → Otsu → 闭运算 → 去碎片 → "
        "填孔 → 开运算 → 最大连通域。适用于明场下高纹理克隆与平滑背景的场景。"
    )
    tags = ("ipsc", "colony", "克隆", "segmentation", "纹理")
    inputs = (PortSpec("image", PortType.IMAGE, "图像"),)
    outputs = (
        PortSpec("mask", PortType.MASK, "克隆掩膜"),
        PortSpec("texture", PortType.IMAGE, "纹理图"),
    )
    params = (
        ParamSpec("window", "int", 0, label="纹理窗口", min=0, max=999, unit="px",
                  description="0=自动（图像高度的 1.5%）"),
        ParamSpec("smooth_sigma", "float", 0.0, label="平滑 Sigma", min=0.0, max=100.0, step=0.5,
                  description="0=自动（窗口/3）"),
        ParamSpec("min_area_frac", "float", 0.01, label="最小面积占比", min=0.0, max=1.0, step=0.001,
                  level="business", description="小于该图像面积比例的纹理区域视为碎片"),
        ParamSpec("keep_largest", "bool", True, label="仅保留最大克隆", level="business"),
    )

    def process(self, inputs: dict[str, Any], params: dict[str, Any], ctx: NodeContext) -> dict[str, Any]:
        gray = self.as_gray(self.require_image(inputs))
        steps: list[dict] = []
        mask, texture = tex.segment_textured_region(
            gray,
            window=params["window"] or None,
            min_frac=params["min_area_frac"],
            smooth_sigma=params["smooth_sigma"] or None,
            keep_largest=params["keep_largest"],
            steps=steps,
        )
        ctx.log(f"完成 {len(steps)} 个子步骤，掩膜前景 {int(np.count_nonzero(mask))} px")
        return {"mask": mask, "texture": to_uint8(texture)}


@register
class ColonyMetrics(Node):
    type = "ipsc_colony_metrics"
    label = "Colony Metrics"
    category = "Domain"
    description = (
        "克隆中心与形态指标：中心坐标、面积、面积占比、等效直径、实心度，"
        "与原型输出的 colony_centers.csv 字段一致。"
    )
    tags = ("ipsc", "colony", "metrics", "中心", "测量")
    inputs = (PortSpec("mask", PortType.MASK, "克隆掩膜"),)
    outputs = (
        PortSpec("regions", PortType.REGIONS, "克隆区域"),
        PortSpec("area_percent", PortType.VALUE, "面积占比"),
        PortSpec("diameter", PortType.VALUE, "等效直径"),
        PortSpec("solidity", PortType.VALUE, "实心度"),
    )

    def process(self, inputs: dict[str, Any], params: dict[str, Any], ctx: NodeContext) -> dict[str, Any]:
        mask = self.require_image(inputs, "mask")
        info = tex.describe_mask(mask)
        shape = (int(mask.shape[0]), int(mask.shape[1]))
        if info is None:
            ctx.log("未检测到克隆区域")
            return {
                "regions": Regions(items=[], shape=shape),
                "area_percent": Value(0.0, "colony_area_percent", "%"),
                "diameter": Value(0.0, "colony_diameter", "px"),
                "solidity": Value(0.0, "colony_solidity", ""),
            }

        contour = info.pop("contour")
        xs, ys = contour[:, 0], contour[:, 1]
        region = Region(
            index=0,
            area=float(info["area_px"]),
            centroid=(info["center_x"], info["center_y"]),
            bbox=(int(xs.min()), int(ys.min()),
                  int(np.ptp(xs) + 1), int(np.ptp(ys) + 1)),
            contour=contour,
            equivalent_diameter=info["equivalent_diameter_px"],
            solidity=info["solidity"],
            extra={
                "centerX": info["center_x"],
                "centerY": info["center_y"],
                "areaFractionPercent": info["area_fraction_percent"],
            },
        )
        ctx.log(
            f"中心=({info['center_x']}, {info['center_y']}) 面积占比={info['area_fraction_percent']}%"
        )
        return {
            "regions": Regions(items=[region], shape=shape),
            "area_percent": Value(info["area_fraction_percent"], "colony_area_percent", "%"),
            "diameter": Value(info["equivalent_diameter_px"], "colony_diameter", "px"),
            "solidity": Value(info["solidity"], "colony_solidity", ""),
        }


@register
class LbpFeatures(Node):
    type = "ipsc_lbp_features"
    label = "LBP Features"
    category = "Domain"
    description = (
        "灰度直方图 + 多尺度 uniform LBP 特征（默认 58 维），"
        "用于纹理分类模型训练与推理，可作为调试时的纹理指纹。"
    )
    tags = ("ipsc", "lbp", "特征", "texture")
    inputs = (
        PortSpec("image", PortType.IMAGE, "图像"),
        PortSpec("mask", PortType.MASK, "掩膜（可选，仅统计前景）", required=False),
    )
    outputs = (
        PortSpec("features", PortType.VALUE, "特征向量"),
        PortSpec("entropy", PortType.VALUE, "纹理熵"),
    )

    def process(self, inputs: dict[str, Any], params: dict[str, Any], ctx: NodeContext) -> dict[str, Any]:
        gray = self.as_gray(self.require_image(inputs))
        mask = inputs.get("mask")
        if isinstance(mask, np.ndarray) and mask.shape[:2] == gray.shape[:2]:
            selector = mask > 0
            if selector.any():
                ys, xs = np.nonzero(selector)
                gray = gray[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
        features = tex.extract_features(gray)
        probabilities = features[: tex.INTENSITY_BINS]
        nonzero = probabilities[probabilities > 0]
        entropy = float(-(nonzero * np.log2(nonzero)).sum()) if nonzero.size else 0.0
        ctx.log(f"特征维度 {features.size}，灰度熵 {entropy:.3f}")
        return {
            "features": Value(float(features.mean()), "lbp_feature_mean", "",
                              values=[float(v) for v in features]),
            "entropy": Value(entropy, "intensity_entropy", "bit"),
        }
