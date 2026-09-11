"""Starter pipeline templates.

They double as the Copilot's skeletons: the planner picks a template for the
recognised task type and then tunes parameters, which keeps generated pipelines
inside the validated node whitelist.
"""

from __future__ import annotations

from typing import Any


def _node(node_id: str, node_type: str, x: int, y: int, params: dict | None = None,
          label: str = "") -> dict:
    return {
        "id": node_id,
        "type": node_type,
        "label": label,
        "params": params or {},
        "position": {"x": x, "y": y},
        "enabled": True,
    }


def _edge(source: str, source_handle: str, target: str, target_handle: str) -> dict:
    return {
        "id": f"{source}:{source_handle}->{target}:{target_handle}",
        "source": source,
        "sourceHandle": source_handle,
        "target": target,
        "targetHandle": target_handle,
    }


COLUMN = 260
ROW = 150


def blank_graph() -> dict:
    return {"nodes": [_node("input", "image_input", 40, 200)], "edges": []}


def ipsc_colony_graph() -> dict:
    """iPSC 克隆定位与形态判定（原型 colony_center.py 的平台化版本）。"""
    nodes = [
        _node("input", "image_input", 40, 220, {"color_mode": "gray", "max_side": 1600}),
        _node("colony", "ipsc_colony_segment", 40 + COLUMN, 220,
              {"min_area_frac": 0.01, "keep_largest": True}),
        _node("metrics", "ipsc_colony_metrics", 40 + COLUMN * 2, 220),
        _node("judge", "threshold_judge", 40 + COLUMN * 3, 220,
              {"operator": "between", "limit": 3.0, "upper": 60.0, "name": "colony_area"}),
        _node("verdict", "ok_ng", 40 + COLUMN * 4, 220,
              {"ok_message": "克隆面积正常", "ng_message": "克隆面积超出范围"}),
        _node("display", "display", 40 + COLUMN * 5, 220),
        _node("report", "json_result", 40 + COLUMN * 5, 220 + ROW * 2),
    ]
    edges = [
        _edge("input", "image", "colony", "image"),
        _edge("colony", "mask", "metrics", "mask"),
        _edge("metrics", "area_percent", "judge", "value"),
        _edge("judge", "result", "verdict", "result"),
        _edge("input", "image", "display", "image"),
        _edge("metrics", "regions", "display", "regions"),
        _edge("verdict", "result", "display", "result"),
        _edge("verdict", "result", "report", "result"),
        _edge("metrics", "regions", "report", "regions"),
    ]
    return {"nodes": nodes, "edges": edges}


def surface_defect_graph() -> dict:
    """污渍/瑕疵检测：CLAHE + 局部阈值 + 形态学 + Blob + 数量判定。"""
    nodes = [
        _node("input", "image_input", 40, 200, {"color_mode": "gray"}),
        _node("clahe", "clahe", 40 + COLUMN, 200, {"clip_limit": 2.5, "tile_grid": 8}),
        _node("blur", "gaussian_blur", 40 + COLUMN * 2, 200, {"kernel": 5}),
        _node("thresh", "adaptive_threshold", 40 + COLUMN * 3, 200,
              {"method": "gaussian", "block_size": 51, "c": 8.0, "invert": True}),
        _node("roi", "rect_roi", 40 + COLUMN * 3, 200 + ROW * 2,
              {"mode": "relative", "x": 0.02, "y": 0.02, "width": 0.96, "height": 0.96}),
        # The ROI is applied to the binary result, not to the grayscale image:
        # masking before thresholding would turn the ROI border itself into the
        # strongest "defect" for the local threshold.
        _node("roi_and", "mask_logic", 40 + COLUMN * 4, 200, {"operation": "and"}),
        _node("open", "morph_open", 40 + COLUMN * 5, 200, {"kernel": 3, "iterations": 1}),
        _node("blob", "blob_analysis", 40 + COLUMN * 6, 200, {"min_area": 60.0}),
        _node("judge", "count_judge", 40 + COLUMN * 7, 200, {"operator": "<=", "limit": 0.0}),
        _node("verdict", "ok_ng", 40 + COLUMN * 8, 200,
              {"ok_message": "表面无缺陷", "ng_message": "检出缺陷"}),
        _node("display", "display", 40 + COLUMN * 9, 200),
    ]
    edges = [
        _edge("input", "image", "clahe", "image"),
        _edge("clahe", "image", "blur", "image"),
        _edge("blur", "image", "thresh", "image"),
        _edge("input", "image", "roi", "image"),
        _edge("thresh", "mask", "roi_and", "mask_a"),
        _edge("roi", "roi", "roi_and", "mask_b"),
        _edge("roi_and", "mask", "open", "mask"),
        _edge("open", "mask", "blob", "mask"),
        _edge("input", "image", "blob", "image"),
        _edge("blob", "regions", "judge", "regions"),
        _edge("judge", "result", "verdict", "result"),
        _edge("input", "image", "display", "image"),
        _edge("blob", "regions", "display", "regions"),
        _edge("verdict", "result", "display", "result"),
    ]
    return {"nodes": nodes, "edges": edges}


def counting_graph() -> dict:
    """计数：Otsu 分割 + 形态学 + Blob + 数量区间判定。"""
    nodes = [
        _node("input", "image_input", 40, 200, {"color_mode": "gray"}),
        _node("blur", "gaussian_blur", 40 + COLUMN, 200, {"kernel": 5}),
        _node("otsu", "otsu_threshold", 40 + COLUMN * 2, 200, {"invert": False}),
        _node("open", "morph_open", 40 + COLUMN * 3, 200, {"kernel": 5}),
        _node("blob", "blob_analysis", 40 + COLUMN * 4, 200, {"min_area": 80.0}),
        _node("count", "count_measure", 40 + COLUMN * 5, 200, {"name": "object_count"}),
        _node("judge", "threshold_judge", 40 + COLUMN * 6, 200,
              {"operator": "between", "limit": 1.0, "upper": 999.0, "name": "count"}),
        _node("verdict", "ok_ng", 40 + COLUMN * 7, 200,
              {"ok_message": "数量正常", "ng_message": "数量异常"}),
        _node("display", "display", 40 + COLUMN * 8, 200),
    ]
    edges = [
        _edge("input", "image", "blur", "image"),
        _edge("blur", "image", "otsu", "image"),
        _edge("otsu", "mask", "open", "mask"),
        _edge("open", "mask", "blob", "mask"),
        _edge("input", "image", "blob", "image"),
        _edge("blob", "regions", "count", "regions"),
        _edge("count", "value", "judge", "value"),
        _edge("judge", "result", "verdict", "result"),
        _edge("input", "image", "display", "image"),
        _edge("blob", "regions", "display", "regions"),
        _edge("verdict", "result", "display", "result"),
    ]
    return {"nodes": nodes, "edges": edges}


def measurement_graph() -> dict:
    """尺寸/面积测量：分割 + 长度测量 + 公差判定。"""
    nodes = [
        _node("input", "image_input", 40, 200, {"color_mode": "gray"}),
        _node("blur", "median_blur", 40 + COLUMN, 200, {"kernel": 5}),
        _node("otsu", "otsu_threshold", 40 + COLUMN * 2, 200),
        _node("close", "morph_close", 40 + COLUMN * 3, 200, {"kernel": 7}),
        _node("contour", "find_contours", 40 + COLUMN * 4, 200, {"min_area": 200.0}),
        _node("length", "length_measure", 40 + COLUMN * 5, 200,
              {"metric": "major_axis", "name": "length"}),
        _node("judge", "threshold_judge", 40 + COLUMN * 6, 200,
              {"operator": "between", "limit": 50.0, "upper": 5000.0, "name": "length"}),
        _node("verdict", "ok_ng", 40 + COLUMN * 7, 200,
              {"ok_message": "尺寸合格", "ng_message": "尺寸超差"}),
        _node("display", "display", 40 + COLUMN * 8, 200),
    ]
    edges = [
        _edge("input", "image", "blur", "image"),
        _edge("blur", "image", "otsu", "image"),
        _edge("otsu", "mask", "close", "mask"),
        _edge("close", "mask", "contour", "mask"),
        _edge("input", "image", "contour", "image"),
        _edge("contour", "regions", "length", "regions"),
        _edge("length", "value", "judge", "value"),
        _edge("judge", "result", "verdict", "result"),
        _edge("input", "image", "display", "image"),
        _edge("contour", "regions", "display", "regions"),
        _edge("verdict", "result", "display", "result"),
    ]
    return {"nodes": nodes, "edges": edges}


def anomaly_graph() -> dict:
    """无缺陷样本上线：无监督异常检测 + 面积判定。"""
    nodes = [
        _node("input", "image_input", 40, 200, {"color_mode": "gray"}),
        _node("anomaly", "ai_anomaly_detect", 40 + COLUMN, 200,
              {"method": "residual", "window": 31, "sensitivity": 3.5, "min_area": 30.0}),
        _node("blob", "blob_analysis", 40 + COLUMN * 2, 200, {"min_area": 30.0}),
        _node("judge", "count_judge", 40 + COLUMN * 3, 200, {"operator": "<=", "limit": 0.0}),
        _node("verdict", "ok_ng", 40 + COLUMN * 4, 200,
              {"ok_message": "无异常", "ng_message": "检出异常区域"}),
        _node("display", "display", 40 + COLUMN * 5, 200),
    ]
    edges = [
        _edge("input", "image", "anomaly", "image"),
        _edge("anomaly", "mask", "blob", "mask"),
        _edge("input", "image", "blob", "image"),
        _edge("blob", "regions", "judge", "regions"),
        _edge("judge", "result", "verdict", "result"),
        _edge("input", "image", "display", "image"),
        _edge("blob", "regions", "display", "regions"),
        _edge("verdict", "result", "display", "result"),
    ]
    return {"nodes": nodes, "edges": edges}


def grain_classify_graph(model_id: str = "") -> dict:
    """Sealed-bag grain species: de-glare → crop grain face → YOLO/ONNX classify."""
    nodes = [
        _node("input", "image_input", 40, 200, {"color_mode": "color", "max_side": 1600}),
        _node("deglare", "grain_deglare", 40 + COLUMN, 200),
        _node("roi", "grain_roi", 40 + COLUMN * 2, 200),
        _node("classify", "ai_classify", 40 + COLUMN * 3, 200, {
            "model_id": model_id, "ok_classes": "", "min_confidence": 0.35,
        }),
        _node("verdict", "ok_ng", 40 + COLUMN * 4, 200, {
            "ok_message": "种类可辨", "ng_message": "置信度不足，请人工确认",
        }),
        _node("display", "display", 40 + COLUMN * 5, 200),
    ]
    edges = [
        _edge("input", "image", "deglare", "image"),
        _edge("deglare", "image", "roi", "image"),
        _edge("roi", "image", "classify", "image"),
        _edge("classify", "result", "verdict", "result"),
        _edge("input", "image", "display", "image"),
        _edge("verdict", "result", "display", "result"),
    ]
    return {"nodes": nodes, "edges": edges}


TEMPLATES: list[dict[str, Any]] = [
    {
        "id": "blank",
        "name": "空白项目",
        "taskType": "unknown",
        "description": "只包含一个图像输入节点，从零搭建流程。",
        "builder": blank_graph,
    },
    {
        "id": "ipsc_colony",
        "name": "iPSC 克隆定位（原型移植）",
        "taskType": "colony_localization",
        "description": "局部纹理分割定位克隆中心，输出面积占比/等效直径/实心度并判定。",
        "builder": ipsc_colony_graph,
    },
    {
        "id": "surface_defect",
        "name": "表面污渍/瑕疵检测",
        "taskType": "defect_detection",
        "description": "CLAHE + 局部自适应阈值 + 形态学 + Blob 面积过滤 + 数量判定。",
        "builder": surface_defect_graph,
    },
    {
        "id": "counting",
        "name": "目标计数",
        "taskType": "counting",
        "description": "Otsu 分割后统计目标数量，并按数量区间判定。",
        "builder": counting_graph,
    },
    {
        "id": "measurement",
        "name": "尺寸测量",
        "taskType": "measurement",
        "description": "分割目标后测量主轴长度，按公差区间判定。",
        "builder": measurement_graph,
    },
    {
        "id": "anomaly",
        "name": "无监督异常检测",
        "taskType": "anomaly_detection",
        "description": "仅用正常样本上线：局部统计残差定位异常区域。",
        "builder": anomaly_graph,
    },
    {
        "id": "grain_classify",
        "name": "密封袋谷物分类",
        "taskType": "classification",
        "description": "去反光 + 粮面裁切 + AI 分类（YOLO-cls / EfficientNet ONNX）。",
        "builder": grain_classify_graph,
    },
]

_BY_ID = {t["id"]: t for t in TEMPLATES}
_BY_TASK = {t["taskType"]: t for t in TEMPLATES}


def list_templates() -> list[dict]:
    return [
        {k: v for k, v in template.items() if k != "builder"} | {"nodeCount": len(template["builder"]()["nodes"])}
        for template in TEMPLATES
    ]


def build_graph(template_id: str) -> dict:
    template = _BY_ID.get(template_id) or _BY_ID["blank"]
    return template["builder"]()


def template_for_task(task_type: str) -> dict | None:
    return _BY_TASK.get(task_type)


def task_type_of(template_id: str) -> str:
    template = _BY_ID.get(template_id)
    return template["taskType"] if template else "unknown"
