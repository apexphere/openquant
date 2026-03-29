"use client";
import { useState, useEffect, useCallback } from "react";
import {
  useDetectorOptimizationSessions,
  useDetectorOptimizationSession,
} from "@/hooks/use-detector-optimization";
import { RegimeTimeline } from "@/components/regime-timeline";
import { StatCard } from "@/components/stat-card";
import type {
  DetectorOptimizationDetail,
  DetectorTrial,
  RegimePeriod,
} from "@/lib/types";
import { startDetectorOptimization, fetchDetectorPreview } from "@/lib/api";

function fmtScore(v: number | null | undefined): string {
  if (v == null) return "\u2014";
  return v.toFixed(4);
}

function scoreColor(v: number | null | undefined): string {
  if (v == null) return "text-[var(--text-secondary)]";
  if (v >= 0.3) return "text-[var(--green)]";
  if (v >= 0.1) return "text-[var(--yellow)]";
  return "text-[var(--red)]";
}

function timeAgo(iso: string | null): string {
  if (!iso) return "";
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}

interface PreviewData {
  candles: Array<{ time: number; close: number }>;
  regimePeriods: RegimePeriod[];
}

function DetailPanel({ detail }: { detail: DetectorOptimizationDetail | null }) {
  const [selectedTrialIdx, setSelectedTrialIdx] = useState<number>(0);
  const [preview, setPreview] = useState<PreviewData | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);

  const trials = detail?.trials ?? [];
  const selectedTrial = trials[selectedTrialIdx] ?? null;

  const loadPreview = useCallback(
    async (trial: DetectorTrial, detectorType: string) => {
      setPreviewLoading(true);
      try {
        const data = await fetchDetectorPreview({
          detector_type: detectorType,
          params: trial.params,
          start_date: "2025-06-01",
          finish_date: "2026-03-25",
        });
        setPreview({
          candles: data.candles,
          regimePeriods: data.regime_periods.map((rp) => ({
            start: rp.start,
            end: rp.end,
            regime: rp.regime,
            color: "",
          })),
        });
      } catch {
        setPreview(null);
      } finally {
        setPreviewLoading(false);
      }
    },
    []
  );

  // Auto-load preview for the top trial when detail loads
  useEffect(() => {
    setSelectedTrialIdx(0);
    if (detail && trials.length > 0) {
      loadPreview(trials[0], detail.detector_type);
    } else {
      setPreview(null);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [detail?.study_name]);

  if (!detail) {
    return (
      <div className="text-[var(--text-secondary)] text-center py-16">
        Select a study to explore.
      </div>
    );
  }

  const bestParams = detail.best_params ?? {};

  function handleTrialClick(idx: number) {
    setSelectedTrialIdx(idx);
    if (trials[idx]) {
      loadPreview(trials[idx], detail!.detector_type);
    }
  }

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
    <div className="space-y-4">
      {/* Summary cards */}
      <div className="grid grid-cols-3 gap-3">
        <StatCard
          label="Best Score"
          value={fmtScore(detail.best_score)}
          className={scoreColor(detail.best_score)}
        />
        <StatCard label="Trials" value={String(detail.n_trials)} />
        <StatCard label="Detector" value={detail.detector_type} />
      </div>

      {/* Regime preview chart */}
      <div className="relative">
        {previewLoading && (
          <div className="absolute inset-0 bg-[var(--bg-primary)]/60 z-10 flex items-center justify-center rounded-lg">
            <span className="text-sm text-[var(--text-secondary)]">
              Loading regime preview...
            </span>
          </div>
        )}
        {selectedTrial && (
          <div className="bg-[var(--bg-surface)] border border-[var(--border)] rounded-lg p-3 mb-1">
            <div className="text-xs text-[var(--text-secondary)] mb-1">
              Viewing Trial #{selectedTrial.trial} &middot; Score:{" "}
              <span className={scoreColor(selectedTrial.score)}>
                {fmtScore(selectedTrial.score)}
              </span>
              <span className="ml-3">
                {Object.entries(selectedTrial.params)
                  .map(
                    ([k, v]) =>
                      `${k}=${typeof v === "number" && !Number.isInteger(v) ? v.toFixed(3) : v}`
                  )
                  .join(", ")}
              </span>
            </div>
          </div>
        )}
        <RegimeTimeline
          chartData={chartData}
          regimePeriods={preview?.regimePeriods ?? null}
        />
      </div>

      {/* Best params */}
      <div className="bg-[var(--bg-surface)] border border-[var(--border)] rounded-lg p-4">
        <div className="text-[13px] font-semibold text-[var(--text-heading)] mb-3">
          Best Parameters
        </div>
        <div className="grid grid-cols-2 gap-x-6 gap-y-1 text-xs">
          {Object.entries(bestParams).map(([k, v]) => (
            <div
              key={k}
              className="flex justify-between py-1 border-b border-[var(--bg-primary)]"
            >
              <span className="text-[var(--text-secondary)]">{k}</span>
              <span className="text-[var(--text-primary)] font-mono">
                {typeof v === "number"
                  ? Number.isInteger(v)
                    ? v
                    : v.toFixed(4)
                  : String(v)}
              </span>
            </div>
          ))}
        </div>
      </div>

      {/* Trials table — clickable rows */}
      {trials.length > 0 && (
        <div className="bg-[var(--bg-surface)] border border-[var(--border)] rounded-lg p-4">
          <div className="text-[13px] font-semibold text-[var(--text-heading)] mb-3">
            Top Trials{" "}
            <span className="font-normal text-[var(--text-secondary)]">
              (click to preview)
            </span>
          </div>
          <table className="w-full text-xs">
            <thead>
              <tr>
                <th className="text-left py-1.5 px-2 text-[var(--text-secondary)] font-medium border-b border-[var(--border)]">
                  #
                </th>
                <th className="text-left py-1.5 px-2 text-[var(--text-secondary)] font-medium border-b border-[var(--border)]">
                  Score
                </th>
                {Object.keys(trials[0]?.params ?? {}).map((p) => (
                  <th
                    key={p}
                    className="text-left py-1.5 px-2 text-[var(--text-secondary)] font-medium border-b border-[var(--border)]"
                  >
                    {p}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {trials.map((trial, i) => (
                <tr
                  key={i}
                  onClick={() => handleTrialClick(i)}
                  className={`border-b border-[var(--bg-primary)] cursor-pointer transition-colors ${
                    selectedTrialIdx === i
                      ? "bg-[var(--blue)]/10"
                      : "hover:bg-[var(--bg-primary)]"
                  }`}
                >
                  <td className="py-2 px-2">{trial.trial}</td>
                  <td className={`py-2 px-2 ${scoreColor(trial.score)}`}>
                    {fmtScore(trial.score)}
                  </td>
                  {Object.values(trial.params).map((v, j) => (
                    <td key={j} className="py-2 px-2 font-mono">
                      {typeof v === "number"
                        ? Number.isInteger(v)
                          ? v
                          : v.toFixed(4)
                        : String(v)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function NewOptimizationForm({ onStarted }: { onStarted: () => void }) {
  const [detectorType, setDetectorType] = useState("breakout_v3");
  const [symbol, setSymbol] = useState("BTC-USDT");
  const [startDate, setStartDate] = useState("2025-06-01");
  const [finishDate, setFinishDate] = useState("2026-03-25");
  const [trials, setTrials] = useState(200);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      await startDetectorOptimization({
        detector_type: detectorType,
        symbol,
        start_date: startDate,
        finish_date: finishDate,
        trials,
      });
      onStarted();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to start");
    } finally {
      setSubmitting(false);
    }
  }

  const inputClass =
    "bg-[var(--bg-primary)] border border-[var(--border)] rounded px-3 py-1.5 text-sm text-[var(--text-primary)] focus:border-[var(--blue)] outline-none";

  return (
    <form
      onSubmit={handleSubmit}
      className="bg-[var(--bg-surface)] border border-[var(--border)] rounded-lg p-4 space-y-3"
    >
      <div className="text-[13px] font-semibold text-[var(--text-heading)] mb-2">
        New Detector Optimization
      </div>
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="text-xs text-[var(--text-secondary)] block mb-1">
            Detector
          </label>
          <select
            value={detectorType}
            onChange={(e) => setDetectorType(e.target.value)}
            className={inputClass + " w-full"}
          >
            <option value="breakout_v3">breakout_v3</option>
            <option value="ema_adx">ema_adx</option>
          </select>
        </div>
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
        <div>
          <label className="text-xs text-[var(--text-secondary)] block mb-1">
            Start
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
            Finish
          </label>
          <input
            type="date"
            value={finishDate}
            onChange={(e) => setFinishDate(e.target.value)}
            className={inputClass + " w-full"}
          />
        </div>
        <div>
          <label className="text-xs text-[var(--text-secondary)] block mb-1">
            Trials
          </label>
          <input
            type="number"
            value={trials}
            onChange={(e) => setTrials(Number(e.target.value))}
            min={10}
            max={2000}
            className={inputClass + " w-full"}
          />
        </div>
      </div>
      {error && <div className="text-xs text-[var(--red)]">{error}</div>}
      <button
        type="submit"
        disabled={submitting}
        className="px-4 py-2 bg-[var(--blue)] text-white text-sm rounded hover:opacity-90 disabled:opacity-50 transition-opacity"
      >
        {submitting ? "Starting..." : "Start Optimization"}
      </button>
    </form>
  );
}

export default function DetectorOptimizationPage() {
  const {
    data: sessions,
    error,
    isLoading,
    mutate,
  } = useDetectorOptimizationSessions();
  const [selectedName, setSelectedName] = useState<string | null>(null);
  const { data: selectedDetail } = useDetectorOptimizationSession(selectedName);
  const [showForm, setShowForm] = useState(false);

  if (error) {
    return (
      <div className="p-6">
        <div className="bg-[var(--red)]/10 border border-[var(--red)]/30 rounded-lg p-4 text-[var(--red)]">
          Could not connect to OpenQuant server at localhost:9000. Is{" "}
          <code>jesse run</code> running?
        </div>
      </div>
    );
  }

  return (
    <div className="p-6">
      <div className="flex items-center justify-between mb-5">
        <h1 className="text-lg font-semibold text-[var(--text-heading)]">
          Detector Optimization
        </h1>
        <button
          onClick={() => setShowForm(!showForm)}
          className="px-3 py-1.5 text-xs border border-[var(--border)] rounded hover:border-[var(--text-secondary)] text-[var(--text-secondary)] transition-colors"
        >
          {showForm ? "Hide Form" : "+ New"}
        </button>
      </div>

      {showForm && (
        <div className="mb-5">
          <NewOptimizationForm
            onStarted={() => {
              setShowForm(false);
              mutate();
            }}
          />
        </div>
      )}

      {isLoading ? (
        <div className="space-y-2">
          {[...Array(3)].map((_, i) => (
            <div
              key={i}
              className="h-12 bg-[var(--bg-surface)] rounded animate-pulse"
            />
          ))}
        </div>
      ) : !sessions || sessions.length === 0 ? (
        <div className="text-center py-16 text-[var(--text-secondary)]">
          <p className="text-lg mb-2">No detector optimization sessions.</p>
          <p className="text-sm">
            Run{" "}
            <code className="text-[var(--blue)]">
              jesse optimize-detector breakout_v3 --start 2025-06-01 --finish
              2026-03-25
            </code>{" "}
            or click{" "}
            <span className="text-[var(--text-primary)]">+ New</span> above.
          </p>
        </div>
      ) : (
        <div className="grid grid-cols-[300px_1fr] gap-6">
          {/* Session list */}
          <div className="space-y-2">
            {sessions.map((session) => (
              <button
                key={session.study_name}
                onClick={() => setSelectedName(session.study_name)}
                className={`w-full text-left p-3 rounded-lg border transition-colors ${
                  selectedName === session.study_name
                    ? "border-[var(--blue)] bg-[var(--blue)]/10"
                    : "border-[var(--border)] bg-[var(--bg-surface)] hover:border-[var(--text-secondary)]"
                }`}
              >
                <div className="flex items-center gap-2">
                  <span className="font-medium text-sm">
                    {session.detector_type}
                  </span>
                  <span className="text-xs text-[var(--text-secondary)]">
                    {session.n_trials} trials
                  </span>
                </div>
                <div className="text-xs text-[var(--text-secondary)] mt-1 flex justify-between">
                  <span>
                    best:{" "}
                    <span className={scoreColor(session.best_score)}>
                      {fmtScore(session.best_score)}
                    </span>
                  </span>
                  <span>{timeAgo(session.datetime_start)}</span>
                </div>
              </button>
            ))}
          </div>

          {/* Detail panel */}
          <DetailPanel detail={selectedDetail ?? null} />
        </div>
      )}
    </div>
  );
}
