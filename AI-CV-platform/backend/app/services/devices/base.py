"""Device adapter contract."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import numpy as np

from app.core.errors import NotImplementedFeature


class DeviceState(str, Enum):
    DISCONNECTED = "disconnected"
    CONNECTED = "connected"
    STREAMING = "streaming"
    ERROR = "error"


class DeviceCapability(str, Enum):
    SOFTWARE_TRIGGER = "software_trigger"
    HARDWARE_TRIGGER = "hardware_trigger"
    CONTINUOUS = "continuous"
    EXPOSURE = "exposure"
    GAIN = "gain"
    DIGITAL_IO = "digital_io"


@dataclass
class DeviceInfo:
    id: str
    name: str
    kind: str = "camera"
    vendor: str = ""
    model: str = ""
    implemented: bool = False
    capabilities: list[DeviceCapability] = field(default_factory=list)
    settings: dict[str, Any] = field(default_factory=dict)
    note: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "kind": self.kind,
            "vendor": self.vendor,
            "model": self.model,
            "implemented": self.implemented,
            "capabilities": [c.value for c in self.capabilities],
            "settings": self.settings,
            "note": self.note,
        }


class DeviceAdapter:
    """Minimum interface a device must provide.

    Subclasses only need :meth:`grab` for image sources; ``NotImplementedFeature``
    is the honest default so the UI can show "接口预留" instead of failing
    silently.
    """

    def __init__(self, info: DeviceInfo) -> None:
        self.info = info
        self.state = DeviceState.DISCONNECTED
        self.last_error: str = ""

    # -- lifecycle -------------------------------------------------------
    def connect(self, **kwargs: Any) -> DeviceState:
        raise NotImplementedFeature(f"设备 {self.info.name} 的连接接口尚未实现")

    def disconnect(self) -> DeviceState:
        self.state = DeviceState.DISCONNECTED
        return self.state

    def configure(self, **kwargs: Any) -> dict:
        self.info.settings.update({k: v for k, v in kwargs.items() if v is not None})
        return self.info.settings

    # -- data ------------------------------------------------------------
    def grab(self, **kwargs: Any) -> np.ndarray:
        raise NotImplementedFeature(f"设备 {self.info.name} 的采集接口尚未实现")

    def write_signal(self, channel: str, value: Any) -> None:
        raise NotImplementedFeature(f"设备 {self.info.name} 的信号输出接口尚未实现")

    # -- status ----------------------------------------------------------
    def status(self) -> dict:
        return {
            **self.info.to_dict(),
            "state": self.state.value,
            "lastError": self.last_error,
        }
