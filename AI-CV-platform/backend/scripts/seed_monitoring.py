"""Seed traffic for the Model Monitoring page.

Monitoring aggregates real User-Mode inferences, so an empty platform shows an
empty dashboard. This script publishes the demo projects and runs a batch of
inferences through them - half replayed from the dataset, half acquired through
the simulated camera - so devices, models, latency and prediction history all
have something to show.

It also creates one demo project whose published pipeline runs a trained
LBP+SVM classifier, because per-model confidence is only recorded when an AI
node is actually part of the deployed graph.

Usage::

    python -m scripts.seed_monitoring [--inferences 24]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.db import init_db, session_scope  # noqa: E402
from app.engine.registry import load_nodes  # noqa: E402
from app.models import ModelAsset, Project  # noqa: E402
from app.services import (  # noqa: E402
    annotation_service,
    dataset_service,
    model_service,
    project_service,
    runtime_service,
)
from app.services.devices import device_manager  # noqa: E402
from app.utils.imageio import encode_png  # noqa: E402
from scripts.seed_demo import _synthetic_frame  # noqa: E402
from sqlalchemy import select  # noqa: E402

AI_PROJECT = "布面 AI 分类（示例）"
COLUMN = 210


def _node(node_id: str, node_type: str, x: int, y: int, params: dict | None = None) -> dict:
    return {
        "id": node_id,
        "type": node_type,
        "label": node_id,
        "position": {"x": x, "y": y},
        "params": params or {},
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


def ensure_ai_project(ok_count: int = 14, ng_count: int = 10) -> str:
    """A project deployed on a trained classifier, so models have telemetry."""
    with session_scope() as db:
        existing = db.execute(select(Project).where(Project.name == AI_PROJECT)).scalar_one_or_none()
        if existing is not None:
            print(f"[skip] 项目已存在: {AI_PROJECT}")
            return existing.id

        project = project_service.create_project(
            db,
            name=AI_PROJECT,
            description="部署 LBP+SVM 分类器的示例项目：监控页的模型置信度、推理耗时来自这里。",
            template_id="blank",
            requirement="用训练好的纹理分类器判断布面是否有污渍，置信度过低时判 NG 交人工复核。",
            labels=["OK", "NG"],
        )
        project.task_type = "defect_detection"
        project_id = project.id
        rng = np.random.default_rng(20260812)
        for index in range(ok_count):
            asset = dataset_service.import_bytes(
                db, project_id, f"ok_{index + 1:03d}.png", encode_png(_synthetic_frame(rng, defects=0)),
                split="train", meta={"synthetic": True},
            )
            annotation_service.save_annotation(db, project_id, asset.id, label="OK")
        for index in range(ng_count):
            image = _synthetic_frame(rng, defects=int(rng.integers(1, 4)))
            asset = dataset_service.import_bytes(
                db, project_id, f"ng_{index + 1:03d}.png", encode_png(image),
                split="train", meta={"synthetic": True},
            )
            annotation_service.save_annotation(db, project_id, asset.id, label="NG")
        print(f"[ok] 项目已创建: {AI_PROJECT} ({project_id})，{ok_count} OK / {ng_count} NG")

    with session_scope() as db:
        model = model_service.train_classifier(db, project_id, name="布面纹理分类器")
        metrics = model.metrics or {}
        print(f"[ok] 模型训练完成: {model.name} ({model.id}) cv={metrics.get('cvAccuracy')}")
        graph = {
            "nodes": [
                _node("input", "image_input", 40, 200, {"color_mode": "gray"}),
                _node("classify", "ai_classify", 40 + COLUMN, 200, {
                    "model_id": model.id,
                    "ok_classes": "OK",
                    "min_confidence": 0.55,
                }),
                _node("verdict", "ok_ng", 40 + COLUMN * 2, 200, {
                    "ok_message": "布面正常",
                    "ng_message": "疑似污渍，请复核",
                }),
                _node("display", "display", 40 + COLUMN * 3, 200),
            ],
            "edges": [
                _edge("input", "image", "classify", "image"),
                _edge("classify", "result", "verdict", "result"),
                _edge("input", "image", "display", "image"),
                _edge("verdict", "result", "display", "result"),
            ],
        }
        project_service.save_graph(db, project_id, graph)
        version = project_service.publish(db, project_id, note="AI 分类流程首次发布")
        print(f"[ok] 已发布 v{version.version}")
    return project_id


def ensure_published(project_id: str) -> bool:
    with session_scope() as db:
        project = project_service.get_project(db, project_id)
        if project.published_version_id:
            return True
        try:
            version = project_service.publish(db, project_id, note="监控演示数据自动发布")
        except Exception as exc:  # noqa: BLE001 - a broken demo graph shouldn't stop seeding
            print(f"[warn] {project.name} 发布失败：{exc}")
            return False
        print(f"[ok] {project.name} 已发布 v{version.version}")
        return True


def run_traffic(project_id: str, count: int, source: str) -> None:
    with session_scope() as db:
        session = runtime_service.get_session(db, project_id)
        session.source = source
    ok = failed = 0
    for _ in range(count):
        try:
            with session_scope() as db:
                runtime_service.inspect_once(db, project_id, "sim_folder" if source == "camera" else None)
            ok += 1
        except Exception as exc:  # noqa: BLE001 - keep generating the rest of the traffic
            failed += 1
            if failed == 1:
                print(f"[warn] 推理失败（{source}）：{type(exc).__name__}: {exc}")
    with session_scope() as db:
        status = runtime_service.status(db, project_id)
    print(
        f"[run] {status['projectName']:22s} {source:7s} 成功 {ok}/{count} "
        f"良率 {status['yieldPercent']}% 平均 {status['avgDurationMs']}ms"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inferences", type=int, default=24, help="每个项目生成的推理次数")
    args = parser.parse_args()

    load_nodes()
    init_db()

    ai_project_id = ensure_ai_project()
    device_manager.connect("sim_folder")
    print("[ok] 模拟相机已连接")

    with session_scope() as db:
        projects = [(p.id, p.name) for p in db.execute(select(Project)).scalars().all()]

    for project_id, name in projects:
        if not ensure_published(project_id):
            continue
        half = max(1, args.inferences // 2)
        run_traffic(project_id, args.inferences - half, "dataset")
        run_traffic(project_id, half, "camera")

    with session_scope() as db:
        models = db.execute(select(ModelAsset)).scalars().all()
    print(
        f"\n完成：{len(projects)} 个项目、{len(models)} 个模型已产生监控数据，"
        f"打开「监控」页查看（AI 项目 {ai_project_id}）"
    )


if __name__ == "__main__":
    main()
