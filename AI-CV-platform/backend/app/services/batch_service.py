"""Batch test: run a pipeline over a dataset, score it, collect error samples."""

from __future__ import annotations

import threading
import time
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import session_scope
from app.core.errors import NotFoundError, ValidationError
from app.engine.executor import ArtifactWriter, ResultCache
from app.engine.graph import Graph
from app.models import Annotation, BatchResult, BatchRun, ImageAsset, Project
from app.services import dataset_service, pipeline_service, project_service, storage

_CANCEL: dict[str, threading.Event] = {}
_THREADS: dict[str, threading.Thread] = {}

DEFAULT_NG_LABELS = ("NG", "ng", "缺陷", "不合格", "bad")


def start_run(
    db: Session,
    project_id: str,
    split: str = "all",
    limit: int = 0,
    ng_labels: list[str] | None = None,
    full_resolution: bool = False,
    save_previews: bool = True,
) -> BatchRun:
    project = project_service.get_project(db, project_id)
    graph = Graph.from_dict(project.graph)
    graph.validate(strict=True)

    assets, total = dataset_service.list_images(
        db, project_id, page=1, page_size=limit or 100000, split=split
    )
    if not assets:
        raise ValidationError("所选数据集没有图像")

    run = BatchRun(
        project_id=project_id,
        version_id=project.published_version_id,
        status="running",
        split=split,
        total=len(assets),
        graph=project.graph,
        metrics={
            "ngLabels": ng_labels or list(DEFAULT_NG_LABELS),
            "fullResolution": full_resolution,
        },
    )
    db.add(run)
    db.flush()
    run_id = run.id
    image_ids = [asset.id for asset in assets]
    db.commit()

    cancel = threading.Event()
    _CANCEL[run_id] = cancel
    thread = threading.Thread(
        target=_worker,
        args=(run_id, project_id, image_ids, ng_labels or list(DEFAULT_NG_LABELS),
              full_resolution, save_previews, cancel),
        name=f"batch-{run_id}",
        daemon=True,
    )
    _THREADS[run_id] = thread
    thread.start()
    return run


def cancel_run(run_id: str) -> bool:
    event = _CANCEL.get(run_id)
    if event is None:
        return False
    event.set()
    return True


def _worker(
    run_id: str,
    project_id: str,
    image_ids: list[str],
    ng_labels: list[str],
    full_resolution: bool,
    save_previews: bool,
    cancel: threading.Event,
) -> None:
    started = time.perf_counter()
    artifacts_root = storage.run_cache_dir("batch", run_id)
    artifacts_url = storage.run_cache_url("batch", run_id)
    cache = ResultCache(max_items=64)

    try:
        with session_scope() as db:
            run = db.get(BatchRun, run_id)
            project = db.get(Project, project_id)
            if run is None or project is None:
                return
            graph_data = run.graph or project.graph
            preview_nodes = pipeline_service.primary_display_nodes(graph_data)

        for index, image_id in enumerate(image_ids):
            if cancel.is_set():
                _finish(run_id, started, status="cancelled", message="用户已取消")
                return
            with session_scope() as db:
                asset = db.get(ImageAsset, image_id)
                if asset is None:
                    continue
                annotation = db.execute(
                    select(Annotation).where(Annotation.image_id == image_id)
                ).scalar_one_or_none()
                gt_label = annotation.label if annotation else None
                context = pipeline_service.image_for_asset(asset, full_resolution)
                image_name = asset.filename

            writer = (
                ArtifactWriter(artifacts_root / image_id, f"{artifacts_url}/{image_id}", max_side=640)
                if save_previews else None
            )
            cache.clear()
            result = pipeline_service.run_single_image(
                graph_data, context, artifacts=writer, cache=cache, preview_nodes=preview_nodes
            )

            verdict = result.verdict if not result.errors else "ERROR"
            preview_url = _first_preview(result)
            outcome = _outcome(verdict, gt_label, ng_labels)

            with session_scope() as db:
                run = db.get(BatchRun, run_id)
                if run is None:
                    return
                db.add(
                    BatchResult(
                        run_id=run_id,
                        image_id=image_id,
                        image_name=image_name,
                        verdict=verdict,
                        gt_label=gt_label,
                        outcome=outcome,
                        measurements=_jsonable(result.measurements),
                        artifacts={"preview": preview_url} if preview_url else {},
                        duration_ms=result.total_ms,
                        error="; ".join(e["message"] for e in result.errors) or None,
                    )
                )
                run.done = index + 1
                if verdict == "OK":
                    run.ok_count += 1
                elif verdict == "NG":
                    run.ng_count += 1
                else:
                    run.error_count += 1

        _finish(run_id, started, status="finished")
    except Exception as exc:  # noqa: BLE001 - worker must always land in a final state
        _finish(run_id, started, status="failed", message=f"{type(exc).__name__}: {exc}")
    finally:
        _CANCEL.pop(run_id, None)
        _THREADS.pop(run_id, None)


def _first_preview(result) -> str | None:
    for info in result.nodes.values():
        for output in info.outputs.values():
            preview = output.get("preview")
            if preview:
                return preview["url"]
    return None


def _jsonable(measurements: dict[str, Any]) -> dict[str, Any]:
    clean: dict[str, Any] = {}
    for key, value in measurements.items():
        if isinstance(value, (int, float, str, bool)) or value is None:
            clean[key] = value
        else:
            clean[key] = str(value)
    return clean


def _outcome(verdict: str, gt_label: str | None, ng_labels: list[str]) -> str | None:
    if not gt_label or verdict not in {"OK", "NG"}:
        return None
    gt_ng = gt_label in ng_labels
    pred_ng = verdict == "NG"
    if gt_ng and pred_ng:
        return "TP"
    if gt_ng and not pred_ng:
        return "FN"
    if not gt_ng and pred_ng:
        return "FP"
    return "TN"


def _finish(run_id: str, started: float, status: str, message: str = "") -> None:
    with session_scope() as db:
        run = db.get(BatchRun, run_id)
        if run is None:
            return
        run.status = status
        run.message = message
        run.duration_ms = (time.perf_counter() - started) * 1000.0
        run.metrics = {**(run.metrics or {}), **compute_metrics(db, run_id)}


def compute_metrics(db: Session, run_id: str) -> dict:
    """Accuracy/Precision/Recall with NG as the positive class."""
    results = db.execute(
        select(BatchResult).where(BatchResult.run_id == run_id)
    ).scalars().all()
    counts = {"TP": 0, "FP": 0, "TN": 0, "FN": 0}
    labelled = 0
    durations: list[float] = []
    for result in results:
        durations.append(result.duration_ms)
        if result.outcome in counts:
            counts[result.outcome] += 1
            labelled += 1

    tp, fp, tn, fn = counts["TP"], counts["FP"], counts["TN"], counts["FN"]
    metrics: dict[str, Any] = {
        "counts": counts,
        "labelledCount": labelled,
        "avgDurationMs": round(sum(durations) / len(durations), 2) if durations else 0.0,
        "maxDurationMs": round(max(durations), 2) if durations else 0.0,
    }
    if labelled:
        metrics["accuracy"] = round((tp + tn) / labelled, 4)
        metrics["precision"] = round(tp / (tp + fp), 4) if (tp + fp) else None
        metrics["recall"] = round(tp / (tp + fn), 4) if (tp + fn) else None
        if metrics.get("precision") and metrics.get("recall"):
            precision, recall = metrics["precision"], metrics["recall"]
            metrics["f1"] = round(2 * precision * recall / (precision + recall), 4)
        metrics["missRate"] = round(fn / (tp + fn), 4) if (tp + fn) else None
        metrics["falseAlarmRate"] = round(fp / (fp + tn), 4) if (fp + tn) else None
    return metrics


def run_summary(db: Session, run: BatchRun) -> dict:
    return {
        "id": run.id,
        "projectId": run.project_id,
        "status": run.status,
        "split": run.split,
        "total": run.total,
        "done": run.done,
        "okCount": run.ok_count,
        "ngCount": run.ng_count,
        "errorCount": run.error_count,
        "durationMs": round(run.duration_ms, 2),
        "metrics": run.metrics or {},
        "message": run.message,
        "createdAt": run.created_at,
        "updatedAt": run.updated_at,
        "yieldPercent": round(run.ok_count / run.done * 100.0, 2) if run.done else 0.0,
    }


def get_run(db: Session, run_id: str) -> BatchRun:
    run = db.get(BatchRun, run_id)
    if run is None:
        raise NotFoundError(f"批量测试记录不存在: {run_id}")
    return run


def list_runs(db: Session, project_id: str, limit: int = 20) -> list[dict]:
    runs = db.execute(
        select(BatchRun)
        .where(BatchRun.project_id == project_id)
        .order_by(BatchRun.created_at.desc())
        .limit(limit)
    ).scalars().all()
    return [run_summary(db, run) for run in runs]


def list_results(
    db: Session, run_id: str, verdict: str | None = None, outcome: str | None = None,
    page: int = 1, page_size: int = 100,
) -> tuple[list[dict], int]:
    query = select(BatchResult).where(BatchResult.run_id == run_id)
    if verdict and verdict != "all":
        query = query.where(BatchResult.verdict == verdict)
    if outcome and outcome != "all":
        if outcome == "errors":
            query = query.where(BatchResult.outcome.in_(["FP", "FN"]))
        else:
            query = query.where(BatchResult.outcome == outcome)
    rows = db.execute(query.order_by(BatchResult.created_at)).scalars().all()
    total = len(rows)
    start = (max(1, page) - 1) * page_size
    page_rows = rows[start:start + page_size]
    return [
        {
            "id": row.id,
            "imageId": row.image_id,
            "imageName": row.image_name,
            "verdict": row.verdict,
            "gtLabel": row.gt_label,
            "outcome": row.outcome,
            "measurements": row.measurements or {},
            "artifacts": row.artifacts or {},
            "durationMs": round(row.duration_ms, 2),
            "error": row.error,
        }
        for row in page_rows
    ], total


def reflow_errors(db: Session, run_id: str, split: str = "train", result_ids: list[str] | None = None) -> dict:
    """Error sample reflow: move FP/FN (or selected) images back into training."""
    run = get_run(db, run_id)
    query = select(BatchResult).where(BatchResult.run_id == run_id)
    if result_ids:
        query = query.where(BatchResult.id.in_(result_ids))
    else:
        query = query.where(BatchResult.outcome.in_(["FP", "FN"]))
    results = db.execute(query).scalars().all()

    moved = 0
    for result in results:
        asset = db.get(ImageAsset, result.image_id)
        if asset is None:
            continue
        asset.split = split
        asset.meta = {
            **(asset.meta or {}),
            "reflow": {
                "runId": run_id,
                "outcome": result.outcome,
                "verdict": result.verdict,
                "gtLabel": result.gt_label,
            },
        }
        annotation = db.execute(
            select(Annotation).where(Annotation.image_id == asset.id)
        ).scalar_one_or_none()
        if annotation is not None:
            annotation.reviewed = False
            annotation.note = (
                f"批量测试 {run_id} 判定 {result.verdict}（标注 {result.gt_label}），需复核"
            )
        moved += 1
    return {"runId": run.id, "moved": moved, "split": split}
