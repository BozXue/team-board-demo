import { Crop, Lock } from "lucide-react";
import type { ParamSpec } from "../../api/types";
import { Toggle } from "../ui";

interface Props {
  spec: ParamSpec;
  value: unknown;
  onChange: (value: unknown) => void;
  labels?: string[];
  onPickRect?: () => void;
  compact?: boolean;
}

export function ParamControl({ spec, value, onChange, labels = [], onPickRect, compact }: Props) {
  const locked = spec.level === "locked";
  const numeric = spec.type === "int" || spec.type === "float";
  const step = spec.step ?? (spec.type === "int" ? 1 : 0.1);
  const hasRange = numeric && spec.min !== null && spec.max !== null;

  const parse = (raw: string): number => {
    const parsed = spec.type === "int" ? parseInt(raw, 10) : parseFloat(raw);
    if (Number.isNaN(parsed)) return 0;
    return parsed;
  };

  return (
    <div className={compact ? "" : "mb-2.5"}>
      <div className="mb-1 flex items-center gap-1.5">
        <span className="text-[11.5px] text-mute">{spec.label}</span>
        {spec.unit ? <span className="text-[10px] text-mute/60">{spec.unit}</span> : null}
        {spec.level === "business" ? (
          <span className="chip bg-brand/15 text-[9.5px] text-brand">业务</span>
        ) : null}
        {locked ? <Lock className="h-3 w-3 text-mute/60" /> : null}
        <div className="flex-1" />
        {numeric ? <span className="mono text-[11px] text-ink/90">{String(value ?? "")}</span> : null}
      </div>

      {spec.type === "bool" ? (
        <Toggle checked={Boolean(value)} onChange={(next) => !locked && onChange(next)} />
      ) : spec.type === "enum" ? (
        <select
          className="field"
          disabled={locked}
          value={String(value ?? "")}
          onChange={(event) => onChange(event.target.value)}
        >
          {spec.options.map((option) => (
            <option key={String(option)} value={String(option)}>
              {String(option)}
            </option>
          ))}
        </select>
      ) : spec.type === "label" ? (
        <select
          className="field"
          disabled={locked}
          value={String(value ?? "")}
          onChange={(event) => onChange(event.target.value)}
        >
          <option value="">（未选择）</option>
          {labels.map((label) => (
            <option key={label} value={label}>
              {label}
            </option>
          ))}
        </select>
      ) : spec.type === "text" ? (
        <textarea
          className="field h-16 resize-none"
          disabled={locked}
          value={String(value ?? "")}
          onChange={(event) => onChange(event.target.value)}
        />
      ) : spec.type === "color" ? (
        <div className="flex items-center gap-2">
          <input
            type="color"
            className="h-7 w-10 rounded border border-line-solid bg-panel-2"
            disabled={locked}
            value={String(value ?? "#38bdf8")}
            onChange={(event) => onChange(event.target.value)}
          />
          <input
            className="field"
            disabled={locked}
            value={String(value ?? "")}
            onChange={(event) => onChange(event.target.value)}
          />
        </div>
      ) : spec.type === "rect" ? (
        <div className="space-y-1.5">
          <div className="grid grid-cols-4 gap-1">
            {["x", "y", "w", "h"].map((key, index) => (
              <input
                key={key}
                className="field px-1.5 text-center"
                disabled={locked}
                type="number"
                value={Number((value as number[])?.[index] ?? 0)}
                onChange={(event) => {
                  const current = Array.isArray(value) ? [...(value as number[])] : [0, 0, 0, 0];
                  current[index] = parseInt(event.target.value, 10) || 0;
                  onChange(current);
                }}
              />
            ))}
          </div>
          {onPickRect ? (
            <button className="btn-ghost w-full py-1 text-[11.5px]" onClick={onPickRect} disabled={locked}>
              <Crop className="h-3.5 w-3.5" /> 在图上框选
            </button>
          ) : null}
        </div>
      ) : numeric ? (
        <div className="flex items-center gap-2">
          {hasRange ? (
            <input
              type="range"
              disabled={locked}
              min={spec.min ?? 0}
              max={spec.max ?? 100}
              step={step}
              value={Number(value ?? 0)}
              onChange={(event) => onChange(parse(event.target.value))}
            />
          ) : null}
          <input
            className="field w-20 px-1.5 py-1 text-center"
            disabled={locked}
            type="number"
            step={step}
            min={spec.min ?? undefined}
            max={spec.max ?? undefined}
            value={Number(value ?? 0)}
            onChange={(event) => onChange(parse(event.target.value))}
          />
        </div>
      ) : (
        <input
          className="field"
          disabled={locked}
          value={String(value ?? "")}
          onChange={(event) => onChange(event.target.value)}
        />
      )}

      {spec.description ? (
        <div className="mt-1 text-[10.5px] leading-relaxed text-mute/80">{spec.description}</div>
      ) : null}
    </div>
  );
}

export function isVisible(spec: ParamSpec, params: Record<string, unknown>): boolean {
  if (!spec.dependsOn) return true;
  const current = params[spec.dependsOn.param];
  return spec.dependsOn.values.some((value) => value === current);
}
