"""FastAPI application entry point."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes import api_router
from app.core.config import settings
from app.core.db import init_db
from app.core.errors import PlatformError
from app.engine.registry import all_node_classes, load_nodes

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)-7s %(name)s: %(message)s"
)
logger = logging.getLogger("aicv")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.ensure_dirs()
    load_nodes()
    init_db()
    logger.info("节点库已加载: %d 个节点", len(all_node_classes()))
    logger.info("数据目录: %s", settings.data_dir)
    yield


app = FastAPI(
    title=settings.app_name,
    version=settings.version,
    description="低代码工业视觉平台：数据管理 · 在线标注 · Pipeline · AI Copilot · Runtime",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(PlatformError)
async def platform_error_handler(request: Request, exc: PlatformError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": exc.message, "detail": exc.detail, "path": request.url.path},
    )


@app.exception_handler(Exception)
async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("未处理异常: %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={"error": "服务内部错误", "detail": str(exc), "path": request.url.path},
    )


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "version": settings.version, "nodes": len(all_node_classes())}


app.include_router(api_router)

# Node previews / batch & runtime result images.
settings.ensure_dirs()
app.mount("/api/artifacts", StaticFiles(directory=str(settings.cache_dir)), name="artifacts")
