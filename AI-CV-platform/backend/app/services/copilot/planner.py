"""Constrained pipeline generation.

The chain is: intent + image diagnosis -> technical route -> template skeleton ->
parameter tuning -> schema/whitelist validation. Any graph coming from an LLM
goes through the same :func:`sanitize` gate before it is allowed to execute.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.engine.graph import Graph
from app.engine.registry import get_node_class, has_node
from app.services import templates
from app.services.copilot.intent import Intent


@dataclass
class Plan:
    graph: dict
    task_type: str
    route: str = "traditional"
    route_reason: str = ""
    summary: str = ""
    steps: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    source: str = "rules"

    def to_dict(self) -> dict:
        return {
            "graph": self.graph,
            "taskType": self.task_type,
            "route": self.route,
            "routeReason": self.route_reason,
            "summary": self.summary,
            "steps": self.steps,
            "warnings": self.warnings,
            "source": self.source,
        }


_TEMPLATE_BY_TASK = {
    "defect_detection": "surface_defect",
    "counting": "counting",
    "measurement": "measurement",
    "presence": "counting",
    "positioning": "measurement",
    "colony_localization": "ipsc_colony",
    "anomaly_detection": "anomaly",
    "classification": "grain_classify",
    "unknown": "surface_defect",
}


def choose_route(intent: Intent, diagnosis: dict | None) -> tuple[str, str]:
    """Traditional vision first; only escalate when the geometry/appearance is not separable."""
    metrics = (diagnosis or {}).get("metrics", {})
    edge_density = float(metrics.get("edgeDensity", 0.0))
    texture_percent = float(metrics.get("texturePercent", 0.0))
    contrast = float(metrics.get("dynamicRange", 255.0))

    if intent.task_type == "classification":
        return "ai", "分类/判型任务缺少明确几何判据，建议用标注样本训练分类模型（LBP+SVM 起步）"
    if intent.task_type == "anomaly_detection":
        return "hybrid", "缺陷形态不确定时先用无监督异常检测定位，再用面积/数量做判定"
    if intent.task_type == "colony_localization":
        return "traditional", "克隆与背景的纹理差异显著，局部标准差 + Otsu 已足够稳定，无需深度学习"
    if edge_density > 30 and texture_percent > 35:
        return "hybrid", (
            f"背景纹理复杂（边缘密度 {edge_density:.1f}%），建议先用 ROI/纹理特征限定区域，"
            "传统阈值不足时再引入 AI 节点"
        )
    if contrast < 35:
        return "traditional", (
            f"当前对比度过低（动态范围 {contrast:.0f}），优先改善照明与曝光；"
            "在成像未改善前切换深度学习不会提升稳定性"
        )
    return "traditional", "目标与背景存在可分的灰度/纹理差异，传统视觉方案更快更可解释"


def build(intent: Intent, diagnosis: dict | None) -> Plan:
    route, route_reason = choose_route(intent, diagnosis)
    template_id = _TEMPLATE_BY_TASK.get(intent.task_type, "surface_defect")
    if route == "hybrid" and intent.task_type in {"defect_detection", "anomaly_detection"}:
        template_id = "anomaly"
    graph = templates.build_graph(template_id)

    metrics = (diagnosis or {}).get("metrics", {})
    findings = {f["key"] for f in (diagnosis or {}).get("findings", [])}
    steps = _tune(graph, intent, metrics, findings)

    summary = _summary(intent, template_id, route)
    plan = Plan(
        graph=graph,
        task_type=intent.task_type,
        route=route,
        route_reason=route_reason,
        summary=summary,
        steps=steps,
        source="rules",
    )
    plan.graph, plan.warnings = sanitize(graph)
    return plan


def _set(graph: dict, node_id: str, **params: Any) -> bool:
    for node in graph["nodes"]:
        if node["id"] == node_id:
            node["params"] = {**(node.get("params") or {}), **params}
            return True
    return False


def _has(graph: dict, node_id: str) -> bool:
    return any(node["id"] == node_id for node in graph["nodes"])


def _tune(graph: dict, intent: Intent, metrics: dict, findings: set[str]) -> list[dict]:
    """Turn diagnosis numbers into concrete parameter choices, with reasons."""
    steps: list[dict] = []

    def explain(node_id: str, reason: str) -> None:
        if _has(graph, node_id):
            steps.append({"nodeId": node_id, "reason": reason})

    is_color = bool(metrics.get("isColor"))
    if is_color and intent.color_relevant:
        _set(graph, "input", color_mode="color")
        explain("input", "任务涉及颜色，保留彩色输入以便后续做颜色分割")
    else:
        _set(graph, "input", color_mode="gray")
        explain("input", "任务与颜色无关，转灰度可减少计算量并简化阈值")

    dark_target = intent.target_polarity == "dark"
    if _has(graph, "roi_and"):
        explain("roi_and", "ROI 作用在二值结果上（而不是先遮挡灰度图），避免 ROI 边界被误判为缺陷")
    if _has(graph, "thresh"):
        uneven = "uneven_illumination" in findings or float(metrics.get("illuminationCv", 0)) > 12
        block = 51
        height = float(metrics.get("height", 1024))
        block = max(15, int(height * 0.03) | 1)
        _set(graph, "thresh", method="gaussian", block_size=block,
             c=8.0 if uneven else 5.0, invert=dark_target)
        explain(
            "thresh",
            f"背景亮度变异 {metrics.get('illuminationCv', 0):.1f}%，"
            f"使用局部自适应阈值（blockSize={block}，约图像高度 3%，大于典型缺陷尺寸）；"
            + ("目标偏暗故反向取阈值" if dark_target else "目标偏亮，正向取阈值"),
        )
    if _has(graph, "otsu"):
        _set(graph, "otsu", invert=dark_target)
        explain("otsu", "灰度分布双峰，Otsu 自动阈值即可；"
                        + ("目标偏暗故反向" if dark_target else "目标偏亮"))

    if _has(graph, "clahe"):
        if "low_contrast" in findings or float(metrics.get("dynamicRange", 255)) < 90:
            _set(graph, "clahe", clip_limit=3.0, tile_grid=8)
            explain("clahe", "动态范围偏窄，用 CLAHE 做局部对比增强（同时限制放大噪声）")
        else:
            _set(graph, "clahe", clip_limit=1.5, tile_grid=8)
            explain("clahe", "对比度尚可，CLAHE 仅做轻度增强，避免放大噪声")

    noise = float(metrics.get("noiseSigma", 0.0))
    if _has(graph, "blur"):
        kernel = 7 if noise > 6 else 5 if noise > 3 else 3
        _set(graph, "blur", kernel=kernel)
        explain("blur", f"估计噪声 σ≈{noise:.1f}，高斯核取 {kernel} 抑制噪声且不过度模糊小缺陷")

    min_area = 60.0
    if intent.constraints.get("minSize"):
        size = float(intent.constraints["minSize"])
        min_area = max(4.0, size * size)
    elif noise > 6:
        min_area = 120.0
    for node_id in ("blob",):
        if _has(graph, node_id):
            _set(graph, node_id, min_area=min_area)
            explain(node_id, f"最小缺陷面积设为 {min_area:.0f} px²，小于该面积的响应视为噪声")

    if _has(graph, "judge"):
        if intent.task_type == "counting" and intent.constraints.get("expectedCount"):
            expected = int(intent.constraints["expectedCount"])
            _set(graph, "judge", operator="between", limit=float(expected), upper=float(expected))
            explain("judge", f"期望数量 {expected}，判定条件设为等于该数量")
        elif intent.task_type == "measurement" and intent.constraints.get("nominal"):
            nominal = float(intent.constraints["nominal"])
            tolerance = float(intent.constraints.get("tolerance", nominal * 0.05))
            _set(graph, "judge", operator="between", limit=nominal - tolerance,
                 upper=nominal + tolerance)
            explain("judge", f"按公差 {nominal}±{tolerance} 设置判定区间")
        elif intent.constraints.get("zeroTolerance"):
            _set(graph, "judge", operator="<=", limit=0.0)
            explain("judge", "需求为零容忍，检出任何目标即判 NG")
        else:
            explain("judge", "判定阈值先给保守默认值，建议用批量测试的 FP/FN 结果继续收敛")

    if _has(graph, "anomaly"):
        sensitivity = 3.0 if noise < 4 else 4.0
        _set(graph, "anomaly", sensitivity=sensitivity,
             window=max(15, int(float(metrics.get("height", 1024)) * 0.03) | 1))
        explain("anomaly", f"异常灵敏度取 {sensitivity}σ（噪声越大阈值越高，抑制误报）")

    if _has(graph, "colony"):
        _set(graph, "colony", min_area_frac=0.01, keep_largest=True)
        explain("colony", "局部标准差纹理 + Otsu 提取高纹理克隆区域，仅保留最大连通域作为主克隆")
    if _has(graph, "metrics"):
        explain("metrics", "输出克隆中心、面积占比、等效直径与实心度，供判定与数据统计使用")
    if _has(graph, "display"):
        explain("display", "叠加轮廓与 OK/NG，供 Viewer 与 Runtime 显示")
    return steps


def _summary(intent: Intent, template_id: str, route: str) -> str:
    template = next((t for t in templates.TEMPLATES if t["id"] == template_id), None)
    name = template["name"] if template else template_id
    route_text = {"traditional": "传统视觉", "ai": "AI 模型", "hybrid": "传统 + AI 混合"}[route]
    target = intent.target_hint or "目标"
    return f"按“{name}”方案生成流程（{route_text}），检测对象：{target}。"


# -- validation ----------------------------------------------------------
def sanitize(graph_data: dict) -> tuple[dict, list[str]]:
    """Drop anything not in the registry and coerce all parameters."""
    warnings: list[str] = []
    nodes: list[dict] = []
    kept: set[str] = set()

    for index, raw in enumerate(graph_data.get("nodes") or []):
        node_id = str(raw.get("id") or f"n{index}")
        node_type = str(raw.get("type") or "")
        if not has_node(node_type):
            warnings.append(f"已移除未注册的节点 {node_id} ({node_type or '空类型'})")
            continue
        node_cls = get_node_class(node_type)
        try:
            params = node_cls.coerce_params(raw.get("params"))
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"节点 {node_id} 参数非法，已回退默认值: {exc}")
            params = node_cls.default_params()
        position = raw.get("position") or {"x": 40 + index * 260, "y": 200}
        nodes.append(
            {
                "id": node_id,
                "type": node_type,
                "label": raw.get("label") or "",
                "params": params,
                "position": position,
                "enabled": bool(raw.get("enabled", True)),
            }
        )
        kept.add(node_id)

    edges: list[dict] = []
    seen_targets: set[tuple[str, str]] = set()
    for index, raw in enumerate(graph_data.get("edges") or []):
        source = str(raw.get("source") or "")
        target = str(raw.get("target") or "")
        source_handle = str(raw.get("sourceHandle") or raw.get("source_handle") or "")
        target_handle = str(raw.get("targetHandle") or raw.get("target_handle") or "")
        if source not in kept or target not in kept:
            warnings.append(f"已移除无效连线 {source}->{target}")
            continue
        source_cls = get_node_class(next(n["type"] for n in nodes if n["id"] == source))
        target_cls = get_node_class(next(n["type"] for n in nodes if n["id"] == target))
        if source_cls.output_type(source_handle) is None:
            source_handle = source_cls.outputs[0].name if source_cls.outputs else ""
            warnings.append(f"连线 {source}->{target} 的输出端口无效，已修正为 {source_handle}")
        if target_cls.input_spec(target_handle) is None:
            target_handle = target_cls.inputs[0].name if target_cls.inputs else ""
            warnings.append(f"连线 {source}->{target} 的输入端口无效，已修正为 {target_handle}")
        if not source_handle or not target_handle:
            warnings.append(f"已移除无法修正的连线 {source}->{target}")
            continue
        if (target, target_handle) in seen_targets:
            warnings.append(f"输入端口 {target}.{target_handle} 重复连接，已忽略后者")
            continue
        seen_targets.add((target, target_handle))
        edges.append(
            {
                "id": raw.get("id") or f"{source}:{source_handle}->{target}:{target_handle}",
                "source": source,
                "sourceHandle": source_handle,
                "target": target,
                "targetHandle": target_handle,
            }
        )

    graph = Graph.from_dict({"nodes": nodes, "edges": edges})
    for issue in graph.validate(strict=False):
        if issue["level"] == "error":
            warnings.append(issue["message"])
    return graph.to_dict(), warnings


def validate_llm_plan(payload: dict, intent: Intent, diagnosis: dict | None) -> Plan | None:
    """Accept an LLM plan only if it survives sanitising and has a judge node."""
    graph_data = payload.get("graph")
    if not isinstance(graph_data, dict) or not graph_data.get("nodes"):
        return None
    graph, warnings = sanitize(graph_data)
    node_types = {node["type"] for node in graph["nodes"]}
    if "image_input" not in node_types:
        return None
    if not {"ok_ng", "threshold_judge", "count_judge"} & node_types:
        warnings.append("生成的流程缺少判定节点，已改用规则模板")
        return None
    task_type = payload.get("taskType") or intent.task_type
    return Plan(
        graph=graph,
        task_type=task_type,
        route=payload.get("route") or "traditional",
        route_reason=payload.get("routeReason") or "",
        summary=payload.get("summary") or "",
        steps=[
            s for s in (payload.get("steps") or [])
            if isinstance(s, dict) and s.get("nodeId")
        ],
        warnings=warnings,
        source="llm",
    )
