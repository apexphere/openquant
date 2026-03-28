"use client";
import { useState } from "react";
import { useBacktestSessions, useBacktestSession, useChartData } from "@/hooks/use-backtest";
import { StatCard } from "@/components/stat-card";
import { RegimeTimeline } from "@/components/regime-timeline";

function getLabel(session: any): string {
  const strategy = session.strategy_name ?? session.state?.form?.routes?.[0]?.strategy ?? "Unknown";
  const symbol = session.state?.form?.routes?.[0]?.symbol ?? "—";
  const start = session.state?.form?.start_date ?? "";
  const finish = session.state?.form?.finish_date ?? "";
  return `${strategy} | ${symbol} | ${start} → ${finish}`;
}

function fmt(n: number | null | undefined, decimals = 2): string {
  if (n == null) return "—";
  return `${n >= 0 ? "+" : ""}${n.toFixed(decimals)}%`;
}

function ComparisonColumn({ sessionId }: { sessionId: string }) {
  const { data: session, isLoading } = useBacktestSession(sessionId);
  const { data: chartData } = useChartData(session?.has_chart_data ? sessionId : null);

  if (isLoading || !session) {
    return <div className="h-64 bg-[var(--bg-surface)] rounded animate-pulse" />;
  }

  const pnl = session.metrics?.net_profit_percentage;
  const sharpe = session.metrics?.sharpe_ratio;
  const winRate = session.metrics?.win_rate;
  const maxDD = session.metrics?.max_drawdown;

  return (
    <div className="space-y-3">
      <div className="flex justify-between items-baseline">
        <span className="font-semibold text-sm text-[var(--text-heading)]">
          {session.strategy_name ?? "Unknown"}
        </span>
        <span className={`text-base font-semibold ${pnl != null && pnl >= 0 ? "text-[var(--green)]" : "text-[var(--red)]"}`}>
          {fmt(pnl)}
        </span>
      </div>

      <RegimeTimeline
        chartData={chartData ?? null}
        regimePeriods={session.regime_periods}
        trades={session.trades ?? undefined}
      />

      <div className="grid grid-cols-3 gap-2">
        <StatCard label="Sharpe" value={sharpe?.toFixed(2) ?? "—"} />
        <StatCard label="Win Rate" value={winRate != null ? `${(winRate * 100).toFixed(0)}%` : "—"} />
        <StatCard label="Max DD" value={maxDD != null ? `${maxDD.toFixed(1)}%` : "—"} />
      </div>
    </div>
  );
}

export default function ComparePage() {
  const { data: sessions, isLoading } = useBacktestSessions();
  const [leftId, setLeftId] = useState<string | null>(null);
  const [rightId, setRightId] = useState<string | null>(null);

  const finished = (sessions ?? []).filter((s) => s.status === "finished");

  return (
    <div className="p-6">
      <h1 className="text-lg font-semibold text-[var(--text-heading)] mb-5">
        Compare Strategies
      </h1>

      {/* Dropdowns */}
      <div className="grid grid-cols-2 gap-4 mb-6">
        <select
          value={leftId ?? ""}
          onChange={(e) => setLeftId(e.target.value || null)}
          className="bg-[var(--bg-surface)] border border-[var(--border)] rounded-lg px-3 py-2 text-sm text-[var(--text-primary)] focus:border-[var(--blue)] outline-none"
        >
          <option value="">Select session...</option>
          {finished.map((s) => (
            <option key={s.id} value={s.id}>{getLabel(s)}</option>
          ))}
        </select>
        <select
          value={rightId ?? ""}
          onChange={(e) => setRightId(e.target.value || null)}
          className="bg-[var(--bg-surface)] border border-[var(--border)] rounded-lg px-3 py-2 text-sm text-[var(--text-primary)] focus:border-[var(--blue)] outline-none"
        >
          <option value="">Select session...</option>
          {finished.map((s) => (
            <option key={s.id} value={s.id}>{getLabel(s)}</option>
          ))}
        </select>
      </div>

      {/* Comparison */}
      {!leftId && !rightId ? (
        <div className="text-center py-16 text-[var(--text-secondary)]">
          Select two sessions to compare side-by-side.
        </div>
      ) : leftId === rightId && leftId ? (
        <div className="bg-[var(--yellow)]/10 border border-[var(--yellow)]/30 rounded-lg p-3 text-[var(--yellow)] text-sm mb-4">
          You selected the same session for both columns.
        </div>
      ) : (
        <div className="grid grid-cols-2 gap-6">
          <div>{leftId && <ComparisonColumn sessionId={leftId} />}</div>
          <div>{rightId && <ComparisonColumn sessionId={rightId} />}</div>
        </div>
      )}
    </div>
  );
}
