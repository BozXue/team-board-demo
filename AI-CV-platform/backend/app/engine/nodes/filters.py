"""Denoising / smoothing filters."""

from __future__ import annotations

from typing import Any

import cv2

from app.engine.base import Node, NodeContext
from app.engine.registry import register
from app.engine.types import ParamSpec, PortSpec, PortType


@register
class GaussianBlur(Node):
    type = "gaussian_blur"
    label = "Gaussian"
    category = "Filter"
    description = "高斯平滑，抑制高频噪声，阈值分割前的常规步骤。"
    tags = ("filter", "gaussian", "高斯", "降噪")
    inputs = (PortSpec("image", PortType.IMAGE, "图像"),)
    outputs = (PortSpec("image", PortType.IMAGE, "图像"),)
    params = (
        ParamSpec("kernel", "int", 5, label="核大小", min=1, max=99, step=2,
                  description="自动取奇数"),
        ParamSpec("sigma", "float", 0.0, label="Sigma", min=0.0, max=50.0, step=0.1,
                  description="0 表示由核大小推导"),
    )

    def process(self, inputs: dict[str, Any], params: dict[str, Any], ctx: NodeContext) -> dict[str, Any]:
        image = self.require_image(inputs)
        k = self.odd(params["kernel"])
        return {"image": cv2.GaussianBlur(image, (k, k), params["sigma"])}


@register
class MedianBlur(Node):
    type = "median_blur"
    label = "Median"
    category = "Filter"
    description = "中值滤波，对椒盐噪声和孤立亮点特别有效。"
    tags = ("filter", "median", "中值")
    inputs = (PortSpec("image", PortType.IMAGE, "图像"),)
    outputs = (PortSpec("image", PortType.IMAGE, "图像"),)
    params = (
        ParamSpec("kernel", "int", 5, label="核大小", min=3, max=99, step=2),
    )

    def process(self, inputs: dict[str, Any], params: dict[str, Any], ctx: NodeContext) -> dict[str, Any]:
        image = self.require_image(inputs)
        return {"image": cv2.medianBlur(image, self.odd(params["kernel"], 3))}


@register
class BilateralFilter(Node):
    type = "bilateral_filter"
    label = "Bilateral"
    category = "Filter"
    description = "双边滤波，降噪同时保留边缘，代价是速度较慢。"
    tags = ("filter", "bilateral", "双边")
    inputs = (PortSpec("image", PortType.IMAGE, "图像"),)
    outputs = (PortSpec("image", PortType.IMAGE, "图像"),)
    params = (
        ParamSpec("diameter", "int", 9, label="邻域直径", min=1, max=51),
        ParamSpec("sigma_color", "float", 50.0, label="颜色 Sigma", min=1.0, max=250.0, step=1.0),
        ParamSpec("sigma_space", "float", 50.0, label="空间 Sigma", min=1.0, max=250.0, step=1.0),
    )

    def process(self, inputs: dict[str, Any], params: dict[str, Any], ctx: NodeContext) -> dict[str, Any]:
        image = self.require_image(inputs)
        return {
            "image": cv2.bilateralFilter(
                image, params["diameter"], params["sigma_color"], params["sigma_space"]
            )
        }


@register
class LocalStdTexture(Node):
    type = "local_std"
    label = "Local Std (纹理)"
    category = "Filter"
    description = (
        "局部标准差纹理图：细胞边界、织物纹理等高频区域响应强，"
        "是 iPSC 克隆分割流程的核心步骤。"
    )
    tags = ("texture", "std", "纹理", "ipsc")
    inputs = (PortSpec("image", PortType.IMAGE, "图像"),)
    outputs = (PortSpec("image", PortType.IMAGE, "纹理强度图"),)
    params = (
        ParamSpec("window", "int", 0, label="窗口", min=0, max=999, unit="px",
                  description="0=自动，按图像高度的 1.5% 取奇数"),
        ParamSpec("smooth_sigma", "float", 0.0, label="平滑 Sigma", min=0.0, max=100.0, step=0.5,
                  description="0=自动，取窗口的 1/3；对纹理图平滑可显著稳定后续阈值"),
    )

    def process(self, inputs: dict[str, Any], params: dict[str, Any], ctx: NodeContext) -> dict[str, Any]:
        import cv2 as _cv2

        from app.engine.algorithms.texture import local_std, resolve_window
        from app.utils.imageio import to_uint8

        image = self.as_gray(self.require_image(inputs))
        window = resolve_window(image.shape[0], params["window"] or None)
        texture = local_std(image, window)
        sigma = params["smooth_sigma"] or window / 3.0
        if sigma > 0:
            texture = _cv2.GaussianBlur(texture, (0, 0), sigma)
        ctx.log(f"window={window} sigma={sigma:.1f}")
        return {"image": to_uint8(texture)}
