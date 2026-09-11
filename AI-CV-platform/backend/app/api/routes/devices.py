"""Device & acquisition endpoints (reserved interface + folder simulator)."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.schemas import DeviceConnectRequest, DeviceGrabRequest
from app.services import dataset_service
from app.services.devices import device_manager
from app.utils.imageio import encode_png

router = APIRouter(prefix="/devices", tags=["devices"])


@router.get("")
def list_devices() -> dict:
    devices = device_manager.list_devices()
    return {
        "devices": devices,
        "implementedCount": sum(1 for d in devices if d["implemented"]),
        "note": "未实现的设备为预留接口：接入厂商 SDK 后即可启用，Pipeline 与流程无需改动",
    }


@router.get("/{device_id}")
def get_device(device_id: str) -> dict:
    return device_manager.get(device_id).status()


@router.post("/{device_id}/connect")
def connect(device_id: str, payload: DeviceConnectRequest) -> dict:
    return device_manager.connect(device_id, **payload.settings)


@router.post("/{device_id}/disconnect")
def disconnect(device_id: str) -> dict:
    return device_manager.disconnect(device_id)


@router.post("/{device_id}/configure")
def configure(device_id: str, payload: DeviceConnectRequest) -> dict:
    return device_manager.configure(device_id, payload.settings)


@router.post("/{device_id}/grab")
def grab(device_id: str, payload: DeviceGrabRequest, db: Session = Depends(get_db)) -> dict:
    """Trigger one acquisition; optionally register the frame in the dataset."""
    frame = device_manager.grab(device_id, project_id=payload.projectId)
    result: dict = {
        "deviceId": device_id,
        "width": int(frame.shape[1]),
        "height": int(frame.shape[0]),
        "channels": 1 if frame.ndim == 2 else int(frame.shape[2]),
    }
    if payload.saveToDataset and payload.projectId:
        from datetime import datetime

        name = f"grab_{device_id}_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')[:-3]}.png"
        asset = dataset_service.import_bytes(
            db, payload.projectId, name, encode_png(frame),
            source="camera", split=payload.split, meta={"deviceId": device_id},
        )
        db.commit()
        result["image"] = {
            "id": asset.id,
            "filename": asset.filename,
            "previewUrl": f"/api/images/{asset.id}/preview",
        }
    return result
