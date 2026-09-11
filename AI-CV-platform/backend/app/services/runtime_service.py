"""Runtime: run a published project in User Mode.

Acquisition is pluggable: ``dataset`` replays the project's images (the default,
so Runtime works today) and ``camera`` goes through the Device Adapter layer,
which currently offers the folder simulator plus reserved hardware adapters.
"""

from __future__ import annotations

import threading
import time
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.db import session_scope
from app.core.errors import NotFoundError, ValidationError
from app.engine.executor import ArtifactWriter, ResultCache
from app.models import ImageAsset, PipelineVersion, Project, RuntimeRecord, RuntimeSession
from app.services import pipeline_service, project_service, storage

_LOOPS: dict[str, threading.Event] = {}
MAX_RECORDS = 200


def _session_sort_key(session: RuntimeSession) -> tuple:
    stamp = session.updated_at or session.created_at
    return (session.status == "running", session.total or 0, stamp)


def _pick_session(rows: list[RuntimeSession]) -> RuntimeSession | None:
    if not rows:
        return None
    return max(rows, key=_session_sort_key)


def collapse_duplicate_sessions(db: Session, project_id: str | None = None) -> int:
    """Keep one runtime session per project; move records off the extras.

    Concurrent GET /runtime used to insert a new row whenever none was visible
    yet, and ``scalar_one_or_none()`` then 500'd the status endpoint.
    """
    query = select(RuntimeSession)
    if project_id:
        query = query.where(RuntimeSession.project_id == project_id)
    grouped: dict[str, list[RuntimeSession]] = {}
    for row in db.execute(query).scalars().all():
        grouped.setdefault(row.project_id, []).append(row)

    removed = 0
    for _pid, rows in grouped.items():
        if len(rows) < 2:
            continue
        keeper = _pick_session(rows)
        if keeper is None:
            continue
        extra_ids = [row.id for row in rows if row.id != keeper.id]
        db.execute(
            update(RuntimeRecord)
            .where(RuntimeRecord.session_id.in_(extra_ids))
            .values(session_id=keeper.id)
        )
        for row in rows:
            if row.id == keeper.id:
                continue
            db.delete(row)
            removed += 1
    if removed:
        db.flush()
    return removed


def get_session(db: Session, project_id: str, create: bool = True) -> RuntimeSession:
    collapse_duplicate_sessions(db, project_id)
    session = _pick_session(
        db.execute(select(RuntimeSession).where(RuntimeSession.project_id == project_id)).scalars().all()
    )
    if session is None:
        if not create:
            raise NotFoundError("该项目还没有运行会话")
        project = project_service.get_project(db, project_id)
        session = RuntimeSession(
            project_id=project_id,
            version_id=project.published_version_id,
            user_params=project.user_params or {},
        )
        try:
            with db.begin_nested():
                db.add(session)
                db.flush()
        except IntegrityError:
            session = _pick_session(
                db.execute(select(RuntimeSession).where(RuntimeSession.project_id == project_id)).scalars().all()
            )
            if session is None:
                raise
    _sync_published_version(db, session)
    return session


def _sync_published_version(db: Session, session: RuntimeSession) -> None:
    """Publishing a new version replaces the exposed parameter set.

    Operator overrides only make sense for the version they were made against,
    so a fresh publish resets the session back to that version's defaults.
    """
    project = project_service.get_project(db, session.project_id)
    published = project.published_version_id
    if not published or (session.version_id == published and session.user_params):
        return
    version = db.get(PipelineVersion, published)
    if version is None:
        return
    session.version_id = published
    session.user_params = version.user_params or {}


def runtime_graph(db: Session, project_id: str) -> tuple[dict, dict]:
    """Published graph with User-Mode overrides applied."""
    project = project_service.get_project(db, project_id)
    version: PipelineVersion | None = None
    if project.published_version_id:
        version = db.get(PipelineVersion, project.published_version_id)
    if version is None:
        raise ValidationError("项目尚未发布：请在 Pipeline 页面点击“发布”后再运行")
    session = get_session(db, project_id)
    params = session.user_params or version.user_params or {}
    return project_service.apply_user_params(version.graph, params), params


def update_user_params(db: Session, project_id: str, values: dict[str, Any]) -> dict:
    """Operators may only move business parameters, within their declared range."""
    project = project_service.get_project(db, project_id)
    version = db.get(PipelineVersion, project.published_version_id) if project.published_version_id else None
    allowed = (version.user_params if version else None) or project_service.exposed_params(
        project.graph, project.user_params
    )
    session = get_session(db, project_id)
    current = dict(session.user_params or allowed)

    for key, value in values.items():
        spec = allowed.get(key)
        if spec is None:
            raise ValidationError(f"参数 {key} 不在用户可调范围内")
        if spec["type"] in {"int", "float"}:
            number = float(value)
            if spec.get("min") is not None:
                number = max(float(spec["min"]), number)
            if spec.get("max") is not None:
                number = min(float(spec["max"]), number)
            value = int(round(number)) if spec["type"] == "int" else number
        elif spec["type"] == "bool":
            value = bool(value)
        elif spec["type"] == "enum" and spec.get("options") and value not in spec["options"]:
            raise ValidationError(f"参数 {key} 取值非法")
        current[key] = {**spec, "value": value}
    session.user_params = current
    return current


def reset_user_params(db: Session, project_id: str) -> dict:
    project = project_service.get_project(db, project_id)
    version = db.get(PipelineVersion, project.published_version_id) if project.published_version_id else None
    defaults = (version.user_params if version else None) or project_service.exposed_params(project.graph, {})
    session = get_session(db, project_id)
    session.user_params = defaults
    return defaults


def _next_image(db: Session, session: RuntimeSession) -> ImageAsset | None:
    assets = db.execute(
        select(ImageAsset)
        .where(ImageAsset.project_id == session.project_id)
        .order_by(ImageAsset.created_at, ImageAsset.filename)
    ).scalars().all()
    if not assets:
        return None
    asset = assets[session.cursor % len(assets)]
    session.cursor = (session.cursor + 1) % len(assets)
    return asset


def inspect_once(db: Session, project_id: str, device_id: str | None = None) -> dict:
    """Acquire one frame, run the published pipeline, store the record."""
    graph_data, _ = runtime_graph(db, project_id)
    session = get_session(db, project_id)

    seq = session.total + 1
    context: dict[str, Any]
    device: str | None = None
    if session.source == "camera":
        device = device_id or "sim_folder"
        graph_data = _swap_input_to_camera(graph_data, device)
        context = {"project_id": project_id, "image_id": None, "image_name": "camera_frame"}
        image_id = None
        image_name = f"采集帧 #{seq}"
    else:
        asset = _next_image(db, session)
        if asset is None:
            raise ValidationError("项目没有可用图像：请先导入数据或改用相机采集")
        context = pipeline_service.image_for_asset(asset, full_resolution=False)
        image_id = asset.id
        image_name = asset.filename

    # Frames go into a ring of slots instead of one "current" folder: monitoring
    # links back to the image a past inference actually saw, and the slot is only
    # reused once its record has been trimmed away.
    slot = f"frames/{seq % MAX_RECORDS}"
    writer = ArtifactWriter(
        storage.run_cache_dir("runtime", session.id) / slot,
        f"{storage.run_cache_url('runtime', session.id)}/{slot}",
        max_side=900,
    )
    result = pipeline_service.run_single_image(
        graph_data, context, artifacts=writer, cache=ResultCache(max_items=32),
        preview_nodes=pipeline_service.primary_display_nodes(graph_data),
    )
    verdict = "ERROR" if result.errors else result.verdict
    preview = None
    for info in result.nodes.values():
        for output in info.outputs.values():
            if output.get("preview"):
                preview = output["preview"]["url"]
                break
        if preview:
            break

    session.total += 1
    if verdict == "OK":
        session.ok_count += 1
    elif verdict == "NG":
        session.ng_count += 1
    else:
        session.error_count += 1
    session.alarm = "" if verdict != "ERROR" else "；".join(e["message"] for e in result.errors)

    record = RuntimeRecord(
        session_id=session.id,
        project_id=project_id,
        seq=seq,
        image_id=image_id,
        image_name=image_name,
        verdict=verdict,
        source=session.source,
        device_id=device,
        model_id=graph_model_id(graph_data),
        confidence=_confidence_of(result.measurements),
        measurements={
            k: (v if isinstance(v, (int, float, str, bool)) or v is None else str(v))
            for k, v in result.measurements.items()
        },
        artifacts={"preview": preview} if preview else {},
        duration_ms=result.total_ms,
        error="; ".join(e["message"] for e in result.errors) or None,
    )
    db.add(record)
    db.flush()
    _trim_records(db, session.id)
    return record_to_dict(record)


def graph_model_id(graph_data: dict) -> str | None:
    """The trained model this graph runs on, if any.

    A graph may chain several AI nodes; monitoring attributes the inference to
    the first one that names a model, which is the classifier in practice.
    """
    for node in graph_data.get("nodes", []):
        if not str(node.get("type", "")).startswith("ai_"):
            continue
        model_id = (node.get("params") or {}).get("model_id")
        if model_id:
            return str(model_id)
    return None


def _confidence_of(measurements: dict[str, Any]) -> float | None:
    value = measurements.get("confidence")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return round(float(value), 4)


def _swap_input_to_camera(graph_data: dict, device_id: str) -> dict:
    """Replace dataset inputs with the camera node for live acquisition."""
    nodes = []
    for node in graph_data.get("nodes", []):
        if node.get("type") == "image_input":
            node = {
                **node,
                "type": "camera_input",
                "params": {"device_id": device_id, "trigger": "software"},
            }
        nodes.append(node)
    return {**graph_data, "nodes": nodes}


def _trim_records(db: Session, session_id: str) -> None:
    records = db.execute(
        select(RuntimeRecord)
        .where(RuntimeRecord.session_id == session_id)
        .order_by(RuntimeRecord.created_at.desc())
    ).scalars().all()
    for record in records[MAX_RECORDS:]:
        db.delete(record)


def start(
    db: Session,
    project_id: str,
    source: str = "dataset",
    interval_ms: int = 1200,
    device_id: str | None = None,
) -> dict:
    if source not in {"dataset", "camera"}:
        raise ValidationError(f"不支持的运行数据源: {source}")
    runtime_graph(db, project_id)  # validates that the project is published
    session = get_session(db, project_id)
    session.source = source
    session.status = "running"
    session.alarm = ""
    db.commit()

    stop_event = _LOOPS.get(session.id)
    if stop_event is not None:
        stop_event.set()
    stop_event = threading.Event()
    _LOOPS[session.id] = stop_event
    thread = threading.Thread(
        target=_loop,
        args=(project_id, session.id, max(200, interval_ms), device_id, stop_event),
        name=f"runtime-{session.id}",
        daemon=True,
    )
    thread.start()
    return status(db, project_id)


def stop(db: Session, project_id: str) -> dict:
    session = get_session(db, project_id)
    event = _LOOPS.pop(session.id, None)
    if event is not None:
        event.set()
    session.status = "stopped"
    return status(db, project_id)


def reset_statistics(db: Session, project_id: str) -> dict:
    session = get_session(db, project_id)
    session.total = 0
    session.ok_count = 0
    session.ng_count = 0
    session.error_count = 0
    session.cursor = 0
    session.alarm = ""
    for record in list(session.records):
        db.delete(record)
    return status(db, project_id)


def _loop(project_id: str, session_id: str, interval_ms: int, device_id: str | None,
          stop_event: threading.Event) -> None:
    while not stop_event.is_set():
        tick = time.perf_counter()
        try:
            with session_scope() as db:
                session = db.get(RuntimeSession, session_id)
                if session is None or session.status != "running":
                    return
                inspect_once(db, project_id, device_id)
        except Exception as exc:  # noqa: BLE001 - runtime must survive one bad frame
            with session_scope() as db:
                session = db.get(RuntimeSession, session_id)
                if session is not None:
                    session.alarm = f"{type(exc).__name__}: {exc}"
                    session.error_count += 1
                    session.status = "error"
            return
        elapsed = (time.perf_counter() - tick) * 1000.0
        stop_event.wait(max(0.05, (interval_ms - elapsed) / 1000.0))


def record_to_dict(record: RuntimeRecord) -> dict:
    return {
        "id": record.id,
        "seq": record.seq,
        "imageId": record.image_id,
        "imageName": record.image_name,
        "verdict": record.verdict,
        "source": record.source,
        "deviceId": record.device_id,
        "modelId": record.model_id,
        "confidence": record.confidence,
        "measurements": record.measurements or {},
        "preview": (record.artifacts or {}).get("preview"),
        "durationMs": round(record.duration_ms, 2),
        "error": record.error,
        "createdAt": record.created_at,
    }


def status(db: Session, project_id: str, history: int = 30) -> dict:
    project: Project = project_service.get_project(db, project_id)
    session = get_session(db, project_id)
    records = db.execute(
        select(RuntimeRecord)
        .where(RuntimeRecord.session_id == session.id)
        .order_by(RuntimeRecord.seq.desc())
        .limit(history)
    ).scalars().all()

    version = db.get(PipelineVersion, project.published_version_id) if project.published_version_id else None
    durations = [r.duration_ms for r in records]
    return {
        "sessionId": session.id,
        "projectId": project_id,
        "projectName": project.name,
        "status": session.status,
        "source": session.source,
        "published": version is not None,
        "version": version.version if version else None,
        "total": session.total,
        "okCount": session.ok_count,
        "ngCount": session.ng_count,
        "errorCount": session.error_count,
        "yieldPercent": round(session.ok_count / session.total * 100.0, 2) if session.total else 0.0,
        "avgDurationMs": round(sum(durations) / len(durations), 2) if durations else 0.0,
        "alarm": session.alarm,
        "userParams": session.user_params or {},
        "records": [record_to_dict(record) for record in records],
    }
