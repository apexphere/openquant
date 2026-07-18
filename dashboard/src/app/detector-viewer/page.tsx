"use client";
import { useState, useEffect, useCallback } from "react";
import { RegimeTimeline } from "@/components/regime-timeline";
import {
  fetchDetectorTypes,
  fetchDetectorPreview,
  fetchDetectorPreviewHistory,
  removeDetectorPreviewHistoryEntry,
  clearDetectorPreviewHistory,
} from "@/lib/api";
import type { RegimePeriod } from "@/lib/types";

interface ParamRange {
  type: string;
  min: number;
  max: number;
}

type DetectorTypes = Record<string, Record<string, ParamRange>>;

interface RegimeDetail {
  regime: string;
  start_date?: string;
  end_date?: string;
  start_ts?: number;
  end_ts?: number;
  days?: number;
  start_price?: number;
  end_price?: number;
  high?: number;
  low?: number;
  pct_change?: number;
}

interface PreviewResult {
  candles: Array<{ time: number; close: number }>;
  regimePeriods: RegimePeriod[];
  regimeDetails: RegimeDetail[];
}

interface HistoryEntry {
  id: string;
  timestamp: string;
  detector_type: string;
  params: Record<string, number>;
  exchange?: string;
  symbol: string;
  start_date: string;
  finish_date: string;
}

const REGIME_LABEL_COLORS: Record<string, string> = {
  "trending-up": "#3b8a4a",
  "trending-down": "#a34a4a",
  "ranging-up": "#6fdc8c",
  "ranging-down": "#ff8389",
  "cold-start": "var(--text-secondary)",
};

function midpoint(range: ParamRange): number {
  const mid = (range.min + range.max) / 2;
  return range.type === "int" ? Math.round(mid) : parseFloat(mid.toFixed(4));
}

function parseParamValue(value: string, type: string): number {
  return type === "int" ? parseInt(value, 10) : parseFloat(value);
}

function timeAgo(iso: string): string {
  const seconds = Math.floor(
    (Date.now() - new Date(iso).getTime()) / 1000
  );
  if (seconds < 60) return "just now";
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}

const inputClass =
  "bg-[var(--bg-primary)] border border-[var(--border)] rounded px-3 py-1.5 text-sm text-[var(--text-primary)] focus:border-[var(--blue)] outline-none";

export default function DetectorViewerPage() {
  const [detectorTypes, setDetectorTypes] = useState<DetectorTypes | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  const [selectedDetector, setSelectedDetector] = useState<string>("");
  const [params, setParams] = useState<Record<string, number>>({});
  const [symbol, setSymbol] = useState("BTC-USDT");
  const [startDate, setStartDate] = useState("2025-06-01");
  const [finishDate, setFinishDate] = useState("2026-03-25");

  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [preview, setPreview] = useState<PreviewResult | null>(null);

  const [history, setHistory] = useState<HistoryEntry[]>([]);
  const [activeHistoryId, setActiveHistoryId] = useState<string | null>(null);

  const refreshHistory = useCallback(() => {
    fetchDetectorPreviewHistory()
      .then(setHistory)
      .catch(() => {});
  }, []);

  // Load history from server on mount
  useEffect(() => {
    refreshHistory();
  }, [refreshHistory]);

  // Fetch detector types on mount
  useEffect(() => {
    fetchDetectorTypes()
      .then((types) => {
        setDetectorTypes(types);
        const first = Object.keys(types)[0];
        if (first) {
          setSelectedDetector(first);
          setParams(
            Object.fromEntries(
              Object.entries(types[first]).map(([k, v]) => [k, midpoint(v)])
            )
          );
        }
      })
      .catch(() => setLoadError("Could not connect to OpenQuant server at localhost:9000."));
  }, []);

  // Update params when detector type changes
  const handleDetectorChange = useCallback(
    (detector: string) => {
      setSelectedDetector(detector);
      if (detectorTypes?.[detector]) {
        setParams(
          Object.fromEntries(
            Object.entries(detectorTypes[detector]).map(([k, v]) => [k, midpoint(v)])
          )
        );
      }
      setPreview(null);
    },
    [detectorTypes]
  );

  const handleParamChange = useCallback(
    (name: string, value: string) => {
      const range = detectorTypes?.[selectedDetector]?.[name];
      if (!range) return;
      const parsed = parseParamValue(value, range.type);
      if (!isNaN(parsed)) {
        setParams((prev) => ({ ...prev, [name]: parsed }));
      }
    },
    [detectorTypes, selectedDetector]
  );

  const removeFromHistory = useCallback(
    (id: string) => {
      removeDetectorPreviewHistoryEntry(id)
        .then(() => refreshHistory())
        .catch(() => {});
    },
    [refreshHistory]
  );

  const handleClearHistory = useCallback(() => {
    clearDetectorPreviewHistory()
      .then(() => {
        setHistory([]);
        refreshHistory();
      })
      .catch(() => {});
  }, [refreshHistory]);

  const applyHistoryEntry = useCallback(
    (entry: HistoryEntry) => {
      setSelectedDetector(entry.detector_type);
      setParams(entry.params);
      setSymbol(entry.symbol);
      setStartDate(entry.start_date);
      setFinishDate(entry.finish_date);
      setPreview(null);
    },
    []
  );

  const runPreview = useCallback(
    async (config: {
      detector_type: string;
      params: Record<string, number>;
      symbol: string;
      start_date: string;
      finish_date: string;
    }) => {
      setRunning(true);
      setError(null);
      try {
        const data = await fetchDetectorPreview(config);
        const periods = data.regime_periods;
        setPreview({
          candles: data.candles,
          regimePeriods: periods.map((rp) => ({
            start: rp.start,
            end: rp.end,
            regime: rp.regime,
            color: "",
          })),
          regimeDetails: periods as RegimeDetail[],
        });
        return true;
      } catch (err: unknown) {
        setError(err instanceof Error ? err.message : "Preview failed");
        setPreview(null);
        return false;
      } finally {
        setRunning(false);
      }
    },
    []
  );

  const handleRun = useCallback(async () => {
    setActiveHistoryId(null);
    const config = {
      detector_type: selectedDetector,
      params,
      symbol,
      start_date: startDate,
      finish_date: finishDate,
    };
    const ok = await runPreview(config);
    if (ok) {
      refreshHistory();
    }
  }, [selectedDetector, params, symbol, startDate, finishDate, refreshHistory, runPreview]);

  const handleHistoryClick = useCallback(
    async (entry: HistoryEntry) => {
      applyHistoryEntry(entry);
      setActiveHistoryId(entry.id);
      await runPreview({
        detector_type: entry.detector_type,
        params: entry.params,
        symbol: entry.symbol,
        start_date: entry.start_date,
        finish_date: entry.finish_date,
      });
    },
    [applyHistoryEntry, runPreview]
  );

  if (loadError) {
    return (
      <div className="p-6">
        <div className="bg-[var(--red)]/10 border border-[var(--red)]/30 rounded-lg p-4 text-[var(--red)]">
          {loadError} Is <code>jesse run</code> running?
        </div>
      </div>
    );
  }

  const paramRanges = detectorTypes?.[selectedDetector] ?? {};

  // Build chart data for RegimeTimeline
  const chartData =
    preview && preview.candles.length > 0
      ? {
          candles_chart: [
            {
              exchange: "",
              symbol: "",
              timeframe: "1D",
              candles: preview.candles,
            },
          ] as any,
          orders_chart: [],
          add_line_to_candle_chart: [],
          add_extra_line_chart: [],
          add_horizontal_line_to_candle_chart: [],
          add_horizontal_line_to_extra_chart: [],
        }
      : null;

  return (
    <div className="p-6">
      <h1 className="text-lg font-semibold text-[var(--text-heading)] mb-5">
        Detector Viewer
      </h1>

      <div className="grid grid-cols-[300px_1fr] gap-6">
        {/* History sidebar */}
        <div className="space-y-2">
          <div className="text-[13px] font-semibold text-[var(--text-heading)] mb-2">
            Run History
          </div>

          {history.length === 0 ? (
            <div className="text-xs text-[var(--text-secondary)] py-6 text-center">
              No history yet. Run a detector to start.
            </div>
          ) : (
            <>
              {history.map((entry) => (
                <div
                  key={entry.id}
                  className={`group relative w-full text-left p-3 rounded-lg border transition-colors cursor-pointer ${
                    activeHistoryId === entry.id
                      ? "border-[var(--blue)] bg-[var(--blue)]/10"
                      : "border-[var(--border)] bg-[var(--bg-surface)] hover:border-[var(--text-secondary)]"
                  }`}
                  onClick={() => handleHistoryClick(entry)}
                >
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      removeFromHistory(entry.id);
                    }}
                    className="absolute top-2 right-2 text-[var(--text-secondary)] hover:text-[var(--red)] opacity-0 group-hover:opacity-100 transition-opacity text-xs leading-none"
                    title="Remove"
                  >
                    &times;
                  </button>
                  <div className="flex items-center gap-2">
                    <span className="font-medium text-sm text-[var(--text-primary)]">
                      {entry.detector_type}
                    </span>
                  </div>
                  <div className="text-xs text-[var(--text-secondary)] mt-1">
                    {entry.symbol}
                  </div>
                  <div className="text-xs text-[var(--text-secondary)] mt-0.5 flex justify-between">
                    <span>
                      {entry.start_date} &rarr; {entry.finish_date}
                    </span>
                    <span>{timeAgo(entry.timestamp)}</span>
                  </div>
                </div>
              ))}
              <button
                onClick={handleClearHistory}
                className="text-xs text-[var(--text-secondary)] hover:text-[var(--red)] transition-colors mt-1"
              >
                Clear All
              </button>
            </>
          )}
        </div>

        {/* Main content */}
        <div>
          {/* Configuration form */}
          <div className="bg-[var(--bg-surface)] border border-[var(--border)] rounded-lg p-4 mb-5">
            <div className="text-[13px] font-semibold text-[var(--text-heading)] mb-3">
              Configure Detector
            </div>

            {!detectorTypes ? (
              <div className="h-20 flex items-center justify-center text-sm text-[var(--text-secondary)]">
                Loading detector types...
              </div>
            ) : (
              <>
                <div className="grid grid-cols-5 gap-3 mb-3">
                  {/* Detector type */}
                  <div>
                    <label className="text-xs text-[var(--text-secondary)] block mb-1">
                      Detector
                    </label>
                    <select
                      value={selectedDetector}
                      onChange={(e) => handleDetectorChange(e.target.value)}
                      className={inputClass + " w-full"}
                    >
                      {Object.keys(detectorTypes).map((dt) => (
                        <option key={dt} value={dt}>
                          {dt}
                        </option>
                      ))}
                    </select>
                  </div>

                  {/* Symbol */}
                  <div>
                    <label className="text-xs text-[var(--text-secondary)] block mb-1">
                      Symbol
                    </label>
                    <select
                      value={symbol}
                      onChange={(e) => setSymbol(e.target.value)}
                      className={inputClass + " w-full"}
                    >
                      <option value="BTC-USDT">BTC-USDT</option>
                      <option value="ETH-USDT">ETH-USDT</option>
                    </select>
                  </div>

                  {/* Date range */}
                  <div>
                    <label className="text-xs text-[var(--text-secondary)] block mb-1">
                      Start Date
                    </label>
                    <input
                      type="date"
                      value={startDate}
                      onChange={(e) => setStartDate(e.target.value)}
                      className={inputClass + " w-full"}
                    />
                  </div>
                  <div>
                    <label className="text-xs text-[var(--text-secondary)] block mb-1">
                      Finish Date
                    </label>
                    <input
                      type="date"
                      value={finishDate}
                      onChange={(e) => setFinishDate(e.target.value)}
                      className={inputClass + " w-full"}
                    />
                  </div>

                  {/* Run button */}
                  <div className="flex items-end">
                    <button
                      onClick={handleRun}
                      disabled={running}
                      className="w-full px-4 py-1.5 bg-[var(--blue)] text-white text-sm rounded hover:opacity-90 disabled:opacity-50 transition-opacity"
                    >
                      {running ? "Running..." : "Run"}
                    </button>
                  </div>
                </div>

                {/* Dynamic parameter inputs */}
                {Object.keys(paramRanges).length > 0 && (
                  <div className="grid grid-cols-4 gap-3">
                    {Object.entries(paramRanges).map(([name, range]) => (
                      <div key={name}>
                        <label className="text-xs text-[var(--text-secondary)] block mb-1">
                          {name}{" "}
                          <span className="text-[10px] opacity-60">
                            ({range.min}–{range.max})
                          </span>
                        </label>
                        <input
                          type="number"
                          value={params[name] ?? midpoint(range)}
                          onChange={(e) => handleParamChange(name, e.target.value)}
                          min={range.min}
                          max={range.max}
                          step={range.type === "int" ? 1 : 0.01}
                          className={inputClass + " w-full"}
                        />
                      </div>
                    ))}
                  </div>
                )}
              </>
            )}
          </div>

          {error && (
            <div className="bg-[var(--red)]/10 border border-[var(--red)]/30 rounded-lg p-3 text-sm text-[var(--red)] mb-5">
              {error}
            </div>
          )}

          {/* Loading overlay + chart */}
          {running && (
            <div className="bg-[var(--bg-surface)] border border-[var(--border)] rounded-lg p-4 mb-5">
              <div className="text-sm text-[var(--text-secondary)] text-center py-8">
                Running detector preview...
              </div>
            </div>
          )}

          {/* Regime timeline chart */}
          {preview && !running && (
            <div className="space-y-4">
              <div className="bg-[var(--bg-surface)] border border-[var(--border)] rounded-lg p-3 mb-1">
                <div className="text-xs text-[var(--text-secondary)]">
                  Detector:{" "}
                  <span className="text-[var(--text-primary)] font-medium">
                    {selectedDetector}
                  </span>
                  <span className="ml-3">
                    {Object.entries(params)
                      .map(
                        ([k, v]) =>
                          `${k}=${typeof v === "number" && !Number.isInteger(v) ? v.toFixed(3) : v}`
                      )
                      .join(", ")}
                  </span>
                </div>
              </div>

              <RegimeTimeline
                chartData={chartData}
                regimePeriods={preview.regimePeriods}
              />

              {/* Regime periods table */}
              {preview.regimeDetails.length > 0 && (
                <div className="bg-[var(--bg-surface)] border border-[var(--border)] rounded-lg p-4">
                  <div className="text-[13px] font-semibold text-[var(--text-heading)] mb-3">
                    Regime Periods
                  </div>
                  <table className="w-full text-xs">
                    <thead>
                      <tr>
                        <th className="text-left py-1.5 px-2 text-[var(--text-secondary)] font-medium border-b border-[var(--border)]">
                          Regime
                        </th>
                        <th className="text-left py-1.5 px-2 text-[var(--text-secondary)] font-medium border-b border-[var(--border)]">
                          Period
                        </th>
                        <th className="text-right py-1.5 px-2 text-[var(--text-secondary)] font-medium border-b border-[var(--border)]">
                          Days
                        </th>
                        <th className="text-right py-1.5 px-2 text-[var(--text-secondary)] font-medium border-b border-[var(--border)]">
                          Start
                        </th>
                        <th className="text-right py-1.5 px-2 text-[var(--text-secondary)] font-medium border-b border-[var(--border)]">
                          End
                        </th>
                        <th className="text-right py-1.5 px-2 text-[var(--text-secondary)] font-medium border-b border-[var(--border)]">
                          High
                        </th>
                        <th className="text-right py-1.5 px-2 text-[var(--text-secondary)] font-medium border-b border-[var(--border)]">
                          Low
                        </th>
                        <th className="text-right py-1.5 px-2 text-[var(--text-secondary)] font-medium border-b border-[var(--border)]">
                          Change
                        </th>
                      </tr>
                    </thead>
                    <tbody>
                      {preview.regimeDetails.map((rd, i) => (
                        <tr
                          key={i}
                          className="border-b border-[var(--bg-primary)]"
                        >
                          <td
                            className="py-1.5 px-2 font-medium"
                            style={{
                              color:
                                REGIME_LABEL_COLORS[rd.regime] ??
                                "var(--text-secondary)",
                            }}
                          >
                            {rd.regime}
                          </td>
                          <td className="py-1.5 px-2 text-[var(--text-secondary)]">
                            {rd.start_date ?? "\u2014"} &rarr; {rd.end_date ?? "\u2014"}
                          </td>
                          <td className="py-1.5 px-2 text-right">{rd.days ?? "\u2014"}</td>
                          <td className="py-1.5 px-2 text-right font-mono">
                            {rd.start_price != null
                              ? `$${rd.start_price.toLocaleString()}`
                              : "\u2014"}
                          </td>
                          <td className="py-1.5 px-2 text-right font-mono">
                            {rd.end_price != null
                              ? `$${rd.end_price.toLocaleString()}`
                              : "\u2014"}
                          </td>
                          <td className="py-1.5 px-2 text-right font-mono">
                            {rd.high != null
                              ? `$${rd.high.toLocaleString()}`
                              : "\u2014"}
                          </td>
                          <td className="py-1.5 px-2 text-right font-mono">
                            {rd.low != null
                              ? `$${rd.low.toLocaleString()}`
                              : "\u2014"}
                          </td>
                          <td
                            className={`py-1.5 px-2 text-right font-mono ${
                              (rd.pct_change ?? 0) >= 0
                                ? "text-[var(--green)]"
                                : "text-[var(--red)]"
                            }`}
                          >
                            {rd.pct_change != null
                              ? `${rd.pct_change >= 0 ? "+" : ""}${rd.pct_change.toFixed(2)}%`
                              : "\u2014"}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          )}

          {/* Empty state */}
          {!preview && !running && !error && (
            <div className="text-center py-16 text-[var(--text-secondary)]">
              <p className="text-lg mb-2">Configure a detector and click Run.</p>
              <p className="text-sm">
                Pick a detector type, adjust parameters, and preview how it labels
                market regimes.
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
