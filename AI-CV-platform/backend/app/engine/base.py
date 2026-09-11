"""Node SDK.

A node is a deterministic function plus metadata. Subclasses declare
``inputs`` / ``outputs`` / ``params`` and implement :meth:`Node.process`;
validation, caching, timing and visualisation are handled by the executor,
so every algorithm added later behaves the same way in the UI.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, ClassVar

import numpy as np

from app.core.errors import ValidationError
from app.engine.types import ParamSpec, PortSpec, PortType


@dataclass
class NodeContext:
    """Everything a node may need besides its inputs."""

    node_id: str
    project_id: str | None = None
    image_id: str | None = None
    image_path: str | None = None
    image_name: str = ""
    resources: dict[str, Any] = field(default_factory=dict)
    logs: list[str] = field(default_factory=list)

    def log(self, message: str) -> None:
        self.logs.append(message)


class Node:
    """Base class for all pipeline nodes."""

    type: ClassVar[str] = ""
    label: ClassVar[str] = ""
    category: ClassVar[str] = "Misc"
    description: ClassVar[str] = ""
    tags: ClassVar[tuple[str, ...]] = ()
    inputs: ClassVar[tuple[PortSpec, ...]] = ()
    outputs: ClassVar[tuple[PortSpec, ...]] = ()
    params: ClassVar[tuple[ParamSpec, ...]] = ()
    # Nodes marked deterministic=False are never served from the result cache.
    deterministic: ClassVar[bool] = True

    def process(self, inputs: dict[str, Any], params: dict[str, Any], ctx: NodeContext) -> dict[str, Any]:
        raise NotImplementedError

    # -- helpers available to subclasses ---------------------------------
    @staticmethod
    def require_image(inputs: dict[str, Any], name: str = "image") -> np.ndarray:
        image = inputs.get(name)
        if not isinstance(image, np.ndarray):
            raise ValidationError(f"输入 {name} 缺失或不是图像")
        return image

    @staticmethod
    def as_gray(image: np.ndarray) -> np.ndarray:
        import cv2

        if image.ndim == 3:
            return cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        return image

    @staticmethod
    def odd(value: int, minimum: int = 1) -> int:
        value = int(max(minimum, value))
        return value if value % 2 == 1 else value + 1

    # -- introspection ---------------------------------------------------
    @classmethod
    def spec(cls) -> dict:
        return {
            "type": cls.type,
            "label": cls.label or cls.type,
            "category": cls.category,
            "description": cls.description,
            "tags": list(cls.tags),
            "inputs": [p.to_dict() for p in cls.inputs],
            "outputs": [p.to_dict() for p in cls.outputs],
            "params": [p.to_dict() for p in cls.params],
        }

    @classmethod
    def default_params(cls) -> dict[str, Any]:
        return {p.name: p.default for p in cls.params}

    @classmethod
    def param_map(cls) -> dict[str, ParamSpec]:
        return {p.name: p for p in cls.params}

    @classmethod
    def coerce_params(cls, raw: dict[str, Any] | None) -> dict[str, Any]:
        raw = raw or {}
        resolved: dict[str, Any] = {}
        for spec in cls.params:
            resolved[spec.name] = spec.coerce(raw.get(spec.name))
        return resolved

    @classmethod
    def output_type(cls, name: str) -> PortType | None:
        for port in cls.outputs:
            if port.name == name:
                return port.type
        return None

    @classmethod
    def input_spec(cls, name: str) -> PortSpec | None:
        for port in cls.inputs:
            if port.name == name:
                return port
        return None
