"""Grain-domain nodes: bag de-glare and grain-face crop before classification."""

from __future__ import annotations

from typing import Any

import numpy as np

from app.engine.algorithms.grain import find_grain_roi, suppress_glare
from app.engine.base import Node, NodeContext
from app.engine.registry import register
from app.engine.types import ParamSpec, PortSpec, PortType, Roi
from app.utils.imageio import to_bgr


@register
class GrainDeglare(Node):
    type = "grain_deglare"
    label = "Grain De-glare"
    category = "Domain"
    description = "去掉密封袋高光（高亮低饱和），避免反光主导颜色分类。"
    tags = ("grain", "谷物", "deglare", "预处理")
    inputs = (PortSpec("image", PortType.IMAGE, "图像"),)
    outputs = (PortSpec("image", PortType.IMAGE, "去反光图"),)

    def process(self, inputs: dict[str, Any], params: dict[str, Any], ctx: NodeContext) -> dict[str, Any]:
        image = to_bgr(self.require_image(inputs))
        cleaned = suppress_glare(image)
        ctx.log("已抑制密封袋高光")
        return {"image": cleaned}


@register
class GrainRoi(Node):
    type = "grain_roi"
    label = "Grain Face ROI"
    category = "Domain"
    description = "按颜色切出粮面外接框，再交给分类模型（对应离线 preprocess.find_grain_roi）。"
    tags = ("grain", "谷物", "roi")
    inputs = (PortSpec("image", PortType.IMAGE, "图像"),)
    outputs = (
        PortSpec("image", PortType.IMAGE, "粮面裁块"),
        PortSpec("roi", PortType.ROI, "粮面 ROI"),
    )
    params = (
        ParamSpec("min_area_frac", "float", 0.04, label="最小面积占比", min=0.0, max=1.0, step=0.01,
                  description="裁块小于该比例时退回整图"),
    )

    def process(self, inputs: dict[str, Any], params: dict[str, Any], ctx: NodeContext) -> dict[str, Any]:
        image = to_bgr(self.require_image(inputs))
        crop, (x, y, w, h) = find_grain_roi(image)
        height, width = image.shape[:2]
        if params["min_area_frac"] > 0 and (w * h) < params["min_area_frac"] * height * width:
            crop, (x, y, w, h) = image, (0, 0, width, height)
        mask = np.zeros((height, width), dtype=bool)
        mask[y:y + h, x:x + w] = True
        ctx.log(f"粮面 ROI {w}×{h} @ ({x},{y})")
        return {
            "image": crop,
            "roi": Roi(mask=mask, bbox=(x, y, w, h), shape=(height, width), kind="rect"),
        }
