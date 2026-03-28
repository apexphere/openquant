"use client";
import { useState, useMemo } from "react";
import Link from "next/link";
import { useBacktestSessions } from "@/hooks/use-backtest";
import { MiniSparkline } from "@/components/mini-sparkline";

function formatTimeAgo(dateStr: string): string {
  const diff = Date.now() - new Date(dateStr).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}

function getStrategyName(session: any): string {
  if (session.strategy_name) return session.strategy_name;
  try {
    return session.state?.form?.routes?.[0]?.strategy ?? "Unknown";
  } catch {
    return "Unknown";
  }
}

function getSymbol(session: any): string {
  try {
    return session.state?.form?.routes?.[0]?.symbol ?? "—";
  } catch {
    return "—";
  }
}

function getPeriod(session: any): string {
  try {
    const start = session.state?.form?.start_date ?? "";
    const finish = session.state?.form?.finish_date ?? "";
    if (!start || !finish) return "—";
    const s = new Date(start).toLocaleDateString("en-US", { month: "short", year: "numeric" });
    const f = new Date(finish).toLocaleDateString("en-US", { month: "short", year: "numeric" });
    return `${s} - ${f}`;
  } catch {
    return "—";
  }
}

export default function BacktestResultsPage() {
  const { data: sessions, error, isLoading } = useBacktestSessions();
  const [strategyFilter, setStrategyFilter] = useState<string | null>(null);
  const [symbolFilter, setSymbolFilter] = useState<string | null>(null);
  const [sortKey, setSortKey] = useState<string>("created_at");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("desc");

  const strategies = useMemo(() => {
    if (!sessions) return [];
    const names = new Set(sessions.map(getStrategyName));
    return Array.from(names).sort();
  }, [sessions]);

  const symbols = useMemo(() => {
    if (!sessions) return [];
    const syms = new Set(sessions.map(getSymbol));
    return Array.from(syms).sort();
  }, [sessions]);

  const filtered = useMemo(() => {
    if (!sessions) return [];
    return sessions.filter((s) => {
      if (strategyFilter && getStrategyName(s) !== strategyFilter) return false;
      if (symbolFilter && getSymbol(s) !== symbolFilter) return false;
      if (s.status !== "finished") return false;
      return true;
    });
  }, [sessions, strategyFilter, symbolFilter]);

  const sorted = useMemo(() => {
    return [...filtered].sort((a, b) => {
      let va: any, vb: any;
      if (sortKey === "created_at") {
        va = new Date(a.created_at).getTime();
        vb = new Date(b.created_at).getTime();
      } else if (sortKey === "pnl") {
        va = a.net_profit_percentage ?? 0;
        vb = b.net_profit_percentage ?? 0;
      } else {
        va = (a as any)[sortKey] ?? 0;
        vb = (b as any)[sortKey] ?? 0;
      }
      return sortDir === "desc" ? vb - va : va - vb;
    });
  }, [filtered, sortKey, sortDir]);

  const handleSort = (key: string) => {
    if (sortKey === key) {
      setSortDir(sortDir === "desc" ? "asc" : "desc");
    } else {
      setSortKey(key);
      setSortDir("desc");
    }
  };

  if (error) {
    return (
      <div className="p-6">
        <div className="bg-[var(--red)]/10 border border-[var(--red)]/30 rounded-lg p-4 text-[var(--red)]">
          Could not connect to OpenQuant server at localhost:9000. Is <code>jesse run</code> running?
        </div>
      </div>
    );
  }

  return (
    <div className="p-6">
      <div className="flex justify-between items-center mb-5">
        <h1 className="text-lg font-semibold text-[var(--text-heading)]">
          Backtest Results
        </h1>
      </div>

      {/* Filter chips */}
      <div className="flex gap-2 mb-4">
        <button
          onClick={() => { setStrategyFilter(null); setSymbolFilter(null); }}
          className={`px-3 py-1 rounded-xl border text-xs transition-colors ${
            !strategyFilter && !symbolFilter
              ? "border-[var(--blue)] text-[var(--blue)] bg-[var(--blue)]/10"
              : "border-[var(--border)] text-[var(--text-secondary)]"
          }`}
        >
          All
        </button>
        {strategies.map((s) => (
          <button
            key={s}
            onClick={() => setStrategyFilter(strategyFilter === s ? null : s)}
            className={`px-3 py-1 rounded-xl border text-xs transition-colors ${
              strategyFilter === s
                ? "border-[var(--blue)] text-[var(--blue)] bg-[var(--blue)]/10"
                : "border-[var(--border)] text-[var(--text-secondary)]"
            }`}
          >
            {s}
          </button>
        ))}
        {symbols.filter((s) => s !== "—").map((s) => (
          <button
            key={s}
            onClick={() => setSymbolFilter(symbolFilter === s ? null : s)}
            className={`px-3 py-1 rounded-xl border text-xs transition-colors ${
              symbolFilter === s
                ? "border-[var(--blue)] text-[var(--blue)] bg-[var(--blue)]/10"
                : "border-[var(--border)] text-[var(--text-secondary)]"
            }`}
          >
            {s}
          </button>
        ))}
      </div>

      {isLoading ? (
        <div className="space-y-2">
          {[...Array(5)].map((_, i) => (
            <div key={i} className="h-12 bg-[var(--bg-surface)] rounded animate-pulse" />
          ))}
        </div>
      ) : sorted.length === 0 ? (
        <div className="text-center py-16 text-[var(--text-secondary)]">
          <p className="text-lg mb-2">No backtests yet.</p>
          <p className="text-sm">
            Run <code className="text-[var(--blue)]">jesse backtest &lt;strategy&gt; --start YYYY-MM-DD --finish YYYY-MM-DD</code>
          </p>
        </div>
      ) : (
        <table className="w-full border-collapse">
          <thead>
            <tr>
              <Th>Strategy</Th>
              <Th>Symbol</Th>
              <Th>Period</Th>
              <Th sortable onClick={() => handleSort("pnl")}>PnL %</Th>
              <Th>Equity</Th>
              <Th sortable onClick={() => handleSort("created_at")}>Time</Th>
            </tr>
          </thead>
          <tbody>
            {sorted.map((session) => {
              const pnl = session.net_profit_percentage;
              return (
                <tr
                  key={session.id}
                  className="border-b border-[var(--border)] hover:bg-[var(--blue)]/[0.04] cursor-pointer transition-colors"
                >
                  <td className="py-2.5 px-3">
                    <Link href={`/backtests/${session.id}`} className="block">
                      <span className="inline-block px-2 py-0.5 rounded-lg text-[11px] bg-[var(--blue)]/15 text-[var(--blue)]">
                        {getStrategyName(session)}
                      </span>
                    </Link>
                  </td>
                  <td className="py-2.5 px-3">
                    <Link href={`/backtests/${session.id}`} className="block">
                      <span className="inline-block px-2 py-0.5 rounded-lg text-[11px] bg-[var(--text-secondary)]/15 text-[var(--text-secondary)]">
                        {getSymbol(session)}
                      </span>
                    </Link>
                  </td>
                  <td className="py-2.5 px-3">
                    <Link href={`/backtests/${session.id}`} className="block">
                      {getPeriod(session)}
                    </Link>
                  </td>
                  <td className={`py-2.5 px-3 ${pnl != null && pnl >= 0 ? "text-[var(--green)]" : "text-[var(--red)]"}`}>
                    <Link href={`/backtests/${session.id}`} className="block">
                      {pnl != null ? `${pnl >= 0 ? "+" : ""}${pnl.toFixed(2)}%` : "—"}
                    </Link>
                  </td>
                  <td className="py-2.5 px-3">
                    <Link href={`/backtests/${session.id}`} className="block">
                      <MiniSparkline data={session.equity_curve_sample} />
                    </Link>
                  </td>
                  <td className="py-2.5 px-3 text-[var(--text-secondary)]">
                    <Link href={`/backtests/${session.id}`} className="block">
                      {formatTimeAgo(session.created_at)}
                    </Link>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
    </div>
  );
}

function Th({
  children,
  sortable,
  onClick,
}: {
  children: React.ReactNode;
  sortable?: boolean;
  onClick?: () => void;
}) {
  return (
    <th
      className={`text-left py-2 px-3 text-[var(--text-secondary)] font-medium text-xs border-b border-[var(--border)] ${
        sortable ? "cursor-pointer hover:text-[var(--text-primary)]" : ""
      }`}
      onClick={onClick}
    >
      {children}
    </th>
  );
}
