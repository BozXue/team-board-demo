"""Morphology nodes: clean up binary masks."""

from __future__ import annotations

from typing import Any

import cv2

from app.engine.base import Node, NodeContext
from app.engine.registry import register
from app.engine.types import ParamSpec, PortSpec, PortType

_SHAPES = {
    "rect": cv2.MORPH_RECT,
    "ellipse": cv2.MORPH_ELLIPSE,
    "cross": cv2.MORPH_CROSS,
}


class _MorphBase(Node):
    category = "Morphology"
    operation: int = cv2.MORPH_ERODE
    inputs = (PortSpec("mask", PortType.MASK, "掩膜"),)
    outputs = (PortSpec("mask", PortType.MASK, "掩膜"),)
    params = (
        ParamSpec("kernel", "int", 3, label="结构元大小", min=1, max=99, step=2, level="business"),
        ParamSpec("shape", "enum", "ellipse", label="结构元形状", options=list(_SHAPES)),
        ParamSpec("iterations", "int", 1, label="迭代次数", min=1, max=20, level="business"),
    )

    def process(self, inputs: dict[str, Any], params: dict[str, Any], ctx: NodeContext) -> dict[str, Any]:
        mask = self.require_image(inputs, "mask")
        size = self.odd(params["kernel"])
        kernel = cv2.getStructuringElement(_SHAPES[params["shape"]], (size, size))
        result = cv2.morphologyEx(mask, self.operation, kernel, iterations=params["iterations"])
        return {"mask": result}


@register
class Erode(_MorphBase):
    type = "erode"
    label = "Erode"
    operation = cv2.MORPH_ERODE
    description = "腐蚀：缩小前景，去掉细小毛刺与噪点。"
    tags = ("morphology", "腐蚀")


@register
class Dilate(_MorphBase):
    type = "dilate"
    label = "Dilate"
    operation = cv2.MORPH_DILATE
    description = "膨胀：扩大前景，连接断裂区域。"
    tags = ("morphology", "膨胀")


@register
class MorphOpen(_MorphBase):
    type = "morph_open"
    label = "Open"
    operation = cv2.MORPH_OPEN
    description = "开运算：先腐蚀后膨胀，去除小噪点同时保持主体尺寸。"
    tags = ("morphology", "开运算")


@register
class MorphClose(_MorphBase):
    type = "morph_close"
    label = "Close"
    operation = cv2.MORPH_CLOSE
    description = "闭运算：先膨胀后腐蚀，填补目标内部空洞与缝隙。"
    tags = ("morphology", "闭运算")


@register
class MaskCleanup(Node):
    type = "mask_cleanup"
    label = "Mask Cleanup"
    category = "Morphology"
    description = (
        "掩膜清理：按面积去除碎片、填补小孔、可选只保留最大连通域。"
        "移植自 iPSC 原型的后处理步骤。"
    )
    tags = ("mask", "cleanup", "面积过滤", "ipsc")
    inputs = (PortSpec("mask", PortType.MASK, "掩膜"),)
    outputs = (PortSpec("mask", PortType.MASK, "掩膜"),)
    params = (
        ParamSpec("min_area_frac", "float", 0.01, label="最小面积占比", min=0.0, max=1.0,
                  step=0.001, level="business", description="小于该图像面积比例的连通域被丢弃"),
        ParamSpec("fill_hole_frac", "float", 0.01, label="填孔面积占比", min=0.0, max=1.0, step=0.001),
        ParamSpec("keep_largest", "bool", False, label="仅保留最大区域", level="business"),
        ParamSpec("fill_all_holes", "bool", False, label="填充全部内部孔洞"),
    )

    def process(self, inputs: dict[str, Any], params: dict[str, Any], ctx: NodeContext) -> dict[str, Any]:
        from app.engine.algorithms import texture as tex

        mask = self.require_image(inputs, "mask")
        height, width = mask.shape[:2]
        pixels = height * width
        if params["min_area_frac"] > 0:
            mask = tex.remove_small_objects(mask, int(params["min_area_frac"] * pixels))
        if params["fill_hole_frac"] > 0:
            mask = tex.remove_small_holes(mask, int(params["fill_hole_frac"] * pixels))
        if params["keep_largest"]:
            mask = tex.largest_component(mask)
        if params["fill_all_holes"]:
            mask = tex.fill_holes(mask)
        return {"mask": mask}
