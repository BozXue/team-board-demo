import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  Camera,
  Gauge,
  MonitorPlay,
  Play,
  RotateCcw,
  SlidersHorizontal,
  Square,
  Zap,
} from "lucide-react";
import { api } from "../api/client";
import type { DeviceStatus, RuntimeRecord, RuntimeStatus, UserParamSpec } from "../api/types";
import { ImageViewer } from "../components/ImageViewer";
import { ParamControl } from "../components/pipeline/ParamControl";
import {
  Badge,
  EmptyState,
  SectionTitle,
  Spinner,
  VerdictBadge,
  formatMs,
  formatNumber,
  usePolling,
} from "../components/ui";
import { useApp } from "../store/app";

export default function RuntimePage() {
  const navigate = useNavigate();
  const { project, toast, reportError } = useApp();
  const projectId = project?.id ?? "";

  const [status, setStatus] = useState<RuntimeStatus | null>(null);
  const [devices, setDevices] = useState<DeviceStatus[]>([]);
  const [source, setSource] = useState<"dataset" | "camera">("dataset");
  const [deviceId, setDeviceId] = useState("");
  const [intervalMs, setIntervalMs] = useState(800);
  const [busy, setBusy] = useState(false);
  const [loadError, setLoadError] = useState(false);
  const [active, setActive] = useState<RuntimeRecord | null>(null);
  const [values, setValues] = useState<Record<string, unknown>>({});

  const refresh = useCallback(async () => {
    if (!projectId) return;
    try {
      const data = await api.runtimeStatus(projectId);
      setLoadError(false);
      setStatus(data);
      setActive((current) => {
        const latest = data.records[0] ?? null;
        if (!current) return latest;
        return data.records.find((record) => record.id === current.id) ?? latest;
      });
      setValues((current) => {
        if (Object.keys(current).length) return current;
        const next: Record<string, unknown> = {};
        Object.entries(data.userParams).forEach(([key, spec]) => {
          next[key] = spec.value;
        });
        return next;
      });
    } catch (error) {
      setLoadError(true);
      reportError(error, "运行状态加载失败");
    }
  }, [projectId, reportError]);

  useEffect(() => {
    void refresh();
    void api
      .listDevices()
      .then((data) => {
        setDevices(data.devices);
        setDeviceId((current) => current || data.devices.find((device) => device.implemented)?.id || "");
      })
      .catch(() => undefined);
  }, [refresh]);

  usePolling(refresh, status?.status === "running" ? 900 : null);

  const start = async () => {
    if (!projectId) return;
    setBusy(true);
    try {
      setStatus(await api.runtimeStart(projectId, { source, intervalMs, deviceId: deviceId || undefined }));
      toast("已开始连续检测", "success");
    } catch (error) {
      reportError(error, "启动失败");
    } finally {
      setBusy(false);
    }
  };

  const stop = async () => {
    if (!projectId) return;
    setBusy(true);
    try {
      setStatus(await api.runtimeStop(projectId));
    } catch (error) {
      reportError(error, "停止失败");
    } finally {
      setBusy(false);
    }
  };

  const trigger = async () => {
    if (!projectId) return;
    setBusy(true);
    try {
      const data = await api.runtimeTrigger(projectId, source === "camera" ? deviceId : undefined);
      setStatus(data.status);
      setActive(data.record);
    } catch (error) {
      reportError(error, "单次检测失败");
    } finally {
      setBusy(false);
    }
  };

  const applyParams = async () => {
    if (!projectId) return;
    try {
      const data = await api.runtimeParams(projectId, values);
      setStatus((current) => (current ? { ...current, userParams: data.userParams } : current));
      toast("参数已生效", "success");
    } catch (error) {
      reportError(error, "参数保存失败");
    }
  };

  const resetParams = async () => {
    if (!projectId) return;
    const data = await api.runtimeResetParams(projectId);
    const next: Record<string, unknown> = {};
    Object.entries(data.userParams).forEach(([key, spec]) => {
      next[key] = spec.value;
    });
    setValues(next);
    setStatus((current) => (current ? { ...current, userParams: data.userParams } : current));
  };

  if (!status) {
    if (loadError) {
      return (
        <EmptyState
          icon={<MonitorPlay className="h-6 w-6" />}
          title="运行状态加载失败"
          hint="刷新页面或点击重试。若刚发布，请确认后端服务已恢复。"
          action={
            <button className="btn-primary" onClick={() => void refresh()}>
              重试
            </button>
          }
        />
      );
    }
    return (
      <div className="flex h-full items-center justify-center gap-2 text-[13px] text-mute">
        <Spinner /> 加载运行状态…
      </div>
    );
  }

  if (!status.published) {
    return (
      <EmptyState
        icon={<MonitorPlay className="h-6 w-6" />}
        title="流程尚未发布"
        hint="运行页使用已发布的流程版本，保证现场执行的稳定性。请先在流程页调试通过，然后点右上角「发布」。"
        action={
          <button className="btn-primary" onClick={() => navigate(`/projects/${projectId}/pipeline`)}>
            去流程页
          </button>
        }
      />
    );
  }

  const userParams = Object.entries(status.userParams) as [string, UserParamSpec][];

  return (
    <div className="flex h-full min-h-0">
      {/* main */}
      <div className="flex min-w-0 flex-1 flex-col">
        <div className="flex h-11 shrink-0 items-center gap-2 border-b border-line px-2">
          <select
            className="field w-36 py-1"
            value={source}
            onChange={(event) => setSource(event.target.value as "dataset" | "camera")}
            disabled={status.status === "running"}
          >
            <option value="dataset">图片来源：数据集</option>
            <option value="camera">图片来源：相机</option>
          </select>
          {source === "camera" ? (
            <select
              className="field w-44 py-1"
              value={deviceId}
              onChange={(event) => setDeviceId(event.target.value)}
              disabled={status.status === "running"}
            >
              {devices.map((device) => (
                <option key={device.id} value={device.id} disabled={!device.implemented}>
                  {device.name}
                  {device.implemented ? "" : "（未实现）"}
                </option>
              ))}
            </select>
          ) : null}
          <label className="flex items-center gap-1.5 text-[11.5px] text-mute">
            节拍
            <input
              className="field w-20 py-1"
              type="number"
              min={100}
              step={100}
              value={intervalMs}
              onChange={(event) => setIntervalMs(parseInt(event.target.value, 10) || 800)}
              disabled={status.status === "running"}
            />
            ms
          </label>

          {status.status === "running" ? (
            <button className="btn-danger" onClick={stop} disabled={busy}>
              <Square className="h-3.5 w-3.5" /> 停止
            </button>
          ) : (
            <button className="btn-primary" onClick={start} disabled={busy}>
              {busy ? <Spinner /> : <Play className="h-3.5 w-3.5" />} 开始连续检测
            </button>
          )}
          <button className="btn-ghost" onClick={trigger} disabled={busy || status.status === "running"}>
            <Zap className="h-3.5 w-3.5" /> 单次触发
          </button>
          <button
            className="btn-subtle"
            title="清空统计"
            onClick={async () => setStatus(await api.runtimeReset(projectId))}
          >
            <RotateCcw className="h-3.5 w-3.5" />
          </button>

          <div className="flex-1" />
          <Badge tone={status.status === "running" ? "ok" : status.status === "error" ? "ng" : "neutral"}>
            {status.status === "running" ? "运行中" : status.status === "error" ? "异常" : "已停止"}
          </Badge>
          <span className="mono text-[11px] text-mute">v{status.version ?? "—"}</span>
        </div>

        <div className="flex min-h-0 flex-1">
          <div className="flex min-w-0 flex-1 flex-col">
            <div className="grid shrink-0 grid-cols-5 gap-2 border-b border-line p-2.5">
              {[
                ["总数", status.total],
                ["OK", status.okCount],
                ["NG", status.ngCount],
                ["良率", `${status.yieldPercent.toFixed(1)}%`],
                ["平均耗时", formatMs(status.avgDurationMs)],
              ].map(([label, value]) => (
                <div key={String(label)} className="rounded-md border border-line bg-panel-2 px-2 py-1.5">
                  <div className="text-[10.5px] text-mute">{label}</div>
                  <div className="mono text-[15px]">{String(value)}</div>
                </div>
              ))}
            </div>

            {status.alarm ? (
              <div className="border-b border-ng/40 bg-ng/10 px-3 py-1.5 text-[12px] text-ng">
                报警：{status.alarm}
              </div>
            ) : null}

            <div className="relative min-h-0 flex-1">
              <ImageViewer
                src={active?.preview ?? null}
                className="h-full"
                emptyHint="点击「单次触发」或「开始连续检测」查看结果"
              />
              {active ? (
                <div className="pointer-events-none absolute top-2 right-2 flex flex-col items-end gap-1">
                  <div className="pointer-events-auto rounded-md border border-line-solid bg-panel/90 px-2 py-1.5 text-right backdrop-blur">
                    <div className="flex items-center justify-end gap-2">
                      <VerdictBadge verdict={active.verdict} />
                      <span className="mono text-[11px] text-mute">#{active.seq}</span>
                    </div>
                    <div className="mono mt-1 text-[11px] text-mute">
                      {active.imageName} · {formatMs(active.durationMs)}
                    </div>
                    {Object.entries(active.measurements ?? {}).map(([key, value]) => (
                      <div key={key} className="mono text-[11px]">
                        <span className="text-mute">{key}</span>{" "}
                        <span className="text-ink">{formatNumber(value, 3)}</span>
                      </div>
                    ))}
                  </div>
                </div>
              ) : null}
            </div>
          </div>

          <div className="flex w-[220px] shrink-0 flex-col border-l border-line">
            <SectionTitle title="检测记录" hint={`最近 ${status.records.length} 条`} />
            <div className="scroll-y flex-1">
              {status.records.map((record) => (
                <button
                  key={record.id}
                  onClick={() => setActive(record)}
                  className={`flex w-full items-center gap-2 border-b border-line px-2 py-1.5 text-left transition ${
                    active?.id === record.id ? "bg-panel-2" : "hover:bg-panel-2/60"
                  }`}
                >
                  <span className="mono w-8 text-[10.5px] text-mute/70">#{record.seq}</span>
                  <VerdictBadge verdict={record.verdict} />
                  <span className="flex-1 truncate text-[11px] text-mute">{record.imageName}</span>
                  <span className="mono text-[10px] text-mute/70">{formatMs(record.durationMs)}</span>
                </button>
              ))}
              {status.records.length === 0 ? (
                <EmptyState icon={<Gauge className="h-5 w-5" />} title="暂无记录" />
              ) : null}
            </div>
          </div>
        </div>
      </div>

      {/* operator params */}
      <div className="flex w-[280px] shrink-0 flex-col border-l border-line">
        <SectionTitle
          title="现场参数"
          hint="只暴露业务级参数，改完点应用"
          actions={
            <button className="btn-subtle px-1.5 py-1" title="恢复默认" onClick={resetParams}>
              <RotateCcw className="h-3.5 w-3.5" />
            </button>
          }
        />
        <div className="scroll-y flex-1 p-2.5">
          {userParams.length === 0 ? (
            <EmptyState
              icon={<SlidersHorizontal className="h-5 w-5" />}
              title="没有现场可调参数"
              hint="在流程里使用带「业务」标记的参数（如面积阈值、判定上下限），发布后会出现在这里。"
            />
          ) : (
            <>
              {userParams.map(([key, spec]) => (
                <div key={key} className="mb-3 border-b border-line pb-2.5 last:border-0">
                  <div className="mb-1 text-[10.5px] text-mute/70">{spec.nodeLabel}</div>
                  <ParamControl
                    compact
                    spec={{
                      name: spec.param,
                      type: spec.type,
                      default: spec.default,
                      label: spec.label,
                      min: spec.min,
                      max: spec.max,
                      step: spec.step,
                      options: spec.options,
                      level: "business",
                      unit: spec.unit,
                      description: spec.description,
                      dependsOn: null,
                    }}
                    value={values[key] ?? spec.value}
                    onChange={(value) => setValues((current) => ({ ...current, [key]: value }))}
                  />
                </div>
              ))}
              <button className="btn-primary w-full" onClick={applyParams}>
                应用参数
              </button>
            </>
          )}
        </div>
        <div className="border-t border-line px-2.5 py-2 text-[10.5px] leading-relaxed text-mute">
          <Camera className="mr-1 inline h-3 w-3" />
          相机采集当前为模拟实现（文件夹回放），接入真实工业相机只需实现设备适配器。
        </div>
      </div>
    </div>
  );
}
