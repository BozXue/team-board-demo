"""Device registry used by the API and by the Camera node."""

from __future__ import annotations

from typing import Any

import numpy as np

from app.core.errors import NotFoundError
from app.services.devices.adapters import default_adapters
from app.services.devices.base import DeviceAdapter, DeviceState


class DeviceManager:
    def __init__(self) -> None:
        self._adapters: dict[str, DeviceAdapter] = {a.info.id: a for a in default_adapters()}

    def register(self, adapter: DeviceAdapter) -> None:
        self._adapters[adapter.info.id] = adapter

    def list_devices(self) -> list[dict]:
        return [adapter.status() for adapter in self._adapters.values()]

    def get(self, device_id: str) -> DeviceAdapter:
        adapter = self._adapters.get(device_id)
        if adapter is None:
            raise NotFoundError(f"设备不存在: {device_id}")
        return adapter

    def connect(self, device_id: str, **kwargs: Any) -> dict:
        adapter = self.get(device_id)
        try:
            adapter.connect(**kwargs)
        except Exception as exc:
            adapter.state = DeviceState.ERROR
            adapter.last_error = str(exc)
            raise
        return adapter.status()

    def disconnect(self, device_id: str) -> dict:
        adapter = self.get(device_id)
        adapter.disconnect()
        return adapter.status()

    def configure(self, device_id: str, settings: dict) -> dict:
        adapter = self.get(device_id)
        adapter.configure(**settings)
        return adapter.status()

    def grab(self, device_id: str, **kwargs: Any) -> np.ndarray:
        adapter = self.get(device_id)
        try:
            return adapter.grab(**kwargs)
        except Exception as exc:
            adapter.last_error = str(exc)
            raise


device_manager = DeviceManager()
