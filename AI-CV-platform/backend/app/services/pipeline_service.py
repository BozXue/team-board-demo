"""Pipeline execution entry points used by the API.

Debug runs keep a per-(project, image) result cache alive between requests, so
dragging a parameter slider only re-executes the affected node and everything
downstream of it.
"""

from __future__ import annotations

import threading
from collections import OrderedDict
from typing import Any

from sqlalchemy.orm import Session

from app.core.errors import ValidationError
from app.engine.executor import ArtifactWriter, ExecutionResult, PipelineExecutor, ResultCache
from app.engine.graph import Graph
from app.models import ImageAsset
from app.services import dataset_service, project_service, storage

_CACHES: OrderedDict[tuple[str, str], ResultCache] = OrderedDict()
_CACHE_LOCK = threading.Lock()
_MAX_SESSIONS = 12


def _session_cache(project_id: str, image_id: str) -> ResultCache:
    key = (project_id, image_id or "none")
    with _CACHE_LOCK:
        cache = _CACHES.get(key)
        if cache is None:
            cache = ResultCache(max_items=192)
            _CACHES[key] = cache
        _CACHES.move_to_end(key)
        while len(_CACHES) > _MAX_SESSIONS:
            _CACHES.popitem(last=False)
        return cache


def clear_cache(project_id: str | None = None) -> int:
    with _CACHE_LOCK:
        keys = [k for k in _CACHES if project_id is None or k[0] == project_id]
        for key in keys:
            _CACHES.pop(key, None)
        return len(keys)


def build_context(db: Session, project_id: str, image_id: str | None, full_resolution: bool = False) -> dict:
    context: dict[str, Any] = {"project_id": project_id, "image_id": image_id}
    if image_id:
        asset = dataset_service.get_image(db, image_id)
        if asset.project_id != project_id:
            raise ValidationError("图像不属于当前项目")
        context["image_path"] = str(
            dataset_service.image_source_path(asset, prefer_preview=not full_resolution)
        )
        context["image_name"] = asset.filename
    return context


def run_debug(
    db: Session,
    project_id: str,
    graph_data: dict | None,
    image_id: str | None = None,
    target_node: str | None = None,
    preview_nodes: list[str] | None = None,
    save_graph: bool = True,
) -> dict:
    """Execute a graph for one image and return per-node debug information."""
    project = project_service.get_project(db, project_id)
    if graph_data is None:
        graph_data = project.graph
    graph = Graph.from_dict(graph_data)
    issues = graph.validate(strict=False)
    if any(issue["level"] == "error" for issue in issues):
        return {
            "order": [],
            "totalMs": 0.0,
            "verdict": "ERROR",
            "reason": "Pipeline 校验未通过",
            "measurements": {},
            "artifacts": {},
            "errors": [
                {"nodeId": issue.get("nodeId"), "message": issue["message"]}
                for issue in issues if issue["level"] == "error"
            ],
            "cache": {"hits": 0, "misses": 0},
            "nodes": {},
            "issues": issues,
        }

    if save_graph:
        project.graph = graph.to_dict()
        project_service.sync_files(project)

    context = build_context(db, project_id, image_id)
    artifacts = ArtifactWriter(
        storage.debug_cache_dir(project_id, image_id or "none"),
        storage.debug_cache_url(project_id, image_id or "none"),
    )
    executor = PipelineExecutor(
        graph,
        artifacts=artifacts,
        cache=_session_cache(project_id, image_id or "none"),
        context=context,
    )
    result = executor.run(
        target=target_node,
        preview=True,
        preview_nodes=set(preview_nodes) if preview_nodes else None,
    )
    payload = result.to_dict()
    payload["issues"] = issues
    payload["imageId"] = image_id
    payload["targetNode"] = target_node
    return payload


def run_single_image(
    graph_data: dict,
    context: dict,
    artifacts: ArtifactWriter | None = None,
    cache: ResultCache | None = None,
    preview_nodes: set[str] | None = None,
) -> ExecutionResult:
    """Stateless execution used by batch test and Runtime workers."""
    graph = Graph.from_dict(graph_data)
    executor = PipelineExecutor(graph, artifacts=artifacts, cache=cache, context=context)
    return executor.run(preview=artifacts is not None, preview_nodes=preview_nodes)


def primary_display_nodes(graph_data: dict) -> set[str]:
    """Display nodes flagged as primary (used for result thumbnails)."""
    graph = Graph.from_dict(graph_data)
    primary = {
        node.id for node in graph.nodes
        if node.type == "display" and node.params.get("primary", True)
    }
    if primary:
        return primary
    displays = {node.id for node in graph.nodes if node.type == "display"}
    if displays:
        return displays
    return set(graph.terminal_nodes())


def image_for_asset(asset: ImageAsset, full_resolution: bool = False) -> dict:
    return {
        "project_id": asset.project_id,
        "image_id": asset.id,
        "image_name": asset.filename,
        "image_path": str(dataset_service.image_source_path(asset, prefer_preview=not full_resolution)),
    }
