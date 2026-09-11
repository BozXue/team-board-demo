"""Project lifecycle, pipeline persistence, versions, publish."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.engine.graph import Graph
from app.schemas import (
    GraphPayload,
    ProjectCreate,
    ProjectUpdate,
    RunRequest,
    VersionCreate,
)
from app.services import pipeline_service, project_service

router = APIRouter(prefix="/projects", tags=["projects"])


@router.get("")
def list_projects(search: str | None = None, db: Session = Depends(get_db)) -> dict:
    return {"projects": project_service.list_projects(db, search)}


@router.post("", status_code=201)
def create_project(payload: ProjectCreate, db: Session = Depends(get_db)) -> dict:
    project = project_service.create_project(
        db,
        name=payload.name,
        description=payload.description,
        template_id=payload.templateId,
        requirement=payload.requirement,
        labels=payload.labels,
    )
    db.commit()
    return project_service.project_detail(db, project.id)


@router.get("/{project_id}")
def get_project(project_id: str, db: Session = Depends(get_db)) -> dict:
    return project_service.project_detail(db, project_id)


@router.patch("/{project_id}")
def update_project(project_id: str, payload: ProjectUpdate, db: Session = Depends(get_db)) -> dict:
    data = {
        "name": payload.name,
        "description": payload.description,
        "task_type": payload.taskType,
        "requirement": payload.requirement,
        "graph": payload.graph,
        "user_params": payload.userParams,
        "meta": payload.meta,
    }
    project_service.update_project(db, project_id, data)
    db.commit()
    return project_service.project_detail(db, project_id)


@router.post("/{project_id}/duplicate", status_code=201)
def duplicate_project(project_id: str, name: str | None = None, db: Session = Depends(get_db)) -> dict:
    clone = project_service.duplicate_project(db, project_id, name)
    db.commit()
    return project_service.project_detail(db, clone.id)


@router.delete("/{project_id}", status_code=204)
def delete_project(project_id: str, db: Session = Depends(get_db)) -> Response:
    project_service.delete_project(db, project_id)
    pipeline_service.clear_cache(project_id)
    db.commit()
    return Response(status_code=204)


# -- pipeline ------------------------------------------------------------
@router.get("/{project_id}/pipeline")
def get_pipeline(project_id: str, db: Session = Depends(get_db)) -> dict:
    project = project_service.get_project(db, project_id)
    graph = Graph.from_dict(project.graph)
    return {
        "graph": graph.to_dict(),
        "issues": graph.validate(strict=False),
        "userParams": project_service.exposed_params(project.graph, project.user_params),
    }


@router.put("/{project_id}/pipeline")
def save_pipeline(project_id: str, payload: GraphPayload, db: Session = Depends(get_db)) -> dict:
    project_service.save_graph(db, project_id, payload.graph)
    db.commit()
    return get_pipeline(project_id, db)


@router.post("/{project_id}/pipeline/validate")
def validate_pipeline(project_id: str, payload: GraphPayload, db: Session = Depends(get_db)) -> dict:
    graph = Graph.from_dict(payload.graph)
    return {"issues": graph.validate(strict=False), "order": graph.topological_order()}


@router.post("/{project_id}/pipeline/run")
def run_pipeline(project_id: str, payload: RunRequest, db: Session = Depends(get_db)) -> dict:
    result = pipeline_service.run_debug(
        db,
        project_id,
        payload.graph,
        image_id=payload.imageId,
        target_node=payload.targetNode,
        preview_nodes=payload.previewNodes,
        save_graph=payload.saveGraph,
    )
    db.commit()
    return result


@router.post("/{project_id}/pipeline/cache/clear")
def clear_pipeline_cache(project_id: str) -> dict:
    return {"cleared": pipeline_service.clear_cache(project_id)}


# -- versions ------------------------------------------------------------
@router.get("/{project_id}/versions")
def list_versions(project_id: str, db: Session = Depends(get_db)) -> dict:
    project = project_service.get_project(db, project_id)
    return {
        "versions": [
            {
                "id": version.id,
                "version": version.version,
                "note": version.note,
                "published": version.published,
                "createdAt": version.created_at,
                "nodeCount": len((version.graph or {}).get("nodes") or []),
            }
            for version in project.versions
        ],
        "publishedVersionId": project.published_version_id,
    }


@router.post("/{project_id}/versions", status_code=201)
def create_version(project_id: str, payload: VersionCreate, db: Session = Depends(get_db)) -> dict:
    version = project_service.create_version(db, project_id, payload.note, payload.publish)
    db.commit()
    return {"id": version.id, "version": version.version, "published": version.published}


@router.post("/{project_id}/versions/{version_id}/restore")
def restore_version(project_id: str, version_id: str, db: Session = Depends(get_db)) -> dict:
    project_service.restore_version(db, project_id, version_id)
    pipeline_service.clear_cache(project_id)
    db.commit()
    return project_service.project_detail(db, project_id)


@router.post("/{project_id}/publish")
def publish_project(project_id: str, payload: VersionCreate, db: Session = Depends(get_db)) -> dict:
    version = project_service.publish(db, project_id, payload.note)
    db.commit()
    return {
        "id": version.id,
        "version": version.version,
        "userParams": version.user_params,
        "published": True,
    }
