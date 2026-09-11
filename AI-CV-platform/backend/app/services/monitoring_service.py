"""Model Monitoring: how deployed pipelines behave in production.

Every User-Mode inference is written to ``runtime_records`` tagged with the
project, acquisition device and model it used, so monitoring is a read-only
aggregation over that table - it never re-runs a pipeline. Records are trimmed
per session (see ``runtime_service.MAX_RECORDS``), so the window is "the last N
inferences per project" rather than an unbounded archive.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ModelAsset, Project, RuntimeRecord, RuntimeSession, utcnow
from app.services.devices import device_manager

# A classifier that is this unsure is usually looking at something it was not
# trained on - worth surfacing before it starts mislabelling parts.
LOW_CONFIDENCE = 0.6
ONLINE_STATES = {"connected", "streaming"}
DATASET_SOURCE = "dataset"


def _percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round(fraction * (len(ordered) - 1))))
    return round(ordered[index], 2)


def _mean(values: list[float], digits: int = 2) -> float:
    return round(sum(values) / len(values), digits) if values else 0.0


def _counts(records: Iterable[RuntimeRecord]) -> dict[str, int]:
    tally = {"total": 0, "okCount": 0, "ngCount": 0, "errorCount": 0}
    for record in records:
        tally["total"] += 1
        if record.verdict == "OK":
            tally["okCount"] += 1
        elif record.verdict == "NG":
            tally["ngCount"] += 1
        else:
            tally["errorCount"] += 1
    return tally


def _yield_percent(tally: dict[str, int]) -> float:
    judged = tally["okCount"] + tally["ngCount"]
    return round(tally["okCount"] / judged * 100.0, 2) if judged else 0.0


def _stats(records: list[RuntimeRecord]) -> dict[str, Any]:
    durations = [r.duration_ms for r in records]
    confidences = [r.confidence for r in records if r.confidence is not None]
    tally = _counts(records)
    return {
        **tally,
        "yieldPercent": _yield_percent(tally),
        "avgDurationMs": _mean(durations),
        "p95DurationMs": _percentile(durations, 0.95),
        "maxDurationMs": round(max(durations), 2) if durations else 0.0,
        "avgConfidence": _mean(confidences, 4),
        "minConfidence": round(min(confidences), 4) if confidences else None,
        "lowConfidenceCount": sum(1 for c in confidences if c < LOW_CONFIDENCE),
        "lastAt": max((r.created_at for r in records), default=None),
    }


def _window(db: Session, hours: int) -> tuple[list[RuntimeRecord], datetime]:
    since = utcnow() - timedelta(hours=hours)
    records = db.execute(
        select(RuntimeRecord)
        .where(RuntimeRecord.created_at >= since)
        .order_by(RuntimeRecord.created_at.desc())
    ).scalars().all()
    return list(records), since


def _confidence_buckets(records: list[RuntimeRecord], bins: int = 10) -> list[int]:
    buckets = [0] * bins
    for record in records:
        if record.confidence is None:
            continue
        index = min(bins - 1, max(0, int(record.confidence * bins)))
        buckets[index] += 1
    return buckets


def overview(db: Session, hours: int = 24) -> dict:
    records, since = _window(db, hours)
    projects = {p.id: p for p in db.execute(select(Project)).scalars().all()}
    models = {m.id: m for m in db.execute(select(ModelAsset)).scalars().all()}
    sessions = {s.project_id: s for s in db.execute(select(RuntimeSession)).scalars().all()}

    by_device: dict[str, list[RuntimeRecord]] = {}
    by_model: dict[str, list[RuntimeRecord]] = {}
    by_project: dict[str, list[RuntimeRecord]] = {}
    dataset_records: list[RuntimeRecord] = []
    for record in records:
        if record.device_id:
            by_device.setdefault(record.device_id, []).append(record)
        else:
            dataset_records.append(record)
        if record.model_id:
            by_model.setdefault(record.model_id, []).append(record)
        if record.project_id:
            by_project.setdefault(record.project_id, []).append(record)

    devices = []
    for info in device_manager.list_devices():
        used = by_device.get(info["id"], [])
        devices.append({
            **info,
            "online": info["state"] in ONLINE_STATES,
            **_stats(used),
        })

    model_rows = []
    for model in models.values():
        used = by_model.get(model.id, [])
        model_rows.append({
            "id": model.id,
            "name": model.name,
            "task": model.task,
            "framework": model.framework,
            "classes": model.classes or [],
            "projectId": model.project_id,
            "projectName": projects[model.project_id].name if model.project_id in projects else None,
            "cvAccuracy": (model.metrics or {}).get("cvAccuracy"),
            "trainedAt": model.created_at,
            "confidenceBuckets": _confidence_buckets(used),
            **_stats(used),
        })
    # models actually serving traffic first, then by training date
    model_rows.sort(key=lambda row: (-row["total"], row["trainedAt"] is None))

    project_rows = []
    for project_id, used in by_project.items():
        project = projects.get(project_id)
        session = sessions.get(project_id)
        project_rows.append({
            "projectId": project_id,
            "projectName": project.name if project else project_id,
            "taskType": project.task_type if project else "unknown",
            "status": session.status if session else "stopped",
            "source": session.source if session else DATASET_SOURCE,
            "alarm": session.alarm if session else "",
            **_stats(used),
        })
    project_rows.sort(key=lambda row: -row["total"])

    return {
        "hours": hours,
        "since": since,
        "generatedAt": utcnow(),
        "summary": {
            **_stats(records),
            "projectCount": len(by_project),
            "deviceCount": sum(1 for device in devices if device["total"]),
            "modelCount": sum(1 for row in model_rows if row["total"]),
            "onlineDevices": sum(1 for device in devices if device["online"]),
            "totalDevices": len(devices),
            "datasetInferences": len(dataset_records),
            "runningSessions": sum(1 for s in sessions.values() if s.status == "running"),
        },
        "devices": devices,
        "models": model_rows,
        "projects": project_rows,
        "timeline": timeline(records, since, hours),
        "alerts": alerts(devices, model_rows, project_rows),
        "retentionNote": (
            "运行记录按会话保留最近 200 条，监控窗口以此为上限；"
            "接入时序库后可延长留存"
        ),
    }


def timeline(records: list[RuntimeRecord], since: datetime, hours: int, buckets: int = 24) -> list[dict]:
    """Inference volume over the window, bucketed for the trend chart."""
    span = max(1.0, hours * 3600.0)
    step = span / buckets
    slots: list[dict[str, Any]] = [
        {
            "ts": since + timedelta(seconds=step * index),
            "total": 0,
            "okCount": 0,
            "ngCount": 0,
            "errorCount": 0,
            "_durations": [],
        }
        for index in range(buckets)
    ]
    for record in records:
        offset = (record.created_at - since).total_seconds()
        index = min(buckets - 1, max(0, int(offset / step)))
        slot = slots[index]
        slot["total"] += 1
        if record.verdict == "OK":
            slot["okCount"] += 1
        elif record.verdict == "NG":
            slot["ngCount"] += 1
        else:
            slot["errorCount"] += 1
        slot["_durations"].append(record.duration_ms)
    for slot in slots:
        slot["avgDurationMs"] = _mean(slot.pop("_durations"))
    return slots


def alerts(devices: list[dict], models: list[dict], projects: list[dict]) -> list[dict]:
    """Rule-based warnings; the things an operator should look at first."""
    items: list[dict] = []
    for device in devices:
        if device["state"] == "error":
            items.append({
                "level": "error",
                "target": device["name"],
                "message": device.get("lastError") or "设备处于错误状态",
            })
    for project in projects:
        if project["status"] == "error":
            items.append({
                "level": "error",
                "target": project["projectName"],
                "message": project["alarm"] or "运行会话已停止在错误状态",
            })
        elif project["total"] >= 10 and project["yieldPercent"] < 50:
            items.append({
                "level": "warning",
                "target": project["projectName"],
                "message": f"良率仅 {project['yieldPercent']}%，建议复核判定阈值",
            })
    for model in models:
        if not model["total"]:
            continue
        if model["avgConfidence"] and model["avgConfidence"] < LOW_CONFIDENCE:
            items.append({
                "level": "warning",
                "target": model["name"],
                "message": f"平均置信度 {model['avgConfidence']:.2f} 偏低，建议补充训练样本",
            })
        elif model["lowConfidenceCount"]:
            items.append({
                "level": "info",
                "target": model["name"],
                "message": (
                    f"{model['lowConfidenceCount']} 次推理置信度低于 {LOW_CONFIDENCE}，"
                    "这些样本值得回流标注"
                ),
            })
    return items


def records(
    db: Session,
    hours: int = 24,
    project_id: str | None = None,
    device_id: str | None = None,
    model_id: str | None = None,
    verdict: str | None = None,
    low_confidence: bool = False,
    page: int = 1,
    page_size: int = 40,
) -> dict:
    """Individual prediction results, newest first."""
    since = utcnow() - timedelta(hours=hours)
    query = select(RuntimeRecord).where(RuntimeRecord.created_at >= since)
    if project_id:
        query = query.where(RuntimeRecord.project_id == project_id)
    if device_id:
        query = (
            query.where(RuntimeRecord.device_id.is_(None))
            if device_id == DATASET_SOURCE
            else query.where(RuntimeRecord.device_id == device_id)
        )
    if model_id:
        query = query.where(RuntimeRecord.model_id == model_id)
    if verdict:
        query = query.where(RuntimeRecord.verdict == verdict.upper())
    if low_confidence:
        query = query.where(
            RuntimeRecord.confidence.is_not(None), RuntimeRecord.confidence < LOW_CONFIDENCE
        )

    rows = db.execute(query.order_by(RuntimeRecord.created_at.desc())).scalars().all()
    total = len(rows)
    start = max(0, (page - 1) * page_size)
    window = rows[start : start + page_size]

    projects = {p.id: p.name for p in db.execute(select(Project)).scalars().all()}
    models = {m.id: m.name for m in db.execute(select(ModelAsset)).scalars().all()}
    return {
        "total": total,
        "page": page,
        "pageSize": page_size,
        "records": [
            {
                "id": record.id,
                "seq": record.seq,
                "projectId": record.project_id,
                "projectName": projects.get(record.project_id or "", "已删除项目"),
                "imageId": record.image_id,
                "imageName": record.image_name,
                "verdict": record.verdict,
                "source": record.source,
                "deviceId": record.device_id,
                "modelId": record.model_id,
                "modelName": models.get(record.model_id or ""),
                "confidence": record.confidence,
                "measurements": record.measurements or {},
                "preview": (record.artifacts or {}).get("preview"),
                "durationMs": round(record.duration_ms, 2),
                "error": record.error,
                "createdAt": record.created_at,
            }
            for record in window
        ],
    }
