import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import {
  Activity,
  AlertTriangle,
  Brain,
  Camera,
  ChevronLeft,
  ChevronRight,
  Cpu,
  Gauge,
  Images,
  RefreshCw,
  Timer,
  X,
} from "lucide-react";
import { api } from "../api/client";
import type { InferenceRecord, MonitoringOverview } from "../api/types";
import { ImageViewer } from "../components/ImageViewer";
import {
  Badge,
  EmptyState,
  Modal,
  SectionTitle,
  Spinner,
  Toggle,
  VerdictBadge,
  formatMs,
  formatNumber,
  formatTime,
  usePolling,
} from "../components/ui";
import { useApp } from "../store/app";

const WINDOWS = [
  { hours: 1, label: "1 小时" },
  { hours: 6, label: "6 小时" },
  { hours: 24, label: "24 小时" },
  { hours: 168, label: "7 天" },
];

const PAGE_SIZE = 20;
const DATASET_DEVICE = "dataset";
const SERIES_LABELS: Record<string, string> = {
  okCount: "OK",
  ngCount: "NG",
  errorCount: "错误",
};

interface Filters {
  projectId?: string;
  deviceId?: string;
  modelId?: string;
  verdict?: string;
  lowConfidence?: boolean;
}

function Kpi({
  icon,
  label,
  value,
  hint,
  tone = "",
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
  hint?: string;
  tone?: string;
}) {
  return (
    <div className="panel px-3 py-2.5">
      <div className="flex items-center gap-1.5 text-[11.5px] text-mute">
        {icon} {label}
      </div>
      <div className={`mt-1 text-[19px] font-semibold leading-tight ${tone}`}>{value}</div>
      {hint ? <div className="mt-0.5 truncate text-[11px] text-mute">{hint}</div> : null}
    </div>
  );
}

/** Confidence distribution as a 10-bucket sparkline; shape matters more than exact counts. */
function ConfidenceBars({ buckets }: { buckets: number[] }) {
  const max = Math.max(1, ...buckets);
  return (
    <div className="flex h-6 items-end gap-[2px]" title="置信度分布 0 → 1">
      {buckets.map((count, index) => (
        <div
          key={index}
          className={`w-[5px] rounded-sm ${index < 6 ? "bg-warn/70" : "bg-brand/70"}`}
          style={{ height: `${Math.max(count ? 12 : 2, (count / max) * 100)}%` }}
        />
      ))}
    </div>
  );
}

export default function MonitorPage() {
  const { reportError } = useApp();
  const [hours, setHours] = useState(24);
  const [overview, setOverview] = useState<MonitoringOverview | null>(null);
  const [records, setRecords] = useState<InferenceRecord[]>([]);
  const [recordTotal, setRecordTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [filters, setFilters] = useState<Filters>({});
  const [loading, setLoading] = useState(false);
  const [auto, setAuto] = useState(false);
  const [detail, setDetail] = useState<InferenceRecord | null>(null);

  const refreshOverview = useCallback(async () => {
    try {
      setOverview(await api.monitoringOverview(hours));
    } catch (error) {
      reportError(error, "监控数据加载失败");
    }
  }, [hours, reportError]);

  const refreshRecords = useCallback(async () => {
    setLoading(true);
    try {
      const data = await api.monitoringRecords({ hours, page, pageSize: PAGE_SIZE, ...filters });
      setRecords(data.records);
      setRecordTotal(data.total);
    } catch (error) {
      reportError(error, "推理明细加载失败");
    } finally {
      setLoading(false);
    }
  }, [hours, page, filters, reportError]);

  useEffect(() => {
    void refreshOverview();
  }, [refreshOverview]);

  useEffect(() => {
    void refreshRecords();
  }, [refreshRecords]);

  usePolling(() => {
    void refreshOverview();
    void refreshRecords();
  }, auto ? 5000 : null);

  const setFilter = (patch: Filters) => {
    setPage(1);
    setFilters((current) => {
      const next = { ...current, ...patch };
      // clicking the active row again clears that filter
      (Object.keys(patch) as (keyof Filters)[]).forEach((key) => {
        if (current[key] === patch[key]) delete next[key];
      });
      return next;
    });
  };

  const chartData = useMemo(
    () =>
      (overview?.timeline ?? []).map((bucket) => ({
        ...bucket,
        label: new Date(bucket.ts).toLocaleTimeString("zh-CN", {
          hour: "2-digit",
          minute: "2-digit",
          hour12: false,
        }),
      })),
    [overview],
  );

  const filterChips = useMemo(() => {
    const chips: { key: keyof Filters; text: string }[] = [];
    if (filters.projectId) {
      const project = overview?.projects.find((item) => item.projectId === filters.projectId);
      chips.push({ key: "projectId", text: `项目：${project?.projectName ?? filters.projectId}` });
    }
    if (filters.deviceId) {
      const device = overview?.devices.find((item) => item.id === filters.deviceId);
      chips.push({
        key: "deviceId",
        text: `采集：${filters.deviceId === DATASET_DEVICE ? "数据集回放" : device?.name ?? filters.deviceId}`,
      });
    }
    if (filters.modelId) {
      const model = overview?.models.find((item) => item.id === filters.modelId);
      chips.push({ key: "modelId", text: `模型：${model?.name ?? filters.modelId}` });
    }
    if (filters.verdict) chips.push({ key: "verdict", text: `判定：${filters.verdict}` });
    if (filters.lowConfidence) chips.push({ key: "lowConfidence", text: "仅低置信度" });
    return chips;
  }, [filters, overview]);

  const summary = overview?.summary;
  const pageCount = Math.max(1, Math.ceil(recordTotal / PAGE_SIZE));

  return (
    <div className="mx-auto max-w-[1400px] px-6 py-6">
      <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold">模型监控</h1>
          <p className="mt-0.5 max-w-3xl text-[12.5px] leading-relaxed text-mute">
            已部署视觉模型的运行情况：设备在线状态、各设备推理量、每个模型的置信度与推理耗时，
            以及每一次预测的结果。数据来自「运行」页的实际推理，未运行过的项目不会出现在这里。
          </p>
        </div>
        <div className="flex items-center gap-1.5">
          {WINDOWS.map((item) => (
            <button
              key={item.hours}
              className={`btn-subtle ${hours === item.hours ? "bg-panel-2 text-ink" : ""}`}
              onClick={() => {
                setHours(item.hours);
                setPage(1);
              }}
            >
              {item.label}
            </button>
          ))}
          <div className="mx-1 h-4 w-px bg-line-solid" />
          <Toggle checked={auto} onChange={setAuto} label="自动刷新" />
          <button
            className="btn-ghost"
            onClick={() => {
              void refreshOverview();
              void refreshRecords();
            }}
          >
            <RefreshCw className="h-3.5 w-3.5" /> 刷新
          </button>
        </div>
      </div>

      {!overview ? (
        <div className="panel grid h-64 place-items-center">
          <Spinner className="text-mute" />
        </div>
      ) : summary && summary.total === 0 ? (
        <div className="panel h-64">
          <EmptyState
            title={`最近 ${overview.hours} 小时没有推理记录`}
            icon={<Activity className="h-5 w-5" />}
            hint="到项目的「运行」页发布并触发一次检测，或运行 backend/scripts/seed_monitoring.py 生成演示数据，这里就会有内容。"
          />
        </div>
      ) : (
        <>
          <div className="grid grid-cols-2 gap-2.5 md:grid-cols-3 xl:grid-cols-6">
            <Kpi
              icon={<Activity className="h-3.5 w-3.5" />}
              label="推理总数"
              value={String(summary?.total ?? 0)}
              hint={`${summary?.projectCount ?? 0} 个项目 · ${summary?.runningSessions ?? 0} 个会话运行中`}
            />
            <Kpi
              icon={<Gauge className="h-3.5 w-3.5" />}
              label="良率"
              value={`${summary?.yieldPercent ?? 0}%`}
              tone={(summary?.yieldPercent ?? 0) >= 80 ? "text-ok" : "text-warn"}
              hint={`OK ${summary?.okCount ?? 0} · NG ${summary?.ngCount ?? 0}`}
            />
            <Kpi
              icon={<Timer className="h-3.5 w-3.5" />}
              label="平均推理耗时"
              value={formatMs(summary?.avgDurationMs ?? 0)}
              hint={`P95 ${formatMs(summary?.p95DurationMs ?? 0)} · 最慢 ${formatMs(summary?.maxDurationMs ?? 0)}`}
            />
            <Kpi
              icon={<Brain className="h-3.5 w-3.5" />}
              label="平均置信度"
              value={summary?.avgConfidence ? summary.avgConfidence.toFixed(3) : "—"}
              tone={summary?.lowConfidenceCount ? "text-warn" : ""}
              hint={
                summary?.avgConfidence
                  ? `${summary.lowConfidenceCount} 次低置信度 · ${summary.modelCount} 个模型在跑`
                  : "当前流程未使用 AI 分类节点"
              }
            />
            <Kpi
              icon={<Cpu className="h-3.5 w-3.5" />}
              label="在线设备"
              value={`${summary?.onlineDevices ?? 0} / ${summary?.totalDevices ?? 0}`}
              hint={`${summary?.deviceCount ?? 0} 个设备有推理量`}
            />
            <Kpi
              icon={<Images className="h-3.5 w-3.5" />}
              label="数据集回放"
              value={String(summary?.datasetInferences ?? 0)}
              hint="不经过相机的推理次数"
            />
          </div>

          {overview.alerts.length ? (
            <div className="mt-3 space-y-1.5">
              {overview.alerts.map((alert, index) => (
                <div
                  key={index}
                  className={`flex items-start gap-2 rounded-md border px-2.5 py-1.5 text-[12px] ${
                    alert.level === "error"
                      ? "border-ng/40 bg-ng/10 text-ng"
                      : alert.level === "warning"
                        ? "border-warn/40 bg-warn/10 text-warn"
                        : "border-line bg-panel-2 text-mute"
                  }`}
                >
                  <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                  <span className="font-medium">{alert.target}</span>
                  <span className="min-w-0 flex-1">{alert.message}</span>
                </div>
              ))}
            </div>
          ) : null}

          <div className="panel mt-3">
            <SectionTitle
              title="推理量趋势"
              hint={`最近 ${overview.hours} 小时，按 ${Math.max(1, Math.round((overview.hours * 60) / 24))} 分钟分桶`}
            />
            <div className="h-[180px] px-2 py-2">
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={chartData} margin={{ top: 6, right: 10, bottom: 0, left: -18 }}>
                  <CartesianGrid stroke="#1a2536" vertical={false} />
                  <XAxis dataKey="label" tick={{ fill: "#8ba0bb", fontSize: 10 }} stroke="#243146" />
                  <YAxis tick={{ fill: "#8ba0bb", fontSize: 10 }} stroke="#243146" allowDecimals={false} />
                  <Tooltip
                    contentStyle={{
                      background: "#111823",
                      border: "1px solid #243146",
                      borderRadius: 6,
                      fontSize: 11,
                    }}
                    formatter={(value, name) => [
                      value,
                      SERIES_LABELS[String(name)] ?? String(name),
                    ]}
                  />
                  {(
                    [
                      ["okCount", "#34d399"],
                      ["ngCount", "#fb7185"],
                      ["errorCount", "#fbbf24"],
                    ] as const
                  ).map(([key, color]) => (
                    <Area
                      key={key}
                      type="monotone"
                      dataKey={key}
                      stackId="1"
                      stroke={color}
                      fill={color}
                      fillOpacity={0.22}
                      strokeWidth={1.2}
                      isAnimationActive={false}
                    />
                  ))}
                </AreaChart>
              </ResponsiveContainer>
            </div>
          </div>

          <div className="mt-3 grid grid-cols-1 gap-3 xl:grid-cols-2">
            <div className="panel">
              <SectionTitle title="设备" hint="在线状态与各设备推理量，点击行可筛选下方明细" />
              <div className="scroll-y max-h-[320px]">
                <table className="w-full text-[12px]">
                  <thead className="sticky top-0 bg-panel-2 text-[11px] text-mute">
                    <tr>
                      <th className="px-2.5 py-1.5 text-left font-normal">设备</th>
                      <th className="px-2 py-1.5 text-left font-normal">状态</th>
                      <th className="px-2 py-1.5 text-right font-normal">推理数</th>
                      <th className="px-2 py-1.5 text-right font-normal">平均耗时</th>
                      <th className="px-2.5 py-1.5 text-right font-normal">最近一次</th>
                    </tr>
                  </thead>
                  <tbody>
                    {overview.devices.map((device) => (
                      <tr
                        key={device.id}
                        onClick={() => setFilter({ deviceId: device.id })}
                        className={`cursor-pointer border-t border-line hover:bg-panel-2 ${
                          filters.deviceId === device.id ? "bg-panel-3" : ""
                        }`}
                      >
                        <td className="px-2.5 py-1.5">
                          <div className="flex items-center gap-1.5">
                            <Camera className="h-3.5 w-3.5 text-mute" />
                            <span className="truncate">{device.name}</span>
                            {device.implemented ? null : <Badge tone="neutral">预留</Badge>}
                          </div>
                        </td>
                        <td className="px-2 py-1.5">
                          <Badge tone={device.online ? "ok" : device.state === "error" ? "ng" : "neutral"}>
                            {device.online ? "在线" : device.state === "error" ? "错误" : "离线"}
                          </Badge>
                        </td>
                        <td className="mono px-2 py-1.5 text-right">{device.total}</td>
                        <td className="mono px-2 py-1.5 text-right text-mute">
                          {device.total ? formatMs(device.avgDurationMs) : "—"}
                        </td>
                        <td className="px-2.5 py-1.5 text-right text-[11px] text-mute">
                          {device.lastAt ? formatTime(device.lastAt) : "—"}
                        </td>
                      </tr>
                    ))}
                    <tr
                      onClick={() => setFilter({ deviceId: DATASET_DEVICE })}
                      className={`cursor-pointer border-t border-line hover:bg-panel-2 ${
                        filters.deviceId === DATASET_DEVICE ? "bg-panel-3" : ""
                      }`}
                    >
                      <td className="px-2.5 py-1.5">
                        <div className="flex items-center gap-1.5">
                          <Images className="h-3.5 w-3.5 text-mute" />
                          数据集回放
                        </div>
                      </td>
                      <td className="px-2 py-1.5">
                        <Badge tone="brand">虚拟</Badge>
                      </td>
                      <td className="mono px-2 py-1.5 text-right">{summary?.datasetInferences ?? 0}</td>
                      <td className="px-2 py-1.5 text-right text-mute">—</td>
                      <td className="px-2.5 py-1.5 text-right text-[11px] text-mute">—</td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </div>

            <div className="panel">
              <SectionTitle title="模型" hint="置信度与耗时按模型统计，点击行可筛选下方明细" />
              <div className="scroll-y max-h-[320px]">
                {overview.models.length === 0 ? (
                  <div className="px-3 py-6 text-center text-[12px] text-mute">
                    还没有训练过模型，可在项目的「模型」页训练 LBP+SVM 分类器
                  </div>
                ) : (
                  <table className="w-full text-[12px]">
                    <thead className="sticky top-0 bg-panel-2 text-[11px] text-mute">
                      <tr>
                        <th className="px-2.5 py-1.5 text-left font-normal">模型</th>
                        <th className="px-2 py-1.5 text-right font-normal">推理数</th>
                        <th className="px-2 py-1.5 text-right font-normal">平均置信度</th>
                        <th className="px-2 py-1.5 text-left font-normal">分布</th>
                        <th className="px-2.5 py-1.5 text-right font-normal">平均 / P95</th>
                      </tr>
                    </thead>
                    <tbody>
                      {overview.models.map((model) => (
                        <tr
                          key={model.id}
                          onClick={() => setFilter({ modelId: model.id })}
                          className={`cursor-pointer border-t border-line hover:bg-panel-2 ${
                            filters.modelId === model.id ? "bg-panel-3" : ""
                          }`}
                        >
                          <td className="px-2.5 py-1.5">
                            <div className="truncate">{model.name}</div>
                            <div className="mono truncate text-[10px] text-mute">
                              {model.projectName ?? "全局模型"} · {model.classes.join("/") || "—"}
                              {model.cvAccuracy ? ` · CV ${model.cvAccuracy}` : ""}
                            </div>
                          </td>
                          <td className="mono px-2 py-1.5 text-right">{model.total}</td>
                          <td
                            className={`mono px-2 py-1.5 text-right ${
                              model.total && model.avgConfidence < 0.6 ? "text-warn" : ""
                            }`}
                          >
                            {model.total ? model.avgConfidence.toFixed(3) : "—"}
                            {model.lowConfidenceCount ? (
                              <div className="text-[10px] text-warn">{model.lowConfidenceCount} 次偏低</div>
                            ) : null}
                          </td>
                          <td className="px-2 py-1.5">
                            {model.total ? <ConfidenceBars buckets={model.confidenceBuckets} /> : "—"}
                          </td>
                          <td className="mono px-2.5 py-1.5 text-right text-mute">
                            {model.total
                              ? `${formatMs(model.avgDurationMs)} / ${formatMs(model.p95DurationMs)}`
                              : "—"}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </div>
            </div>
          </div>

          <div className="panel mt-3">
            <SectionTitle title="部署项目" hint="每个项目的在线判定结果，点击项目名进入运行页" />
            <table className="w-full text-[12px]">
              <thead className="bg-panel-2 text-[11px] text-mute">
                <tr>
                  <th className="px-2.5 py-1.5 text-left font-normal">项目</th>
                  <th className="px-2 py-1.5 text-left font-normal">会话</th>
                  <th className="px-2 py-1.5 text-right font-normal">推理数</th>
                  <th className="px-2 py-1.5 text-right font-normal">OK / NG / 错误</th>
                  <th className="px-2 py-1.5 text-right font-normal">良率</th>
                  <th className="px-2 py-1.5 text-right font-normal">平均耗时</th>
                  <th className="px-2.5 py-1.5 text-right font-normal">最近一次</th>
                </tr>
              </thead>
              <tbody>
                {overview.projects.map((project) => (
                  <tr
                    key={project.projectId}
                    onClick={() => setFilter({ projectId: project.projectId })}
                    className={`cursor-pointer border-t border-line hover:bg-panel-2 ${
                      filters.projectId === project.projectId ? "bg-panel-3" : ""
                    }`}
                  >
                    <td className="px-2.5 py-1.5">
                      <Link
                        to={`/projects/${project.projectId}/runtime`}
                        className="text-brand hover:underline"
                        onClick={(event) => event.stopPropagation()}
                      >
                        {project.projectName}
                      </Link>
                      <span className="ml-1.5 text-[10.5px] text-mute">{project.taskType}</span>
                    </td>
                    <td className="px-2 py-1.5">
                      <Badge
                        tone={
                          project.status === "running"
                            ? "ok"
                            : project.status === "error"
                              ? "ng"
                              : "neutral"
                        }
                      >
                        {project.status === "running"
                          ? "运行中"
                          : project.status === "error"
                            ? "错误"
                            : "已停止"}
                      </Badge>
                      <span className="ml-1.5 text-[10.5px] text-mute">
                        {project.source === "camera" ? "相机" : "数据集"}
                      </span>
                    </td>
                    <td className="mono px-2 py-1.5 text-right">{project.total}</td>
                    <td className="mono px-2 py-1.5 text-right text-mute">
                      <span className="text-ok">{project.okCount}</span> /{" "}
                      <span className="text-ng">{project.ngCount}</span> /{" "}
                      <span className="text-warn">{project.errorCount}</span>
                    </td>
                    <td
                      className={`mono px-2 py-1.5 text-right ${
                        project.yieldPercent >= 80 ? "text-ok" : "text-warn"
                      }`}
                    >
                      {project.yieldPercent}%
                    </td>
                    <td className="mono px-2 py-1.5 text-right text-mute">
                      {formatMs(project.avgDurationMs)}
                    </td>
                    <td className="px-2.5 py-1.5 text-right text-[11px] text-mute">
                      {project.lastAt ? formatTime(project.lastAt) : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="panel mt-3">
            <SectionTitle
              title="推理明细"
              hint={`${recordTotal} 条记录 · ${overview.retentionNote}`}
              actions={
                <>
                  {(["OK", "NG", "ERROR"] as const).map((verdict) => (
                    <button
                      key={verdict}
                      className={`btn-subtle ${filters.verdict === verdict ? "bg-panel-2 text-ink" : ""}`}
                      onClick={() => setFilter({ verdict })}
                    >
                      {verdict}
                    </button>
                  ))}
                  <button
                    className={`btn-subtle ${filters.lowConfidence ? "bg-panel-2 text-ink" : ""}`}
                    onClick={() => setFilter({ lowConfidence: !filters.lowConfidence })}
                  >
                    低置信度
                  </button>
                  {loading ? <Spinner className="text-mute" /> : null}
                </>
              }
            />

            {filterChips.length ? (
              <div className="flex flex-wrap items-center gap-1.5 border-b border-line px-3 py-1.5">
                {filterChips.map((chip) => (
                  <button
                    key={chip.key}
                    className="chip bg-brand/15 text-brand"
                    onClick={() => setFilter({ [chip.key]: undefined } as Filters)}
                  >
                    {chip.text} <X className="h-3 w-3" />
                  </button>
                ))}
                <button
                  className="btn-subtle px-1.5 py-0.5 text-[11px]"
                  onClick={() => {
                    setFilters({});
                    setPage(1);
                  }}
                >
                  清空筛选
                </button>
              </div>
            ) : null}

            {records.length === 0 ? (
              <div className="px-3 py-8 text-center text-[12px] text-mute">没有符合条件的推理记录</div>
            ) : (
              <table className="w-full text-[12px]">
                <thead className="bg-panel-2 text-[11px] text-mute">
                  <tr>
                    <th className="px-2.5 py-1.5 text-left font-normal">预览</th>
                    <th className="px-2 py-1.5 text-left font-normal">时间</th>
                    <th className="px-2 py-1.5 text-left font-normal">项目 / 图像</th>
                    <th className="px-2 py-1.5 text-left font-normal">模型</th>
                    <th className="px-2 py-1.5 text-left font-normal">采集</th>
                    <th className="px-2 py-1.5 text-center font-normal">判定</th>
                    <th className="px-2 py-1.5 text-right font-normal">置信度</th>
                    <th className="px-2.5 py-1.5 text-right font-normal">耗时</th>
                  </tr>
                </thead>
                <tbody>
                  {records.map((record) => (
                    <tr
                      key={record.id}
                      onClick={() => setDetail(record)}
                      className="cursor-pointer border-t border-line hover:bg-panel-2"
                    >
                      <td className="px-2.5 py-1">
                        {record.preview ? (
                          <img
                            src={record.preview}
                            alt={record.imageName}
                            className="h-9 w-12 rounded border border-line object-cover"
                          />
                        ) : (
                          <div className="grid h-9 w-12 place-items-center rounded border border-line bg-panel-3 text-mute">
                            <Images className="h-3.5 w-3.5" />
                          </div>
                        )}
                      </td>
                      <td className="px-2 py-1 text-[11px] text-mute">{formatTime(record.createdAt)}</td>
                      <td className="px-2 py-1">
                        <div className="truncate">{record.projectName}</div>
                        <div className="mono truncate text-[10px] text-mute">{record.imageName}</div>
                      </td>
                      <td className="px-2 py-1 text-mute">{record.modelName ?? "—"}</td>
                      <td className="px-2 py-1 text-mute">
                        {record.deviceId ?? (record.source === "camera" ? "相机" : "数据集")}
                      </td>
                      <td className="px-2 py-1 text-center">
                        <VerdictBadge verdict={record.verdict} />
                      </td>
                      <td
                        className={`mono px-2 py-1 text-right ${
                          record.confidence !== null && record.confidence < 0.6 ? "text-warn" : ""
                        }`}
                      >
                        {record.confidence !== null ? record.confidence.toFixed(3) : "—"}
                      </td>
                      <td className="mono px-2.5 py-1 text-right text-mute">
                        {formatMs(record.durationMs)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}

            {pageCount > 1 ? (
              <div className="flex items-center justify-end gap-2 border-t border-line px-3 py-1.5 text-[11.5px] text-mute">
                <span>
                  第 {page} / {pageCount} 页
                </span>
                <button
                  className="btn-subtle px-1.5 py-0.5"
                  disabled={page <= 1}
                  onClick={() => setPage((value) => Math.max(1, value - 1))}
                >
                  <ChevronLeft className="h-3.5 w-3.5" />
                </button>
                <button
                  className="btn-subtle px-1.5 py-0.5"
                  disabled={page >= pageCount}
                  onClick={() => setPage((value) => Math.min(pageCount, value + 1))}
                >
                  <ChevronRight className="h-3.5 w-3.5" />
                </button>
              </div>
            ) : null}
          </div>
        </>
      )}

      <Modal
        open={Boolean(detail)}
        title={detail ? `${detail.projectName} · ${detail.imageName}` : ""}
        width="max-w-4xl"
        onClose={() => setDetail(null)}
      >
        {detail ? (
          <div className="grid grid-cols-1 gap-3 md:grid-cols-[1.4fr_1fr]">
            <div className="h-[52vh] overflow-hidden rounded-md border border-line">
              <ImageViewer src={detail.preview} className="h-full" emptyHint="该次推理没有保留预览图" />
            </div>
            <div className="space-y-2 text-[12px]">
              <div className="flex items-center gap-2">
                <VerdictBadge verdict={detail.verdict} />
                <span className="text-mute">{formatTime(detail.createdAt)}</span>
              </div>
              {detail.error ? (
                <div className="rounded-md border border-ng/40 bg-ng/10 px-2 py-1.5 text-[11.5px] text-ng">
                  {detail.error}
                </div>
              ) : null}
              <div className="grid grid-cols-2 gap-x-3 gap-y-1 rounded-md border border-line bg-panel-2 px-2.5 py-2 text-[11.5px]">
                {[
                  ["序号", `#${detail.seq}`],
                  ["模型", detail.modelName ?? "未使用模型"],
                  ["置信度", detail.confidence !== null ? detail.confidence.toFixed(4) : "—"],
                  ["耗时", formatMs(detail.durationMs)],
                  ["采集", detail.deviceId ?? (detail.source === "camera" ? "相机" : "数据集回放")],
                ].map(([label, value]) => (
                  <span key={label} className="truncate">
                    <span className="text-mute">{label}：</span>
                    {value}
                  </span>
                ))}
              </div>
              <div className="rounded-md border border-line bg-panel-2 px-2.5 py-2">
                <div className="mb-1 text-[11.5px] text-mute">测量值</div>
                {Object.keys(detail.measurements).length ? (
                  <div className="mono grid grid-cols-2 gap-x-3 gap-y-0.5 text-[11px]">
                    {Object.entries(detail.measurements).map(([key, value]) => (
                      <span key={key} className="truncate">
                        {key}: <span className="text-ink/90">{formatNumber(value, 3)}</span>
                      </span>
                    ))}
                  </div>
                ) : (
                  <div className="text-[11.5px] text-mute">该流程未输出测量值</div>
                )}
              </div>
              {detail.projectId ? (
                <Link
                  to={`/projects/${detail.projectId}/runtime`}
                  className="btn-ghost w-full justify-center"
                  onClick={() => setDetail(null)}
                >
                  打开运行页
                </Link>
              ) : null}
            </div>
          </div>
        ) : null}
      </Modal>
    </div>
  );
}
