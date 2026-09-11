import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Background,
  BackgroundVariant,
  Controls,
  MiniMap,
  ReactFlow,
  ReactFlowProvider,
  useEdgesState,
  useNodesState,
  useReactFlow,
  type Connection,
  type Edge,
  type NodeChange,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import {
  AlertTriangle,
  Boxes,
  Crop,
  Eraser,
  History,
  Play,
  Save,
  Zap,
} from "lucide-react";
import { api } from "../api/client";
import type { GraphNode, ImageAsset, PortType } from "../api/types";
import { ImageViewer } from "../components/ImageViewer";
import { NodeCard, type AicvNode } from "../components/pipeline/NodeCard";
import { NodeLibrary } from "../components/pipeline/NodeLibrary";
import { PropertiesPanel } from "../components/pipeline/PropertiesPanel";
import { ResultsPanel } from "../components/pipeline/ResultsPanel";
import { Badge, Modal, SectionTitle, Spinner, Toggle, formatTime } from "../components/ui";
import { useApp } from "../store/app";
import { usePipeline } from "../store/pipeline";

const PORT_COLORS: Record<PortType, string> = {
  image: "#38bdf8",
  mask: "#a78bfa",
  roi: "#fbbf24",
  regions: "#34d399",
  value: "#f472b6",
  result: "#fb923c",
  any: "#94a3b8",
};

const COMPATIBLE: Record<PortType, PortType[]> = {
  image: ["image", "any"],
  mask: ["mask", "image", "any"],
  roi: ["roi", "mask", "any"],
  regions: ["regions", "any"],
  value: ["value", "any"],
  result: ["result", "any"],
  any: ["image", "mask", "roi", "regions", "value", "result", "any"],
};

const nodeTypes = { aicv: NodeCard };

function PipelineEditor() {
  const { project, nodeSpecs, mode, toast, reportError, loadProject } = useApp();
  const projectId = project?.id ?? "";
  const {
    graph,
    issues,
    selectedId,
    imageId,
    result,
    running,
    saving,
    dirty,
    autoRun,
    targetNode,
    load,
    select,
    setImage,
    setAutoRun,
    addNode,
    removeNodes,
    addEdge,
    removeEdges,
    moveNode,
    updateParams,
    save,
    run,
  } = usePipeline();

  const { screenToFlowPosition } = useReactFlow();
  const wrapRef = useRef<HTMLDivElement>(null);
  const [images, setImages] = useState<ImageAsset[]>([]);
  const [enlarged, setEnlarged] = useState<string | null>(null);
  const [rectParam, setRectParam] = useState<string | null>(null);
  const [roiPicker, setRoiPicker] = useState<string | null>(null);
  const [versionsOpen, setVersionsOpen] = useState(false);
  const [versions, setVersions] = useState<
    { id: string; version: number; note: string; published: boolean; createdAt: string; nodeCount: number }[]
  >([]);

  const [rfNodes, setRfNodes, onNodesChange] = useNodesState<AicvNode>([]);
  const [rfEdges, setRfEdges, onEdgesChange] = useEdgesState<Edge>([]);

  // hydrate store from project
  useEffect(() => {
    if (project && usePipeline.getState().projectId !== project.id) {
      load(project.id, project.graph, project.issues);
    }
  }, [project, load]);

  // debug images
  useEffect(() => {
    if (!projectId) return;
    void api
      .listImages(projectId, { pageSize: 200 })
      .then((data) => {
        setImages(data.images);
        if (!usePipeline.getState().imageId && data.images.length) setImage(data.images[0].id);
      })
      .catch(() => undefined);
  }, [projectId, setImage]);

  // sync react-flow view from graph
  useEffect(() => {
    setRfNodes(
      graph.nodes.map((node) => ({
        id: node.id,
        type: "aicv" as const,
        position: node.position,
        selected: node.id === selectedId,
        data: {
          graphNode: node,
          spec: nodeSpecs[node.type],
          run: result?.nodes[node.id],
          isTarget: targetNode === node.id,
        },
      })),
    );
  }, [graph.nodes, nodeSpecs, result, selectedId, targetNode, setRfNodes]);

  useEffect(() => {
    setRfEdges(
      graph.edges.map((edge) => {
        const spec = nodeSpecs[graph.nodes.find((node) => node.id === edge.source)?.type ?? ""];
        const port = spec?.outputs.find((output) => output.name === edge.sourceHandle);
        return {
          id: edge.id,
          source: edge.source,
          target: edge.target,
          sourceHandle: edge.sourceHandle,
          targetHandle: edge.targetHandle,
          style: { stroke: PORT_COLORS[port?.type ?? "any"], strokeWidth: 1.6 },
          animated: running,
        };
      }),
    );
  }, [graph.edges, graph.nodes, nodeSpecs, running, setRfEdges]);

  // debounced autosave + autorun
  const dirtyRef = useRef(false);
  dirtyRef.current = dirty;
  useEffect(() => {
    if (!dirty) return;
    const timer = window.setTimeout(() => {
      void save().then(() => {
        if (usePipeline.getState().autoRun && usePipeline.getState().imageId) void run({ target: targetNode });
      });
    }, 700);
    return () => window.clearTimeout(timer);
  }, [graph, dirty, save, run, targetNode]);

  const handleNodesChange = useCallback(
    (changes: NodeChange<AicvNode>[]) => {
      onNodesChange(changes);
      changes.forEach((change) => {
        if (change.type === "position" && change.dragging === false && change.position) {
          moveNode(change.id, change.position);
        }
        if (change.type === "select" && change.selected) select(change.id);
        if (change.type === "remove") removeNodes([change.id]);
      });
    },
    [onNodesChange, moveNode, select, removeNodes],
  );

  const onConnect = useCallback(
    (connection: Connection) => {
      const sourceNode = graph.nodes.find((node) => node.id === connection.source);
      const targetNodeItem = graph.nodes.find((node) => node.id === connection.target);
      if (!sourceNode || !targetNodeItem) return;
      const sourcePort = nodeSpecs[sourceNode.type]?.outputs.find(
        (output) => output.name === connection.sourceHandle,
      );
      const targetPort = nodeSpecs[targetNodeItem.type]?.inputs.find(
        (input) => input.name === connection.targetHandle,
      );
      if (!sourcePort || !targetPort) return;
      if (!COMPATIBLE[sourcePort.type]?.includes(targetPort.type)) {
        toast(`端口类型不匹配：${sourcePort.type} → ${targetPort.type}`, "error");
        return;
      }
      addEdge({
        source: connection.source!,
        target: connection.target!,
        sourceHandle: connection.sourceHandle!,
        targetHandle: connection.targetHandle!,
      });
    },
    [graph.nodes, nodeSpecs, addEdge, toast],
  );

  const onDrop = useCallback(
    (event: React.DragEvent) => {
      event.preventDefault();
      const type = event.dataTransfer.getData("application/aicv-node");
      const spec = nodeSpecs[type];
      if (!spec) return;
      const position = screenToFlowPosition({ x: event.clientX, y: event.clientY });
      addNode(spec, { x: Math.round(position.x), y: Math.round(position.y) });
    },
    [nodeSpecs, screenToFlowPosition, addNode],
  );

  const selectedNode: GraphNode | null = useMemo(
    () => graph.nodes.find((node) => node.id === selectedId) ?? null,
    [graph.nodes, selectedId],
  );

  const activeImage = images.find((image) => image.id === imageId) ?? null;
  const errors = issues.filter((issue) => issue.level === "error");
  const warnings = issues.filter((issue) => issue.level === "warning");

  // ROI nodes store coordinates either as 0-1 ratios or pixels, so drawn shapes
  // must be converted with the source image size before landing in params.
  const roundTo = (value: number) => Math.round(value * 10000) / 10000;

  const writeRoiRect = (rect: [number, number, number, number]) => {
    if (!selectedNode || !activeImage) return;
    const relative = selectedNode.params.mode !== "absolute";
    const [x, y, w, h] = rect;
    const { width: iw, height: ih } = activeImage;
    if (selectedNode.type === "circle_roi") {
      const cx = x + w / 2;
      const cy = y + h / 2;
      const radius = Math.min(w, h) / 2;
      updateParams(
        selectedNode.id,
        relative
          ? { cx: roundTo(cx / iw), cy: roundTo(cy / ih), radius: roundTo(radius / Math.min(iw, ih)) }
          : { cx: Math.round(cx), cy: Math.round(cy), radius: Math.round(radius) },
      );
    } else {
      updateParams(
        selectedNode.id,
        relative
          ? { x: roundTo(x / iw), y: roundTo(y / ih), width: roundTo(w / iw), height: roundTo(h / ih) }
          : { x, y, width: w, height: h },
      );
    }
    setRoiPicker(null);
    toast("ROI 参数已更新", "success");
  };

  const writeRoiPolygon = (points: [number, number][]) => {
    if (!selectedNode || !activeImage || points.length < 3) return;
    const relative = selectedNode.params.mode !== "absolute";
    const { width: iw, height: ih } = activeImage;
    const converted = points.map(([x, y]) =>
      relative ? [roundTo(x / iw), roundTo(y / ih)] : [Math.round(x), Math.round(y)],
    );
    updateParams(selectedNode.id, { points: JSON.stringify(converted) });
    setRoiPicker(null);
    toast(`已写入 ${points.length} 个顶点`, "success");
  };

  const openVersions = async () => {
    if (!projectId) return;
    try {
      const data = await api.listVersions(projectId);
      setVersions(data.versions);
      setVersionsOpen(true);
    } catch (error) {
      reportError(error, "版本列表加载失败");
    }
  };

  const restore = async (versionId: string) => {
    if (!projectId) return;
    try {
      const detail = await api.restoreVersion(projectId, versionId);
      load(detail.id, detail.graph, detail.issues);
      setVersionsOpen(false);
      toast("已回滚到所选版本", "success");
      await loadProject(projectId);
    } catch (error) {
      reportError(error, "回滚失败");
    }
  };

  return (
    <div className="flex h-full min-h-0">
      {mode === "engineer" ? (
        <div className="flex w-[210px] shrink-0 flex-col border-r border-line">
          <SectionTitle title="算子库" hint={`${Object.keys(nodeSpecs).length} 个算子`} />
          <NodeLibrary
            onAdd={(spec) =>
              addNode(spec, {
                x: 80 + Math.round(Math.random() * 120),
                y: 80 + Math.round(Math.random() * 160),
              })
            }
          />
        </div>
      ) : null}

      <div className="flex min-w-0 flex-1 flex-col">
        {/* toolbar */}
        <div className="flex h-10 shrink-0 items-center gap-2 border-b border-line px-2">
          <select
            className="field w-56 py-1"
            value={imageId ?? ""}
            onChange={(event) => setImage(event.target.value || null)}
          >
            <option value="">（选择调试图片）</option>
            {images.map((image) => (
              <option key={image.id} value={image.id}>
                {image.filename}
                {image.annotation?.label ? ` [${image.annotation.label}]` : ""}
              </option>
            ))}
          </select>
          <button className="btn-primary" disabled={running} onClick={() => void run({ target: targetNode })}>
            {running ? <Spinner /> : <Play className="h-3.5 w-3.5" />} 运行
            {targetNode ? `到 ${targetNode}` : ""}
          </button>
          <Toggle checked={autoRun} onChange={setAutoRun} label="自动执行" />
          <div className="mx-1 h-4 w-px bg-line-solid" />
          <button className="btn-ghost" disabled={saving || !dirty} onClick={() => void save()}>
            {saving ? <Spinner /> : <Save className="h-3.5 w-3.5" />} {dirty ? "保存" : "已保存"}
          </button>
          <button
            className="btn-subtle"
            title="清空节点缓存后重跑"
            onClick={async () => {
              if (!projectId) return;
              await api.clearPipelineCache(projectId);
              toast("缓存已清空", "success");
              void run({ target: targetNode });
            }}
          >
            <Eraser className="h-3.5 w-3.5" /> 清缓存
          </button>
          <button className="btn-subtle" onClick={openVersions}>
            <History className="h-3.5 w-3.5" /> 版本
          </button>

          <div className="flex-1" />
          {errors.length ? (
            <Badge tone="ng">
              <AlertTriangle className="h-3 w-3" /> {errors.length} 错误
            </Badge>
          ) : null}
          {warnings.length ? <Badge tone="warn">{warnings.length} 警告</Badge> : null}
          {result ? (
            <span className="mono text-[11px] text-mute">
              {result.order.length} 节点 / {result.totalMs.toFixed(0)}ms
            </span>
          ) : null}
        </div>

        {/* canvas */}
        <div ref={wrapRef} className="relative min-h-0 flex-1" onDragOver={(event) => event.preventDefault()} onDrop={onDrop}>
          <ReactFlow
            nodes={rfNodes}
            edges={rfEdges}
            nodeTypes={nodeTypes}
            onNodesChange={handleNodesChange}
            onEdgesChange={onEdgesChange}
            onConnect={onConnect}
            onEdgesDelete={(edges) => removeEdges(edges.map((edge) => edge.id))}
            onPaneClick={() => select(null)}
            fitView
            minZoom={0.2}
            maxZoom={2}
            proOptions={{ hideAttribution: true }}
            deleteKeyCode={mode === "engineer" ? ["Backspace", "Delete"] : null}
            nodesDraggable={mode === "engineer"}
            nodesConnectable={mode === "engineer"}
          >
            <Background variant={BackgroundVariant.Dots} gap={18} size={1} color="#1e2b3d" />
            <Controls showInteractive={false} />
            <MiniMap pannable zoomable nodeColor="#243146" maskColor="rgba(10,14,21,0.7)" />
          </ReactFlow>

          {graph.nodes.length === 0 ? (
            <div className="pointer-events-none absolute inset-0 grid place-items-center">
              <div className="pointer-events-auto panel max-w-sm p-4 text-center">
                <Boxes className="mx-auto h-6 w-6 text-mute" />
                <div className="mt-2 text-[13px] font-medium">流程还是空的</div>
                <div className="mt-1 text-[12px] leading-relaxed text-mute">
                  可以到「AI 助手」页描述检测需求自动生成流程，或从左侧算子库拖入节点手动搭建。
                </div>
              </div>
            </div>
          ) : null}

          {issues.length ? (
            <div className="absolute bottom-2 left-2 max-w-md space-y-1">
              {issues.slice(0, 4).map((issue, index) => (
                <button
                  key={index}
                  onClick={() => issue.nodeId && select(issue.nodeId)}
                  className={`block w-full truncate rounded-md border px-2 py-1 text-left text-[11px] ${
                    issue.level === "error"
                      ? "border-ng/40 bg-ng/10 text-ng"
                      : "border-warn/40 bg-warn/10 text-warn"
                  }`}
                >
                  {issue.nodeId ? `${issue.nodeId}: ` : ""}
                  {issue.message}
                </button>
              ))}
            </div>
          ) : null}
        </div>

        {/* results dock */}
        <div className="h-[248px] shrink-0 border-t border-line">
          <ResultsPanel
            result={result}
            selectedId={selectedId}
            onSelectNode={select}
            onEnlarge={setEnlarged}
          />
        </div>
      </div>

      {/* properties */}
      <div className="flex w-[290px] shrink-0 flex-col border-l border-line">
        <PropertiesPanel
          node={selectedNode}
          spec={selectedNode ? nodeSpecs[selectedNode.type] : undefined}
          onPickRect={(param) => {
            if (!activeImage) {
              toast("请先选择调试图片", "error");
              return;
            }
            setRectParam(param);
          }}
          onPickRoi={(nodeType) => {
            if (!activeImage) {
              toast("请先选择调试图片", "error");
              return;
            }
            setRoiPicker(nodeType);
          }}
        />
      </div>

      <Modal open={Boolean(enlarged)} title="中间结果" width="max-w-4xl" onClose={() => setEnlarged(null)}>
        <div className="h-[70vh]">
          <ImageViewer src={enlarged} className="h-full" showProbe />
        </div>
      </Modal>

      <Modal
        open={Boolean(rectParam)}
        title="在图上框选区域"
        width="max-w-4xl"
        onClose={() => setRectParam(null)}
      >
        <div className="mb-2 flex items-center gap-2 text-[12px] text-mute">
          <Crop className="h-3.5 w-3.5" /> 拖动鼠标框选，松开后自动写入参数
        </div>
        <div className="h-[65vh]">
          <ImageViewer
            src={activeImage?.previewUrl ?? null}
            tool="rect"
            className="h-full"
            onCreateRect={(rect) => {
              if (selectedNode && rectParam) updateParams(selectedNode.id, { [rectParam]: rect });
              setRectParam(null);
              toast(`已写入区域 ${rect.join(", ")}`, "success");
            }}
          />
        </div>
      </Modal>

      <Modal
        open={Boolean(roiPicker)}
        title={roiPicker === "polygon_roi" ? "绘制多边形 ROI" : "框选 ROI"}
        width="max-w-4xl"
        onClose={() => setRoiPicker(null)}
      >
        <div className="mb-2 text-[12px] text-mute">
          {roiPicker === "polygon_roi"
            ? "依次点击顶点，Enter 或双击闭合。坐标会按当前坐标模式写入参数。"
            : "拖动鼠标框选区域，松开后写入参数。圆形 ROI 取框的内切圆。"}
        </div>
        <div className="h-[65vh]">
          <ImageViewer
            src={activeImage?.previewUrl ?? null}
            tool={roiPicker === "polygon_roi" ? "polygon" : "rect"}
            className="h-full"
            onCreateRect={writeRoiRect}
            onCreateShape={(shape) => writeRoiPolygon(shape.points)}
          />
        </div>
      </Modal>

      <Modal open={versionsOpen} title="流程版本" onClose={() => setVersionsOpen(false)}>
        <div className="space-y-1.5">
          {versions.length === 0 ? (
            <div className="text-[12.5px] text-mute">还没有保存过版本，点右上角「发布」会生成第一个版本。</div>
          ) : (
            versions.map((version) => (
              <div
                key={version.id}
                className="flex items-center gap-2 rounded-md border border-line bg-panel-2 px-2 py-1.5 text-[12px]"
              >
                <span className="mono text-brand">v{version.version}</span>
                {version.published ? <Badge tone="ok">发布中</Badge> : null}
                <span className="flex-1 truncate text-mute">{version.note || "无说明"}</span>
                <span className="text-[11px] text-mute/70">{formatTime(version.createdAt)}</span>
                <button className="btn-ghost px-2 py-0.5 text-[11px]" onClick={() => void restore(version.id)}>
                  回滚
                </button>
              </div>
            ))
          )}
        </div>
      </Modal>

      {!activeImage && images.length === 0 ? (
        <div className="pointer-events-none absolute right-4 bottom-4 rounded-md border border-warn/40 bg-warn/10 px-2.5 py-1.5 text-[11.5px] text-warn">
          <Zap className="mr-1 inline h-3 w-3" /> 项目里还没有图片，先到「数据」页导入
        </div>
      ) : null}
    </div>
  );
}

export default function PipelinePage() {
  return (
    <ReactFlowProvider>
      <PipelineEditor />
    </ReactFlowProvider>
  );
}
