"""Input nodes: dataset image and (reserved) camera acquisition."""

from __future__ import annotations

from typing import Any

import numpy as np

from app.core.errors import ValidationError
from app.engine.base import Node, NodeContext
from app.engine.registry import register
from app.engine.types import ParamSpec, PortSpec, PortType
from app.utils.imageio import load_image, to_bgr, to_gray


@register
class ImageInput(Node):
    type = "image_input"
    label = "Image"
    category = "Input"
    description = "读取当前选中的数据集图像（批量测试/Runtime 时由引擎逐张注入）。"
    tags = ("input", "image", "图像")
    outputs = (
        PortSpec("image", PortType.IMAGE, "图像"),
    )
    params = (
        ParamSpec("source", "enum", "dataset", label="图像来源",
                  options=["dataset", "path"],
                  description="dataset=引擎注入的当前图像；path=固定文件路径"),
        ParamSpec("path", "str", "", label="文件路径", depends_on=("source", ("path",))),
        ParamSpec("color_mode", "enum", "keep", label="颜色模式",
                  options=["keep", "gray", "color"]),
        ParamSpec("max_side", "int", 1600, label="最大边长", min=0, max=8192, unit="px",
                  description="0 表示使用原图；大图缩放可显著提升调试速度"),
    )

    def process(self, inputs: dict[str, Any], params: dict[str, Any], ctx: NodeContext) -> dict[str, Any]:
        path = params["path"] if params["source"] == "path" else ctx.image_path
        if not path:
            raise ValidationError("没有可用的输入图像：请在数据页选择一张图像，或将来源设为 path")
        image = load_image(path)
        if params["color_mode"] == "gray":
            image = to_gray(image)
        elif params["color_mode"] == "color":
            image = to_bgr(image)
        max_side = int(params["max_side"] or 0)
        if max_side > 0:
            from app.utils.imageio import fit_within

            image = fit_within(image, max_side)
        ctx.log(f"载入 {ctx.image_name or path} -> {image.shape}")
        return {"image": image}


@register
class ConstantImage(Node):
    type = "test_pattern"
    label = "Test Pattern"
    category = "Input"
    description = "生成测试图（棋盘格/渐变/噪声），无需数据即可验证流程。"
    tags = ("input", "debug")
    outputs = (PortSpec("image", PortType.IMAGE, "图像"),)
    params = (
        ParamSpec("pattern", "enum", "gradient", label="图案",
                  options=["gradient", "checker", "noise"]),
        ParamSpec("width", "int", 640, label="宽", min=16, max=4096),
        ParamSpec("height", "int", 480, label="高", min=16, max=4096),
        ParamSpec("seed", "int", 0, label="随机种子", min=0, max=10000),
    )

    def process(self, inputs: dict[str, Any], params: dict[str, Any], ctx: NodeContext) -> dict[str, Any]:
        w, h = params["width"], params["height"]
        if params["pattern"] == "gradient":
            row = np.linspace(0, 255, w, dtype=np.float32)
            image = np.tile(row, (h, 1)).astype(np.uint8)
        elif params["pattern"] == "checker":
            step = max(8, min(w, h) // 8)
            yy, xx = np.mgrid[0:h, 0:w]
            image = (((yy // step + xx // step) % 2) * 200 + 30).astype(np.uint8)
        else:
            rng = np.random.default_rng(params["seed"])
            image = rng.integers(0, 256, size=(h, w), dtype=np.uint8)
        return {"image": image}


@register
class CameraInput(Node):
    type = "camera_input"
    label = "Camera (预留)"
    category = "Input"
    description = (
        "工业相机采集节点。已按统一设备接口预留：内置文件夹模拟相机可直接联调，"
        "真实相机 SDK（GigE/USB3/GenICam）后续在 Device Adapter 中接入。"
    )
    tags = ("input", "camera", "采集", "预留")
    deterministic = False
    outputs = (PortSpec("image", PortType.IMAGE, "图像"),)
    params = (
        ParamSpec("device_id", "str", "sim_folder", label="设备 ID",
                  description="见 设备与接口 页面；sim_folder 为文件夹模拟相机"),
        ParamSpec("trigger", "enum", "software", label="触发方式",
                  options=["software", "hardware", "continuous"]),
        ParamSpec("exposure_us", "int", 10000, label="曝光", min=1, max=1000000, unit="us"),
        ParamSpec("gain", "float", 1.0, label="增益", min=0.1, max=32.0, step=0.1),
        ParamSpec("timeout_ms", "int", 2000, label="超时", min=10, max=60000, unit="ms"),
    )

    def process(self, inputs: dict[str, Any], params: dict[str, Any], ctx: NodeContext) -> dict[str, Any]:
        from app.services.devices import device_manager

        frame = device_manager.grab(
            params["device_id"],
            trigger=params["trigger"],
            exposure_us=params["exposure_us"],
            gain=params["gain"],
            timeout_ms=params["timeout_ms"],
            project_id=ctx.project_id,
        )
        ctx.log(f"采集设备 {params['device_id']} 返回 {frame.shape}")
        return {"image": frame}
