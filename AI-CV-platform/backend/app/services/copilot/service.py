"""Copilot orchestration: understand → diagnose → recommend → generate."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.engine.registry import catalog
from app.models import CopilotMessage, ImageAsset
from app.services import dataset_service, diagnostics, project_service
from app.services.copilot import advisor, intent as intent_module, llm, planner

SAMPLE_LIMIT = 4


def diagnose_project(db: Session, project_id: str, image_id: str | None = None,
                     sample: int = SAMPLE_LIMIT) -> dict:
    """Diagnose one image, or a sample of the dataset when none is selected."""
    if image_id:
        asset = dataset_service.get_image(db, image_id)
        result = diagnostics.analyze_path(dataset_service.image_source_path(asset)).to_dict()
        result["sampleCount"] = 1
        result["images"] = [asset.filename]
        return result

    assets = db.execute(
        select(ImageAsset)
        .where(ImageAsset.project_id == project_id)
        .order_by(ImageAsset.created_at)
        .limit(max(1, sample))
    ).scalars().all()
    if not assets:
        return {"level": "info", "metrics": {}, "findings": [
            {
                "key": "no_data", "level": "info", "title": "尚未导入图像",
                "detail": "AI 诊断需要至少一张图像", "advice": "请先在数据页导入图像",
                "value": None,
            }
        ], "sampleCount": 0, "images": []}

    diagnoses = []
    for asset in assets:
        try:
            diagnoses.append(diagnostics.analyze_path(dataset_service.image_source_path(asset)))
        except Exception:  # noqa: BLE001 - a broken file must not break diagnosis
            continue
    result = diagnostics.aggregate(diagnoses)
    result["images"] = [asset.filename for asset in assets]
    return result


def plan_pipeline(
    db: Session,
    project_id: str,
    text: str,
    image_id: str | None = None,
    use_llm: bool = True,
) -> dict:
    """The full guided chain, returning a ready-to-apply Pipeline."""
    project = project_service.get_project(db, project_id)
    parsed = intent_module.parse(text or project.requirement)
    diagnosis = diagnose_project(db, project_id, image_id)

    llm_payload = None
    if use_llm and llm.enabled():
        llm_payload = llm.chat_json(
            [
                {"role": "system", "content": llm.system_prompt(catalog(), intent_module.TASK_TYPES)},
                {
                    "role": "user",
                    "content": (
                        f"{llm.summarize_context({'name': project.name, 'requirement': text or project.requirement}, diagnosis)}\n\n"
                        f"规则引擎初判任务类型: {parsed.task_type}\n"
                        "请给出可执行的 Pipeline JSON。"
                    ),
                },
            ]
        )
        parsed = intent_module.merge_llm(parsed, llm_payload)

    plan = None
    if llm_payload:
        plan = planner.validate_llm_plan(llm_payload, parsed, diagnosis)
    if plan is None:
        plan = planner.build(parsed, diagnosis)
    elif not plan.steps:
        plan.steps = planner.build(parsed, diagnosis).steps

    payload = {
        "intent": parsed.to_dict(),
        "diagnosis": diagnosis,
        "plan": plan.to_dict(),
        "llm": llm.info(),
    }
    _log(db, project_id, "user", text, {"imageId": image_id})
    _log(db, project_id, "assistant", plan.summary or "已生成流程", payload)
    return payload


def apply_plan(db: Session, project_id: str, graph: dict, task_type: str | None = None) -> dict:
    """Persist a generated pipeline after re-validating it."""
    sanitized, warnings = planner.sanitize(graph)
    project_service.save_graph(db, project_id, sanitized)
    if task_type:
        project = project_service.get_project(db, project_id)
        project.task_type = task_type
    return {"graph": sanitized, "warnings": warnings}


def debug_advice(db: Session, project_id: str, run_summary: dict, results: list[dict]) -> dict:
    diagnosis = diagnose_project(db, project_id)
    advice = advisor.suggest_from_batch(run_summary, results, diagnosis)
    _log(db, project_id, "assistant", "批量测试调试建议", advice)
    return advice


def answer(db: Session, project_id: str, question: str, node_type: str | None = None,
           params: dict | None = None) -> dict:
    """Free-form Q&A: LLM when configured, otherwise the static knowledge base."""
    project = project_service.get_project(db, project_id)
    static = advisor.explain_node(node_type, params) if node_type else None
    text = None
    if node_type:
        text = advisor.explain_with_llm(node_type, params, question)
    elif llm.enabled():
        text = llm.chat(
            [
                {
                    "role": "system",
                    "content": "你是工业视觉平台的 AI Copilot，用中文简洁回答。"
                               "只描述平台已有能力（节点库、标注、批量测试、Runtime），不要编造功能。",
                },
                {
                    "role": "user",
                    "content": f"项目: {project.name}\n需求: {project.requirement}\n问题: {question}",
                },
            ],
            temperature=0.3,
        )
    if not text:
        text = _offline_answer(question, static)
    _log(db, project_id, "user", question, {"nodeType": node_type})
    _log(db, project_id, "assistant", text, {"nodeType": node_type})
    return {"answer": text, "nodeExplanation": static, "llm": llm.info()}


def _offline_answer(question: str, static: dict | None) -> str:
    if static and static.get("found"):
        lines = [f"【{static['label']}】{static['description']}"]
        for item in static["params"]:
            advice = item["advice"] or item["description"] or ""
            if advice:
                lines.append(f"- {item['label']}（当前 {item['current']}）：{advice}")
        return "\n".join(lines)
    return (
        "未配置 LLM，当前使用内置规则引擎。你可以：\n"
        "1) 在“任务描述”里写清检测对象与判定标准，点击“生成流程”自动搭建 Pipeline；\n"
        "2) 在节点属性面板点击“解释”查看参数含义与调参方向；\n"
        "3) 跑一次批量测试，Copilot 会根据漏检/误检样本给出具体的参数调整建议。\n"
        f"（配置 AICV_LLM_API_KEY 后可获得自然语言问答；你的问题：{question}）"
    )


def history(db: Session, project_id: str, limit: int = 40) -> list[dict]:
    rows = db.execute(
        select(CopilotMessage)
        .where(CopilotMessage.project_id == project_id)
        .order_by(CopilotMessage.created_at.desc())
        .limit(limit)
    ).scalars().all()
    return [
        {
            "id": row.id,
            "role": row.role,
            "content": row.content,
            "payload": row.payload or {},
            "createdAt": row.created_at,
        }
        for row in reversed(rows)
    ]


def clear_history(db: Session, project_id: str) -> int:
    rows = db.execute(
        select(CopilotMessage).where(CopilotMessage.project_id == project_id)
    ).scalars().all()
    for row in rows:
        db.delete(row)
    return len(rows)


def _log(db: Session, project_id: str, role: str, content: str, payload: dict | None = None) -> None:
    db.add(
        CopilotMessage(
            project_id=project_id, role=role, content=content or "",
            payload=_jsonable(payload or {}),
        )
    )


def _jsonable(payload: dict) -> dict:
    import json

    try:
        json.dumps(payload, default=str)
        return payload
    except TypeError:
        return {"repr": str(payload)[:2000]}
