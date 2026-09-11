"""Platform metadata: version, node library, templates, Copilot status."""

from __future__ import annotations

from fastapi import APIRouter

from app.core.config import settings
from app.engine.registry import CATEGORY_ORDER, all_node_classes, catalog
from app.schemas import NodeExplainRequest
from app.services import templates
from app.services.copilot import advisor, llm
from app.services.copilot.intent import TASK_LABELS

router = APIRouter(tags=["meta"])


@router.get("/meta")
def platform_meta() -> dict:
    nodes = all_node_classes()
    return {
        "appName": settings.app_name,
        "version": settings.version,
        "nodeCount": len(nodes),
        "categories": CATEGORY_ORDER,
        "taskTypes": [{"value": key, "label": label} for key, label in TASK_LABELS.items()],
        "llm": llm.info(),
        "limits": {
            "maxPreviewSide": settings.max_preview_side,
            "thumbnailSide": settings.thumbnail_side,
        },
    }


@router.get("/nodes")
def node_catalog() -> dict:
    return {"catalog": catalog()}


@router.get("/templates")
def pipeline_templates() -> dict:
    return {"templates": templates.list_templates()}


@router.post("/nodes/explain")
def explain_node(payload: NodeExplainRequest) -> dict:
    return advisor.explain_node(payload.nodeType, payload.params)
