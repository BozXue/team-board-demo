import { useMemo } from "react";
import { Area, AreaChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

const COLORS: Record<string, string> = {
  gray: "#8ba0bb",
  b: "#60a5fa",
  g: "#34d399",
  r: "#fb7185",
};

export function Histogram({
  channels,
  height = 110,
}: {
  channels: Record<string, number[]>;
  height?: number;
}) {
  const keys = useMemo(() => Object.keys(channels), [channels]);
  const data = useMemo(() => {
    const bins = channels[keys[0]]?.length ?? 0;
    return Array.from({ length: bins }, (_, index) => {
      const row: Record<string, number> = { bin: Math.round((index * 255) / Math.max(1, bins - 1)) };
      keys.forEach((key) => {
        row[key] = channels[key][index] ?? 0;
      });
      return row;
    });
  }, [channels, keys]);

  if (!keys.length) return null;

  return (
    <div style={{ height }}>
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={data} margin={{ top: 4, right: 4, bottom: 0, left: 0 }}>
          <XAxis
            dataKey="bin"
            tick={{ fill: "#8ba0bb", fontSize: 10 }}
            stroke="#243146"
            ticks={[0, 64, 128, 192, 255]}
          />
          <YAxis hide />
          <Tooltip
            contentStyle={{
              background: "#111823",
              border: "1px solid #243146",
              borderRadius: 6,
              fontSize: 11,
            }}
            labelFormatter={(value) => `灰度 ${value}`}
          />
          {keys.map((key) => (
            <Area
              key={key}
              type="monotone"
              dataKey={key}
              stroke={COLORS[key] ?? "#38bdf8"}
              fill={COLORS[key] ?? "#38bdf8"}
              fillOpacity={0.22}
              strokeWidth={1.2}
              isAnimationActive={false}
            />
          ))}
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}
