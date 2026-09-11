import { Handle, Position, type Node, type NodeProps } from "@xyflow/react";
import { AlertTriangle, Ban, CheckCircle2, Loader2 } from "lucide-react";
import type { GraphNode, NodeRunInfo, NodeSpec, PortType } from "../../api/types";

export interface AicvNodeData extends Record<string, unknown> {
  graphNode: GraphNode;
  spec: NodeSpec | undefined;
  run: NodeRunInfo | undefined;
  isTarget: boolean;
}

export type AicvNode = Node<AicvNodeData, "aicv">;

const PORT_COLORS: Record<PortType, string> = {
  image: "#38bdf8",
  mask: "#a78bfa",
  roi: "#fbbf24",
  regions: "#34d399",
  value: "#f472b6",
  result: "#fb923c",
  any: "#94a3b8",
};

export function NodeCard({ data, selected }: NodeProps<AicvNode>) {
  const { graphNode, spec, run, isTarget } = data;
  const inputs = spec?.inputs ?? [];
  const outputs = spec?.outputs ?? [];
  const rows = Math.max(inputs.length, outputs.length);
  const disabled = !graphNode.enabled;

  const status = run?.status;
  const border = selected
    ? "border-brand"
    : status === "error"
      ? "border-ng/70"
      : isTarget
        ? "border-warn/70"
        : "border-line-solid";

  return (
    <div
      className={`w-[200px] rounded-lg border bg-panel shadow-lg transition ${border} ${
        disabled ? "opacity-45" : ""
      }`}
    >
      <div className="flex items-center gap-1.5 rounded-t-lg border-b border-line bg-panel-2 px-2 py-1.5">
        <span
          className="h-2 w-2 shrink-0 rounded-full"
          style={{ background: spec ? PORT_COLORS[spec.outputs[0]?.type ?? "any"] : "#64748b" }}
        />
        <div className="min-w-0 flex-1">
          <div className="truncate text-[12px] font-medium leading-tight">{graphNode.label}</div>
          <div className="mono truncate text-[9.5px] leading-tight text-mute">{graphNode.id}</div>
        </div>
        {status === "error" ? (
          <AlertTriangle className="h-3.5 w-3.5 shrink-0 text-ng" />
        ) : status === "success" ? (
          <CheckCircle2 className="h-3.5 w-3.5 shrink-0 text-ok/80" />
        ) : status === "pending" ? (
          <Loader2 className="h-3.5 w-3.5 shrink-0 animate-spin text-mute" />
        ) : disabled ? (
          <Ban className="h-3.5 w-3.5 shrink-0 text-mute" />
        ) : null}
      </div>

      <div className="py-1">
        {Array.from({ length: rows }).map((_, index) => {
          const input = inputs[index];
          const output = outputs[index];
          return (
            <div key={index} className="relative flex h-[18px] items-center justify-between px-2">
              {input ? (
                <>
                  <Handle
                    type="target"
                    id={input.name}
                    position={Position.Left}
                    style={{ background: PORT_COLORS[input.type], left: -5 }}
                  />
                  <span className="text-[10px] text-mute">
                    {input.label}
                    {input.required ? "" : "?"}
                  </span>
                </>
              ) : (
                <span />
              )}
              {output ? (
                <>
                  <span className="text-[10px] text-mute">{output.label}</span>
                  <Handle
                    type="source"
                    id={output.name}
                    position={Position.Right}
                    style={{ background: PORT_COLORS[output.type], right: -5 }}
                  />
                </>
              ) : null}
            </div>
          );
        })}
      </div>

      {run?.status === "success" ? (
        <div className="mono flex items-center justify-between rounded-b-lg border-t border-line bg-panel-2/60 px-2 py-0.5 text-[9.5px] text-mute">
          <span>{run.durationMs < 1 ? "<1ms" : `${run.durationMs.toFixed(0)}ms`}</span>
          {run.cached ? <span className="text-brand/80">cache</span> : null}
        </div>
      ) : run?.status === "error" ? (
        <div className="truncate rounded-b-lg border-t border-ng/30 bg-ng/10 px-2 py-0.5 text-[9.5px] text-ng">
          {run.error}
        </div>
      ) : null}
    </div>
  );
}
