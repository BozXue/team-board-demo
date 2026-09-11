"""Deterministic DAG execution with per-node caching, timing and previews.

The executor is the part of the platform every other feature funnels through:
single-node debugging, live preview while dragging a slider, batch test and
Runtime all call :meth:`PipelineExecutor.run` with different options.
"""

from __future__ import annotations

import hashlib
import json
import time
import traceback
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from app.core.errors import PlatformError
from app.engine import render
from app.engine.base import NodeContext
from app.engine.graph import Graph, GraphNode
from app.engine.types import (
    Judgement,
    PortType,
    Regions,
    Roi,
    Value,
    describe_value,
)
from app.utils.imageio import fit_within, save_jpeg, save_png

PREVIEW_MAX_SIDE = 900


class ResultCache:
    """Bounded LRU of node outputs, keyed by a structural signature."""

    def __init__(self, max_items: int = 256) -> None:
        self._store: OrderedDict[str, dict[str, Any]] = OrderedDict()
        self.max_items = max_items
        self.hits = 0
        self.misses = 0

    def get(self, key: str) -> dict[str, Any] | None:
        if key in self._store:
            self._store.move_to_end(key)
            self.hits += 1
            return self._store[key]
        self.misses += 1
        return None

    def put(self, key: str, outputs: dict[str, Any]) -> None:
        self._store[key] = outputs
        self._store.move_to_end(key)
        while len(self._store) > self.max_items:
            self._store.popitem(last=False)

    def clear(self) -> None:
        self._store.clear()


class ArtifactWriter:
    """Writes node previews under a directory exposed by ``/api/artifacts``."""

    def __init__(self, root: Path, url_prefix: str, max_side: int = PREVIEW_MAX_SIDE) -> None:
        self.root = Path(root)
        self.url_prefix = url_prefix.rstrip("/")
        self.max_side = max_side
        # Preview filenames are stable (node + port) so runs overwrite instead of
        # piling up; the version token keeps the browser from serving a stale one.
        self.version = int(time.time() * 1000)

    def write(self, name: str, image: np.ndarray, lossless: bool = False) -> dict:
        preview = fit_within(image, self.max_side)
        safe = "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in name)
        if lossless or preview.ndim == 2:
            filename = f"{safe}.png"
            save_png(self.root / filename, preview)
        else:
            filename = f"{safe}.jpg"
            save_jpeg(self.root / filename, preview)
        return {
            "url": f"{self.url_prefix}/{filename}?v={self.version}",
            "width": int(preview.shape[1]),
            "height": int(preview.shape[0]),
        }


@dataclass
class NodeRunInfo:
    node_id: str
    node_type: str
    status: str = "pending"
    duration_ms: float = 0.0
    cached: bool = False
    error: str | None = None
    params: dict[str, Any] = field(default_factory=dict)
    inputs: dict[str, dict] = field(default_factory=dict)
    outputs: dict[str, dict] = field(default_factory=dict)
    logs: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "nodeId": self.node_id,
            "nodeType": self.node_type,
            "status": self.status,
            "durationMs": round(self.duration_ms, 2),
            "cached": self.cached,
            "error": self.error,
            "params": self.params,
            "inputs": self.inputs,
            "outputs": self.outputs,
            "logs": self.logs,
        }


@dataclass
class ExecutionResult:
    nodes: dict[str, NodeRunInfo] = field(default_factory=dict)
    order: list[str] = field(default_factory=list)
    total_ms: float = 0.0
    verdict: str = "UNKNOWN"
    reason: str = ""
    measurements: dict[str, Any] = field(default_factory=dict)
    outputs: dict[str, Any] = field(default_factory=dict)
    artifacts: dict[str, str] = field(default_factory=dict)
    errors: list[dict] = field(default_factory=list)
    cache_hits: int = 0
    cache_misses: int = 0

    @property
    def ok(self) -> bool:
        return not self.errors

    def to_dict(self) -> dict:
        return {
            "order": self.order,
            "totalMs": round(self.total_ms, 2),
            "verdict": self.verdict,
            "reason": self.reason,
            "measurements": self.measurements,
            "artifacts": self.artifacts,
            "errors": self.errors,
            "cache": {"hits": self.cache_hits, "misses": self.cache_misses},
            "nodes": {nid: info.to_dict() for nid, info in self.nodes.items()},
        }


class PipelineExecutor:
    def __init__(
        self,
        graph: Graph,
        artifacts: ArtifactWriter | None = None,
        cache: ResultCache | None = None,
        context: dict[str, Any] | None = None,
        resources: dict[str, Any] | None = None,
    ) -> None:
        self.graph = graph
        self.artifacts = artifacts
        self.cache = cache if cache is not None else ResultCache()
        self.context = context or {}
        self.resources = resources or {}

    # -- signatures ------------------------------------------------------
    def _source_signature(self) -> str:
        parts = [str(self.context.get("image_id") or ""), str(self.context.get("image_path") or "")]
        path = self.context.get("image_path")
        if path:
            try:
                stat = Path(path).stat()
                parts.append(f"{stat.st_mtime_ns}:{stat.st_size}")
            except OSError:
                pass
        return "|".join(parts)

    def _signature(self, node_id: str, params: dict, node_sigs: dict[str, str]) -> str:
        node = self.graph.node(node_id)
        payload = {
            "type": node.type,
            "params": params,
            "source": self._source_signature(),
            "inputs": sorted(
                (e.target_handle, node_sigs.get(e.source, "?"), e.source_handle)
                for e in self.graph.incoming(node_id)
            ),
        }
        blob = json.dumps(payload, sort_keys=True, default=str).encode()
        return hashlib.sha1(blob).hexdigest()[:20]

    # -- execution -------------------------------------------------------
    def run(
        self,
        target: str | None = None,
        preview: bool = True,
        preview_nodes: set[str] | None = None,
        stop_on_error: bool = False,
    ) -> ExecutionResult:
        """Execute the graph (or just the ancestors of ``target``)."""
        result = ExecutionResult()
        selected = self.graph.ancestors(target) if target else None
        order = self.graph.topological_order(selected)
        node_map = self.graph.node_map
        active = [nid for nid in order if node_map[nid].enabled]
        result.order = active

        values: dict[tuple[str, str], Any] = {}
        node_sigs: dict[str, str] = {}
        failed: set[str] = set()
        started = time.perf_counter()

        for node_id in active:
            node = node_map[node_id]
            info = NodeRunInfo(node_id=node_id, node_type=node.type)
            result.nodes[node_id] = info

            upstream_failed = [
                e.source for e in self.graph.incoming(node_id)
                if e.source in failed or (e.source in active and (e.source, e.source_handle) not in values)
            ]
            if upstream_failed:
                info.status = "skipped"
                info.error = f"上游节点未产生输出: {', '.join(sorted(set(upstream_failed)))}"
                failed.add(node_id)
                continue

            try:
                node_cls = node.cls
                params = node_cls.coerce_params(node.params)
                info.params = params
                inputs = self._collect_inputs(node, values)
                info.inputs = {k: describe_value(v) for k, v in inputs.items()}

                signature = self._signature(node_id, params, node_sigs)
                node_sigs[node_id] = signature

                cached = self.cache.get(signature) if node_cls.deterministic else None
                if cached is not None:
                    outputs = cached
                    info.cached = True
                    info.duration_ms = 0.0
                else:
                    ctx = NodeContext(
                        node_id=node_id,
                        project_id=self.context.get("project_id"),
                        image_id=self.context.get("image_id"),
                        image_path=self.context.get("image_path"),
                        image_name=self.context.get("image_name", ""),
                        resources=self.resources,
                    )
                    tick = time.perf_counter()
                    outputs = node_cls().process(inputs, params, ctx) or {}
                    info.duration_ms = (time.perf_counter() - tick) * 1000.0
                    info.logs = ctx.logs
                    if node_cls.deterministic:
                        self.cache.put(signature, outputs)

                for port in node_cls.outputs:
                    if port.name in outputs:
                        values[(node_id, port.name)] = outputs[port.name]

                info.status = "success"
                want_preview = preview and (preview_nodes is None or node_id in preview_nodes)
                info.outputs = self._describe_outputs(node, outputs, inputs, want_preview)
                self._collect_result(node, outputs, result)

            except Exception as exc:  # noqa: BLE001 - one node must not kill the run
                info.status = "error"
                info.error = str(exc) if isinstance(exc, PlatformError) else f"{type(exc).__name__}: {exc}"
                info.logs.append(traceback.format_exc(limit=3))
                failed.add(node_id)
                result.errors.append(
                    {"nodeId": node_id, "nodeType": node.type, "message": info.error}
                )
                if stop_on_error:
                    break

        result.total_ms = (time.perf_counter() - started) * 1000.0
        result.cache_hits = self.cache.hits
        result.cache_misses = self.cache.misses
        if result.verdict == "UNKNOWN" and result.errors:
            result.verdict = "ERROR"
        return result

    # -- helpers ---------------------------------------------------------
    def _collect_inputs(self, node: GraphNode, values: dict[tuple[str, str], Any]) -> dict[str, Any]:
        inputs: dict[str, Any] = {}
        for edge in self.graph.incoming(node.id):
            if (edge.source, edge.source_handle) not in values:
                continue
            value = values[(edge.source, edge.source_handle)]
            spec = node.cls.input_spec(edge.target_handle)
            inputs[edge.target_handle] = self._adapt(value, spec.type if spec else PortType.ANY)
        return inputs

    @staticmethod
    def _adapt(value: Any, target: PortType) -> Any:
        """Apply the implicit conversions declared in ``graph._COMPATIBLE``."""
        if target == PortType.IMAGE and isinstance(value, np.ndarray):
            return value
        if target == PortType.MASK and isinstance(value, Roi):
            return (value.mask.astype(np.uint8)) * 255
        if target == PortType.IMAGE and isinstance(value, Roi):
            return (value.mask.astype(np.uint8)) * 255
        return value

    def _base_image_for(self, inputs: dict[str, Any], outputs: dict[str, Any]) -> np.ndarray | None:
        for source in (inputs, outputs):
            for value in source.values():
                if isinstance(value, np.ndarray) and value.ndim in (2, 3):
                    return value
        return None

    def _describe_outputs(
        self, node: GraphNode, outputs: dict[str, Any], inputs: dict[str, Any], want_preview: bool
    ) -> dict[str, dict]:
        described: dict[str, dict] = {}
        base = self._base_image_for(inputs, outputs)
        for port in node.cls.outputs:
            if port.name not in outputs:
                continue
            value = outputs[port.name]
            entry: dict[str, Any] = {"type": port.type.value, "summary": describe_value(value)}
            if want_preview and self.artifacts is not None:
                image, kind = render.preview_for(value, port.type, base)
                if image is not None:
                    entry["preview"] = self.artifacts.write(f"{node.id}__{port.name}", image)
                    entry["previewKind"] = kind
            described[port.name] = entry
        return described

    def _collect_result(self, node: GraphNode, outputs: dict[str, Any], result: ExecutionResult) -> None:
        """Promote Judge/Measure/Output payloads into the run-level result."""
        for port in node.cls.outputs:
            value = outputs.get(port.name)
            if isinstance(value, Judgement):
                # The last judgement in topological order wins; NG is sticky.
                if result.verdict != "NG":
                    result.verdict = value.verdict
                    result.reason = value.reason
                result.measurements.update(value.measurements)
            elif isinstance(value, Value):
                key = value.name or f"{node.id}.{port.name}"
                result.measurements[key] = value.value
            elif isinstance(value, Regions):
                result.measurements.setdefault(f"{node.id}.count", len(value))
        payload = outputs.get("report_payload")
        if isinstance(payload, dict):
            result.outputs[node.id] = payload
            saved = payload.get("savedPath")
            if saved:
                result.artifacts[node.id] = str(saved)
