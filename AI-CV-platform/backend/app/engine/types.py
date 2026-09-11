"""Pipeline data contracts.

Every node declares its input/output ports with one of the ``PortType`` values
below, so the graph can be validated before anything is executed and new
algorithms can only enter the platform through this contract.

Runtime representation of each port type:

==========  ==========================================================
IMAGE       ``np.ndarray`` uint8, ``HxW`` (gray) or ``HxWx3`` (BGR)
MASK        ``np.ndarray`` uint8, ``HxW``, values 0/255
ROI         :class:`Roi` - binary region plus its bounding box
REGIONS     :class:`Regions` - contours with geometric properties
VALUE       :class:`Value` - a scalar measurement with a unit
RESULT      :class:`Judgement` - OK/NG verdict with reason + measurements
==========  ==========================================================
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Literal

import numpy as np


class PortType(str, Enum):
    IMAGE = "image"
    MASK = "mask"
    ROI = "roi"
    REGIONS = "regions"
    VALUE = "value"
    RESULT = "result"
    ANY = "any"


ParamLevel = Literal["engineer", "business", "locked"]
ParamType = Literal["int", "float", "bool", "str", "enum", "text", "rect", "color", "label"]


@dataclass(slots=True)
class PortSpec:
    name: str
    type: PortType
    label: str = ""
    required: bool = True
    description: str = ""

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "type": self.type.value,
            "label": self.label or self.name,
            "required": self.required,
            "description": self.description,
        }


@dataclass(slots=True)
class ParamSpec:
    """Declaration of one node parameter.

    ``level`` drives the double-mode UI: ``engineer`` parameters are hidden in
    User Mode, ``business`` parameters are the ones exposed to operators after
    publishing, ``locked`` parameters are read-only outside Developer Mode.
    """

    name: str
    type: ParamType
    default: Any = None
    label: str = ""
    min: float | None = None
    max: float | None = None
    step: float | None = None
    options: list[Any] = field(default_factory=list)
    level: ParamLevel = "engineer"
    unit: str = ""
    description: str = ""
    # Only show this parameter when another parameter has one of these values.
    depends_on: tuple[str, tuple[Any, ...]] | None = None

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "type": self.type,
            "default": self.default,
            "label": self.label or self.name,
            "min": self.min,
            "max": self.max,
            "step": self.step,
            "options": self.options,
            "level": self.level,
            "unit": self.unit,
            "description": self.description,
            "dependsOn": (
                {"param": self.depends_on[0], "values": list(self.depends_on[1])}
                if self.depends_on
                else None
            ),
        }

    def coerce(self, value: Any) -> Any:
        """Validate + clamp a raw (JSON) parameter value."""
        from app.core.errors import ValidationError

        if value is None:
            return self.default
        try:
            if self.type == "int":
                value = int(round(float(value)))
            elif self.type == "float":
                value = float(value)
            elif self.type == "bool":
                value = bool(value) if not isinstance(value, str) else value.lower() in {"1", "true", "yes"}
            elif self.type in {"str", "text", "color", "label"}:
                value = str(value)
            elif self.type == "enum":
                if self.options and value not in self.options:
                    raise ValidationError(
                        f"参数 {self.name} 取值 {value!r} 不在允许范围 {self.options}"
                    )
        except (TypeError, ValueError) as exc:
            raise ValidationError(f"参数 {self.name} 类型非法: {value!r}") from exc

        if self.type in {"int", "float"}:
            if self.min is not None and value < self.min:
                value = type(value)(self.min)
            if self.max is not None and value > self.max:
                value = type(value)(self.max)
        return value


@dataclass
class Roi:
    """A region of interest: boolean mask + bounding box (x, y, w, h)."""

    mask: np.ndarray
    bbox: tuple[int, int, int, int]
    shape: tuple[int, int]
    kind: str = "rect"

    @property
    def area(self) -> int:
        return int(np.count_nonzero(self.mask))


@dataclass
class Region:
    index: int
    area: float
    centroid: tuple[float, float]
    bbox: tuple[int, int, int, int]
    contour: np.ndarray
    perimeter: float = 0.0
    circularity: float = 0.0
    solidity: float = 0.0
    aspect_ratio: float = 1.0
    equivalent_diameter: float = 0.0
    mean_intensity: float | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "index": self.index,
            "area": round(float(self.area), 2),
            "centroid": [round(float(self.centroid[0]), 1), round(float(self.centroid[1]), 1)],
            "bbox": [int(v) for v in self.bbox],
            "perimeter": round(float(self.perimeter), 2),
            "circularity": round(float(self.circularity), 3),
            "solidity": round(float(self.solidity), 3),
            "aspectRatio": round(float(self.aspect_ratio), 3),
            "equivalentDiameter": round(float(self.equivalent_diameter), 2),
            "meanIntensity": (
                None if self.mean_intensity is None else round(float(self.mean_intensity), 2)
            ),
            **self.extra,
        }


@dataclass
class Regions:
    items: list[Region]
    shape: tuple[int, int]

    def __len__(self) -> int:
        return len(self.items)

    def to_dict(self) -> dict:
        return {
            "count": len(self.items),
            "shape": [int(self.shape[0]), int(self.shape[1])],
            "items": [r.to_dict() for r in self.items],
        }


@dataclass
class Value:
    value: float
    name: str = "value"
    unit: str = "px"
    values: list[float] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "value": None if self.value is None else round(float(self.value), 4),
            "unit": self.unit,
            "values": [round(float(v), 4) for v in self.values[:200]],
            "count": len(self.values),
        }


@dataclass
class Judgement:
    verdict: str = "OK"
    reason: str = ""
    measurements: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.verdict == "OK"

    def to_dict(self) -> dict:
        return {"verdict": self.verdict, "reason": self.reason, "measurements": self.measurements}


def is_gray(image: np.ndarray) -> bool:
    return image.ndim == 2


def describe_value(value: Any) -> dict:
    """Small JSON summary of any port payload (used by the debug panel)."""
    if isinstance(value, np.ndarray):
        return {
            "shape": list(value.shape),
            "dtype": str(value.dtype),
            "min": float(value.min()) if value.size else 0.0,
            "max": float(value.max()) if value.size else 0.0,
            "mean": round(float(value.mean()), 3) if value.size else 0.0,
        }
    if isinstance(value, Roi):
        return {"kind": value.kind, "bbox": list(value.bbox), "area": value.area}
    if isinstance(value, (Regions, Value, Judgement)):
        return value.to_dict()
    if isinstance(value, (int, float, str, bool)) or value is None:
        return {"value": value}
    return {"repr": repr(value)[:200]}
