"""Pipeline graph: parsing, validation and topological ordering."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.core.errors import ValidationError
from app.engine.base import Node
from app.engine.registry import get_node_class, has_node
from app.engine.types import PortType

# Implicit conversions the executor is allowed to perform: a mask is a valid
# grayscale image, an ROI carries a mask, and everything fits an ANY port.
_COMPATIBLE: dict[PortType, set[PortType]] = {
    PortType.IMAGE: {PortType.IMAGE, PortType.MASK},
    PortType.MASK: {PortType.MASK, PortType.ROI},
    PortType.ROI: {PortType.ROI},
    PortType.REGIONS: {PortType.REGIONS},
    PortType.VALUE: {PortType.VALUE},
    PortType.RESULT: {PortType.RESULT},
    PortType.ANY: set(PortType),
}


def types_compatible(source: PortType, target: PortType) -> bool:
    if target == PortType.ANY or source == PortType.ANY:
        return True
    return source in _COMPATIBLE.get(target, {target})


@dataclass
class GraphNode:
    id: str
    type: str
    label: str = ""
    params: dict[str, Any] = field(default_factory=dict)
    position: dict[str, float] = field(default_factory=dict)
    enabled: bool = True

    @property
    def cls(self) -> type[Node]:
        return get_node_class(self.type)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "type": self.type,
            "label": self.label,
            "params": self.params,
            "position": self.position or {"x": 0, "y": 0},
            "enabled": self.enabled,
        }


@dataclass
class GraphEdge:
    id: str
    source: str
    target: str
    source_handle: str
    target_handle: str

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "source": self.source,
            "target": self.target,
            "sourceHandle": self.source_handle,
            "targetHandle": self.target_handle,
        }


@dataclass
class Graph:
    nodes: list[GraphNode] = field(default_factory=list)
    edges: list[GraphEdge] = field(default_factory=list)

    # -- construction ----------------------------------------------------
    @classmethod
    def from_dict(cls, data: dict | None) -> "Graph":
        data = data or {}
        nodes: list[GraphNode] = []
        for raw in data.get("nodes") or []:
            node_id = str(raw.get("id") or "").strip()
            node_type = str(raw.get("type") or "").strip()
            if not node_id or not node_type:
                raise ValidationError("节点缺少 id 或 type", {"node": raw})
            nodes.append(
                GraphNode(
                    id=node_id,
                    type=node_type,
                    label=str(raw.get("label") or ""),
                    params=dict(raw.get("params") or {}),
                    position=dict(raw.get("position") or {}),
                    enabled=bool(raw.get("enabled", True)),
                )
            )
        edges: list[GraphEdge] = []
        for i, raw in enumerate(data.get("edges") or []):
            edges.append(
                GraphEdge(
                    id=str(raw.get("id") or f"e{i}"),
                    source=str(raw.get("source") or ""),
                    target=str(raw.get("target") or ""),
                    source_handle=str(raw.get("sourceHandle") or raw.get("source_handle") or ""),
                    target_handle=str(raw.get("targetHandle") or raw.get("target_handle") or ""),
                )
            )
        return cls(nodes=nodes, edges=edges)

    def to_dict(self) -> dict:
        return {"nodes": [n.to_dict() for n in self.nodes], "edges": [e.to_dict() for e in self.edges]}

    # -- lookup ----------------------------------------------------------
    @property
    def node_map(self) -> dict[str, GraphNode]:
        return {n.id: n for n in self.nodes}

    def node(self, node_id: str) -> GraphNode:
        node = self.node_map.get(node_id)
        if node is None:
            raise ValidationError(f"节点不存在: {node_id}")
        return node

    def incoming(self, node_id: str) -> list[GraphEdge]:
        return [e for e in self.edges if e.target == node_id]

    def outgoing(self, node_id: str) -> list[GraphEdge]:
        return [e for e in self.edges if e.source == node_id]

    # -- validation ------------------------------------------------------
    def validate(self, strict: bool = True) -> list[dict]:
        """Return a list of issues; raise on fatal ones when ``strict``."""
        issues: list[dict] = []
        seen: set[str] = set()
        for node in self.nodes:
            if node.id in seen:
                issues.append({"level": "error", "nodeId": node.id, "message": "节点 id 重复"})
            seen.add(node.id)
            if not has_node(node.type):
                issues.append(
                    {"level": "error", "nodeId": node.id, "message": f"未注册的节点类型 {node.type}"}
                )

        for edge in self.edges:
            if edge.source not in seen or edge.target not in seen:
                issues.append({"level": "error", "edgeId": edge.id, "message": "连线端点不存在"})
                continue
            src_node, dst_node = self.node(edge.source), self.node(edge.target)
            if not (has_node(src_node.type) and has_node(dst_node.type)):
                continue
            src_type = src_node.cls.output_type(edge.source_handle)
            dst_spec = dst_node.cls.input_spec(edge.target_handle)
            if src_type is None:
                issues.append(
                    {"level": "error", "edgeId": edge.id,
                     "message": f"{src_node.type} 没有输出端口 {edge.source_handle}"}
                )
            elif dst_spec is None:
                issues.append(
                    {"level": "error", "edgeId": edge.id,
                     "message": f"{dst_node.type} 没有输入端口 {edge.target_handle}"}
                )
            elif not types_compatible(src_type, dst_spec.type):
                issues.append(
                    {"level": "error", "edgeId": edge.id,
                     "message": f"数据类型不匹配: {src_type.value} → {dst_spec.type.value}"}
                )

        # A required input port may be fed by at most one edge and must be fed.
        for node in self.nodes:
            if not has_node(node.type) or not node.enabled:
                continue
            fed: dict[str, int] = {}
            for edge in self.incoming(node.id):
                fed[edge.target_handle] = fed.get(edge.target_handle, 0) + 1
            for handle, count in fed.items():
                if count > 1:
                    issues.append(
                        {"level": "error", "nodeId": node.id,
                         "message": f"输入端口 {handle} 被重复连接"}
                    )
            for port in node.cls.inputs:
                if port.required and port.name not in fed:
                    issues.append(
                        {"level": "warning", "nodeId": node.id,
                         "message": f"必填输入 {port.label or port.name} 未连接"}
                    )

        try:
            self.topological_order()
        except ValidationError as exc:
            issues.append({"level": "error", "message": exc.message})

        if strict:
            fatal = [i for i in issues if i["level"] == "error"]
            if fatal:
                raise ValidationError(f"Pipeline 校验失败: {fatal[0]['message']}", {"issues": issues})
        return issues

    # -- ordering --------------------------------------------------------
    def topological_order(self, node_ids: set[str] | None = None) -> list[str]:
        ids = {n.id for n in self.nodes} if node_ids is None else set(node_ids)
        indegree = {nid: 0 for nid in ids}
        children: dict[str, list[str]] = {nid: [] for nid in ids}
        for edge in self.edges:
            if edge.source in ids and edge.target in ids:
                indegree[edge.target] += 1
                children[edge.source].append(edge.target)

        # Stable order: keep the author's node order for independent branches.
        order_hint = {n.id: i for i, n in enumerate(self.nodes)}
        ready = sorted([nid for nid, d in indegree.items() if d == 0], key=lambda n: order_hint.get(n, 0))
        result: list[str] = []
        while ready:
            current = ready.pop(0)
            result.append(current)
            for child in children[current]:
                indegree[child] -= 1
                if indegree[child] == 0:
                    ready.append(child)
            ready.sort(key=lambda n: order_hint.get(n, 0))

        if len(result) != len(ids):
            cyclic = sorted(ids - set(result))
            raise ValidationError(f"Pipeline 中存在环路: {', '.join(cyclic)}")
        return result

    def ancestors(self, node_id: str) -> set[str]:
        """The node itself plus everything it (transitively) depends on."""
        parents: dict[str, list[str]] = {}
        for edge in self.edges:
            parents.setdefault(edge.target, []).append(edge.source)
        seen: set[str] = set()
        stack = [node_id]
        while stack:
            current = stack.pop()
            if current in seen:
                continue
            seen.add(current)
            stack.extend(parents.get(current, []))
        return seen

    def terminal_nodes(self) -> list[str]:
        with_out = {e.source for e in self.edges}
        return [n.id for n in self.nodes if n.id not in with_out]
