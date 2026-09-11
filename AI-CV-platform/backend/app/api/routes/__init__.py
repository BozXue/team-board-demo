"""API routers."""

from fastapi import APIRouter

from app.api.routes import (
    annotations,
    batch,
    copilot,
    datasets,
    devices,
    meta,
    models,
    monitoring,
    projects,
    runtime,
)

api_router = APIRouter(prefix="/api")
api_router.include_router(meta.router)
api_router.include_router(projects.router)
api_router.include_router(datasets.router)
api_router.include_router(annotations.router)
api_router.include_router(batch.router)
api_router.include_router(copilot.router)
api_router.include_router(runtime.router)
api_router.include_router(models.router)
api_router.include_router(devices.router)
api_router.include_router(monitoring.router)

__all__ = ["api_router"]
