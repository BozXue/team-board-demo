import { useEffect, useState } from "react";
import { Ban, Crop, Eye, HelpCircle, RotateCcw, Trash2 } from "lucide-react";
import { api } from "../../api/client";
import type { GraphNode, NodeExplanation, NodeSpec } from "../../api/types";
import { EmptyState, SectionTitle, Spinner } from "../ui";
import { ParamControl, isVisible } from "./ParamControl";
import { useApp } from "../../store/app";
import { usePipeline } from "../../store/pipeline";

const ROI_NODES: Record<string, string> = {
  rect_roi: "框选矩形 ROI",
  circle_roi: "框选圆形 ROI",
  polygon_roi: "绘制多边形 ROI",
};

export function PropertiesPanel({
  node,
  spec,
  onPickRect,
  onPickRoi,
}: {
  node: GraphNode | null;
  spec: NodeSpec | undefined;
  onPickRect?: (param: string) => void;
  onPickRoi?: (nodeType: string) => void;
}) {
  const { mode, project, reportError } = useApp();
  const { updateParams, renameNode, toggleNode, removeNodes, setTargetNode, targetNode } = usePipeline();
  const [explanation, setExplanation] = useState<NodeExplanation | null>(null);
  const [explaining, setExplaining] = useState(false);

  useEffect(() => {
    setExplanation(null);
  }, [node?.id]);

  if (!node) {
    return (
      <EmptyState
        title="未选择节点"
        hint="在画布上点选一个节点，这里会显示它的参数。不清楚参数含义时，点「参数说明」让 AI 解释。"
      />
    );
  }

  const params = spec?.params ?? [];
  const visible = params.filter(
    (param) => isVisible(param, node.params) && (mode === "engineer" || param.level === "business"),
  );

  const explain = async () => {
    if (!project) return;
    setExplaining(true);
    try {
      setExplanation(await api.explainNode(node.type, node.params));
    } catch (error) {
      reportError(error, "参数说明获取失败");
    } finally {
      setExplaining(false);
    }
  };

  const resetDefaults = () => {
    const patch: Record<string, unknown> = {};
    params.forEach((param) => {
      patch[param.name] = param.default;
    });
    updateParams(node.id, patch);
  };

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <SectionTitle
        title={spec?.label ?? node.type}
        hint={`${node.id} · ${spec?.category ?? "未知分类"}`}
        actions={
          <>
            <button
              className={`btn-subtle px-1.5 py-1 ${targetNode === node.id ? "text-warn" : ""}`}
              title="只执行到此节点（调试）"
              onClick={() => setTargetNode(targetNode === node.id ? null : node.id)}
            >
              <Eye className="h-3.5 w-3.5" />
            </button>
            <button
              className="btn-subtle px-1.5 py-1"
              title={node.enabled ? "禁用节点" : "启用节点"}
              onClick={() => toggleNode(node.id)}
            >
              <Ban className="h-3.5 w-3.5" />
            </button>
            <button className="btn-subtle px-1.5 py-1" title="恢复默认参数" onClick={resetDefaults}>
              <RotateCcw className="h-3.5 w-3.5" />
            </button>
            <button
              className="btn-subtle px-1.5 py-1 hover:text-ng"
              title="删除节点"
              onClick={() => removeNodes([node.id])}
            >
              <Trash2 className="h-3.5 w-3.5" />
            </button>
          </>
        }
      />

      <div className="scroll-y flex-1 px-2.5 py-2.5">
        {spec?.description ? (
          <div className="mb-2.5 rounded-md border border-line bg-panel-2 px-2 py-1.5 text-[11.5px] leading-relaxed text-mute">
            {spec.description}
          </div>
        ) : null}

        {ROI_NODES[node.type] && onPickRoi ? (
          <button className="btn-ghost mb-2.5 w-full" onClick={() => onPickRoi(node.type)}>
            <Crop className="h-3.5 w-3.5" /> {ROI_NODES[node.type]}
          </button>
        ) : null}

        {mode === "engineer" ? (
          <div className="mb-2.5">
            <div className="mb-1 text-[11.5px] text-mute">节点名称</div>
            <input
              className="field"
              value={node.label}
              onChange={(event) => renameNode(node.id, event.target.value)}
            />
          </div>
        ) : null}

        {visible.length === 0 ? (
          <div className="rounded-md border border-dashed border-line-solid px-2 py-4 text-center text-[11.5px] text-mute">
            {mode === "engineer" ? "该节点没有可调参数" : "该节点没有面向操作员的参数"}
          </div>
        ) : (
          visible.map((param) => (
            <ParamControl
              key={param.name}
              spec={param}
              value={node.params[param.name] ?? param.default}
              labels={(project?.labels ?? []).map((label) => label.name)}
              onChange={(value) => updateParams(node.id, { [param.name]: value })}
              onPickRect={param.type === "rect" && onPickRect ? () => onPickRect(param.name) : undefined}
            />
          ))
        )}

        <button className="btn-ghost mt-1 w-full" onClick={explain} disabled={explaining}>
          {explaining ? <Spinner /> : <HelpCircle className="h-3.5 w-3.5" />} 参数说明（AI）
        </button>

        {explanation?.params?.length ? (
          <div className="mt-2 space-y-1.5">
            {explanation.params.map((item) => (
              <div key={item.name} className="rounded-md border border-line bg-panel-2 px-2 py-1.5">
                <div className="flex items-center gap-1.5 text-[11.5px] font-medium">
                  {item.label}
                  <span className="mono text-[10px] text-mute">
                    {String(item.current)}
                    {item.range.min !== null ? ` (${item.range.min}~${item.range.max})` : ""}
                  </span>
                </div>
                <div className="mt-0.5 text-[11px] leading-relaxed text-mute">{item.description}</div>
                {item.advice ? (
                  <div className="mt-0.5 text-[11px] leading-relaxed text-brand/90">{item.advice}</div>
                ) : null}
              </div>
            ))}
          </div>
        ) : null}
      </div>
    </div>
  );
}
