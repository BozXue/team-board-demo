"""Threshold based segmentation: image -> mask."""

from __future__ import annotations

from typing import Any

import cv2
import numpy as np

from app.engine.base import Node, NodeContext
from app.engine.registry import register
from app.engine.types import ParamSpec, PortSpec, PortType
from app.utils.imageio import to_bgr


@register
class Threshold(Node):
    type = "threshold"
    label = "Threshold"
    category = "Segmentation"
    description = "全局阈值分割。光照稳定时最快最稳，光照漂移时建议改用 Adaptive/Otsu。"
    tags = ("threshold", "阈值", "分割")
    inputs = (PortSpec("image", PortType.IMAGE, "图像"),)
    outputs = (PortSpec("mask", PortType.MASK, "二值掩膜"),)
    params = (
        ParamSpec("threshold", "int", 128, label="阈值", min=0, max=255, level="business"),
        ParamSpec("invert", "bool", False, label="反向（暗目标）", level="business"),
    )

    def process(self, inputs: dict[str, Any], params: dict[str, Any], ctx: NodeContext) -> dict[str, Any]:
        gray = self.as_gray(self.require_image(inputs))
        mode = cv2.THRESH_BINARY_INV if params["invert"] else cv2.THRESH_BINARY
        _, mask = cv2.threshold(gray, params["threshold"], 255, mode)
        return {"mask": mask}


@register
class OtsuThreshold(Node):
    type = "otsu_threshold"
    label = "Otsu"
    category = "Segmentation"
    description = "Otsu 自动阈值，适合前景/背景灰度分布双峰的场景。"
    tags = ("threshold", "otsu", "自动阈值")
    inputs = (PortSpec("image", PortType.IMAGE, "图像"),)
    outputs = (
        PortSpec("mask", PortType.MASK, "二值掩膜"),
        PortSpec("threshold", PortType.VALUE, "阈值"),
    )
    params = (
        ParamSpec("invert", "bool", False, label="反向（暗目标）", level="business"),
        ParamSpec("bias", "int", 0, label="阈值偏置", min=-100, max=100, level="business",
                  description="在 Otsu 结果上加减偏置，用于微调灵敏度"),
    )

    def process(self, inputs: dict[str, Any], params: dict[str, Any], ctx: NodeContext) -> dict[str, Any]:
        from app.engine.types import Value

        gray = self.as_gray(self.require_image(inputs))
        level, _ = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        level = float(np.clip(level + params["bias"], 0, 255))
        mode = cv2.THRESH_BINARY_INV if params["invert"] else cv2.THRESH_BINARY
        _, mask = cv2.threshold(gray, level, 255, mode)
        ctx.log(f"Otsu 阈值={level:.1f}")
        return {"mask": mask, "threshold": Value(level, "otsu_threshold", "gray")}


@register
class AdaptiveThreshold(Node):
    type = "adaptive_threshold"
    label = "Adaptive Threshold"
    category = "Segmentation"
    description = (
        "局部自适应阈值。背景不均匀或环境光变化时优先使用，"
        "blockSize 需大于缺陷尺寸。"
    )
    tags = ("threshold", "adaptive", "局部阈值")
    inputs = (PortSpec("image", PortType.IMAGE, "图像"),)
    outputs = (PortSpec("mask", PortType.MASK, "二值掩膜"),)
    params = (
        ParamSpec("method", "enum", "gaussian", label="邻域权重", options=["mean", "gaussian"]),
        ParamSpec("block_size", "int", 35, label="邻域大小", min=3, max=999, step=2,
                  level="business", description="自动取奇数，应大于目标缺陷尺寸"),
        ParamSpec("c", "float", 5.0, label="偏置 C", min=-50.0, max=50.0, step=0.5,
                  level="business", description="越大越保守（检出更少）"),
        ParamSpec("invert", "bool", True, label="反向（暗目标）", level="business"),
    )

    def process(self, inputs: dict[str, Any], params: dict[str, Any], ctx: NodeContext) -> dict[str, Any]:
        gray = self.as_gray(self.require_image(inputs))
        method = (
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C if params["method"] == "gaussian"
            else cv2.ADAPTIVE_THRESH_MEAN_C
        )
        mode = cv2.THRESH_BINARY_INV if params["invert"] else cv2.THRESH_BINARY
        mask = cv2.adaptiveThreshold(
            gray, 255, method, mode, self.odd(params["block_size"], 3), params["c"]
        )
        return {"mask": mask}


@register
class ColorThreshold(Node):
    type = "color_threshold"
    label = "Color Threshold"
    category = "Segmentation"
    description = "在 HSV/BGR/Lab 空间做三通道区间分割，用于颜色缺陷或色标定位。"
    tags = ("color", "threshold", "颜色分割")
    inputs = (PortSpec("image", PortType.IMAGE, "图像"),)
    outputs = (PortSpec("mask", PortType.MASK, "二值掩膜"),)
    params = (
        ParamSpec("space", "enum", "hsv", label="颜色空间", options=["hsv", "bgr", "lab"]),
        ParamSpec("low1", "int", 0, label="通道1 下限", min=0, max=255, level="business"),
        ParamSpec("high1", "int", 179, label="通道1 上限", min=0, max=255, level="business"),
        ParamSpec("low2", "int", 60, label="通道2 下限", min=0, max=255, level="business"),
        ParamSpec("high2", "int", 255, label="通道2 上限", min=0, max=255, level="business"),
        ParamSpec("low3", "int", 60, label="通道3 下限", min=0, max=255, level="business"),
        ParamSpec("high3", "int", 255, label="通道3 上限", min=0, max=255, level="business"),
    )

    _CODES = {"hsv": cv2.COLOR_BGR2HSV, "lab": cv2.COLOR_BGR2LAB}

    def process(self, inputs: dict[str, Any], params: dict[str, Any], ctx: NodeContext) -> dict[str, Any]:
        image = to_bgr(self.require_image(inputs))
        if params["space"] != "bgr":
            image = cv2.cvtColor(image, self._CODES[params["space"]])
        lower = np.array([params["low1"], params["low2"], params["low3"]], dtype=np.uint8)
        upper = np.array([params["high1"], params["high2"], params["high3"]], dtype=np.uint8)
        return {"mask": cv2.inRange(image, lower, upper)}


@register
class MaskLogic(Node):
    type = "mask_logic"
    label = "Mask Logic"
    category = "Segmentation"
    description = "两个掩膜的 AND/OR/XOR/SUB 运算，用于组合多个判据。"
    tags = ("mask", "logic", "逻辑")
    inputs = (
        PortSpec("mask_a", PortType.MASK, "掩膜 A"),
        PortSpec("mask_b", PortType.MASK, "掩膜 B"),
    )
    outputs = (PortSpec("mask", PortType.MASK, "掩膜"),)
    params = (
        ParamSpec("operation", "enum", "and", label="运算", options=["and", "or", "xor", "subtract"]),
    )

    def process(self, inputs: dict[str, Any], params: dict[str, Any], ctx: NodeContext) -> dict[str, Any]:
        a = self.require_image(inputs, "mask_a")
        b = self.require_image(inputs, "mask_b")
        if a.shape[:2] != b.shape[:2]:
            b = cv2.resize(b, (a.shape[1], a.shape[0]), interpolation=cv2.INTER_NEAREST)
        op = params["operation"]
        if op == "and":
            mask = cv2.bitwise_and(a, b)
        elif op == "or":
            mask = cv2.bitwise_or(a, b)
        elif op == "xor":
            mask = cv2.bitwise_xor(a, b)
        else:
            mask = cv2.bitwise_and(a, cv2.bitwise_not(b))
        return {"mask": mask}
