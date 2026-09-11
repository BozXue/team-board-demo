"""Project lifecycle: create / open / copy / delete, versions, publish."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.engine.graph import Graph
from app.engine.registry import get_node_class
from app.models import (
    Annotation,
    BatchRun,
    ImageAsset,
    LabelClass,
    ModelAsset,
    PipelineVersion,
    Project,
    new_id,
)
from app.services import storage, templates

DEFAULT_LABELS = [("OK", "#34d399"), ("NG", "#f87171")]


def get_project(db: Session, project_id: str) -> Project:
    project = db.get(Project, project_id)
    if project is None:
        raise NotFoundError(f"项目不存在: {project_id}")
    return project


def list_projects(db: Session, search: str | None = None) -> list[dict]:
    query = select(Project).order_by(Project.updated_at.desc())
    if search:
        query = query.where(Project.name.like(f"%{search}%"))
    projects = db.execute(query).scalars().all()

    image_counts = dict(
        db.execute(
            select(ImageAsset.project_id, func.count(ImageAsset.id)).group_by(ImageAsset.project_id)
        ).all()
    )
    annotation_counts = dict(
        db.execute(
            select(Annotation.project_id, func.count(Annotation.id)).group_by(Annotation.project_id)
        ).all()
    )
    return [
        summarize(project, image_counts.get(project.id, 0), annotation_counts.get(project.id, 0))
        for project in projects
    ]


def summarize(project: Project, image_count: int = 0, annotation_count: int = 0) -> dict:
    graph = project.graph or {}
    return {
        "id": project.id,
        "name": project.name,
        "description": project.description,
        "taskType": project.task_type,
        "requirement": project.requirement,
        "nodeCount": len(graph.get("nodes") or []),
        "imageCount": image_count,
        "annotationCount": annotation_count,
        "publishedVersionId": project.published_version_id,
        "createdAt": project.created_at,
        "updatedAt": project.updated_at,
        "meta": project.meta or {},
    }


def create_project(
    db: Session,
    name: str,
    description: str = "",
    template_id: str = "blank",
    requirement: str = "",
    labels: list[str] | None = None,
) -> Project:
    name = (name or "").strip()
    if not name:
        raise ValidationError("项目名称不能为空")
    exists = db.execute(select(Project).where(Project.name == name)).scalar_one_or_none()
    if exists is not None:
        raise ConflictError(f"项目名称已存在: {name}")

    graph = templates.build_graph(template_id)
    project = Project(
        id=new_id(),
        name=name,
        description=description,
        task_type=templates.task_type_of(template_id),
        requirement=requirement,
        graph=graph,
        user_params={},
        meta={"template": template_id},
    )
    db.add(project)
    db.flush()

    label_names = labels or [name for name, _ in DEFAULT_LABELS]
    palette = dict(DEFAULT_LABELS)
    for index, label in enumerate(label_names):
        db.add(
            LabelClass(
                project_id=project.id,
                name=label,
                color=palette.get(label, _color_for(index)),
                order_index=index,
            )
        )

    storage.ensure_project_dirs(project.id)
    sync_files(project)
    return project


def _color_for(index: int) -> str:
    palette = ["#38bdf8", "#a78bfa", "#fbbf24", "#f472b6", "#4ade80", "#f87171", "#22d3ee"]
    return palette[index % len(palette)]


def update_project(db: Session, project_id: str, data: dict) -> Project:
    project = get_project(db, project_id)
    if data.get("name") is not None:
        name = str(data["name"]).strip()
        if not name:
            raise ValidationError("项目名称不能为空")
        other = db.execute(
            select(Project).where(Project.name == name, Project.id != project_id)
        ).scalar_one_or_none()
        if other is not None:
            raise ConflictError(f"项目名称已存在: {name}")
        data["name"] = name
    for field in ("name", "description", "task_type", "requirement"):
        if field in data and data[field] is not None:
            setattr(project, field, data[field])
    if data.get("graph") is not None:
        project.graph = Graph.from_dict(data["graph"]).to_dict()
    if data.get("user_params") is not None:
        project.user_params = data["user_params"]
    if data.get("meta") is not None:
        project.meta = {**(project.meta or {}), **data["meta"]}
    sync_files(project)
    return project


def duplicate_project(db: Session, project_id: str, new_name: str | None = None) -> Project:
    source = get_project(db, project_id)
    name = (new_name or f"{source.name} 副本").strip()
    if db.execute(select(Project).where(Project.name == name)).scalar_one_or_none():
        name = f"{name} {new_id()[:4]}"

    clone = Project(
        id=new_id(),
        name=name,
        description=source.description,
        task_type=source.task_type,
        requirement=source.requirement,
        graph=source.graph,
        user_params=source.user_params,
        meta={**(source.meta or {}), "copiedFrom": source.id},
    )
    db.add(clone)
    db.flush()

    for label in source.label_classes:
        db.add(
            LabelClass(
                project_id=clone.id, name=label.name, color=label.color,
                order_index=label.order_index,
            )
        )

    storage.copy_project_dir(source.id, clone.id)
    id_map: dict[str, str] = {}
    for asset in source.images:
        copy = ImageAsset(
            project_id=clone.id,
            filename=asset.filename,
            rel_path=asset.rel_path,
            width=asset.width,
            height=asset.height,
            channels=asset.channels,
            size_bytes=asset.size_bytes,
            image_format=asset.image_format,
            split=asset.split,
            source=asset.source,
            meta=asset.meta,
        )
        db.add(copy)
        db.flush()
        id_map[asset.id] = copy.id
        # Derivatives are named after the image id, so re-point them.
        root = storage.project_dir(clone.id)
        for kind, attr in (("thumbs", "thumb_path"), ("previews", "preview_path")):
            old_rel = getattr(asset, attr)
            if not old_rel:
                continue
            old_file = root / old_rel
            new_rel = f"{kind}/{copy.id}.jpg"
            if old_file.exists():
                (root / new_rel).write_bytes(old_file.read_bytes())
            setattr(copy, attr, new_rel)

    for asset in source.images:
        if asset.annotation is None:
            continue
        db.add(
            Annotation(
                project_id=clone.id,
                image_id=id_map[asset.id],
                label=asset.annotation.label,
                shapes=asset.annotation.shapes,
                reviewed=asset.annotation.reviewed,
                note=asset.annotation.note,
            )
        )

    sync_files(clone)
    return clone


def delete_project(db: Session, project_id: str) -> None:
    from app.services import model_service

    project = get_project(db, project_id)
    # Models are not a child table (they can be global), so cascade by hand -
    # otherwise deleted projects keep haunting the model library and monitoring.
    for model in db.execute(
        select(ModelAsset).where(ModelAsset.project_id == project_id)
    ).scalars().all():
        model_service.delete_model(db, model.id)
    db.delete(project)
    storage.delete_project_dir(project_id)


# -- pipeline & versions -------------------------------------------------
def save_graph(db: Session, project_id: str, graph: dict) -> Project:
    project = get_project(db, project_id)
    parsed = Graph.from_dict(graph)
    parsed.validate(strict=False)
    project.graph = parsed.to_dict()
    sync_files(project)
    return project


def create_version(db: Session, project_id: str, note: str = "", publish: bool = False) -> PipelineVersion:
    project = get_project(db, project_id)
    latest = db.execute(
        select(func.max(PipelineVersion.version)).where(PipelineVersion.project_id == project_id)
    ).scalar()
    version = PipelineVersion(
        project_id=project_id,
        version=int(latest or 0) + 1,
        note=note,
        graph=project.graph,
        user_params=exposed_params(project.graph, project.user_params),
        published=publish,
    )
    db.add(version)
    db.flush()
    if publish:
        project.published_version_id = version.id
    return version


def restore_version(db: Session, project_id: str, version_id: str) -> Project:
    project = get_project(db, project_id)
    version = db.get(PipelineVersion, version_id)
    if version is None or version.project_id != project_id:
        raise NotFoundError(f"版本不存在: {version_id}")
    project.graph = version.graph
    project.user_params = version.user_params
    sync_files(project)
    return project


def exposed_params(graph: dict, overrides: dict | None = None) -> dict:
    """Business-level parameters of a graph, i.e. what User Mode may change."""
    overrides = overrides or {}
    parsed = Graph.from_dict(graph)
    exposed: dict[str, dict] = {}
    for node in parsed.nodes:
        try:
            node_cls = get_node_class(node.type)
        except NotFoundError:
            continue
        for spec in node_cls.params:
            if spec.level != "business":
                continue
            key = f"{node.id}.{spec.name}"
            current = node.params.get(spec.name, spec.default)
            exposed[key] = {
                "nodeId": node.id,
                "nodeType": node.type,
                "nodeLabel": node.label or node_cls.label,
                "param": spec.name,
                "label": spec.label or spec.name,
                "type": spec.type,
                "unit": spec.unit,
                "options": spec.options,
                "min": spec.min,
                "max": spec.max,
                "step": spec.step,
                "description": spec.description,
                "default": current,
                "value": overrides.get(key, {}).get("value", current) if isinstance(
                    overrides.get(key), dict
                ) else overrides.get(key, current),
            }
    return exposed


def apply_user_params(graph: dict, user_params: dict | None) -> dict:
    """Overlay User-Mode parameter values onto a graph before execution."""
    if not user_params:
        return graph
    parsed = Graph.from_dict(graph)
    nodes = {node.id: node for node in parsed.nodes}
    for key, entry in user_params.items():
        node_id, _, param = key.partition(".")
        node = nodes.get(node_id)
        if node is None or not param:
            continue
        value = entry.get("value") if isinstance(entry, dict) else entry
        if value is not None:
            node.params = {**node.params, param: value}
    return parsed.to_dict()


def publish(db: Session, project_id: str, note: str = "") -> PipelineVersion:
    project = get_project(db, project_id)
    parsed = Graph.from_dict(project.graph)
    parsed.validate(strict=True)
    if not any(node.type == "ok_ng" for node in parsed.nodes):
        raise ValidationError("发布前流程需要包含 OK/NG 节点，Runtime 才能显示判定结果")
    version = create_version(db, project_id, note=note or "发布", publish=True)
    project.user_params = version.user_params
    sync_files(project)
    return version


def project_detail(db: Session, project_id: str) -> dict:
    project = get_project(db, project_id)
    image_count = int(db.execute(
        select(func.count(ImageAsset.id)).where(ImageAsset.project_id == project_id)
    ).scalar_one())
    annotation_count = int(db.execute(
        select(func.count(Annotation.id)).where(Annotation.project_id == project_id)
    ).scalar_one())
    run_count = int(db.execute(
        select(func.count(BatchRun.id)).where(BatchRun.project_id == project_id)
    ).scalar_one())
    parsed = Graph.from_dict(project.graph)
    return {
        **summarize(project, image_count, annotation_count),
        "graph": project.graph or {"nodes": [], "edges": []},
        "userParams": exposed_params(project.graph, project.user_params),
        "labels": [
            {"id": label.id, "name": label.name, "color": label.color, "order": label.order_index}
            for label in project.label_classes
        ],
        "versions": [
            {
                "id": version.id,
                "version": version.version,
                "note": version.note,
                "published": version.published,
                "createdAt": version.created_at,
            }
            for version in project.versions
        ],
        "batchRunCount": run_count,
        "issues": parsed.validate(strict=False),
    }


def sync_files(project: Project) -> None:
    storage.write_project_files(
        project.id,
        {
            "id": project.id,
            "name": project.name,
            "description": project.description,
            "taskType": project.task_type,
            "requirement": project.requirement,
            "userParams": project.user_params,
            "meta": project.meta,
            "updatedAt": project.updated_at,
        },
        project.graph or {},
    )
