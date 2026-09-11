"""Parameter explanation and debug advice."""

from __future__ import annotations

from typing import Any

from app.engine.registry import get_node_class, has_node
from app.services.copilot import llm

# Business-language explanations for the parameters operators actually see.
_PARAM_NOTES: dict[tuple[str, str], str] = {
    ("adaptive_threshold", "block_size"): "邻域越大越能容忍背景渐变，但必须明显大于缺陷本身，否则缺陷会被当成背景。",
    ("adaptive_threshold", "c"): "相当于“灵敏度”：调大更保守（漏检增加），调小更敏感（误检增加）。",
    ("threshold", "threshold"): "固定阈值对光照变化敏感；若现场光照会变，改用 Adaptive 或 Otsu。",
    ("otsu_threshold", "bias"): "在自动阈值上加偏置，用于在不改流程的情况下微调灵敏度。",
    ("gaussian_blur", "kernel"): "核越大噪声越少，但小缺陷也会被抹掉；一般取小于缺陷尺寸的一半。",
    ("blob_analysis", "min_area"): "最小缺陷面积，直接对应用户侧的“最小可接受缺陷尺寸”。",
    ("clahe", "clip_limit"): "限制对比度放大倍数，过大会把噪声也放大。",
    ("morph_open", "kernel"): "开运算尺寸越大去噪越强，同时会削掉细长缺陷。",
    ("threshold_judge", "limit"): "判定阈值：建议用批量测试中 OK/NG 样本的测量值分布来确定。",
    ("count_judge", "limit"): "允许的缺陷数量，零容忍场景填 0。",
    ("ipsc_colony_segment", "min_area_frac"): "小于该图像面积比例的纹理块视为碎片/杂质而非克隆。",
    ("ipsc_colony_segment", "window"): "纹理窗口应接近细胞团的纹理尺度，默认取图像高度的 1.5%。",
    ("ai_anomaly_detect", "sensitivity"): "以 σ 为单位的异常门限，噪声大的产线应适当调高以抑制误报。",
}


def explain_node(node_type: str, params: dict | None = None) -> dict:
    """Node + parameter explanation used by the properties panel “解释”按钮。"""
    if not has_node(node_type):
        return {"nodeType": node_type, "found": False, "message": f"未注册的节点类型: {node_type}"}
    node_cls = get_node_class(node_type)
    params = params or {}
    items = []
    for spec in node_cls.params:
        note = _PARAM_NOTES.get((node_type, spec.name), "")
        items.append(
            {
                "name": spec.name,
                "label": spec.label or spec.name,
                "level": spec.level,
                "current": params.get(spec.name, spec.default),
                "default": spec.default,
                "range": {"min": spec.min, "max": spec.max, "options": spec.options},
                "description": spec.description,
                "advice": note,
            }
        )
    return {
        "nodeType": node_type,
        "found": True,
        "label": node_cls.label,
        "category": node_cls.category,
        "description": node_cls.description,
        "inputs": [p.to_dict() for p in node_cls.inputs],
        "outputs": [p.to_dict() for p in node_cls.outputs],
        "params": items,
    }


def suggest_from_batch(run: dict, results: list[dict], diagnosis: dict | None = None) -> dict:
    """Debug advice from a batch run: separate over-detection from under-detection."""
    metrics = run.get("metrics") or {}
    counts = metrics.get("counts") or {}
    fp, fn = int(counts.get("FP", 0)), int(counts.get("FN", 0))
    errors = [r for r in results if r.get("verdict") == "ERROR"]
    suggestions: list[dict] = []

    if errors:
        messages: dict[str, int] = {}
        for result in errors:
            key = (result.get("error") or "未知错误").split(";")[0][:120]
            messages[key] = messages.get(key, 0) + 1
        top = sorted(messages.items(), key=lambda kv: -kv[1])[0]
        suggestions.append(
            {
                "level": "critical",
                "title": f"{len(errors)} 张图执行失败",
                "detail": f"最常见错误：{top[0]}（{top[1]} 次）",
                "action": "先修复报错节点：单节点调试该样本，检查输入类型与参数范围",
            }
        )

    if fn:
        suggestions.append(
            {
                "level": "warning",
                "title": f"漏检 {fn} 例（FN）",
                "detail": "标注为 NG 但流程判 OK，说明缺陷响应不足或被过滤掉了",
                "action": "调小判定阈值 / 调小 Blob 最小面积 / 减弱形态学开运算；"
                          "若缺陷本身对比度极低，优先改善照明",
            }
        )
    if fp:
        suggestions.append(
            {
                "level": "warning",
                "title": f"误检 {fp} 例（FP）",
                "detail": "标注为 OK 但流程判 NG，通常是背景纹理或噪声被当成缺陷",
                "action": "调大 Blob 最小面积 / 提高圆度或长宽比约束 / 增大 Adaptive Threshold 的 C；"
                          "必要时加 ROI 排除边缘区域",
            }
        )

    findings = {f["key"] for f in (diagnosis or {}).get("findings", [])}
    if "uneven_illumination" in findings and (fp or fn):
        suggestions.append(
            {
                "level": "info",
                "title": "环境光不均匀是主要不稳定来源",
                "detail": "批量样本的背景亮度差异较大，固定阈值会随光照漂移",
                "action": "把 Threshold 换成 Adaptive Threshold（或加 CLAHE），"
                          "同时建议现场增加漫射照明、固定曝光",
            }
        )
    if "blur" in findings:
        suggestions.append(
            {
                "level": "info",
                "title": "部分样本偏模糊",
                "detail": "清晰度不足会同时抬高漏检与误检",
                "action": "检查对焦与景深；不建议靠算法补偿",
            }
        )

    variance = _threshold_hint(results)
    if variance:
        suggestions.append(variance)

    if not suggestions:
        suggestions.append(
            {
                "level": "ok",
                "title": "本轮没有发现明显问题",
                "detail": f"良率 {run.get('yieldPercent', 0)}%，"
                          f"平均耗时 {metrics.get('avgDurationMs', 0)} ms",
                "action": "可以扩大样本量继续验证，或发布为 Runtime 项目",
            }
        )
    return {"suggestions": suggestions, "counts": counts}


def _threshold_hint(results: list[dict]) -> dict | None:
    """If OK/NG measurement ranges overlap, propose a data-driven threshold."""
    ok_values: dict[str, list[float]] = {}
    ng_values: dict[str, list[float]] = {}
    for result in results:
        target = ok_values if result.get("gtLabel") not in {"NG", "ng"} else ng_values
        for key, value in (result.get("measurements") or {}).items():
            if isinstance(value, (int, float)):
                target.setdefault(key, []).append(float(value))
    for key in set(ok_values) & set(ng_values):
        ok_list, ng_list = ok_values[key], ng_values[key]
        if len(ok_list) < 2 or len(ng_list) < 2:
            continue
        ok_max, ng_min = max(ok_list), min(ng_list)
        if ok_max < ng_min:
            proposed = round((ok_max + ng_min) / 2.0, 3)
            return {
                "level": "info",
                "title": f"测量值 {key} 可完全区分 OK/NG",
                "detail": f"OK 最大 {round(ok_max, 3)}，NG 最小 {round(ng_min, 3)}",
                "action": f"把判定阈值设为 {proposed} 可在当前样本上做到零漏检零误检",
            }
    return None


def explain_with_llm(node_type: str, params: dict | None, question: str) -> str | None:
    """Optional natural-language answer layered on top of the static explanation."""
    if not llm.enabled():
        return None
    base = explain_node(node_type, params)
    messages = [
        {
            "role": "system",
            "content": "你是工业视觉平台的参数顾问。用中文、面向工程师简洁回答，"
                       "解释参数作用与调参方向，不要编造平台不存在的功能。",
        },
        {
            "role": "user",
            "content": f"节点信息：{llm.any_to_text(base)}\n\n问题：{question}",
        },
    ]
    return llm.chat(messages, temperature=0.3, max_tokens=600)


def autotune_space(node_type: str, params: dict | None = None) -> list[dict[str, Any]]:
    """Searchable numeric parameters for the (P1) auto-tuning feature."""
    if not has_node(node_type):
        return []
    node_cls = get_node_class(node_type)
    space: list[dict[str, Any]] = []
    for spec in node_cls.params:
        if spec.type not in {"int", "float"} or spec.min is None or spec.max is None:
            continue
        current = (params or {}).get(spec.name, spec.default) or 0
        low = max(spec.min, float(current) * 0.5)
        high = min(spec.max, max(float(current) * 1.5, low + (spec.step or 1)))
        space.append({"param": spec.name, "min": low, "max": high, "step": spec.step or 1})
    return space
