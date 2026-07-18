"use client";

import { useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { useBacktestSession, useChartData } from "@/hooks/use-backtest";
import { useSessionResearchNotes } from "@/hooks/use-research-notes";
import { createResearchNote } from "@/lib/api";
import { StatCard } from "@/components/stat-card";
import { RegimeTimeline } from "@/components/regime-timeline";
import type { BacktestSessionDetail, Trade, ResearchNote } from "@/lib/types";

function formatPnl(value: number | null | undefined): string {
  if (value == null) return "--";
  const sign = value >= 0 ? "+" : "";
  return `${sign}${value.toFixed(2)}%`;
}

function formatDate(ts: number): string {
  return new Date(ts).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

function formatPeriod(session: BacktestSessionDetail): string {
  const start = session.state?.form?.start_date;
  const finish = session.state?.form?.finish_date;
  if (!start || !finish) return "";
  const s = new Date(start).toLocaleDateString("en-US", {
    month: "short",
    year: "numeric",
  });
  const f = new Date(finish).toLocaleDateString("en-US", {
    month: "short",
    year: "numeric",
  });
  return `${s} - ${f}`;
}

function formatHoldingPeriod(seconds: number): string {
  const hours = Math.floor(seconds / 3600);
  if (hours < 24) return `${hours}h`;
  const days = Math.floor(hours / 24);
  return `${days}d ${hours % 24}h`;
}

function getStrategyName(session: BacktestSessionDetail): string {
  if (session.strategy_name) return session.strategy_name;
  return session.state?.form?.routes?.[0]?.strategy ?? "Unknown";
}

function getSymbol(session: BacktestSessionDetail): string {
  return session.state?.form?.routes?.[0]?.symbol ?? "--";
}

function SkeletonBlock({ className = "" }: { className?: string }) {
  return (
    <div
      className={`bg-[var(--bg-surface)] rounded animate-pulse ${className}`}
    />
  );
}

export default function BacktestDetailPage() {
  const params = useParams();
  const id = typeof params.id === "string" ? params.id : null;
  const { data: session, error, isLoading } = useBacktestSession(id);
  const { data: chartData } = useChartData(
    session?.has_chart_data ? id : null
  );
  const { data: notes, mutate: mutateNotes } = useSessionResearchNotes(id);

  if (isLoading) {
    return (
      <div className="p-6 space-y-4">
        <SkeletonBlock className="h-8 w-96" />
        <div className="grid grid-cols-4 gap-3">
          {[...Array(4)].map((_, i) => (
            <SkeletonBlock key={i} className="h-20" />
          ))}
        </div>
        <SkeletonBlock className="h-72" />
        <div className="grid grid-cols-2 gap-4">
          <SkeletonBlock className="h-64" />
          <SkeletonBlock className="h-64" />
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-6">
        <div className="bg-[var(--red)]/10 border border-[var(--red)]/30 rounded-lg p-4 text-[var(--red)]">
          Failed to load session. Is the OpenQuant server running?
        </div>
      </div>
    );
  }

  if (!session) {
    return (
      <div className="p-6">
        <div className="text-center py-16 text-[var(--text-secondary)]">
          <p className="text-lg mb-2">Session not found</p>
          <Link href="/" className="text-sm text-[var(--blue)] hover:underline">
            Back to results
          </Link>
        </div>
      </div>
    );
  }

  const metrics = session.metrics;
  const trades = session.trades;
  const pnlColor =
    metrics && metrics.net_profit_percentage >= 0
      ? "text-[var(--green)]"
      : "text-[var(--red)]";
  const vsColor =
    metrics?.benchmark?.alpha != null &&
    metrics.benchmark.alpha >= 0
      ? "text-[var(--green)]"
      : "text-[var(--red)]";

  return (
    <div className="p-6 space-y-5">
      {/* Header */}
      <div>
        <Link
          href="/"
          className="text-sm text-[var(--text-secondary)] hover:text-[var(--text-primary)] transition-colors"
        >
          &larr; Back
        </Link>
        <h1 className="text-lg font-semibold text-[var(--text-heading)] mt-1">
          {getStrategyName(session)} &middot; {getSymbol(session)} &middot;{" "}
          {formatPeriod(session)}
        </h1>
      </div>

      {/* Stat cards */}
      {metrics && (
        <div className="grid grid-cols-4 gap-3">
          <StatCard
            label="Net PnL"
            value={formatPnl(metrics.net_profit_percentage)}
            className={pnlColor}
          />
          <StatCard
            label="Sharpe Ratio"
            value={(metrics.sharpe_ratio ?? 0).toFixed(2)}
          />
          <StatCard
            label="Win Rate"
            value={`${(metrics.win_rate ?? 0).toFixed(1)}%`}
          />
          <StatCard
            label="vs Buy & Hold"
            value={
              metrics.benchmark?.alpha != null
                ? formatPnl(metrics.benchmark.alpha)
                : "--"
            }
            className={vsColor}
          />
        </div>
      )}

      {/* Regime timeline + price chart */}
      <RegimeTimeline
        chartData={chartData ?? null}
        regimePeriods={session.regime_periods ?? null}
        equityCurve={
          session.equity_curve && (session.equity_curve as any[]).length > 0
            ? ((session.equity_curve as any[])[0].data ?? []).map((pt: any) => ({ time: pt.time, value: pt.value }))
            : null
        }
        trades={trades ?? undefined}
      />

      {/* Bottom section: trades table + stats sidebar */}
      <div className="grid grid-cols-2 gap-4">
        {/* Trades table */}
        <div className="bg-[var(--bg-surface)] border border-[var(--border)] rounded-lg p-4 overflow-auto max-h-[420px]">
          <div className="text-[13px] font-semibold text-[var(--text-heading)] mb-3">
            Trades ({trades?.length ?? 0})
          </div>
          {trades && trades.length > 0 ? (
            <table className="w-full border-collapse text-xs">
              <thead>
                <tr className="text-[var(--text-secondary)] border-b border-[var(--border)]">
                  <th className="text-left py-1.5 font-medium">Entry</th>
                  <th className="text-left py-1.5 font-medium">Exit</th>
                  <th className="text-left py-1.5 font-medium">Type</th>
                  <th className="text-right py-1.5 font-medium">PnL %</th>
                  <th className="text-right py-1.5 font-medium">Duration</th>
                </tr>
              </thead>
              <tbody>
                {trades.map((trade: Trade) => (
                  <tr
                    key={trade.id}
                    className="border-b border-[var(--border)]/50"
                  >
                    <td className="py-1.5 text-[var(--text-primary)]">
                      {formatDate(trade.opened_at)}
                    </td>
                    <td className="py-1.5 text-[var(--text-primary)]">
                      {formatDate(trade.closed_at)}
                    </td>
                    <td className="py-1.5">
                      <span
                        className={
                          trade.type === "long"
                            ? "text-[var(--green)]"
                            : "text-[var(--red)]"
                        }
                      >
                        {trade.type.toUpperCase()}
                      </span>
                    </td>
                    <td
                      className={`py-1.5 text-right ${
                        trade.PNL_percentage >= 0
                          ? "text-[var(--green)]"
                          : "text-[var(--red)]"
                      }`}
                    >
                      {formatPnl(trade.PNL_percentage)}
                    </td>
                    <td className="py-1.5 text-right text-[var(--text-secondary)]">
                      {formatHoldingPeriod(trade.holding_period)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <div className="text-[var(--text-secondary)] text-center py-8 text-sm">
              No trades recorded.
            </div>
          )}
        </div>

        {/* Session stats sidebar */}
        <div className="bg-[var(--bg-surface)] border border-[var(--border)] rounded-lg p-4">
          <div className="text-[13px] font-semibold text-[var(--text-heading)] mb-3">
            Session Stats
          </div>
          {metrics ? (
            <div className="space-y-3 text-sm">
              <StatRow
                label="Max Drawdown"
                value={`${(metrics.max_drawdown ?? 0).toFixed(2)}%`}
                className="text-[var(--red)]"
              />
              <StatRow
                label="Avg Trade Duration"
                value={formatHoldingPeriod(metrics.average_holding_period ?? 0)}
              />
              <StatRow
                label="Profit Factor"
                value={(metrics.profit_factor ?? 0).toFixed(2)}
              />
              <StatRow
                label="Win/Loss Ratio"
                value={(metrics.ratio_avg_win_loss ?? 0).toFixed(2)}
              />
              <StatRow
                label="Total Fees"
                value={`$${(metrics.fee ?? 0).toFixed(2)}`}
              />
              <StatRow
                label="Regime Changes"
                value={String(session.regime_periods?.length ?? 0)}
              />
              <StatRow
                label="Total Trades"
                value={String(metrics.total ?? 0)}
              />
              <StatRow
                label="Winning Streak"
                value={String(metrics.winning_streak)}
                className="text-[var(--green)]"
              />
              <StatRow
                label="Losing Streak"
                value={String(metrics.losing_streak)}
                className="text-[var(--red)]"
              />
            </div>
          ) : (
            <div className="text-[var(--text-secondary)] text-center py-8 text-sm">
              No metrics available.
            </div>
          )}
        </div>
      </div>

      {/* Research Notes */}
      <ResearchNotesPanel
        sessionId={id ?? ""}
        strategyName={getStrategyName(session)}
        notes={notes ?? []}
        onNoteCreated={() => mutateNotes()}
      />
    </div>
  );
}

function ResearchNotesPanel({
  sessionId,
  strategyName,
  notes,
  onNoteCreated,
}: {
  sessionId: string;
  strategyName: string;
  notes: ResearchNote[];
  onNoteCreated: () => void;
}) {
  const [isAdding, setIsAdding] = useState(false);
  const [hypothesis, setHypothesis] = useState("");
  const [diagnosis, setDiagnosis] = useState("");
  const [nextSteps, setNextSteps] = useState("");
  const [resultSummary, setResultSummary] = useState("");
  const [saving, setSaving] = useState(false);

  async function handleSave() {
    setSaving(true);
    try {
      await createResearchNote({
        session_id: sessionId,
        strategy_name: strategyName,
        hypothesis: hypothesis || undefined,
        result_summary: resultSummary || undefined,
        diagnosis: diagnosis || undefined,
        next_steps: nextSteps || undefined,
        author: "human",
      });
      setHypothesis("");
      setDiagnosis("");
      setNextSteps("");
      setResultSummary("");
      setIsAdding(false);
      onNoteCreated();
    } finally {
      setSaving(false);
    }
  }

  function formatNoteDate(ts: number): string {
    if (ts > 1e12) {
      return new Date(ts).toLocaleDateString("en-US", {
        month: "short",
        day: "numeric",
        year: "numeric",
      });
    }
    return "?";
  }

  return (
    <div className="bg-[var(--bg-surface)] border border-[var(--border)] rounded-lg p-4">
      <div className="flex items-center justify-between mb-3">
        <div className="text-[13px] font-semibold text-[var(--text-heading)]">
          Research Notes ({notes.length})
        </div>
        {!isAdding && (
          <button
            onClick={() => setIsAdding(true)}
            className="text-xs text-[var(--blue)] hover:underline"
          >
            + Add Note
          </button>
        )}
      </div>

      {/* Add note form */}
      {isAdding && (
        <div className="border border-[var(--border)] rounded-lg p-3 mb-3 space-y-2">
          <NoteField
            label="Hypothesis"
            value={hypothesis}
            onChange={setHypothesis}
            placeholder="What did you expect?"
          />
          <NoteField
            label="Result"
            value={resultSummary}
            onChange={setResultSummary}
            placeholder="PnL, Sharpe, win rate, trades (one line)"
          />
          <NoteField
            label="Diagnosis"
            value={diagnosis}
            onChange={setDiagnosis}
            placeholder="What went wrong (or right) and why?"
          />
          <NoteField
            label="Next Steps"
            value={nextSteps}
            onChange={setNextSteps}
            placeholder="What to try based on this"
          />
          <div className="flex gap-2 pt-1">
            <button
              onClick={handleSave}
              disabled={saving}
              className="text-xs px-3 py-1.5 bg-[var(--blue)] text-white rounded hover:opacity-90 disabled:opacity-50"
            >
              {saving ? "Saving..." : "Save"}
            </button>
            <button
              onClick={() => setIsAdding(false)}
              className="text-xs px-3 py-1.5 text-[var(--text-secondary)] hover:text-[var(--text-primary)]"
            >
              Cancel
            </button>
          </div>
        </div>
      )}

      {/* Existing notes */}
      {notes.length > 0 ? (
        <div className="space-y-3">
          {notes.map((note) => (
            <div
              key={note.id}
              className="border border-[var(--border)]/50 rounded p-3"
            >
              <div className="flex items-center gap-2 mb-2 text-xs text-[var(--text-secondary)]">
                <span>Round {note.round_number ?? "?"}</span>
                <span>&middot;</span>
                <span>{formatNoteDate(note.created_at)}</span>
                <span>&middot;</span>
                <span>{note.author ?? "human"}</span>
                {note.tags.length > 0 && (
                  <>
                    <span>&middot;</span>
                    {note.tags.map((tag) => (
                      <span
                        key={tag}
                        className="px-1.5 py-0.5 bg-[var(--border)] rounded text-[10px]"
                      >
                        {tag}
                      </span>
                    ))}
                  </>
                )}
              </div>
              <div className="space-y-1.5 text-xs">
                {note.hypothesis && (
                  <NoteRow label="Hypothesis" value={note.hypothesis} />
                )}
                {note.result_summary && (
                  <NoteRow label="Result" value={note.result_summary} />
                )}
                {note.regime_quality && (
                  <NoteRow label="Regime" value={note.regime_quality} />
                )}
                {note.diagnosis && (
                  <NoteRow label="Diagnosis" value={note.diagnosis} />
                )}
                {note.next_steps && (
                  <NoteRow label="Next" value={note.next_steps} />
                )}
              </div>
            </div>
          ))}
        </div>
      ) : (
        !isAdding && (
          <div className="text-[var(--text-secondary)] text-center py-6 text-sm">
            No research notes yet. Click &ldquo;+ Add Note&rdquo; or use{" "}
            <code className="text-xs bg-[var(--border)] px-1 py-0.5 rounded">
              jesse annotate {sessionId.slice(0, 8)}...
            </code>
          </div>
        )
      )}
    </div>
  );
}

function NoteField({
  label,
  value,
  onChange,
  placeholder,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  placeholder: string;
}) {
  return (
    <div>
      <label className="text-[10px] uppercase tracking-wide text-[var(--text-secondary)] mb-0.5 block">
        {label}
      </label>
      <textarea
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        rows={2}
        className="w-full bg-[var(--bg-primary)] border border-[var(--border)] rounded px-2 py-1.5 text-xs text-[var(--text-primary)] placeholder-[var(--text-secondary)]/50 resize-none focus:outline-none focus:border-[var(--blue)]"
      />
    </div>
  );
}

function NoteRow({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <span className="text-[var(--text-secondary)]">{label}: </span>
      <span className="text-[var(--text-primary)]">{value}</span>
    </div>
  );
}

function StatRow({
  label,
  value,
  className = "",
}: {
  label: string;
  value: string;
  className?: string;
}) {
  return (
    <div className="flex justify-between items-center py-1.5 border-b border-[var(--border)]/30">
      <span className="text-[var(--text-secondary)]">{label}</span>
      <span className={`font-medium ${className || "text-[var(--text-primary)]"}`}>
        {value}
      </span>
    </div>
  );
}
