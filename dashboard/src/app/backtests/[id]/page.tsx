"use client";

import { useParams } from "next/navigation";
import Link from "next/link";
import { useBacktestSession, useChartData } from "@/hooks/use-backtest";
import { StatCard } from "@/components/stat-card";
import { RegimeTimeline } from "@/components/regime-timeline";
import type { BacktestSessionDetail, Trade } from "@/lib/types";

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
    metrics.benchmark.strat_vs_buy_and_hold >= 0
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
              metrics.benchmark?.strat_vs_buy_and_hold != null
                ? formatPnl(metrics.benchmark.strat_vs_buy_and_hold)
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
