"""Request/response models for the REST API."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ProjectCreate(BaseModel):
    name: str
    description: str = ""
    templateId: str = "blank"
    requirement: str = ""
    labels: list[str] | None = None


class ProjectUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    taskType: str | None = None
    requirement: str | None = None
    graph: dict | None = None
    userParams: dict | None = None
    meta: dict | None = None


class GraphPayload(BaseModel):
    graph: dict


class VersionCreate(BaseModel):
    note: str = ""
    publish: bool = False


class RunRequest(BaseModel):
    graph: dict | None = None
    imageId: str | None = None
    targetNode: str | None = None
    previewNodes: list[str] | None = None
    saveGraph: bool = True


class ImportFolderRequest(BaseModel):
    path: str
    recursive: bool = False
    limit: int = Field(default=500, ge=1, le=5000)


class ImageIdsRequest(BaseModel):
    imageIds: list[str]


class SplitRequest(BaseModel):
    imageIds: list[str] = []
    split: str = "train"


class AutoSplitRequest(BaseModel):
    train: float = 0.7
    val: float = 0.2
    seed: int = 42


class LabelCreate(BaseModel):
    name: str
    color: str | None = None


class AnnotationSave(BaseModel):
    imageId: str
    label: str | None = None
    shapes: list[dict] | None = None
    reviewed: bool | None = None
    note: str | None = None


class BulkLabelRequest(BaseModel):
    imageIds: list[str]
    label: str


class AnnotationImport(BaseModel):
    format: str = "coco"
    data: dict


class SamPredictRequest(BaseModel):
    imageId: str
    points: list[list[float]] = []
    labels: list[int] = []
    box: list[float] | None = None


class BatchStartRequest(BaseModel):
    split: str = "all"
    limit: int = 0
    ngLabels: list[str] | None = None
    fullResolution: bool = False
    savePreviews: bool = True


class ReflowRequest(BaseModel):
    split: str = "train"
    resultIds: list[str] | None = None


class CopilotPlanRequest(BaseModel):
    text: str = ""
    imageId: str | None = None
    useLlm: bool = True


class CopilotApplyRequest(BaseModel):
    graph: dict
    taskType: str | None = None


class CopilotAskRequest(BaseModel):
    question: str
    nodeType: str | None = None
    params: dict | None = None


class RuntimeStartRequest(BaseModel):
    source: str = "dataset"
    intervalMs: int = Field(default=1200, ge=200, le=60000)
    deviceId: str | None = None


class RuntimeParamsRequest(BaseModel):
    values: dict[str, Any]


class TrainRequest(BaseModel):
    name: str | None = None
    splits: list[str] | None = None
    kernel: str = "rbf"
    c: float = 10.0
    arch: str = "lbp_svm"
    epochs: int = Field(default=8, ge=1, le=200)
    imgsz: int = Field(default=384, ge=64, le=1280)
    batch: int = Field(default=8, ge=1, le=128)
    yoloBase: str = "yolo11n-cls.pt"


class DeviceConnectRequest(BaseModel):
    settings: dict[str, Any] = {}


class DeviceGrabRequest(BaseModel):
    projectId: str | None = None
    saveToDataset: bool = True
    split: str = "unassigned"


class NodeExplainRequest(BaseModel):
    nodeType: str
    params: dict | None = None
