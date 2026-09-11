import type { ReactNode } from "react";
import { useEffect, useRef, useState } from "react";
import { AlertTriangle, CheckCircle2, Info, Loader2, X } from "lucide-react";
import { useApp } from "../store/app";

export function Spinner({ className = "" }: { className?: string }) {
  return <Loader2 className={`h-4 w-4 animate-spin ${className}`} />;
}

export function SectionTitle({
  title,
  hint,
  actions,
}: {
  title: string;
  hint?: string;
  actions?: ReactNode;
}) {
  return (
    <div className="flex items-center justify-between gap-3 border-b border-line px-3 py-2">
      <div className="min-w-0">
        <div className="truncate text-[13px] font-semibold">{title}</div>
        {hint ? <div className="truncate text-[11px] text-mute">{hint}</div> : null}
      </div>
      {actions ? <div className="flex shrink-0 items-center gap-1.5">{actions}</div> : null}
    </div>
  );
}

export function EmptyState({
  title,
  hint,
  icon,
  action,
}: {
  title: string;
  hint?: string;
  icon?: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-2 p-8 text-center">
      {icon ? <div className="text-mute/70">{icon}</div> : null}
      <div className="text-[13px] font-medium text-ink/90">{title}</div>
      {hint ? <div className="max-w-sm text-[12px] leading-relaxed text-mute">{hint}</div> : null}
      {action ? <div className="mt-2">{action}</div> : null}
    </div>
  );
}

export function Badge({
  children,
  tone = "neutral",
}: {
  children: ReactNode;
  tone?: "neutral" | "ok" | "ng" | "warn" | "brand";
}) {
  const tones: Record<string, string> = {
    neutral: "bg-panel-3 text-mute",
    ok: "bg-ok/15 text-ok",
    ng: "bg-ng/15 text-ng",
    warn: "bg-warn/15 text-warn",
    brand: "bg-brand/15 text-brand",
  };
  return <span className={`chip ${tones[tone]}`}>{children}</span>;
}

export function VerdictBadge({ verdict }: { verdict: string }) {
  const map: Record<string, { tone: "ok" | "ng" | "warn" | "neutral"; text: string }> = {
    OK: { tone: "ok", text: "OK" },
    NG: { tone: "ng", text: "NG" },
    ERROR: { tone: "warn", text: "错误" },
    UNKNOWN: { tone: "neutral", text: "未判定" },
  };
  const item = map[(verdict ?? "").toUpperCase()] ?? { tone: "neutral" as const, text: verdict || "—" };
  return <Badge tone={item.tone}>{item.text}</Badge>;
}

export function Modal({
  open,
  title,
  onClose,
  children,
  footer,
  width = "max-w-lg",
}: {
  open: boolean;
  title: string;
  onClose: () => void;
  children: ReactNode;
  footer?: ReactNode;
  width?: string;
}) {
  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
      <div className={`panel w-full ${width} shadow-2xl`}>
        <div className="flex items-center justify-between border-b border-line px-4 py-2.5">
          <div className="text-[13px] font-semibold">{title}</div>
          <button className="btn-subtle px-1.5 py-1" onClick={onClose} aria-label="关闭">
            <X className="h-4 w-4" />
          </button>
        </div>
        <div className="scroll-y max-h-[70vh] px-4 py-3">{children}</div>
        {footer ? (
          <div className="flex justify-end gap-2 border-t border-line px-4 py-2.5">{footer}</div>
        ) : null}
      </div>
    </div>
  );
}

export function Toasts() {
  const toasts = useApp((s) => s.toasts);
  const dismiss = useApp((s) => s.dismissToast);
  const icons = {
    info: <Info className="h-4 w-4 text-brand" />,
    success: <CheckCircle2 className="h-4 w-4 text-ok" />,
    error: <AlertTriangle className="h-4 w-4 text-ng" />,
  };
  return (
    <div className="pointer-events-none fixed bottom-4 left-1/2 z-[60] flex -translate-x-1/2 flex-col items-center gap-2">
      {toasts.map((toast) => (
        <div
          key={toast.id}
          className="panel pointer-events-auto flex max-w-[520px] items-start gap-2 px-3 py-2 text-[12.5px] shadow-xl"
          onClick={() => dismiss(toast.id)}
        >
          <div className="mt-px shrink-0">{icons[toast.level]}</div>
          <div className="whitespace-pre-wrap">{toast.message}</div>
        </div>
      ))}
    </div>
  );
}

export function Tabs<T extends string>({
  tabs,
  value,
  onChange,
}: {
  tabs: { value: T; label: string; count?: number }[];
  value: T;
  onChange: (value: T) => void;
}) {
  return (
    <div className="flex items-center gap-1 border-b border-line px-2">
      {tabs.map((tab) => (
        <button
          key={tab.value}
          onClick={() => onChange(tab.value)}
          className={`-mb-px border-b-2 px-2.5 py-2 text-[12.5px] transition ${
            value === tab.value
              ? "border-brand text-ink"
              : "border-transparent text-mute hover:text-ink"
          }`}
        >
          {tab.label}
          {tab.count !== undefined ? (
            <span className="ml-1.5 text-[11px] text-mute">{tab.count}</span>
          ) : null}
        </button>
      ))}
    </div>
  );
}

export function Toggle({
  checked,
  onChange,
  label,
}: {
  checked: boolean;
  onChange: (value: boolean) => void;
  label?: string;
}) {
  return (
    <button
      onClick={() => onChange(!checked)}
      className="inline-flex items-center gap-2 text-[12.5px] text-mute hover:text-ink"
    >
      <span
        className={`relative h-4 w-7 rounded-full transition ${checked ? "bg-brand-dim" : "bg-panel-3"}`}
      >
        <span
          className={`absolute top-0.5 h-3 w-3 rounded-full bg-white transition-all ${
            checked ? "left-3.5" : "left-0.5"
          }`}
        />
      </span>
      {label}
    </button>
  );
}

export function Confirm({
  open,
  title,
  message,
  confirmText = "确认",
  onConfirm,
  onCancel,
}: {
  open: boolean;
  title: string;
  message: string;
  confirmText?: string;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  return (
    <Modal
      open={open}
      title={title}
      onClose={onCancel}
      width="max-w-sm"
      footer={
        <>
          <button className="btn-ghost" onClick={onCancel}>
            取消
          </button>
          <button className="btn-danger" onClick={onConfirm}>
            {confirmText}
          </button>
        </>
      }
    >
      <div className="text-[12.5px] leading-relaxed text-mute">{message}</div>
    </Modal>
  );
}

export function useDebounced<T>(value: T, delay = 300): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const timer = window.setTimeout(() => setDebounced(value), delay);
    return () => window.clearTimeout(timer);
  }, [value, delay]);
  return debounced;
}

export function usePolling(callback: () => void, intervalMs: number | null) {
  const ref = useRef(callback);
  ref.current = callback;
  useEffect(() => {
    if (intervalMs === null) return;
    const timer = window.setInterval(() => ref.current(), intervalMs);
    return () => window.clearInterval(timer);
  }, [intervalMs]);
}

export function formatBytes(bytes: number): string {
  if (!bytes) return "0 B";
  const units = ["B", "KB", "MB", "GB"];
  const index = Math.min(units.length - 1, Math.floor(Math.log(bytes) / Math.log(1024)));
  return `${(bytes / 1024 ** index).toFixed(index === 0 ? 0 : 1)} ${units[index]}`;
}

export function formatMs(ms: number): string {
  if (ms < 1) return "<1ms";
  if (ms < 1000) return `${ms.toFixed(ms < 10 ? 1 : 0)}ms`;
  return `${(ms / 1000).toFixed(2)}s`;
}

export function formatNumber(value: unknown, digits = 3): string {
  if (typeof value === "number") {
    if (Number.isInteger(value)) return String(value);
    return value.toFixed(digits);
  }
  if (value === null || value === undefined) return "—";
  if (typeof value === "boolean") return value ? "true" : "false";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

export function formatTime(iso: string): string {
  if (!iso) return "—";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return date.toLocaleString("zh-CN", { hour12: false });
}
