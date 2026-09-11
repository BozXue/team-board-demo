"""Node registry: the whitelist the AI Copilot is allowed to plan against."""

from __future__ import annotations

from app.core.errors import NotFoundError
from app.engine.base import Node

_REGISTRY: dict[str, type[Node]] = {}

CATEGORY_ORDER = [
    "Input",
    "ROI",
    "Enhance",
    "Filter",
    "Segmentation",
    "Morphology",
    "Feature",
    "Measure",
    "Judge",
    "AI",
    "Domain",
    "Output",
]


def register(cls: type[Node]) -> type[Node]:
    if not cls.type:
        raise ValueError(f"{cls.__name__} 缺少 type 定义")
    if cls.type in _REGISTRY:
        raise ValueError(f"节点类型重复注册: {cls.type}")
    _REGISTRY[cls.type] = cls
    return cls


def get_node_class(node_type: str) -> type[Node]:
    try:
        return _REGISTRY[node_type]
    except KeyError as exc:
        raise NotFoundError(f"未注册的节点类型: {node_type}") from exc


def has_node(node_type: str) -> bool:
    return node_type in _REGISTRY


def all_node_classes() -> dict[str, type[Node]]:
    return dict(_REGISTRY)


def node_types() -> list[str]:
    return sorted(_REGISTRY)


def catalog() -> list[dict]:
    """Node library grouped by category, ordered for the UI palette."""
    groups: dict[str, list[dict]] = {}
    for cls in _REGISTRY.values():
        groups.setdefault(cls.category, []).append(cls.spec())

    def category_key(name: str) -> tuple[int, str]:
        return (CATEGORY_ORDER.index(name) if name in CATEGORY_ORDER else 99, name)

    return [
        {"category": name, "nodes": sorted(groups[name], key=lambda s: s["label"])}
        for name in sorted(groups, key=category_key)
    ]


def load_nodes() -> None:
    """Import every node module so the decorators run."""
    from app.engine import nodes  # noqa: F401

    nodes.load_all()
