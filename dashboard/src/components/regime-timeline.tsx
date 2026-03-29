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
  "trending-up": "#134a25",
  "trending-down": "#4a1313",
  "ranging-up": "#2a2a38",
  "ranging-down": "#2a2a38",
  ranging: "#2a2a38",
  "cold-start": "#133044",
};

const REGIME_TEXT_COLORS: Record<string, string> = {
  "trending-up": "#3fb950",
  "trending-down": "#f85149",
  "ranging-up": "#8b949e",
  "ranging-down": "#8b949e",
  ranging: "#8b949e",
  "cold-start": "#58a6ff",
};

interface EquityCurvePoint {
  time: number;
  value: number;
}

interface RegimeTimelineProps {
  chartData: ChartData | null;
  regimePeriods: RegimePeriod[] | null;
  equityCurve?: EquityCurvePoint[] | null;
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
  equityCurve,
  trades,
}: RegimeTimelineProps) {
  if (!regimePeriods && !chartData && !equityCurve) {
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

  // Build merged chart data: price + equity on same time axis
  let priceChart = null;
  const hasCandles = chartData?.candles_chart && chartData.candles_chart.length > 0;
  const hasEquity = equityCurve && equityCurve.length > 0;

  if (hasCandles || hasEquity) {
    // Build price data
    // Extract candle data — candles_chart is [{exchange, symbol, timeframe, candles: [{time, open, close, high, low, volume}]}]
    let priceData: Array<{ time: number; close: number }> = [];
    if (hasCandles) {
      const candlesList = (chartData!.candles_chart as any);
      const rawCandles = Array.isArray(candlesList) && candlesList.length > 0 && candlesList[0].candles
        ? candlesList[0].candles
        : candlesList;
      const raw = rawCandles.map((c: any) => ({
        time: (c.time ?? c[0]) * 1000, // convert seconds to ms
        close: c.close ?? c[4],
      }));
      priceData = lttbDownsample(raw, 2000);
    }

    // Build equity data — already daily, times in seconds
    const equityData: Array<{ time: number; value: number }> = [];
    if (hasEquity) {
      for (const pt of equityCurve!) {
        equityData.push({ time: pt.time * 1000, value: pt.value }); // seconds to ms
      }
    }

    // Merge: price as base, map equity value for each price point
    // Use binary search to find the closest equity point <= each price timestamp
    function findEquityValue(time: number): number | undefined {
      if (equityData.length === 0) return undefined;
      if (time <= equityData[0].time) return equityData[0].value;
      if (time >= equityData[equityData.length - 1].time) return equityData[equityData.length - 1].value;
      let lo = 0, hi = equityData.length - 1;
      while (lo < hi - 1) {
        const mid = Math.floor((lo + hi) / 2);
        if (equityData[mid].time <= time) lo = mid;
        else hi = mid;
      }
      return equityData[lo].value;
    }

    let mergedData: Array<{ time: number; close?: number; equity?: number }>;

    if (priceData.length > 0 && equityData.length > 0) {
      mergedData = priceData.map((p) => ({
        time: p.time,
        close: p.close,
        equity: findEquityValue(p.time),
      }));
    } else if (priceData.length > 0) {
      mergedData = priceData.map((p) => ({ time: p.time, close: p.close }));
    } else if (equityData.length > 0) {
      mergedData = equityData.map((pt) => ({ time: pt.time, equity: pt.value }));
    } else {
      mergedData = [];
    }

    priceChart = (
      <ResponsiveContainer width="100%" height={300}>
        <ComposedChart
          data={mergedData}
          margin={{ top: 5, right: 60, bottom: 5, left: 5 }}
        >
          <XAxis
            dataKey="time"
            tick={false}
            axisLine={{ stroke: "var(--border)" }}
          />
          {/* Left axis: Price */}
          {hasCandles && (
            <YAxis
              yAxisId="price"
              orientation="left"
              domain={["auto", "auto"]}
              tick={{ fill: "var(--text-secondary)", fontSize: 11 }}
              axisLine={false}
              tickLine={false}
              width={60}
              tickFormatter={(v: number) =>
                v >= 1000 ? `$${(v / 1000).toFixed(1)}k` : `$${v.toFixed(0)}`
              }
            />
          )}
          {/* Right axis: Equity */}
          {hasEquity && (
            <YAxis
              yAxisId="equity"
              orientation="right"
              domain={["auto", "auto"]}
              tick={{ fill: "var(--green)", fontSize: 11 }}
              axisLine={false}
              tickLine={false}
              width={55}
              tickFormatter={(v: number) => `$${(v / 1000).toFixed(1)}k`}
            />
          )}
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
            formatter={(value: number, name: string) => [
              `$${value.toFixed(2)}`,
              name === "close" ? "Price" : "Portfolio",
            ]}
          />

          {/* Regime background shading — full height colored bands */}
          {regimePeriods?.map((period, i) => (
            <ReferenceArea
              key={i}
              x1={period.start}
              x2={period.end}
              fill={REGIME_COLORS[period.regime] ?? "transparent"}
              fillOpacity={0.8}
              yAxisId={hasCandles ? "price" : "equity"}
              ifOverflow="extendDomain"
              label={undefined}
            />
          ))}

          {/* Price line */}
          {hasCandles && (
            <Line
              yAxisId="price"
              type="monotone"
              dataKey="close"
              stroke="var(--text-secondary)"
              strokeWidth={1}
              dot={false}
              isAnimationActive={false}
              opacity={0.6}
            />
          )}

          {/* Equity curve */}
          {hasEquity && (
            <Line
              yAxisId={hasCandles ? "equity" : "equity"}
              type="monotone"
              dataKey="equity"
              stroke="var(--green)"
              strokeWidth={2}
              dot={false}
              isAnimationActive={false}
            />
          )}

          {/* Trade entry markers */}
          {hasCandles && trades?.map((trade, i) => (
            <ReferenceDot
              key={`entry-${i}`}
              x={trade.opened_at}
              y={trade.entry_price}
              yAxisId="price"
              r={4}
              fill={trade.type === "long" ? "var(--green)" : "var(--red)"}
              stroke="none"
            />
          ))}

          {/* Trade exit markers */}
          {hasCandles && trades?.map((trade, i) => (
            <ReferenceDot
              key={`exit-${i}`}
              x={trade.closed_at}
              y={trade.exit_price}
              yAxisId="price"
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
        {hasCandles && (
          <span className="flex items-center gap-1">
            <span className="w-2 h-2 rounded-sm bg-[var(--text-secondary)]" /> Price
          </span>
        )}
        {hasEquity && (
          <span className="flex items-center gap-1">
            <span className="w-2 h-2 rounded-sm bg-[var(--green)]" /> Portfolio
          </span>
        )}
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
