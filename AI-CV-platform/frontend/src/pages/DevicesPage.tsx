import { useCallback, useEffect, useState } from "react";
import { Cable, Camera, Cpu, Plug, PlugZap, RefreshCw } from "lucide-react";
import { api } from "../api/client";
import type { DeviceStatus } from "../api/types";
import { Badge, Spinner, formatTime } from "../components/ui";
import { useApp } from "../store/app";

const KIND_ICONS: Record<string, typeof Camera> = {
  camera: Camera,
  io: Cable,
  light: Cpu,
};

export default function DevicesPage() {
  const { projects, toast, reportError } = useApp();
  const [devices, setDevices] = useState<DeviceStatus[]>([]);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [grabTarget, setGrabTarget] = useState<Record<string, string>>({});
  const [lastGrab, setLastGrab] = useState<{ url: string; label: string } | null>(null);

  const refresh = useCallback(async () => {
    try {
      const data = await api.listDevices();
      setDevices(data.devices);
      setNote(data.note);
    } catch (error) {
      reportError(error, "设备列表加载失败");
    }
  }, [reportError]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const act = async (device: DeviceStatus, action: "connect" | "disconnect") => {
    setBusy(device.id);
    try {
      const updated =
        action === "connect" ? await api.connectDevice(device.id) : await api.disconnectDevice(device.id);
      setDevices((current) => current.map((item) => (item.id === updated.id ? updated : item)));
    } catch (error) {
      reportError(error, "设备操作失败");
    } finally {
      setBusy(null);
    }
  };

  const grab = async (device: DeviceStatus) => {
    setBusy(device.id);
    try {
      const projectId = grabTarget[device.id] || undefined;
      const data = await api.grabDevice(device.id, projectId);
      if (data.image) {
        setLastGrab({ url: data.image.previewUrl, label: `${device.name} · ${data.image.filename}` });
        toast(`已采集并存入数据集：${data.image.filename}`, "success");
      } else {
        toast(`采集成功：${data.width}×${data.height}（未保存，选择项目后可入库）`, "success");
      }
      await refresh();
    } catch (error) {
      reportError(error, "采图失败");
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="mx-auto max-w-6xl px-6 py-6">
      <div className="mb-4 flex items-end justify-between">
        <div>
          <h1 className="text-lg font-semibold">设备与采集</h1>
          <p className="mt-0.5 max-w-3xl text-[12.5px] leading-relaxed text-mute">{note}</p>
        </div>
        <button className="btn-ghost" onClick={refresh}>
          <RefreshCw className="h-3.5 w-3.5" /> 刷新
        </button>
      </div>

      {devices.length === 0 ? (
        <Spinner />
      ) : (
        <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
          {devices.map((device) => {
            const Icon = KIND_ICONS[device.kind] ?? Cpu;
            const connected = device.state === "connected";
            return (
              <div key={device.id} className="panel p-3.5">
                <div className="flex items-start gap-2.5">
                  <div
                    className={`grid h-9 w-9 shrink-0 place-items-center rounded-md ${
                      device.implemented ? "bg-brand-dim/15 text-brand" : "bg-panel-3 text-mute"
                    }`}
                  >
                    <Icon className="h-4 w-4" />
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-1.5">
                      <span className="truncate text-[13px] font-medium">{device.name}</span>
                      <Badge tone={connected ? "ok" : device.state === "error" ? "ng" : "neutral"}>
                        {connected ? "已连接" : device.state === "error" ? "错误" : "未连接"}
                      </Badge>
                      {device.implemented ? null : <Badge tone="warn">接口预留</Badge>}
                    </div>
                    <div className="mono mt-0.5 text-[10.5px] text-mute">
                      {device.id} · {device.vendor} {device.model}
                    </div>
                    <p className="mt-1.5 text-[11.5px] leading-relaxed text-mute">{device.note}</p>
                    <div className="mt-1.5 flex flex-wrap gap-1">
                      {device.capabilities.map((capability) => (
                        <span key={capability} className="chip bg-panel-3 text-mute">
                          {capability}
                        </span>
                      ))}
                    </div>
                    {device.lastError ? (
                      <div className="mt-1.5 rounded-md border border-ng/40 bg-ng/10 px-2 py-1 text-[11px] text-ng">
                        {device.lastError}
                      </div>
                    ) : null}
                  </div>
                </div>

                <div className="mt-3 flex flex-wrap items-center gap-1.5">
                  <button
                    className="btn-ghost"
                    disabled={!device.implemented || busy === device.id}
                    onClick={() => act(device, connected ? "disconnect" : "connect")}
                  >
                    {connected ? <Plug className="h-3.5 w-3.5" /> : <PlugZap className="h-3.5 w-3.5" />}
                    {connected ? "断开" : "连接"}
                  </button>
                  <select
                    className="field w-40 py-1"
                    value={grabTarget[device.id] ?? ""}
                    onChange={(event) =>
                      setGrabTarget((current) => ({ ...current, [device.id]: event.target.value }))
                    }
                  >
                    <option value="">采图不入库</option>
                    {projects.map((project) => (
                      <option key={project.id} value={project.id}>
                        存入：{project.name}
                      </option>
                    ))}
                  </select>
                  <button
                    className="btn-primary"
                    disabled={!device.implemented || busy === device.id}
                    onClick={() => grab(device)}
                  >
                    {busy === device.id ? <Spinner /> : <Camera className="h-3.5 w-3.5" />} 采集一张
                  </button>
                  {Object.keys(device.settings ?? {}).length ? (
                    <span className="mono text-[10.5px] text-mute">
                      {Object.entries(device.settings)
                        .map(([key, value]) => `${key}=${String(value)}`)
                        .join(" · ")}
                    </span>
                  ) : null}
                </div>
              </div>
            );
          })}
        </div>
      )}

      {lastGrab ? (
        <div className="panel mt-4 p-3">
          <div className="mb-2 text-[12.5px]">
            最近采集：<span className="text-mute">{lastGrab.label}</span>
            <span className="ml-2 text-[11px] text-mute/70">{formatTime(new Date().toISOString())}</span>
          </div>
          <img src={lastGrab.url} alt="最近采集" className="max-h-72 rounded-md border border-line" />
        </div>
      ) : null}
    </div>
  );
}
