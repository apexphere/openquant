"use client";

import Link from "next/link";
import { useStrategiesWithNotes } from "@/hooks/use-research-notes";

function formatDate(ts: number): string {
  if (ts > 1e12) {
    return new Date(ts).toLocaleDateString("en-US", {
      month: "short",
      day: "numeric",
      year: "numeric",
    });
  }
  return "?";
}

export default function ResearchIndexPage() {
  const { data: strategies, isLoading } = useStrategiesWithNotes();

  return (
    <div className="p-6 space-y-5">
      <div>
        <h1 className="text-lg font-semibold text-[var(--text-heading)]">
          Research Notes
        </h1>
        <p className="text-sm text-[var(--text-secondary)] mt-1">
          Strategy research history and iteration notes
        </p>
      </div>

      {isLoading ? (
        <div className="space-y-2">
          {[...Array(3)].map((_, i) => (
            <div
              key={i}
              className="h-16 bg-[var(--bg-surface)] rounded animate-pulse"
            />
          ))}
        </div>
      ) : strategies && strategies.length > 0 ? (
        <div className="space-y-2">
          {strategies.map((s) => (
            <Link
              key={s.strategy_name}
              href={`/research/${encodeURIComponent(s.strategy_name)}`}
              className="block bg-[var(--bg-surface)] border border-[var(--border)] rounded-lg p-4 hover:border-[var(--blue)]/50 transition-colors"
            >
              <div className="flex items-center justify-between">
                <div>
                  <div className="text-sm font-medium text-[var(--text-heading)]">
                    {s.strategy_name}
                  </div>
                  <div className="text-xs text-[var(--text-secondary)] mt-0.5">
                    {s.note_count} note{s.note_count !== 1 ? "s" : ""} &middot;
                    last updated {formatDate(s.last_updated)}
                  </div>
                </div>
                <span className="text-[var(--text-secondary)]">&rarr;</span>
              </div>
            </Link>
          ))}
        </div>
      ) : (
        <div className="text-center py-16 text-[var(--text-secondary)]">
          <p className="text-sm mb-2">No research notes yet.</p>
          <p className="text-xs">
            Use{" "}
            <code className="bg-[var(--border)] px-1.5 py-0.5 rounded">
              jesse annotate &lt;session-id&gt;
            </code>{" "}
            or add notes from a backtest detail page.
          </p>
        </div>
      )}
    </div>
  );
}
