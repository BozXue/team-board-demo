"""Optional LLM backend (OpenAI-compatible chat completions).

The Copilot must degrade gracefully: without ``AICV_LLM_API_KEY`` every feature
still works through the rule-based planner, and any LLM output is treated as an
untrusted suggestion that must pass schema + whitelist validation.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)


def enabled() -> bool:
    return settings.llm_enabled


def info() -> dict:
    return {
        "enabled": enabled(),
        "model": settings.llm_model if enabled() else None,
        "baseUrl": settings.llm_base_url if enabled() else None,
        "fallback": "rule-based planner",
    }


def chat(messages: list[dict], temperature: float = 0.2, max_tokens: int = 1600) -> str | None:
    if not enabled():
        return None
    payload = {
        "model": settings.llm_model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    try:
        response = httpx.post(
            f"{settings.llm_base_url.rstrip('/')}/chat/completions",
            headers={
                "Authorization": f"Bearer {settings.llm_api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=settings.llm_timeout,
        )
        response.raise_for_status()
        data = response.json()
        return data["choices"][0]["message"]["content"]
    except Exception as exc:  # noqa: BLE001 - LLM is best-effort
        logger.warning("LLM 调用失败，回退到规则引擎: %s", exc)
        return None


def chat_json(messages: list[dict], temperature: float = 0.2) -> dict | None:
    """Chat completion parsed as JSON (tolerating ```json fences)."""
    content = chat(messages, temperature=temperature)
    if not content:
        return None
    return parse_json(content)


def parse_json(content: str) -> dict | None:
    text = content.strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fenced:
        text = fenced.group(1)
    else:
        start, end = text.find("{"), text.rfind("}")
        if start >= 0 and end > start:
            text = text[start:end + 1]
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError as exc:
        logger.warning("LLM 输出不是合法 JSON: %s", exc)
        return None


def system_prompt(node_catalog: list[dict], task_types: list[str]) -> str:
    """Constrain generation to the registered node whitelist."""
    lines = [
        "你是工业视觉平台的 AI Copilot。你只能使用平台已注册的节点，且只能输出 JSON。",
        "禁止发明节点类型、端口名或参数名。优先使用传统视觉方案；只有在传统方法明显不可行时才推荐深度学习。",
        "",
        f"可选任务类型: {', '.join(task_types)}",
        "",
        "可用节点（type | 输入端口 | 输出端口 | 参数）：",
    ]
    for group in node_catalog:
        for node in group["nodes"]:
            inputs = ",".join(p["name"] for p in node["inputs"]) or "-"
            outputs = ",".join(p["name"] for p in node["outputs"]) or "-"
            params = ",".join(p["name"] for p in node["params"]) or "-"
            lines.append(f"- {node['type']} | in:{inputs} | out:{outputs} | params:{params}")
    lines += [
        "",
        "输出 JSON 结构：",
        json.dumps(
            {
                "taskType": "defect_detection",
                "route": "traditional",
                "routeReason": "为什么走传统视觉或 AI",
                "summary": "一句话方案说明",
                "graph": {
                    "nodes": [
                        {"id": "input", "type": "image_input", "params": {}},
                        {"id": "verdict", "type": "ok_ng", "params": {}},
                    ],
                    "edges": [
                        {"source": "input", "sourceHandle": "image",
                         "target": "verdict", "targetHandle": "result"}
                    ],
                },
                "steps": [{"nodeId": "input", "reason": "读取图像"}],
                "questions": ["需要澄清的问题（可为空）"],
            },
            ensure_ascii=False,
        ),
        "",
        "流程必须以 image_input 开始，包含 ok_ng 判定，并接一个 display 节点用于结果显示。",
    ]
    return "\n".join(lines)


def summarize_context(project: dict, diagnosis: dict | None) -> str:
    parts = [f"项目: {project.get('name')}", f"需求描述: {project.get('requirement') or '（无）'}"]
    if diagnosis:
        metrics = diagnosis.get("metrics", {})
        parts.append(
            "图像诊断: "
            + json.dumps(
                {
                    k: metrics.get(k)
                    for k in ("mean", "dynamicRange", "sharpness", "noiseSigma",
                              "illuminationCv", "texturePercent", "edgeDensity", "isColor")
                },
                ensure_ascii=False,
            )
        )
        findings = "; ".join(f"{f['title']}({f['level']})" for f in diagnosis.get("findings", []))
        parts.append(f"诊断结论: {findings or '无明显问题'}")
    return "\n".join(parts)


def any_to_text(value: Any) -> str:
    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
