"""Device layer (reserved).

The platform core only depends on the :class:`DeviceAdapter` contract below.
Real hardware (GigE/USB3 cameras, PLC, robots, MES) is added as adapters
without touching the pipeline engine — the folder-simulated camera implements
the same contract so acquisition flows can be built and tested today.
"""

from __future__ import annotations

from app.services.devices.base import (
    DeviceAdapter,
    DeviceCapability,
    DeviceInfo,
    DeviceState,
)
from app.services.devices.manager import DeviceManager, device_manager

__all__ = [
    "DeviceAdapter",
    "DeviceCapability",
    "DeviceInfo",
    "DeviceState",
    "DeviceManager",
    "device_manager",
]
