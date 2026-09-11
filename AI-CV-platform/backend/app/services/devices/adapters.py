"""Concrete adapters: one working simulator plus reserved hardware stubs."""

from __future__ import annotations

import itertools
import threading
from pathlib import Path
from typing import Any

import numpy as np

from app.core.config import settings
from app.core.errors import NotImplementedFeature, ValidationError
from app.services.devices.base import (
    DeviceAdapter,
    DeviceCapability,
    DeviceInfo,
    DeviceState,
)
from app.utils.imageio import SUPPORTED_EXTS, load_image


class FolderCamera(DeviceAdapter):
    """Simulated camera that replays images from a folder.

    Lets the acquisition path (trigger → frame → pipeline → result) be built and
    demoed before any camera SDK is integrated.
    """

    def __init__(self) -> None:
        super().__init__(
            DeviceInfo(
                id="sim_folder",
                name="文件夹模拟相机",
                kind="camera",
                vendor="Platform",
                model="Simulator",
                implemented=True,
                capabilities=[
                    DeviceCapability.SOFTWARE_TRIGGER,
                    DeviceCapability.CONTINUOUS,
                ],
                settings={"folder": "", "loop": True},
                note="按文件名顺序循环输出图像，用于联调采集流程",
            )
        )
        self._lock = threading.Lock()
        self._files: list[Path] = []
        self._cycle: itertools.cycle | None = None

    def _resolve_folder(self, project_id: str | None) -> Path:
        folder = self.info.settings.get("folder")
        if folder:
            return Path(folder)
        if project_id:
            return settings.projects_dir / project_id / "images"
        raise ValidationError("模拟相机未设置图像目录")

    def connect(self, **kwargs: Any) -> DeviceState:
        self.configure(**kwargs)
        self.state = DeviceState.CONNECTED
        self.last_error = ""
        return self.state

    def grab(self, project_id: str | None = None, **kwargs: Any) -> np.ndarray:
        folder = self._resolve_folder(project_id)
        with self._lock:
            files = sorted(
                p for p in folder.glob("*") if p.is_file() and p.suffix.lower() in SUPPORTED_EXTS
            )
            if not files:
                raise ValidationError(f"模拟相机目录中没有图像: {folder}")
            if files != self._files:
                self._files = files
                self._cycle = itertools.cycle(files)
            path = next(self._cycle)  # type: ignore[arg-type]
        self.state = DeviceState.CONNECTED
        return load_image(path)


class ReservedCamera(DeviceAdapter):
    """Industrial camera placeholder (GenICam / vendor SDK)."""

    def __init__(self, device_id: str, name: str, vendor: str, note: str) -> None:
        super().__init__(
            DeviceInfo(
                id=device_id,
                name=name,
                kind="camera",
                vendor=vendor,
                implemented=False,
                capabilities=[
                    DeviceCapability.SOFTWARE_TRIGGER,
                    DeviceCapability.HARDWARE_TRIGGER,
                    DeviceCapability.CONTINUOUS,
                    DeviceCapability.EXPOSURE,
                    DeviceCapability.GAIN,
                ],
                settings={"exposure_us": 10000, "gain": 1.0, "pixel_format": "Mono8"},
                note=note,
            )
        )

    def connect(self, **kwargs: Any) -> DeviceState:
        raise NotImplementedFeature(
            f"{self.info.name} 采集接口已预留：接入厂商 SDK 后即可启用（无需改动 Pipeline）"
        )


class ReservedIoDevice(DeviceAdapter):
    """PLC / robot / MES placeholder."""

    def __init__(self, device_id: str, name: str, kind: str, note: str) -> None:
        super().__init__(
            DeviceInfo(
                id=device_id,
                name=name,
                kind=kind,
                implemented=False,
                capabilities=[DeviceCapability.DIGITAL_IO],
                settings={"endpoint": "", "protocol": kind},
                note=note,
            )
        )

    def connect(self, **kwargs: Any) -> DeviceState:
        raise NotImplementedFeature(f"{self.info.name} 通信接口已预留（P2 阶段接入）")


def default_adapters() -> list[DeviceAdapter]:
    return [
        FolderCamera(),
        ReservedCamera("genicam", "GenICam / GigE Vision 相机", "GenICam",
                       "标准 GenICam 接口，计划通过 harvesters/aravis 接入"),
        ReservedCamera("hik_mvs", "海康 MVS 工业相机", "Hikrobot",
                       "MVS SDK Python 封装，支持硬触发与曝光控制"),
        ReservedCamera("basler_pylon", "Basler pylon 相机", "Basler",
                       "pypylon 接入，支持连续采集与硬触发"),
        ReservedIoDevice("plc_modbus", "PLC (Modbus TCP)", "plc",
                         "读写线圈/寄存器，用于触发与 OK/NG 信号回传"),
        ReservedIoDevice("mes_rest", "MES (REST)", "mes",
                         "检测结果上传与工单信息拉取"),
        ReservedIoDevice("robot_ros2", "机器人 (ROS2)", "robot",
                         "位姿下发与手眼标定联动，V3.0 规划"),
    ]
