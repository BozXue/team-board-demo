import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Download,
  Lightbulb,
  Play,
  RefreshCw,
  Repeat,
  StopCircle,
  TestTubes,
} from "lucide-react";
import { api } from "../api/client";
import type { BatchResultRow, BatchRunSummary, DebugSuggestion } from "../api/types";
import { ImageViewer } from "../components/ImageViewer";
import {
  Badge,
  EmptyState,
  Modal,
  SectionTitle,
  Spinner,
  VerdictBadge,
  formatMs,
  formatNumber,
  formatTime,
  usePolling,
} from "../components/ui";
import { useApp } from "../store/app";

// Backend stores confusion-matrix outcomes as TP/FP/TN/FN (null when unlabelled).
const OUTCOME_LABELS: Record<string, string> = {
  TP: "正确报警(TP)",
  TN: "正确放行(TN)",
  FP: "误报(FP)",
  FN: "漏检(FN)",
};

const OUTCOME_TONES: Record<string, "ok" | "ng" | "warn" | "neutral"> = {
  TP: "ok",
  TN: "ok",
  FP: "warn",
  FN: "ng",
};

export default function BatchPage() {
  const { project, toast, reportError } = useApp();
  const projectId = project?.id ?? "";

  const [runs, setRuns] = useState<BatchRunSummary[]>([]);
  const [activeRunId, setActiveRunId] = useState<string | null>(null);
  const [run, setRun] = useState<BatchRunSummary | null>(null);
  const [results, setResults] = useState<BatchResultRow[]>([]);
  const [outcome, setOutcome] = useState("");
  const [advice, setAdvice] = useState<DebugSuggestion[]>([]);
  const [starting, setStarting] = useState(false);
  const [split, setSplit] = useState("");
  const [limit, setLimit] = useState(0);
  const [ngLabels, setNgLabels] = useState("NG");
  const [preview, setPreview] = useState<BatchResultRow | null>(null);

  const refreshRuns = useCallback(async () => {
    if (!projectId) return;
    try {
      const data = await api.listBatches(projectId);
      setRuns(data.runs);
      setActiveRunId((current) => current ?? data.runs[0]?.id ?? null);
    } catch (error) {
      reportError(error, "批量测试记录加载失败");
    }
  }, [projectId, reportError]);

  useEffect(() => {
    void refreshRuns();
  }, [refreshRuns]);

  const refreshRun = useCallback(async () => {
    if (!activeRunId) return;
    try {
      const summary = await api.getBatch(activeRunId);
      setRun(summary);
      const data = await api.batchResults(activeRunId, {
        outcome: outcome || undefined,
        pageSize: 300,
      });
      setResults(data.results);
      if (summary.status === "finished") {
        const adviceData = await api.batchAdvice(activeRunId);
        setAdvice(adviceData.suggestions);
      } else {
        setAdvice([]);
      }
    } catch (error) {
      reportError(error, "批量结果加载失败");
    }
  }, [activeRunId, outcome, reportError]);

  useEffect(() => {
    void refreshRun();
  }, [refreshRun]);

  const isRunning = run?.status === "running" || run?.status === "pending";
  usePolling(() => {
    void refreshRun();
    void refreshRuns();
  }, isRunning ? 1200 : null);

  const start = async () => {
    if (!projectId) return;
    setStarting(true);
    try {
      const created = await api.startBatch(projectId, {
        split: split || undefined,
        limit: limit || undefined,
        ngLabels: ngLabels
          .split(/[,，]/)
          .map((item) => item.trim())
          .filter(Boolean),
      });
      setActiveRunId(created.id);
      setRun(created);
      await refreshRuns();
      toast("批量测试已启动", "success");
    } catch (error) {
      reportError(error, "启动失败");
    } finally {
      setStarting(false);
    }
  };

  const cancel = async () => {
    if (!activeRunId) return;
    await api.cancelBatch(activeRunId);
    await refreshRun();
  };

  const reflow = async () => {
    if (!activeRunId) return;
    try {
      const data = await api.reflowBatch(activeRunId, "train");
      toast(`已将 ${data.moved} 张误判样本回流到训练集`, "success");
    } catch (error) {
      reportError(error, "回流失败");
    }
  };

  const metrics = run?.metrics ?? {};
  const counts = metrics.counts ?? {};

  const cards = useMemo(
    () => [
      { label: "已处理", value: `${run?.done ?? 0}/${run?.total ?? 0}` },
      { label: "OK / NG", value: `${run?.okCount ?? 0} / ${run?.ngCount ?? 0}` },
      { label: "良率", value: `${(run?.yieldPercent ?? 0).toFixed(1)}%` },
      {
        label: "准确率",
        value: metrics.accuracy !== undefined ? `${(metrics.accuracy * 100).toFixed(1)}%` : "—",
      },
      {
        label: "漏检率",
        value: metrics.missRate !== null && metrics.missRate !== undefined ? `${(metrics.missRate * 100).toFixed(1)}%` : "—",
      },
      {
        label: "误报率",
        value:
          metrics.falseAlarmRate !== null && metrics.falseAlarmRate !== undefined
            ? `${(metrics.falseAlarmRate * 100).toFixed(1)}%`
            : "—",
      },
      { label: "平均耗时", value: formatMs(metrics.avgDurationMs ?? 0) },
      { label: "最慢", value: formatMs(metrics.maxDurationMs ?? 0) },
    ],
    [run, metrics],
  );

  return (
    <div className="flex h-full min-h-0">
      <div className="flex w-[250px] shrink-0 flex-col border-r border-line">
        <SectionTitle
          title="批量测试"
          hint="用当前流程跑整个数据集"
          actions={
            <button className="btn-subtle px-1.5 py-1" onClick={refreshRuns} title="刷新">
              <RefreshCw className="h-3.5 w-3.5" />
            </button>
          }
        />
        <div className="space-y-2 border-b border-line p-2.5">
          <div className="grid grid-cols-2 gap-1.5">
            <div>
              <label className="label-text">数据划分</label>
              <select className="field mt-1 py-1" value={split} onChange={(event) => setSplit(event.target.value)}>
                <option value="">全部</option>
                <option value="train">训练</option>
                <option value="val">验证</option>
                <option value="test">测试</option>
                <option value="unassigned">未分配</option>
              </select>
            </div>
            <div>
              <label className="label-text">数量上限</label>
              <input
                className="field mt-1 py-1"
                type="number"
                min={0}
                value={limit}
                onChange={(event) => setLimit(parseInt(event.target.value, 10) || 0)}
              />
            </div>
          </div>
          <div>
            <label className="label-text">视为 NG 的标注类别</label>
            <input
              className="field mt-1 py-1"
              value={ngLabels}
              onChange={(event) => setNgLabels(event.target.value)}
            />
          </div>
          <div className="flex gap-1.5">
            <button className="btn-primary flex-1" onClick={start} disabled={starting || isRunning}>
              {starting ? <Spinner /> : <Play className="h-3.5 w-3.5" />} 开始测试
            </button>
            {isRunning ? (
              <button className="btn-ghost" onClick={cancel} title="中止">
                <StopCircle className="h-3.5 w-3.5" />
              </button>
            ) : null}
          </div>
        </div>

        <div className="scroll-y flex-1">
          {runs.map((item) => (
            <button
              key={item.id}
              onClick={() => setActiveRunId(item.id)}
              className={`block w-full border-b border-line px-2.5 py-2 text-left transition ${
                activeRunId === item.id ? "bg-panel-2" : "hover:bg-panel-2/60"
              }`}
            >
              <div className="flex items-center gap-1.5">
                <Badge
                  tone={
                    item.status === "finished"
                      ? "ok"
                      : item.status === "failed"
                        ? "ng"
                        : item.status === "running" || item.status === "pending"
                          ? "brand"
                          : "neutral"
                  }
                >
                  {item.status}
                </Badge>
                <span className="mono text-[11px] text-mute">
                  {item.done}/{item.total}
                </span>
                <span className="ml-auto text-[10.5px] text-mute/70">{formatTime(item.createdAt)}</span>
              </div>
              <div className="mt-1 text-[11.5px] text-mute">
                良率 {item.yieldPercent.toFixed(1)}%
                {item.metrics?.accuracy !== undefined
                  ? ` · 准确率 ${(item.metrics.accuracy * 100).toFixed(1)}%`
                  : ""}
              </div>
            </button>
          ))}
          {runs.length === 0 ? (
            <EmptyState
              icon={<TestTubes className="h-5 w-5" />}
              title="还没有测试记录"
              hint="配置好流程后跑一轮批量测试，可以量化良率、漏检和误报。"
            />
          ) : null}
        </div>
      </div>

      <div className="flex min-w-0 flex-1 flex-col">
        {!run ? (
          <EmptyState title="选择一次测试查看结果" />
        ) : (
          <>
            <div className="border-b border-line p-3">
              <div className="grid grid-cols-4 gap-2 xl:grid-cols-8">
                {cards.map((card) => (
                  <div key={card.label} className="rounded-md border border-line bg-panel-2 px-2 py-1.5">
                    <div className="text-[10.5px] text-mute">{card.label}</div>
                    <div className="mono text-[14px]">{card.value}</div>
                  </div>
                ))}
              </div>

              {isRunning ? (
                <div className="mt-2 h-1 overflow-hidden rounded-full bg-panel-3">
                  <div
                    className="h-full bg-brand-dim transition-all"
                    style={{ width: `${((run.done ?? 0) / Math.max(1, run.total)) * 100}%` }}
                  />
                </div>
              ) : null}

              {run.message ? <div className="mt-2 text-[11.5px] text-mute">{run.message}</div> : null}

              {advice.length ? (
                <div className="mt-2 space-y-1">
                  {advice.map((item, index) => (
                    <div
                      key={index}
                      className={`rounded-md border px-2 py-1.5 text-[11.5px] ${
                        item.level === "critical"
                          ? "border-ng/40 bg-ng/10 text-ng"
                          : item.level === "warning"
                            ? "border-warn/40 bg-warn/10 text-warn"
                            : "border-brand/30 bg-brand/10 text-brand"
                      }`}
                    >
                      <div className="flex items-center gap-1.5 font-medium">
                        <Lightbulb className="h-3 w-3" /> {item.title}
                      </div>
                      <div className="mt-0.5 leading-relaxed opacity-90">{item.detail}</div>
                      {item.action ? <div className="mt-0.5 leading-relaxed">建议：{item.action}</div> : null}
                    </div>
                  ))}
                </div>
              ) : null}
            </div>

            <div className="flex h-9 shrink-0 items-center gap-1.5 border-b border-line px-2">
              <select
                className="field w-40 py-1"
                value={outcome}
                onChange={(event) => setOutcome(event.target.value)}
              >
                <option value="">全部结果</option>
                {Object.entries(OUTCOME_LABELS).map(([key, label]) => (
                  <option key={key} value={key}>
                    {label} {counts[key] !== undefined ? `(${counts[key]})` : ""}
                  </option>
                ))}
              </select>
              <button className="btn-subtle" onClick={reflow} title="把误报/漏检样本移入训练集">
                <Repeat className="h-3.5 w-3.5" /> 误判回流
              </button>
              <a className="btn-subtle" href={api.batchCsvUrl(run.id)} download>
                <Download className="h-3.5 w-3.5" /> 导出 CSV
              </a>
              <div className="flex-1" />
              <span className="mono text-[11px] text-mute">{results.length} 条</span>
            </div>

            <div className="scroll-y flex-1 p-2">
              <div className="grid grid-cols-2 gap-2 md:grid-cols-3 xl:grid-cols-4">
                {results.map((row) => (
                  <button
                    key={row.id}
                    className="panel overflow-hidden p-0 text-left transition hover:border-brand/40"
                    onClick={() => setPreview(row)}
                  >
                    <div className="relative h-28 bg-black/40">
                      {row.artifacts.preview ? (
                        <img
                          src={row.artifacts.preview}
                          alt={row.imageName}
                          loading="lazy"
                          className="h-full w-full object-contain"
                        />
                      ) : (
                        <div className="grid h-full place-items-center text-[11px] text-mute">无预览</div>
                      )}
                      <span className="absolute top-1 left-1">
                        <VerdictBadge verdict={row.verdict} />
                      </span>
                      {row.outcome ? (
                        <span className="absolute top-1 right-1">
                          <Badge tone={OUTCOME_TONES[row.outcome] ?? "neutral"}>
                            {OUTCOME_LABELS[row.outcome] ?? row.outcome}
                          </Badge>
                        </span>
                      ) : null}
                    </div>
                    <div className="px-2 py-1.5">
                      <div className="truncate text-[11.5px]">{row.imageName}</div>
                      <div className="mono truncate text-[10.5px] text-mute">
                        {row.error
                          ? row.error
                          : Object.entries(row.measurements ?? {})
                              .slice(0, 2)
                              .map(([key, value]) => `${key}=${formatNumber(value, 2)}`)
                              .join(" · ") || formatMs(row.durationMs)}
                      </div>
                    </div>
                  </button>
                ))}
              </div>
              {results.length === 0 ? <EmptyState title="没有符合条件的结果" /> : null}
            </div>
          </>
        )}
      </div>

      <Modal
        open={Boolean(preview)}
        title={preview?.imageName ?? ""}
        width="max-w-4xl"
        onClose={() => setPreview(null)}
      >
        <div className="mb-2 flex flex-wrap items-center gap-2 text-[12px]">
          <VerdictBadge verdict={preview?.verdict ?? "unknown"} />
          {preview?.gtLabel ? <Badge>标注 {preview.gtLabel}</Badge> : null}
          {preview?.outcome ? (
            <Badge tone={OUTCOME_TONES[preview.outcome] ?? "neutral"}>
              {OUTCOME_LABELS[preview.outcome] ?? preview.outcome}
            </Badge>
          ) : null}
          <span className="mono text-mute">{formatMs(preview?.durationMs ?? 0)}</span>
          {Object.entries(preview?.measurements ?? {}).map(([key, value]) => (
            <span key={key} className="mono text-mute">
              {key}={formatNumber(value, 3)}
            </span>
          ))}
        </div>
        <div className="h-[62vh]">
          <ImageViewer src={preview?.artifacts.preview ?? null} className="h-full" />
        </div>
        {preview?.error ? (
          <div className="mt-2 rounded-md border border-ng/40 bg-ng/10 px-2 py-1.5 text-[12px] text-ng">
            {preview.error}
          </div>
        ) : null}
      </Modal>
    </div>
  );
}
