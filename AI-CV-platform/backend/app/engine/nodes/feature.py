"""Feature extraction: edges, contours, blobs, circles, lines."""

from __future__ import annotations

from typing import Any

import cv2
import numpy as np

from app.engine.algorithms.geometry import mask_from_regions, regions_from_mask
from app.engine.base import Node, NodeContext
from app.engine.registry import register
from app.engine.types import ParamSpec, PortSpec, PortType, Region, Regions
from app.utils.imageio import to_uint8


@register
class Canny(Node):
    type = "canny"
    label = "Canny"
    category = "Feature"
    description = "Canny 边缘检测，输出边缘掩膜。"
    tags = ("edge", "canny", "边缘")
    inputs = (PortSpec("image", PortType.IMAGE, "图像"),)
    outputs = (PortSpec("mask", PortType.MASK, "边缘"),)
    params = (
        ParamSpec("low", "int", 50, label="低阈值", min=0, max=500, level="business"),
        ParamSpec("high", "int", 150, label="高阈值", min=0, max=500, level="business"),
        ParamSpec("aperture", "int", 3, label="Sobel 孔径", min=3, max=7, step=2),
        ParamSpec("l2_gradient", "bool", False, label="L2 梯度"),
    )

    def process(self, inputs: dict[str, Any], params: dict[str, Any], ctx: NodeContext) -> dict[str, Any]:
        gray = self.as_gray(self.require_image(inputs))
        low, high = params["low"], params["high"]
        if high < low:
            low, high = high, low
        edges = cv2.Canny(gray, low, high, apertureSize=self.odd(params["aperture"], 3),
                          L2gradient=params["l2_gradient"])
        return {"mask": edges}


@register
class Sobel(Node):
    type = "sobel"
    label = "Sobel"
    category = "Feature"
    description = "Sobel 梯度幅值图，可作为边缘强度或纹理特征。"
    tags = ("edge", "sobel", "梯度")
    inputs = (PortSpec("image", PortType.IMAGE, "图像"),)
    outputs = (PortSpec("image", PortType.IMAGE, "梯度图"),)
    params = (
        ParamSpec("direction", "enum", "magnitude", label="方向", options=["x", "y", "magnitude"]),
        ParamSpec("kernel", "int", 3, label="核大小", min=1, max=31, step=2),
    )

    def process(self, inputs: dict[str, Any], params: dict[str, Any], ctx: NodeContext) -> dict[str, Any]:
        gray = self.as_gray(self.require_image(inputs))
        k = self.odd(params["kernel"])
        gx = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=k)
        gy = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=k)
        if params["direction"] == "x":
            data = np.abs(gx)
        elif params["direction"] == "y":
            data = np.abs(gy)
        else:
            data = cv2.magnitude(gx, gy)
        return {"image": to_uint8(data)}


@register
class Laplacian(Node):
    type = "laplacian"
    label = "Laplacian"
    category = "Feature"
    description = "拉普拉斯二阶导数，对模糊/清晰度评价与细节增强有用。"
    tags = ("edge", "laplacian")
    inputs = (PortSpec("image", PortType.IMAGE, "图像"),)
    outputs = (PortSpec("image", PortType.IMAGE, "响应图"),)
    params = (
        ParamSpec("kernel", "int", 3, label="核大小", min=1, max=31, step=2),
    )

    def process(self, inputs: dict[str, Any], params: dict[str, Any], ctx: NodeContext) -> dict[str, Any]:
        gray = self.as_gray(self.require_image(inputs))
        response = cv2.Laplacian(gray, cv2.CV_32F, ksize=self.odd(params["kernel"]))
        return {"image": to_uint8(np.abs(response))}


@register
class FindContours(Node):
    type = "find_contours"
    label = "Contour"
    category = "Feature"
    description = "从掩膜提取轮廓与几何属性，是测量与判定的输入。"
    tags = ("contour", "轮廓")
    inputs = (
        PortSpec("mask", PortType.MASK, "掩膜"),
        PortSpec("image", PortType.IMAGE, "原图（可选，用于灰度统计）", required=False),
    )
    outputs = (PortSpec("regions", PortType.REGIONS, "区域"),)
    params = (
        ParamSpec("external_only", "bool", True, label="仅外轮廓"),
        ParamSpec("min_area", "float", 10.0, label="最小面积", min=0.0, max=1e9, unit="px²",
                  level="business"),
    )

    def process(self, inputs: dict[str, Any], params: dict[str, Any], ctx: NodeContext) -> dict[str, Any]:
        mask = self.require_image(inputs, "mask")
        regions = regions_from_mask(
            mask, inputs.get("image"), params["external_only"], params["min_area"]
        )
        ctx.log(f"提取到 {len(regions)} 个区域")
        return {"regions": regions}


@register
class BlobAnalysis(Node):
    type = "blob_analysis"
    label = "Blob"
    category = "Feature"
    description = (
        "Blob 分析：提取连通域并按面积/圆度/长宽比筛选，"
        "典型用于污点、缺陷、颗粒检测。"
    )
    tags = ("blob", "连通域", "缺陷")
    inputs = (
        PortSpec("mask", PortType.MASK, "掩膜"),
        PortSpec("image", PortType.IMAGE, "原图（可选）", required=False),
    )
    outputs = (
        PortSpec("regions", PortType.REGIONS, "区域"),
        PortSpec("mask", PortType.MASK, "筛选后掩膜"),
    )
    params = (
        ParamSpec("min_area", "float", 50.0, label="最小面积", min=0.0, max=1e9, unit="px²",
                  level="business", description="小于该面积的目标视为噪声"),
        ParamSpec("max_area", "float", 0.0, label="最大面积", min=0.0, max=1e9, unit="px²",
                  level="business", description="0 表示不限制"),
        ParamSpec("min_circularity", "float", 0.0, label="最小圆度", min=0.0, max=1.0, step=0.01),
        ParamSpec("max_aspect_ratio", "float", 0.0, label="最大长宽比", min=0.0, max=100.0, step=0.1,
                  description="0 表示不限制"),
    )

    def process(self, inputs: dict[str, Any], params: dict[str, Any], ctx: NodeContext) -> dict[str, Any]:
        mask = self.require_image(inputs, "mask")
        regions = regions_from_mask(mask, inputs.get("image"), True, params["min_area"])
        kept: list[Region] = []
        for region in regions.items:
            if params["max_area"] > 0 and region.area > params["max_area"]:
                continue
            if region.circularity < params["min_circularity"]:
                continue
            ratio = max(region.aspect_ratio, 1.0 / region.aspect_ratio) if region.aspect_ratio else 1.0
            if params["max_aspect_ratio"] > 0 and ratio > params["max_aspect_ratio"]:
                continue
            kept.append(region)
        for index, region in enumerate(kept):
            region.index = index
        result = Regions(items=kept, shape=regions.shape)
        ctx.log(f"筛选后保留 {len(kept)}/{len(regions)} 个 Blob")
        return {"regions": result, "mask": mask_from_regions(result)}


@register
class HoughCircle(Node):
    type = "hough_circle"
    label = "Circle"
    category = "Feature"
    description = "霍夫圆检测，输出圆心与半径（作为区域返回）。"
    tags = ("circle", "hough", "圆")
    inputs = (PortSpec("image", PortType.IMAGE, "图像"),)
    outputs = (PortSpec("regions", PortType.REGIONS, "圆"),)
    params = (
        ParamSpec("dp", "float", 1.5, label="累加器缩放", min=1.0, max=5.0, step=0.1),
        ParamSpec("min_dist", "int", 40, label="圆心最小间距", min=1, max=2000, unit="px"),
        ParamSpec("param1", "float", 120.0, label="Canny 高阈值", min=1.0, max=500.0),
        ParamSpec("param2", "float", 40.0, label="圆心累加阈值", min=1.0, max=500.0, level="business"),
        ParamSpec("min_radius", "int", 5, label="最小半径", min=0, max=4000, unit="px", level="business"),
        ParamSpec("max_radius", "int", 0, label="最大半径", min=0, max=4000, unit="px", level="business"),
    )

    def process(self, inputs: dict[str, Any], params: dict[str, Any], ctx: NodeContext) -> dict[str, Any]:
        gray = self.as_gray(self.require_image(inputs))
        circles = cv2.HoughCircles(
            gray, cv2.HOUGH_GRADIENT, dp=params["dp"], minDist=params["min_dist"],
            param1=params["param1"], param2=params["param2"],
            minRadius=params["min_radius"], maxRadius=params["max_radius"],
        )
        items: list[Region] = []
        if circles is not None:
            for index, (cx, cy, radius) in enumerate(np.round(circles[0]).astype(int)):
                angles = np.linspace(0, 2 * np.pi, 72, endpoint=False)
                contour = np.stack(
                    [cx + radius * np.cos(angles), cy + radius * np.sin(angles)], axis=1
                ).astype(np.int32)
                items.append(
                    Region(
                        index=index,
                        area=float(np.pi * radius * radius),
                        centroid=(float(cx), float(cy)),
                        bbox=(int(cx - radius), int(cy - radius), int(2 * radius), int(2 * radius)),
                        contour=contour,
                        perimeter=float(2 * np.pi * radius),
                        circularity=1.0,
                        solidity=1.0,
                        equivalent_diameter=float(2 * radius),
                        extra={"radius": float(radius)},
                    )
                )
        ctx.log(f"检测到 {len(items)} 个圆")
        return {"regions": Regions(items=items, shape=gray.shape[:2])}


@register
class HoughLine(Node):
    type = "hough_line"
    label = "Line"
    category = "Feature"
    description = "概率霍夫直线检测，输出线段（作为两点区域返回）。"
    tags = ("line", "hough", "直线")
    inputs = (PortSpec("image", PortType.IMAGE, "图像/边缘"),)
    outputs = (PortSpec("regions", PortType.REGIONS, "线段"),)
    params = (
        ParamSpec("threshold", "int", 80, label="累加阈值", min=1, max=1000, level="business"),
        ParamSpec("min_length", "int", 50, label="最小长度", min=1, max=5000, unit="px",
                  level="business"),
        ParamSpec("max_gap", "int", 10, label="最大间隙", min=0, max=1000, unit="px"),
        ParamSpec("auto_edge", "bool", True, label="自动做 Canny",
                  description="输入不是边缘图时先做边缘检测"),
    )

    def process(self, inputs: dict[str, Any], params: dict[str, Any], ctx: NodeContext) -> dict[str, Any]:
        gray = self.as_gray(self.require_image(inputs))
        edges = cv2.Canny(gray, 50, 150) if params["auto_edge"] else gray
        lines = cv2.HoughLinesP(
            edges, 1, np.pi / 180, params["threshold"],
            minLineLength=params["min_length"], maxLineGap=params["max_gap"],
        )
        items: list[Region] = []
        if lines is not None:
            for index, (x1, y1, x2, y2) in enumerate(lines[:, 0, :]):
                length = float(np.hypot(x2 - x1, y2 - y1))
                angle = float(np.degrees(np.arctan2(y2 - y1, x2 - x1)) % 180.0)
                items.append(
                    Region(
                        index=index,
                        area=0.0,
                        centroid=((x1 + x2) / 2.0, (y1 + y2) / 2.0),
                        bbox=(int(min(x1, x2)), int(min(y1, y2)), int(abs(x2 - x1)), int(abs(y2 - y1))),
                        contour=np.array([[x1, y1], [x2, y2]], dtype=np.int32),
                        perimeter=length,
                        extra={"length": round(length, 2), "angle": round(angle, 2)},
                    )
                )
        ctx.log(f"检测到 {len(items)} 条线段")
        return {"regions": Regions(items=items, shape=gray.shape[:2])}


@register
class TemplateMatch(Node):
    type = "template_match"
    label = "Template Match"
    category = "Feature"
    description = "归一化相关模板匹配，用于存在性检测与粗定位。"
    tags = ("template", "match", "模板匹配", "定位")
    inputs = (
        PortSpec("image", PortType.IMAGE, "图像"),
        PortSpec("template", PortType.IMAGE, "模板"),
    )
    outputs = (
        PortSpec("regions", PortType.REGIONS, "匹配位置"),
        PortSpec("score", PortType.VALUE, "最高得分"),
    )
    params = (
        ParamSpec("threshold", "float", 0.8, label="匹配阈值", min=0.0, max=1.0, step=0.01,
                  level="business"),
        ParamSpec("max_matches", "int", 10, label="最多匹配数", min=1, max=200),
    )

    def process(self, inputs: dict[str, Any], params: dict[str, Any], ctx: NodeContext) -> dict[str, Any]:
        from app.engine.types import Value

        gray = self.as_gray(self.require_image(inputs))
        template = self.as_gray(self.require_image(inputs, "template"))
        th, tw = template.shape[:2]
        if th > gray.shape[0] or tw > gray.shape[1]:
            raise ValueError("模板尺寸大于输入图像")
        score_map = cv2.matchTemplate(gray, template, cv2.TM_CCOEFF_NORMED)
        items: list[Region] = []
        working = score_map.copy()
        best = float(working.max()) if working.size else 0.0
        for index in range(params["max_matches"]):
            _, max_val, _, max_loc = cv2.minMaxLoc(working)
            if max_val < params["threshold"]:
                break
            x, y = max_loc
            contour = np.array(
                [[x, y], [x + tw, y], [x + tw, y + th], [x, y + th]], dtype=np.int32
            )
            items.append(
                Region(
                    index=index,
                    area=float(tw * th),
                    centroid=(x + tw / 2.0, y + th / 2.0),
                    bbox=(int(x), int(y), int(tw), int(th)),
                    contour=contour,
                    perimeter=float(2 * (tw + th)),
                    extra={"score": round(float(max_val), 4)},
                )
            )
            cv2.rectangle(working, (max(0, x - tw // 2), max(0, y - th // 2)),
                          (x + tw // 2, y + th // 2), 0.0, -1)
        ctx.log(f"匹配到 {len(items)} 处，最高得分 {best:.3f}")
        return {
            "regions": Regions(items=items, shape=gray.shape[:2]),
            "score": Value(best, "match_score", ""),
        }
