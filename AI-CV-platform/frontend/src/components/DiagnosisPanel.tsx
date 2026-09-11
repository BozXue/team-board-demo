import { AlertOctagon, AlertTriangle, CheckCircle2, Info } from "lucide-react";
import type { Diagnosis } from "../api/types";
import { formatNumber } from "./ui";

const ICONS = {
  ok: <CheckCircle2 className="h-3.5 w-3.5 text-ok" />,
  info: <Info className="h-3.5 w-3.5 text-brand" />,
  warning: <AlertTriangle className="h-3.5 w-3.5 text-warn" />,
  critical: <AlertOctagon className="h-3.5 w-3.5 text-ng" />,
};

const METRIC_LABELS: Record<string, string> = {
  mean: "平均亮度",
  std: "对比度(std)",
  p1: "暗部 1%",
  p99: "亮部 99%",
  clipLow: "欠曝比例",
  clipHigh: "过曝比例",
  sharpness: "清晰度",
  noise: "噪声",
  uniformity: "均匀性",
  textureEnergy: "纹理能量",
  saturation: "饱和度",
  edgeDensity: "边缘密度",
};

export function DiagnosisPanel({ diagnosis }: { diagnosis: Diagnosis }) {
  const metrics = Object.entries(diagnosis.metrics ?? {});
  return (
    <div className="space-y-2">
      {metrics.length ? (
        <div className="grid grid-cols-2 gap-1.5">
          {metrics.map(([key, value]) => (
            <div key={key} className="rounded-md border border-line bg-panel-2 px-2 py-1.5">
              <div className="text-[10.5px] text-mute">{METRIC_LABELS[key] ?? key}</div>
              <div className="mono text-[12.5px]">{formatNumber(value, 2)}</div>
            </div>
          ))}
        </div>
      ) : null}

      <div className="space-y-1.5">
        {(diagnosis.findings ?? []).map((finding) => (
          <div key={finding.key} className="rounded-md border border-line bg-panel-2 px-2 py-1.5">
            <div className="flex items-center gap-1.5 text-[12.5px] font-medium">
              {ICONS[finding.level]} {finding.title}
            </div>
            <div className="mt-0.5 text-[11.5px] leading-relaxed text-mute">{finding.detail}</div>
            {finding.advice ? (
              <div className="mt-1 text-[11.5px] leading-relaxed text-brand/90">建议：{finding.advice}</div>
            ) : null}
          </div>
        ))}
      </div>
    </div>
  );
}
