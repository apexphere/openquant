"use client";
import {
  ComposedChart,
  Line,
  ReferenceArea,
  ReferenceDot,
  XAxis,
  YAxis,
  ResponsiveContainer,
  Tooltip,
} from "recharts";
import type { RegimePeriod, ChartData } from "@/lib/types";

const REGIME_COLORS: Record<string, string> = {
  "trending-up": "rgba(63,185,80,0.15)",
  "trending-down": "rgba(248,81,73,0.15)",
  "ranging-up": "rgba(139,148,158,0.1)",
  "ranging-down": "rgba(139,148,158,0.1)",
  ranging: "rgba(139,148,158,0.1)",
  "cold-start": "rgba(56,139,253,0.1)",
};

const REGIME_TEXT_COLORS: Record<string, string> = {
  "trending-up": "#3fb950",
  "trending-down": "#f85149",
  "ranging-up": "#8b949e",
  "ranging-down": "#8b949e",
  ranging: "#8b949e",
  "cold-start": "#58a6ff",
};

interface RegimeTimelineProps {
  chartData: ChartData | null;
  regimePeriods: RegimePeriod[] | null;
  trades?: Array<{
    opened_at: number;
    closed_at: number;
    type: string;
    entry_price: number;
    exit_price: number;
  }>;
}

function lttbDownsample(
  data: Array<{ time: number; close: number }>,
  target: number
): Array<{ time: number; close: number }> {
  if (data.length <= target) return data;

  const sampled: Array<{ time: number; close: number }> = [data[0]];
  const bucketSize = (data.length - 2) / (target - 2);

  let prevIndex = 0;

  for (let i = 0; i < target - 2; i++) {
    const rangeStart = Math.floor((i + 1) * bucketSize) + 1;
    const rangeEnd = Math.min(
      Math.floor((i + 2) * bucketSize) + 1,
      data.length - 1
    );

    // Average of next bucket for area calculation
    let avgX = 0;
    let avgY = 0;
    for (let j = rangeStart; j < rangeEnd; j++) {
      avgX += data[j].time;
      avgY += data[j].close;
    }
    avgX /= rangeEnd - rangeStart || 1;
    avgY /= rangeEnd - rangeStart || 1;

    // Find point in current bucket with largest triangle area
    const currStart = Math.floor(i * bucketSize) + 1;
    const currEnd = Math.min(Math.floor((i + 1) * bucketSize) + 1, data.length);

    let maxArea = -1;
    let maxIndex = currStart;

    for (let j = currStart; j < currEnd; j++) {
      const area = Math.abs(
        (data[prevIndex].time - avgX) * (data[j].close - data[prevIndex].close) -
          (data[prevIndex].time - data[j].time) * (avgY - data[prevIndex].close)
      );
      if (area > maxArea) {
        maxArea = area;
        maxIndex = j;
      }
    }

    sampled.push(data[maxIndex]);
    prevIndex = maxIndex;
  }

  sampled.push(data[data.length - 1]);
  return sampled;
}

export function RegimeTimeline({
  chartData,
  regimePeriods,
  trades,
}: RegimeTimelineProps) {
  if (!regimePeriods && !chartData) {
    return (
      <div className="bg-[var(--bg-surface)] border border-[var(--border)] rounded-lg p-4">
        <div className="text-[var(--text-secondary)] text-center py-8">
          No regime or chart data available. Run a backtest with a regime detector enabled.
        </div>
      </div>
    );
  }

  // Regime bar (always shown if regimePeriods exist)
  const regimeBar = regimePeriods && regimePeriods.length > 0 && (
    <div className="flex h-7 rounded overflow-hidden mb-2">
      {regimePeriods.map((period, i) => {
        const totalDuration =
          regimePeriods[regimePeriods.length - 1].end - regimePeriods[0].start;
        const width = ((period.end - period.start) / totalDuration) * 100;
        const regime = period.regime;
        return (
          <div
            key={i}
            className="flex items-center justify-center text-[10px] font-semibold tracking-wide"
            style={{
              width: `${width}%`,
              backgroundColor: REGIME_COLORS[regime] ?? "rgba(139,148,158,0.1)",
              color: REGIME_TEXT_COLORS[regime] ?? "#8b949e",
            }}
          >
            {width > 8 ? regime.toUpperCase().replace("-", " ") : ""}
          </div>
        );
      })}
    </div>
  );

  // Price chart (only if chartData exists)
  let priceChart = null;
  if (chartData?.candles_chart && chartData.candles_chart.length > 0) {
    const raw = chartData.candles_chart.map((c) => ({
      time: c[0],
      close: c[4], // OHLCV: [time, open, high, low, close, volume]
    }));

    const downsampled = lttbDownsample(raw, 2000);

    priceChart = (
      <ResponsiveContainer width="100%" height={250}>
        <ComposedChart
          data={downsampled}
          margin={{ top: 5, right: 5, bottom: 5, left: 5 }}
        >
          <XAxis
            dataKey="time"
            tick={false}
            axisLine={{ stroke: "var(--border)" }}
          />
          <YAxis
            domain={["auto", "auto"]}
            tick={{ fill: "var(--text-secondary)", fontSize: 11 }}
            axisLine={false}
            tickLine={false}
            width={60}
            tickFormatter={(v: number) =>
              v >= 1000 ? `$${(v / 1000).toFixed(1)}k` : `$${v}`
            }
          />
          <Tooltip
            contentStyle={{
              background: "var(--bg-surface)",
              border: "1px solid var(--border)",
              borderRadius: 6,
              fontSize: 12,
            }}
            labelFormatter={(ts: number) =>
              new Date(ts).toLocaleDateString()
            }
            formatter={(value: number) => [`$${value.toFixed(2)}`, "Price"]}
          />

          {/* Regime background shading */}
          {regimePeriods?.map((period, i) => (
            <ReferenceArea
              key={i}
              x1={period.start}
              x2={period.end}
              fill={REGIME_COLORS[period.regime] ?? "transparent"}
              fillOpacity={1}
            />
          ))}

          <Line
            type="monotone"
            dataKey="close"
            stroke="var(--text-primary)"
            strokeWidth={1.5}
            dot={false}
            isAnimationActive={false}
          />

          {/* Trade entry markers */}
          {trades?.map((trade, i) => (
            <ReferenceDot
              key={`entry-${i}`}
              x={trade.opened_at}
              y={trade.entry_price}
              r={4}
              fill={trade.type === "long" ? "var(--green)" : "var(--red)"}
              stroke="none"
            />
          ))}

          {/* Trade exit markers */}
          {trades?.map((trade, i) => (
            <ReferenceDot
              key={`exit-${i}`}
              x={trade.closed_at}
              y={trade.exit_price}
              r={3}
              fill="none"
              stroke="var(--text-secondary)"
              strokeWidth={1.5}
            />
          ))}
        </ComposedChart>
      </ResponsiveContainer>
    );
  }

  return (
    <div className="bg-[var(--bg-surface)] border border-[var(--border)] rounded-lg p-4">
      <div className="text-[13px] font-semibold text-[var(--text-heading)] mb-3">
        Regime Timeline + Price Action
      </div>
      {regimeBar}
      {priceChart ?? (
        <div className="text-[var(--text-secondary)] text-center py-8 text-sm">
          No chart data. Re-run this backtest to generate price chart.
        </div>
      )}
      <div className="flex gap-4 mt-2 text-[11px] text-[var(--text-secondary)]">
        <span className="flex items-center gap-1">
          <span className="w-2 h-2 rounded-sm bg-[var(--text-primary)]" /> Price
        </span>
        <span className="flex items-center gap-1">
          <span className="w-2 h-2 rounded-full bg-[var(--green)]" /> Long Entry
        </span>
        <span className="flex items-center gap-1">
          <span className="w-2 h-2 rounded-full bg-[var(--red)]" /> Short Entry
        </span>
        <span className="flex items-center gap-1">
          <span className="w-2 h-2 rounded-full border border-[var(--text-secondary)]" /> Exit
        </span>
      </div>
    </div>
  );
}
