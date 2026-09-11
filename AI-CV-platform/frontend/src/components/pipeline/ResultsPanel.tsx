import { useState } from "react";
import { AlertTriangle, Clock, Gauge, ImageIcon, Terminal } from "lucide-react";
import type { RunResult } from "../../api/types";
import { EmptyState, VerdictBadge, formatMs, formatNumber } from "../ui";

export function ResultsPanel({
  result,
  selectedId,
  onSelectNode,
  onEnlarge,
}: {
  result: RunResult | null;
  selectedId: string | null;
  onSelectNode: (id: string) => void;
  onEnlarge: (url: string) => void;
}) {
  const [tab, setTab] = useState<"preview" | "data" | "logs">("preview");

  if (!result) {
    return (
      <EmptyState
        title="尚未执行"
        icon={<Gauge className="h-5 w-5" />}
        hint="选一张调试图片后点「运行」，这里会显示每个节点的耗时、中间图像和判定结果。"
      />
    );
  }

  const node = selectedId ? result.nodes[selectedId] : undefined;
  const outputs = node ? Object.entries(node.outputs) : [];

  return (
    <div className="flex h-full min-h-0">
      {/* execution order */}
      <div className="flex w-[190px] shrink-0 flex-col border-r border-line">
        <div className="flex items-center gap-1.5 border-b border-line px-2 py-1.5 text-[11px] text-mute">
          <Clock className="h-3 w-3" /> 执行顺序 · 共 {formatMs(result.totalMs)}
          <span className="ml-auto text-[10px]">
            缓存 {result.cache.hits}/{result.cache.hits + result.cache.misses}
          </span>
        </div>
        <div className="scroll-y flex-1">
          {result.order.map((id, index) => {
            const info = result.nodes[id];
            return (
              <button
                key={id}
                onClick={() => onSelectNode(id)}
                className={`flex w-full items-center gap-1.5 px-2 py-1 text-left text-[11.5px] transition ${
                  selectedId === id ? "bg-panel-3 text-ink" : "text-mute hover:bg-panel-2"
                }`}
              >
                <span className="mono w-4 text-[10px] text-mute/60">{index + 1}</span>
                <span
                  className={`h-1.5 w-1.5 shrink-0 rounded-full ${
                    info?.status === "error"
                      ? "bg-ng"
                      : info?.status === "success"
                        ? info.cached
                          ? "bg-brand/60"
                          : "bg-ok"
                        : "bg-mute/40"
                  }`}
                />
                <span className="flex-1 truncate">{id}</span>
                <span className="mono text-[10px]">{info ? formatMs(info.durationMs) : "—"}</span>
              </button>
            );
          })}
        </div>
      </div>

      {/* node detail */}
      <div className="flex min-w-0 flex-1 flex-col">
        <div className="flex items-center gap-1 border-b border-line px-2">
          {(
            [
              ["preview", "中间图像", ImageIcon],
              ["data", "输出数据", Gauge],
              ["logs", "日志", Terminal],
            ] as const
          ).map(([value, label, Icon]) => (
            <button
              key={value}
              onClick={() => setTab(value)}
              className={`-mb-px flex items-center gap-1 border-b-2 px-2 py-1.5 text-[11.5px] ${
                tab === value ? "border-brand text-ink" : "border-transparent text-mute hover:text-ink"
              }`}
            >
              <Icon className="h-3 w-3" /> {label}
            </button>
          ))}
          <div className="flex-1" />
          {node ? (
            <span className="mono text-[10.5px] text-mute">
              {node.nodeType} · {formatMs(node.durationMs)}
              {node.cached ? " · cache" : ""}
            </span>
          ) : null}
        </div>

        <div className="scroll-y flex-1 p-2">
          {!node ? (
            <div className="text-[12px] text-mute">选择左侧节点查看细节</div>
          ) : node.status === "error" ? (
            <div className="flex items-start gap-2 rounded-md border border-ng/40 bg-ng/10 px-2 py-2 text-[12px] text-ng">
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" /> {node.error}
            </div>
          ) : tab === "preview" ? (
            outputs.length === 0 ? (
              <div className="text-[12px] text-mute">该节点没有可视化输出</div>
            ) : (
              <div className="flex flex-wrap gap-2">
                {outputs.map(([port, payload]) =>
                  payload.preview ? (
                    <button
                      key={port}
                      className="group relative overflow-hidden rounded-md border border-line hover:border-brand/60"
                      onClick={() => onEnlarge(payload.preview!.url)}
                      title="点击放大"
                    >
                      <img
                        src={payload.preview.url}
                        alt={port}
                        className="h-[150px] w-auto max-w-[280px] object-contain bg-black/40"
                      />
                      <span className="absolute bottom-0 left-0 bg-black/70 px-1 text-[10px] text-brand">
                        {port} · {payload.type}
                      </span>
                    </button>
                  ) : (
                    <div
                      key={port}
                      className="w-[150px] rounded-md border border-line bg-panel-2 px-2 py-1.5 text-[11px]"
                    >
                      <div className="text-brand">
                        {port} · {payload.type}
                      </div>
                      <div className="mono mt-0.5 text-mute">
                        {Object.entries(payload.summary ?? {})
                          .slice(0, 4)
                          .map(([key, value]) => `${key}=${formatNumber(value, 2)}`)
                          .join("\n")}
                      </div>
                    </div>
                  ),
                )}
              </div>
            )
          ) : tab === "data" ? (
            <div className="space-y-2">
              {outputs.map(([port, payload]) => (
                <div key={port} className="rounded-md border border-line bg-panel-2 px-2 py-1.5">
                  <div className="text-[11.5px] text-brand">
                    {port} · {payload.type}
                  </div>
                  <div className="mono mt-1 grid grid-cols-2 gap-x-3 gap-y-0.5 text-[11px] text-mute">
                    {Object.entries(payload.summary ?? {}).map(([key, value]) => (
                      <span key={key} className="truncate">
                        {key}: <span className="text-ink/90">{formatNumber(value, 3)}</span>
                      </span>
                    ))}
                  </div>
                </div>
              ))}
              <div className="rounded-md border border-line bg-panel-2 px-2 py-1.5">
                <div className="text-[11.5px] text-mute">生效参数</div>
                <div className="mono mt-1 grid grid-cols-2 gap-x-3 gap-y-0.5 text-[11px] text-mute">
                  {Object.entries(node.params ?? {}).map(([key, value]) => (
                    <span key={key} className="truncate">
                      {key}: <span className="text-ink/90">{formatNumber(value, 3)}</span>
                    </span>
                  ))}
                </div>
              </div>
            </div>
          ) : (
            <pre className="mono whitespace-pre-wrap text-[11px] leading-relaxed text-mute">
              {node.logs?.length ? node.logs.join("\n") : "无日志输出"}
            </pre>
          )}
        </div>
      </div>

      {/* verdict */}
      <div className="w-[210px] shrink-0 border-l border-line">
        <div className="border-b border-line px-2 py-1.5 text-[11px] text-mute">判定结果</div>
        <div className="scroll-y h-[calc(100%-30px)] p-2">
          <div className="flex items-center gap-2">
            <VerdictBadge verdict={result.verdict} />
            <span className="text-[11.5px] text-mute">{result.reason || "—"}</span>
          </div>
          {Object.keys(result.measurements ?? {}).length ? (
            <div className="mt-2 space-y-1">
              {Object.entries(result.measurements).map(([key, value]) => (
                <div
                  key={key}
                  className="flex items-center justify-between rounded-md border border-line bg-panel-2 px-2 py-1 text-[11.5px]"
                >
                  <span className="truncate text-mute">{key}</span>
                  <span className="mono text-ink/90">{formatNumber(value, 3)}</span>
                </div>
              ))}
            </div>
          ) : (
            <div className="mt-2 text-[11.5px] text-mute">
              流程未产生测量值，添加「判定 / 测量」类节点即可。
            </div>
          )}
          {result.errors.length ? (
            <div className="mt-2 space-y-1">
              {result.errors.map((error, index) => (
                <div
                  key={index}
                  className="rounded-md border border-ng/40 bg-ng/10 px-2 py-1 text-[11px] text-ng"
                >
                  {error.nodeId ? `${error.nodeId}: ` : ""}
                  {error.message}
                </div>
              ))}
            </div>
          ) : null}
        </div>
      </div>
    </div>
  );
}
