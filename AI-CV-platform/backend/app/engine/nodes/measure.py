"""Measurement nodes: regions/images -> scalar values."""

from __future__ import annotations

from typing import Any

import numpy as np

from app.core.errors import ValidationError
from app.engine.algorithms.geometry import major_axis_length, mask_from_regions, orientation_deg
from app.engine.base import Node, NodeContext
from app.engine.registry import register
from app.engine.types import ParamSpec, PortSpec, PortType, Regions, Roi, Value

_AGGREGATE = ParamSpec(
    "aggregate", "enum", "max", label="统计方式",
    options=["max", "sum", "mean", "min", "first"],
)


def _require_regions(inputs: dict[str, Any]) -> Regions:
    regions = inputs.get("regions")
    if not isinstance(regions, Regions):
        raise ValidationError("需要 Regions 输入（请先接 Contour 或 Blob 节点）")
    return regions


def _aggregate(values: list[float], how: str) -> float:
    if not values:
        return 0.0
    if how == "sum":
        return float(np.sum(values))
    if how == "mean":
        return float(np.mean(values))
    if how == "min":
        return float(np.min(values))
    if how == "first":
        return float(values[0])
    return float(np.max(values))


@register
class RegionFilter(Node):
    type = "region_filter"
    label = "Region Filter"
    category = "Measure"
    description = "按面积/圆度区间筛选区域，用户侧的“最小缺陷尺寸”通常映射到这里。"
    tags = ("filter", "area", "面积过滤")
    inputs = (PortSpec("regions", PortType.REGIONS, "区域"),)
    outputs = (
        PortSpec("regions", PortType.REGIONS, "区域"),
        PortSpec("mask", PortType.MASK, "掩膜"),
        PortSpec("count", PortType.VALUE, "数量"),
    )
    params = (
        ParamSpec("min_area", "float", 0.0, label="最小面积", min=0.0, max=1e9, unit="px²",
                  level="business"),
        ParamSpec("max_area", "float", 0.0, label="最大面积", min=0.0, max=1e9, unit="px²",
                  level="business", description="0 表示不限制"),
        ParamSpec("min_circularity", "float", 0.0, label="最小圆度", min=0.0, max=1.0, step=0.01),
        ParamSpec("max_circularity", "float", 1.0, label="最大圆度", min=0.0, max=1.5, step=0.01),
    )

    def process(self, inputs: dict[str, Any], params: dict[str, Any], ctx: NodeContext) -> dict[str, Any]:
        regions = _require_regions(inputs)
        kept = [
            r for r in regions.items
            if r.area >= params["min_area"]
            and (params["max_area"] <= 0 or r.area <= params["max_area"])
            and params["min_circularity"] <= r.circularity <= params["max_circularity"]
        ]
        for index, region in enumerate(kept):
            region.index = index
        result = Regions(items=kept, shape=regions.shape)
        return {
            "regions": result,
            "mask": mask_from_regions(result),
            "count": Value(float(len(kept)), "region_count", "个"),
        }


@register
class AreaMeasure(Node):
    type = "area_measure"
    label = "Area"
    category = "Measure"
    description = "区域面积测量，可输出像素面积或占图像面积的百分比。"
    tags = ("area", "面积", "measure")
    inputs = (PortSpec("regions", PortType.REGIONS, "区域"),)
    outputs = (PortSpec("value", PortType.VALUE, "面积"),)
    params = (
        _AGGREGATE,
        ParamSpec("unit", "enum", "px", label="单位", options=["px", "percent"]),
        ParamSpec("name", "str", "area", label="测量名称"),
    )

    def process(self, inputs: dict[str, Any], params: dict[str, Any], ctx: NodeContext) -> dict[str, Any]:
        regions = _require_regions(inputs)
        areas = [r.area for r in regions.items]
        if params["unit"] == "percent":
            total = float(regions.shape[0] * regions.shape[1]) or 1.0
            areas = [a / total * 100.0 for a in areas]
        value = _aggregate(areas, params["aggregate"])
        return {
            "value": Value(value, params["name"], "%" if params["unit"] == "percent" else "px²",
                           values=areas)
        }


@register
class CountMeasure(Node):
    type = "count_measure"
    label = "Count"
    category = "Measure"
    description = "统计区域数量（计数类任务的核心测量）。"
    tags = ("count", "计数", "measure")
    inputs = (PortSpec("regions", PortType.REGIONS, "区域"),)
    outputs = (PortSpec("value", PortType.VALUE, "数量"),)
    params = (
        ParamSpec("name", "str", "count", label="测量名称"),
    )

    def process(self, inputs: dict[str, Any], params: dict[str, Any], ctx: NodeContext) -> dict[str, Any]:
        regions = _require_regions(inputs)
        return {"value": Value(float(len(regions)), params["name"], "个")}


@register
class LengthMeasure(Node):
    type = "length_measure"
    label = "Length"
    category = "Measure"
    description = "长度测量：最小外接矩形长边、等效直径或周长。"
    tags = ("length", "尺寸", "measure")
    inputs = (PortSpec("regions", PortType.REGIONS, "区域"),)
    outputs = (PortSpec("value", PortType.VALUE, "长度"),)
    params = (
        ParamSpec("metric", "enum", "major_axis", label="度量",
                  options=["major_axis", "equivalent_diameter", "perimeter", "bbox_width",
                           "bbox_height"]),
        _AGGREGATE,
        ParamSpec("mm_per_px", "float", 0.0, label="标定系数", min=0.0, max=1000.0, step=0.0001,
                  unit="mm/px", description="0 表示输出像素值"),
        ParamSpec("name", "str", "length", label="测量名称"),
    )

    def process(self, inputs: dict[str, Any], params: dict[str, Any], ctx: NodeContext) -> dict[str, Any]:
        regions = _require_regions(inputs)
        metric = params["metric"]
        values: list[float] = []
        for region in regions.items:
            if metric == "major_axis":
                values.append(major_axis_length(region.contour))
            elif metric == "equivalent_diameter":
                values.append(region.equivalent_diameter)
            elif metric == "perimeter":
                values.append(region.perimeter)
            elif metric == "bbox_width":
                values.append(float(region.bbox[2]))
            else:
                values.append(float(region.bbox[3]))
        unit = "px"
        if params["mm_per_px"] > 0:
            values = [v * params["mm_per_px"] for v in values]
            unit = "mm"
        return {"value": Value(_aggregate(values, params["aggregate"]), params["name"], unit,
                               values=values)}


@register
class DistanceMeasure(Node):
    type = "distance_measure"
    label = "Distance"
    category = "Measure"
    description = "距离测量：区域中心到图像中心、到指定点，或区域之间的最大间距。"
    tags = ("distance", "距离", "measure")
    inputs = (PortSpec("regions", PortType.REGIONS, "区域"),)
    outputs = (PortSpec("value", PortType.VALUE, "距离"),)
    params = (
        ParamSpec("mode", "enum", "to_image_center", label="模式",
                  options=["to_image_center", "to_point", "max_pairwise"]),
        ParamSpec("point_x", "float", 0.5, label="参考点 X（相对）", min=0.0, max=1.0, step=0.001,
                  depends_on=("mode", ("to_point",))),
        ParamSpec("point_y", "float", 0.5, label="参考点 Y（相对）", min=0.0, max=1.0, step=0.001,
                  depends_on=("mode", ("to_point",))),
        ParamSpec("mm_per_px", "float", 0.0, label="标定系数", min=0.0, max=1000.0, step=0.0001,
                  unit="mm/px"),
        ParamSpec("name", "str", "distance", label="测量名称"),
    )

    def process(self, inputs: dict[str, Any], params: dict[str, Any], ctx: NodeContext) -> dict[str, Any]:
        regions = _require_regions(inputs)
        height, width = regions.shape
        centers = [r.centroid for r in regions.items]
        values: list[float] = []
        if params["mode"] == "max_pairwise":
            for i in range(len(centers)):
                for j in range(i + 1, len(centers)):
                    values.append(float(np.hypot(centers[i][0] - centers[j][0],
                                                 centers[i][1] - centers[j][1])))
            aggregated = max(values) if values else 0.0
        else:
            if params["mode"] == "to_point":
                ref = (params["point_x"] * width, params["point_y"] * height)
            else:
                ref = (width / 2.0, height / 2.0)
            values = [float(np.hypot(cx - ref[0], cy - ref[1])) for cx, cy in centers]
            aggregated = values[0] if values else 0.0
        unit = "px"
        if params["mm_per_px"] > 0:
            factor = params["mm_per_px"]
            values = [v * factor for v in values]
            aggregated *= factor
            unit = "mm"
        return {"value": Value(aggregated, params["name"], unit, values=values)}


@register
class AngleMeasure(Node):
    type = "angle_measure"
    label = "Angle"
    category = "Measure"
    description = "角度测量：最大区域的主轴方向角（0-180°）。"
    tags = ("angle", "角度", "measure")
    inputs = (PortSpec("regions", PortType.REGIONS, "区域"),)
    outputs = (PortSpec("value", PortType.VALUE, "角度"),)
    params = (
        ParamSpec("name", "str", "angle", label="测量名称"),
    )

    def process(self, inputs: dict[str, Any], params: dict[str, Any], ctx: NodeContext) -> dict[str, Any]:
        regions = _require_regions(inputs)
        values = [orientation_deg(r.contour) for r in regions.items]
        return {"value": Value(values[0] if values else 0.0, params["name"], "°", values=values)}


@register
class IntensityStats(Node):
    type = "intensity_stats"
    label = "Intensity"
    category = "Measure"
    description = "灰度统计（均值/标准差/最值/占比），可限定在 ROI 或掩膜内。"
    tags = ("intensity", "灰度", "statistics")
    inputs = (
        PortSpec("image", PortType.IMAGE, "图像"),
        PortSpec("mask", PortType.MASK, "掩膜（可选）", required=False),
    )
    outputs = (PortSpec("value", PortType.VALUE, "统计值"),)
    params = (
        ParamSpec("metric", "enum", "mean", label="统计量",
                  options=["mean", "std", "min", "max", "foreground_ratio"]),
        ParamSpec("name", "str", "intensity", label="测量名称"),
    )

    def process(self, inputs: dict[str, Any], params: dict[str, Any], ctx: NodeContext) -> dict[str, Any]:
        gray = self.as_gray(self.require_image(inputs))
        mask = inputs.get("mask")
        if isinstance(mask, Roi):
            selector = mask.mask.astype(bool)
        elif isinstance(mask, np.ndarray):
            selector = mask.astype(bool) if mask.dtype == bool else mask > 0
        else:
            selector = None

        if params["metric"] == "foreground_ratio":
            if selector is None:
                raise ValidationError("foreground_ratio 需要掩膜输入")
            ratio = float(np.count_nonzero(selector)) / float(selector.size) * 100.0
            return {"value": Value(ratio, params["name"], "%")}

        data = gray[selector] if selector is not None and selector.any() else gray.reshape(-1)
        metric = params["metric"]
        value = {
            "mean": float(np.mean(data)),
            "std": float(np.std(data)),
            "min": float(np.min(data)),
            "max": float(np.max(data)),
        }[metric]
        return {"value": Value(value, params["name"], "gray")}
