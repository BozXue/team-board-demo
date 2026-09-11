"""Colour space conversion and intensity enhancement."""

from __future__ import annotations

from typing import Any

import cv2
import numpy as np

from app.engine.base import Node, NodeContext
from app.engine.registry import register
from app.engine.types import ParamSpec, PortSpec, PortType
from app.utils.imageio import to_bgr, to_gray


@register
class ToGray(Node):
    type = "to_gray"
    label = "Gray"
    category = "Enhance"
    description = "转换为单通道灰度图，是大多数传统视觉流程的第一步。"
    tags = ("gray", "灰度")
    inputs = (PortSpec("image", PortType.IMAGE, "图像"),)
    outputs = (PortSpec("image", PortType.IMAGE, "灰度图"),)

    def process(self, inputs: dict[str, Any], params: dict[str, Any], ctx: NodeContext) -> dict[str, Any]:
        return {"image": to_gray(self.require_image(inputs))}


@register
class ColorConvert(Node):
    type = "color_convert"
    label = "Color Space"
    category = "Enhance"
    description = "RGB/HSV/Lab 颜色空间转换，可选输出单通道，便于颜色分割。"
    tags = ("color", "hsv", "lab", "颜色空间")
    inputs = (PortSpec("image", PortType.IMAGE, "图像"),)
    outputs = (PortSpec("image", PortType.IMAGE, "图像"),)
    params = (
        ParamSpec("space", "enum", "hsv", label="目标空间", options=["rgb", "hsv", "lab", "ycrcb"]),
        ParamSpec("channel", "enum", "all", label="输出通道", options=["all", "0", "1", "2"]),
    )

    _CODES = {
        "rgb": cv2.COLOR_BGR2RGB,
        "hsv": cv2.COLOR_BGR2HSV,
        "lab": cv2.COLOR_BGR2LAB,
        "ycrcb": cv2.COLOR_BGR2YCrCb,
    }

    def process(self, inputs: dict[str, Any], params: dict[str, Any], ctx: NodeContext) -> dict[str, Any]:
        image = to_bgr(self.require_image(inputs))
        converted = cv2.cvtColor(image, self._CODES[params["space"]])
        if params["channel"] != "all":
            converted = converted[..., int(params["channel"])]
        return {"image": converted}


@register
class BrightnessContrast(Node):
    type = "brightness_contrast"
    label = "Brightness / Contrast"
    category = "Enhance"
    description = "线性拉伸 dst = alpha*src + beta，用于补偿曝光差异。"
    tags = ("brightness", "contrast", "亮度", "对比度")
    inputs = (PortSpec("image", PortType.IMAGE, "图像"),)
    outputs = (PortSpec("image", PortType.IMAGE, "图像"),)
    params = (
        ParamSpec("alpha", "float", 1.0, label="对比度", min=0.0, max=5.0, step=0.05,
                  level="business"),
        ParamSpec("beta", "float", 0.0, label="亮度", min=-128, max=128, step=1, level="business"),
    )

    def process(self, inputs: dict[str, Any], params: dict[str, Any], ctx: NodeContext) -> dict[str, Any]:
        image = self.require_image(inputs)
        return {"image": cv2.convertScaleAbs(image, alpha=params["alpha"], beta=params["beta"])}


@register
class Gamma(Node):
    type = "gamma"
    label = "Gamma"
    category = "Enhance"
    description = "Gamma 校正，<1 提亮暗部，>1 压暗亮部。"
    tags = ("gamma",)
    inputs = (PortSpec("image", PortType.IMAGE, "图像"),)
    outputs = (PortSpec("image", PortType.IMAGE, "图像"),)
    params = (
        ParamSpec("gamma", "float", 1.0, label="Gamma", min=0.1, max=5.0, step=0.05,
                  level="business"),
    )

    def process(self, inputs: dict[str, Any], params: dict[str, Any], ctx: NodeContext) -> dict[str, Any]:
        image = self.require_image(inputs)
        inv = 1.0 / max(1e-6, params["gamma"])
        table = np.clip(((np.arange(256) / 255.0) ** inv) * 255.0, 0, 255).astype(np.uint8)
        return {"image": cv2.LUT(image, table)}


@register
class Clahe(Node):
    type = "clahe"
    label = "CLAHE"
    category = "Enhance"
    description = "限制对比度自适应直方图均衡，改善背景不均匀与局部低对比。"
    tags = ("clahe", "局部增强")
    inputs = (PortSpec("image", PortType.IMAGE, "图像"),)
    outputs = (PortSpec("image", PortType.IMAGE, "图像"),)
    params = (
        ParamSpec("clip_limit", "float", 2.0, label="Clip Limit", min=0.5, max=20.0, step=0.1),
        ParamSpec("tile_grid", "int", 8, label="Tile 网格", min=1, max=64),
    )

    def process(self, inputs: dict[str, Any], params: dict[str, Any], ctx: NodeContext) -> dict[str, Any]:
        image = self.require_image(inputs)
        clahe = cv2.createCLAHE(
            clipLimit=params["clip_limit"],
            tileGridSize=(params["tile_grid"], params["tile_grid"]),
        )
        if image.ndim == 3:
            lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB)
            lab[..., 0] = clahe.apply(lab[..., 0])
            return {"image": cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)}
        return {"image": clahe.apply(image)}


@register
class HistEqualize(Node):
    type = "hist_equalize"
    label = "Histogram EQ"
    category = "Enhance"
    description = "全局直方图均衡化。"
    tags = ("histogram", "均衡化")
    inputs = (PortSpec("image", PortType.IMAGE, "图像"),)
    outputs = (PortSpec("image", PortType.IMAGE, "图像"),)

    def process(self, inputs: dict[str, Any], params: dict[str, Any], ctx: NodeContext) -> dict[str, Any]:
        return {"image": cv2.equalizeHist(to_gray(self.require_image(inputs)))}


@register
class Normalize(Node):
    type = "normalize"
    label = "Normalize"
    category = "Enhance"
    description = "把灰度拉伸到指定区间（可按分位数裁剪抑制离群像素）。"
    tags = ("normalize", "归一化")
    inputs = (PortSpec("image", PortType.IMAGE, "图像"),)
    outputs = (PortSpec("image", PortType.IMAGE, "图像"),)
    params = (
        ParamSpec("low_percentile", "float", 0.5, label="低分位", min=0.0, max=49.0, step=0.1,
                  unit="%"),
        ParamSpec("high_percentile", "float", 99.5, label="高分位", min=50.0, max=100.0, step=0.1,
                  unit="%"),
    )

    def process(self, inputs: dict[str, Any], params: dict[str, Any], ctx: NodeContext) -> dict[str, Any]:
        image = self.require_image(inputs).astype(np.float32)
        lo = float(np.percentile(image, params["low_percentile"]))
        hi = float(np.percentile(image, params["high_percentile"]))
        if hi <= lo:
            hi = lo + 1.0
        scaled = np.clip((image - lo) / (hi - lo) * 255.0, 0, 255).astype(np.uint8)
        return {"image": scaled}


@register
class Invert(Node):
    type = "invert"
    label = "Invert"
    category = "Enhance"
    description = "灰度反转，常用于把暗缺陷变成亮目标。"
    tags = ("invert", "反转")
    inputs = (PortSpec("image", PortType.IMAGE, "图像"),)
    outputs = (PortSpec("image", PortType.IMAGE, "图像"),)

    def process(self, inputs: dict[str, Any], params: dict[str, Any], ctx: NodeContext) -> dict[str, Any]:
        return {"image": cv2.bitwise_not(self.require_image(inputs))}


@register
class Resize(Node):
    type = "resize"
    label = "Resize"
    category = "Enhance"
    description = "缩放图像（等比或指定尺寸）。"
    tags = ("resize", "缩放", "geometry")
    inputs = (PortSpec("image", PortType.IMAGE, "图像"),)
    outputs = (PortSpec("image", PortType.IMAGE, "图像"),)
    params = (
        ParamSpec("mode", "enum", "scale", label="模式", options=["scale", "size"]),
        ParamSpec("scale", "float", 0.5, label="比例", min=0.05, max=8.0, step=0.05,
                  depends_on=("mode", ("scale",))),
        ParamSpec("width", "int", 640, label="宽", min=8, max=8192, depends_on=("mode", ("size",))),
        ParamSpec("height", "int", 480, label="高", min=8, max=8192, depends_on=("mode", ("size",))),
        ParamSpec("interpolation", "enum", "area", label="插值",
                  options=["nearest", "linear", "cubic", "area"]),
    )

    _INTERP = {
        "nearest": cv2.INTER_NEAREST,
        "linear": cv2.INTER_LINEAR,
        "cubic": cv2.INTER_CUBIC,
        "area": cv2.INTER_AREA,
    }

    def process(self, inputs: dict[str, Any], params: dict[str, Any], ctx: NodeContext) -> dict[str, Any]:
        image = self.require_image(inputs)
        h, w = image.shape[:2]
        if params["mode"] == "scale":
            size = (max(1, int(w * params["scale"])), max(1, int(h * params["scale"])))
        else:
            size = (params["width"], params["height"])
        return {"image": cv2.resize(image, size, interpolation=self._INTERP[params["interpolation"]])}


@register
class RotateFlip(Node):
    type = "rotate_flip"
    label = "Rotate / Flip"
    category = "Enhance"
    description = "旋转与镜像，用于统一相机安装方向。"
    tags = ("rotate", "flip", "旋转", "geometry")
    inputs = (PortSpec("image", PortType.IMAGE, "图像"),)
    outputs = (PortSpec("image", PortType.IMAGE, "图像"),)
    params = (
        ParamSpec("angle", "float", 0.0, label="旋转角度", min=-180.0, max=180.0, step=0.5,
                  unit="°"),
        ParamSpec("flip", "enum", "none", label="镜像", options=["none", "horizontal", "vertical", "both"]),
        ParamSpec("keep_size", "bool", True, label="保持尺寸"),
    )

    def process(self, inputs: dict[str, Any], params: dict[str, Any], ctx: NodeContext) -> dict[str, Any]:
        image = self.require_image(inputs)
        angle = params["angle"]
        if abs(angle) > 1e-6:
            h, w = image.shape[:2]
            center = (w / 2.0, h / 2.0)
            matrix = cv2.getRotationMatrix2D(center, angle, 1.0)
            if params["keep_size"]:
                out_size = (w, h)
            else:
                cos, sin = abs(matrix[0, 0]), abs(matrix[0, 1])
                out_w, out_h = int(h * sin + w * cos), int(h * cos + w * sin)
                matrix[0, 2] += out_w / 2.0 - center[0]
                matrix[1, 2] += out_h / 2.0 - center[1]
                out_size = (out_w, out_h)
            image = cv2.warpAffine(image, matrix, out_size, flags=cv2.INTER_LINEAR,
                                   borderMode=cv2.BORDER_REPLICATE)
        flip = params["flip"]
        if flip != "none":
            code = {"horizontal": 1, "vertical": 0, "both": -1}[flip]
            image = cv2.flip(image, code)
        return {"image": image}
