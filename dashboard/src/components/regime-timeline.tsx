"use client";
import { useState, useCallback } from "react";
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
  "ranging-up": "#1a2a3a",
  "ranging-down": "#2a1a30",
  ranging: "#2a2a38",
  "cold-start": "#133044",
};

const REGIME_TEXT_COLORS: Record<string, string> = {
  "trending-up": "#3fb950",
  "trending-down": "#f85149",
  "ranging-up": "#58a6ff",
  "ranging-down": "#d2a8ff",
  ranging: "#8b949e",
  "cold-start": "#58a6ff",
};

interface CandleRecord {
  time: number;
  open: number;
  close: number;
  high: number;
  low: number;
}

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

function fmtDate(ts: number): string {
  return new Date(ts * 1000).toLocaleDateString("en-US", {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

function fmtPrice(v: number): string {
  return v >= 1000 ? `$${v.toLocaleString("en-US", { maximumFractionDigits: 0 })}` : `$${v.toFixed(2)}`;
}

interface RegimeStats {
  regime: string;
  startDate: string;
  endDate: string;
  startPrice: number;
  endPrice: number;
  high: number;
  low: number;
  pctChange: number;
  days: number;
}

function computeRegimeStats(
  period: RegimePeriod,
  candles: CandleRecord[]
): RegimeStats | null {
  if (candles.length === 0) return null;

  const startTs = period.start;
  const endTs = period.end;

  const inRange = candles.filter((c) => c.time >= startTs && c.time <= endTs);
  if (inRange.length === 0) return null;

  const startCandle = inRange[0];
  const endCandle = inRange[inRange.length - 1];
  const high = Math.max(...inRange.map((c) => c.high));
  const low = Math.min(...inRange.map((c) => c.low));
  const pctChange =
    startCandle.close > 0
      ? ((endCandle.close - startCandle.close) / startCandle.close) * 100
      : 0;
  const days = Math.round((endTs - startTs) / 86400);

  return {
    regime: period.regime,
    startDate: fmtDate(startTs),
    endDate: fmtDate(endTs),
    startPrice: startCandle.close,
    endPrice: endCandle.close,
    high,
    low,
    pctChange,
    days,
  };
}

function formatStatsText(stats: RegimeStats): string {
  const sign = stats.pctChange >= 0 ? "+" : "";
  return [
    `Regime: ${stats.regime}`,
    `Period: ${stats.startDate} - ${stats.endDate} (${stats.days}d)`,
    `Start: ${fmtPrice(stats.startPrice)}  End: ${fmtPrice(stats.endPrice)}  (${sign}${stats.pctChange.toFixed(2)}%)`,
    `High: ${fmtPrice(stats.high)}  Low: ${fmtPrice(stats.low)}`,
  ].join("\n");
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

    let avgX = 0;
    let avgY = 0;
    for (let j = rangeStart; j < rangeEnd; j++) {
      avgX += data[j].time;
      avgY += data[j].close;
    }
    avgX /= rangeEnd - rangeStart || 1;
    avgY /= rangeEnd - rangeStart || 1;

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

function RegimeTooltip({ stats }: { stats: RegimeStats }) {
  const sign = stats.pctChange >= 0 ? "+" : "";
  const changeColor =
    stats.pctChange >= 0 ? "text-[var(--green)]" : "text-[var(--red)]";

  return (
    <div className="bg-[var(--bg-primary)] border border-[var(--border)] rounded-lg px-3 py-2 shadow-lg text-xs min-w-[200px]">
      <div
        className="font-semibold mb-1.5"
        style={{ color: REGIME_TEXT_COLORS[stats.regime] ?? "#8b949e" }}
      >
        {stats.regime.toUpperCase().replace("-", " ")}
      </div>
      <div className="space-y-0.5 text-[var(--text-secondary)]">
        <div>
          {stats.startDate} &rarr; {stats.endDate}{" "}
          <span className="text-[var(--text-primary)]">({stats.days}d)</span>
        </div>
        <div className="flex justify-between gap-4">
          <span>
            Start:{" "}
            <span className="text-[var(--text-primary)]">
              {fmtPrice(stats.startPrice)}
            </span>
          </span>
          <span>
            End:{" "}
            <span className="text-[var(--text-primary)]">
              {fmtPrice(stats.endPrice)}
            </span>
          </span>
        </div>
        <div className="flex justify-between gap-4">
          <span>
            High:{" "}
            <span className="text-[var(--text-primary)]">
              {fmtPrice(stats.high)}
            </span>
          </span>
          <span>
            Low:{" "}
            <span className="text-[var(--text-primary)]">
              {fmtPrice(stats.low)}
            </span>
          </span>
        </div>
        <div className={changeColor}>
          {sign}
          {stats.pctChange.toFixed(2)}%
        </div>
      </div>
      <div className="text-[10px] text-[var(--text-secondary)] mt-1.5 border-t border-[var(--border)] pt-1">
        Click to copy
      </div>
    </div>
  );
}

export function RegimeTimeline({
  chartData,
  regimePeriods,
  equityCurve,
  trades,
}: RegimeTimelineProps) {
  const [hoveredIdx, setHoveredIdx] = useState<number | null>(null);
  const [copied, setCopied] = useState(false);

  // Extract full candle records (with OHLC) for regime stats
  let fullCandles: CandleRecord[] = [];
  if (chartData?.candles_chart) {
    const candlesList = chartData.candles_chart as any;
    const rawCandles =
      Array.isArray(candlesList) &&
      candlesList.length > 0 &&
      candlesList[0].candles
        ? candlesList[0].candles
        : candlesList;
    fullCandles = rawCandles.map((c: any) => ({
      time: c.time ?? c[0],
      open: c.open ?? c[1],
      close: c.close ?? c[4] ?? c[2],
      high: c.high ?? c[3],
      low: c.low ?? c[4],
    }));
  }

  const handleRegimeClick = useCallback(
    (period: RegimePeriod) => {
      const stats = computeRegimeStats(period, fullCandles);
      if (!stats) return;
      const text = formatStatsText(stats);
      navigator.clipboard.writeText(text).then(() => {
        setCopied(true);
        setTimeout(() => setCopied(false), 1500);
      });
    },
    [fullCandles]
  );

  if (!regimePeriods && !chartData && !equityCurve) {
    return (
      <div className="bg-[var(--bg-surface)] border border-[var(--border)] rounded-lg p-4">
        <div className="text-[var(--text-secondary)] text-center py-8">
          No regime or chart data available. Run a backtest with a regime
          detector enabled.
        </div>
      </div>
    );
  }

  // Chart time range for aligning regime bar with chart X-axis
  const chartTimeRange = (() => {
    if (fullCandles.length > 0) {
      return { start: fullCandles[0].time, end: fullCandles[fullCandles.length - 1].time };
    }
    if (regimePeriods && regimePeriods.length > 0) {
      return { start: regimePeriods[0].start, end: regimePeriods[regimePeriods.length - 1].end };
    }
    return null;
  })();

  // Regime bar with hover tooltip + click to copy
  const regimeBar = regimePeriods && regimePeriods.length > 0 && chartTimeRange && (() => {
    const totalDuration = chartTimeRange.end - chartTimeRange.start;
    if (totalDuration <= 0) return null;

    // Build segments: gap before first regime, then each regime period
    const segments: Array<{ type: "gap" | "regime"; width: number; idx: number }> = [];

    const gapBefore = regimePeriods[0].start - chartTimeRange.start;
    if (gapBefore > 0) {
      segments.push({ type: "gap", width: (gapBefore / totalDuration) * 100, idx: -1 });
    }

    for (let i = 0; i < regimePeriods.length; i++) {
      const w = ((regimePeriods[i].end - regimePeriods[i].start) / totalDuration) * 100;
      segments.push({ type: "regime", width: w, idx: i });
    }

    return (
      <div className="relative" style={{ marginLeft: 65, marginRight: 60 }}>
        <div className="flex h-7 rounded overflow-hidden mb-2">
          {segments.map((seg, si) => {
            if (seg.type === "gap") {
              return <div key={`gap-${si}`} style={{ width: `${seg.width}%` }} className="bg-[var(--bg-primary)]" />;
            }
            const period = regimePeriods[seg.idx];
            const regime = period.regime;
            return (
              <div
                key={seg.idx}
                className="flex items-center justify-center text-[10px] font-semibold tracking-wide cursor-pointer transition-opacity"
                style={{
                  width: `${seg.width}%`,
                  backgroundColor: REGIME_COLORS[regime] ?? "rgba(139,148,158,0.1)",
                  color: REGIME_TEXT_COLORS[regime] ?? "#8b949e",
                  opacity: hoveredIdx !== null && hoveredIdx !== seg.idx ? 0.4 : 1,
                }}
                onMouseEnter={() => setHoveredIdx(seg.idx)}
                onMouseLeave={() => setHoveredIdx(null)}
                onClick={() => handleRegimeClick(period)}
              >
                {seg.width > 8 ? regime.toUpperCase().replace("-", " ") : ""}
              </div>
            );
          })}
        </div>
        {/* Tooltip */}
        {hoveredIdx !== null && regimePeriods[hoveredIdx] && (() => {
          const stats = computeRegimeStats(regimePeriods[hoveredIdx], fullCandles);
          if (!stats) return null;

          // Position tooltip aligned to chart time range
          const periodCenter = (regimePeriods[hoveredIdx].start + regimePeriods[hoveredIdx].end) / 2;
          const centerPct = ((periodCenter - chartTimeRange.start) / totalDuration) * 100;
          const clampedPct = Math.max(15, Math.min(85, centerPct));

          return (
            <div className="absolute z-20 -translate-x-1/2" style={{ left: `${clampedPct}%`, top: "32px" }}>
              <RegimeTooltip stats={stats} />
            </div>
          );
        })()}
        {copied && (
          <div className="absolute top-0 right-0 text-[10px] text-[var(--green)] bg-[var(--bg-primary)] px-2 py-0.5 rounded">
            Copied!
          </div>
        )}
      </div>
    );
  })();

  // Build merged chart data: price + equity on same time axis
  let priceChart = null;
  const hasCandles = chartData?.candles_chart && chartData.candles_chart.length > 0;
  const hasEquity = equityCurve && equityCurve.length > 0;

  if (hasCandles || hasEquity) {
    let priceData: Array<{ time: number; close: number }> = [];
    if (hasCandles) {
      const candlesList = chartData!.candles_chart as any;
      const rawCandles =
        Array.isArray(candlesList) &&
        candlesList.length > 0 &&
        candlesList[0].candles
          ? candlesList[0].candles
          : candlesList;
      const raw = rawCandles.map((c: any) => ({
        time: (c.time ?? c[0]) * 1000,
        close: c.close ?? c[4],
      }));
      priceData = lttbDownsample(raw, 2000);
    }

    const equityData: Array<{ time: number; value: number }> = [];
    if (hasEquity) {
      for (const pt of equityCurve!) {
        equityData.push({ time: pt.time * 1000, value: pt.value });
      }
    }

    function findEquityValue(time: number): number | undefined {
      if (equityData.length === 0) return undefined;
      if (time <= equityData[0].time) return equityData[0].value;
      if (time >= equityData[equityData.length - 1].time)
        return equityData[equityData.length - 1].value;
      let lo = 0,
        hi = equityData.length - 1;
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
      mergedData = equityData.map((pt) => ({
        time: pt.time,
        equity: pt.value,
      }));
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
                v >= 1000
                  ? `$${(v / 1000).toFixed(1)}k`
                  : `$${v.toFixed(0)}`
              }
            />
          )}
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

          {regimePeriods?.map((period, i) => (
            <ReferenceArea
              key={i}
              x1={period.start * 1000}
              x2={period.end * 1000}
              fill={REGIME_COLORS[period.regime] ?? "transparent"}
              fillOpacity={0.8}
              yAxisId={hasCandles ? "price" : "equity"}
              ifOverflow="extendDomain"
              label={undefined}
            />
          ))}

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

          {hasEquity && (
            <Line
              yAxisId="equity"
              type="monotone"
              dataKey="equity"
              stroke="var(--green)"
              strokeWidth={2}
              dot={false}
              isAnimationActive={false}
            />
          )}

          {hasCandles &&
            trades?.map((trade, i) => (
              <ReferenceDot
                key={`entry-${i}`}
                x={trade.opened_at}
                y={trade.entry_price}
                yAxisId="price"
                r={4}
                fill={
                  trade.type === "long" ? "var(--green)" : "var(--red)"
                }
                stroke="none"
              />
            ))}

          {hasCandles &&
            trades?.map((trade, i) => (
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
            <span className="w-2 h-2 rounded-sm bg-[var(--text-secondary)]" />{" "}
            Price
          </span>
        )}
        {hasEquity && (
          <span className="flex items-center gap-1">
            <span className="w-2 h-2 rounded-sm bg-[var(--green)]" /> Portfolio
          </span>
        )}
        <span className="flex items-center gap-1">
          <span className="w-2 h-2 rounded-full bg-[var(--green)]" /> Long
          Entry
        </span>
        <span className="flex items-center gap-1">
          <span className="w-2 h-2 rounded-full bg-[var(--red)]" /> Short
          Entry
        </span>
        <span className="flex items-center gap-1">
          <span className="w-2 h-2 rounded-full border border-[var(--text-secondary)]" />{" "}
          Exit
        </span>
      </div>
    </div>
  );
}
