"""ROI nodes: limit where the rest of the pipeline looks."""

from __future__ import annotations

import json
from typing import Any

import cv2
import numpy as np

from app.core.errors import ValidationError
from app.engine.base import Node, NodeContext
from app.engine.registry import register
from app.engine.types import ParamSpec, PortSpec, PortType, Roi

_MODE = ParamSpec(
    "mode", "enum", "relative", label="坐标模式", options=["relative", "absolute"],
    description="relative=按图像尺寸比例(0-1)，切换分辨率仍然有效；absolute=像素",
)


def _scale(value: float, extent: int, relative: bool) -> int:
    return int(round(value * extent)) if relative else int(round(value))


@register
class RectRoi(Node):
    type = "rect_roi"
    label = "Rectangle ROI"
    category = "ROI"
    description = "矩形 ROI，可在 Viewer 中直接框选后回填参数。"
    tags = ("roi", "rect", "矩形")
    inputs = (PortSpec("image", PortType.IMAGE, "图像"),)
    outputs = (PortSpec("roi", PortType.ROI, "ROI"),)
    params = (
        _MODE,
        ParamSpec("x", "float", 0.0, label="X", min=0, max=1e6, step=0.001, level="business"),
        ParamSpec("y", "float", 0.0, label="Y", min=0, max=1e6, step=0.001, level="business"),
        ParamSpec("width", "float", 1.0, label="宽", min=0, max=1e6, step=0.001, level="business"),
        ParamSpec("height", "float", 1.0, label="高", min=0, max=1e6, step=0.001, level="business"),
    )

    def process(self, inputs: dict[str, Any], params: dict[str, Any], ctx: NodeContext) -> dict[str, Any]:
        image = self.require_image(inputs)
        h, w = image.shape[:2]
        relative = params["mode"] == "relative"
        x = max(0, min(w - 1, _scale(params["x"], w, relative)))
        y = max(0, min(h - 1, _scale(params["y"], h, relative)))
        rw = max(1, min(w - x, _scale(params["width"], w, relative)))
        rh = max(1, min(h - y, _scale(params["height"], h, relative)))
        mask = np.zeros((h, w), dtype=bool)
        mask[y:y + rh, x:x + rw] = True
        return {"roi": Roi(mask=mask, bbox=(x, y, rw, rh), shape=(h, w), kind="rect")}


@register
class CircleRoi(Node):
    type = "circle_roi"
    label = "Circle ROI"
    category = "ROI"
    description = "圆形 ROI，适合圆形工件/培养皿视野。"
    tags = ("roi", "circle", "圆")
    inputs = (PortSpec("image", PortType.IMAGE, "图像"),)
    outputs = (PortSpec("roi", PortType.ROI, "ROI"),)
    params = (
        _MODE,
        ParamSpec("cx", "float", 0.5, label="圆心 X", min=0, max=1e6, step=0.001, level="business"),
        ParamSpec("cy", "float", 0.5, label="圆心 Y", min=0, max=1e6, step=0.001, level="business"),
        ParamSpec("radius", "float", 0.45, label="半径", min=0.0001, max=1e6, step=0.001,
                  level="business"),
    )

    def process(self, inputs: dict[str, Any], params: dict[str, Any], ctx: NodeContext) -> dict[str, Any]:
        image = self.require_image(inputs)
        h, w = image.shape[:2]
        relative = params["mode"] == "relative"
        cx = _scale(params["cx"], w, relative)
        cy = _scale(params["cy"], h, relative)
        radius = max(1, _scale(params["radius"], min(h, w), relative))
        canvas = np.zeros((h, w), dtype=np.uint8)
        cv2.circle(canvas, (cx, cy), radius, 255, -1)
        x0, y0 = max(0, cx - radius), max(0, cy - radius)
        x1, y1 = min(w, cx + radius), min(h, cy + radius)
        return {
            "roi": Roi(mask=canvas.astype(bool), bbox=(x0, y0, x1 - x0, y1 - y0),
                       shape=(h, w), kind="circle")
        }


@register
class PolygonRoi(Node):
    type = "polygon_roi"
    label = "Polygon ROI"
    category = "ROI"
    description = "多边形 ROI，点集可由 Viewer 绘制生成。"
    tags = ("roi", "polygon", "多边形")
    inputs = (PortSpec("image", PortType.IMAGE, "图像"),)
    outputs = (PortSpec("roi", PortType.ROI, "ROI"),)
    params = (
        _MODE,
        ParamSpec("points", "text", "[[0.1,0.1],[0.9,0.1],[0.9,0.9],[0.1,0.9]]",
                  label="点集", description="JSON 数组 [[x,y], ...]"),
        ParamSpec("invert", "bool", False, label="反向（排除区域）"),
    )

    def process(self, inputs: dict[str, Any], params: dict[str, Any], ctx: NodeContext) -> dict[str, Any]:
        image = self.require_image(inputs)
        h, w = image.shape[:2]
        try:
            raw = json.loads(params["points"])
            points = [(float(p[0]), float(p[1])) for p in raw]
        except Exception as exc:  # noqa: BLE001
            raise ValidationError(f"多边形点集格式错误: {exc}") from exc
        if len(points) < 3:
            raise ValidationError("多边形至少需要 3 个点")
        relative = params["mode"] == "relative"
        pts = np.array(
            [[_scale(px, w, relative), _scale(py, h, relative)] for px, py in points],
            dtype=np.int32,
        )
        canvas = np.zeros((h, w), dtype=np.uint8)
        cv2.fillPoly(canvas, [pts], 255)
        if params["invert"]:
            canvas = 255 - canvas
        ys, xs = np.nonzero(canvas)
        if len(xs) == 0:
            raise ValidationError("多边形 ROI 为空")
        bbox = (int(xs.min()), int(ys.min()), int(xs.max() - xs.min() + 1), int(ys.max() - ys.min() + 1))
        return {"roi": Roi(mask=canvas.astype(bool), bbox=bbox, shape=(h, w), kind="polygon")}


@register
class Crop(Node):
    type = "crop"
    label = "Crop"
    category = "ROI"
    description = "按 ROI 外接矩形裁剪图像，后续节点只处理裁剪区域。"
    tags = ("roi", "crop", "裁剪")
    inputs = (
        PortSpec("image", PortType.IMAGE, "图像"),
        PortSpec("roi", PortType.ROI, "ROI"),
    )
    outputs = (PortSpec("image", PortType.IMAGE, "图像"),)
    params = (
        ParamSpec("padding", "int", 0, label="外扩", min=0, max=2000, unit="px"),
    )

    def process(self, inputs: dict[str, Any], params: dict[str, Any], ctx: NodeContext) -> dict[str, Any]:
        image = self.require_image(inputs)
        roi = inputs.get("roi")
        if not isinstance(roi, Roi):
            raise ValidationError("Crop 需要 ROI 输入")
        h, w = image.shape[:2]
        x, y, rw, rh = roi.bbox
        pad = params["padding"]
        x0, y0 = max(0, x - pad), max(0, y - pad)
        x1, y1 = min(w, x + rw + pad), min(h, y + rh + pad)
        return {"image": image[y0:y1, x0:x1].copy()}


@register
class ApplyMask(Node):
    type = "apply_mask"
    label = "Mask"
    category = "ROI"
    description = "把 ROI 之外的区域填充为固定灰度，保持图像尺寸不变。"
    tags = ("roi", "mask", "掩膜")
    inputs = (
        PortSpec("image", PortType.IMAGE, "图像"),
        PortSpec("roi", PortType.ROI, "ROI"),
    )
    outputs = (PortSpec("image", PortType.IMAGE, "图像"),)
    params = (
        ParamSpec("fill", "int", 0, label="填充灰度", min=0, max=255),
    )

    def process(self, inputs: dict[str, Any], params: dict[str, Any], ctx: NodeContext) -> dict[str, Any]:
        image = self.require_image(inputs).copy()
        roi = inputs.get("roi")
        if isinstance(roi, Roi):
            mask = roi.mask.astype(bool)
        elif isinstance(roi, np.ndarray):
            mask = roi.astype(bool)
        else:
            raise ValidationError("Mask 需要 ROI 或 Mask 输入")
        if mask.shape != image.shape[:2]:
            mask = cv2.resize(mask.astype(np.uint8), (image.shape[1], image.shape[0]),
                              interpolation=cv2.INTER_NEAREST).astype(bool)
        image[~mask] = params["fill"]
        return {"image": image}
