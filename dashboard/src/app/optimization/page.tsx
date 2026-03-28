"use client";
import { useState } from "react";
import { useOptimizationSessions } from "@/hooks/use-optimization";
import { StatCard } from "@/components/stat-card";
import type { OptimizationSession, OptimizationTrial } from "@/lib/types";

function getStrategyName(session: OptimizationSession): string {
  if (session.strategy_name) return session.strategy_name;
  if (session.state?.form?.routes?.[0]?.strategy) return session.state.form.routes[0].strategy;
  // Fallback: extract class name from strategy_codes
  const codes = (session as any).strategy_codes;
  if (codes && typeof codes === "object") {
    for (const v of Object.values(codes)) {
      if (typeof v === "string") {
        const match = (v as string).match(/class\s+(\w+)\s*\(/);
        if (match) return match[1];
      }
    }
  }
  return "Unknown";
}

function TrialScatter({ trials }: { trials: OptimizationTrial[] }) {
  if (!trials || trials.length === 0) {
    return (
      <div className="text-[var(--text-secondary)] text-center py-8">
        No trial data available.
      </div>
    );
  }

  const paramNames = Object.keys(trials[0]?.parameters ?? {});
  if (paramNames.length < 2) {
    // 1D bar chart fallback
    const paramName = paramNames[0] ?? "param";
    return (
      <div className="space-y-1">
        <div className="text-xs text-[var(--text-secondary)] mb-2">
          {paramName} vs Fitness
        </div>
        {trials.slice(0, 20).map((t, i) => {
          const val = t.parameters[paramName];
          const maxFitness = Math.max(...trials.map((tr) => tr.fitness));
          const width = (t.fitness / maxFitness) * 100;
          return (
            <div key={i} className="flex items-center gap-2 text-xs">
              <span className="w-16 text-right text-[var(--text-secondary)]">{val}</span>
              <div className="flex-1 h-4 bg-[var(--border)] rounded overflow-hidden">
                <div
                  className="h-full rounded bg-[var(--green)]"
                  style={{ width: `${Math.max(width, 2)}%`, opacity: 0.3 + (width / 100) * 0.7 }}
                />
              </div>
              <span className="w-12 text-right">{t.fitness.toFixed(2)}</span>
            </div>
          );
        })}
      </div>
    );
  }

  // 2D scatter
  const [xParam, yParam] = paramNames;
  const xValues = trials.map((t) => t.parameters[xParam] as number);
  const yValues = trials.map((t) => t.parameters[yParam] as number);
  const xMin = Math.min(...xValues);
  const xMax = Math.max(...xValues);
  const yMin = Math.min(...yValues);
  const yMax = Math.max(...yValues);
  const xRange = xMax - xMin || 1;
  const yRange = yMax - yMin || 1;
  const maxFitness = Math.max(...trials.map((t) => t.fitness));
  const minFitness = Math.min(...trials.map((t) => t.fitness));
  const fRange = maxFitness - minFitness || 1;

  return (
    <div>
      <div className="text-xs text-[var(--text-secondary)] mb-2">
        {xParam} vs {yParam} (color = fitness)
      </div>
      <svg viewBox="0 0 400 300" className="w-full" style={{ maxHeight: 300 }}>
        {trials.map((t, i) => {
          const x = 40 + ((t.parameters[xParam] as number - xMin) / xRange) * 340;
          const y = 280 - ((t.parameters[yParam] as number - yMin) / yRange) * 260;
          const norm = (t.fitness - minFitness) / fRange;
          const color =
            norm > 0.5
              ? `rgba(63,185,80,${0.3 + norm * 0.7})`
              : `rgba(248,81,73,${0.3 + (1 - norm) * 0.7})`;
          return (
            <circle
              key={i}
              cx={x}
              cy={y}
              r={i === 0 ? 6 : 4}
              fill={color}
              stroke={i === 0 ? "var(--green)" : "none"}
              strokeWidth={2}
            >
              <title>
                {xParam}={t.parameters[xParam]}, {yParam}={t.parameters[yParam]}, fitness={t.fitness.toFixed(3)}
              </title>
            </circle>
          );
        })}
        {/* Axes */}
        <line x1="40" y1="280" x2="380" y2="280" stroke="var(--border)" />
        <line x1="40" y1="20" x2="40" y2="280" stroke="var(--border)" />
        <text x="210" y="298" fill="var(--text-secondary)" fontSize="10" textAnchor="middle">{xParam}</text>
        <text x="12" y="150" fill="var(--text-secondary)" fontSize="10" textAnchor="middle" transform="rotate(-90,12,150)">{yParam}</text>
      </svg>
    </div>
  );
}

export default function OptimizationPage() {
  const { data: sessions, error, isLoading } = useOptimizationSessions();
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const selected = sessions?.find((s) => s.id === selectedId);

  if (error) {
    return (
      <div className="p-6">
        <div className="bg-[var(--red)]/10 border border-[var(--red)]/30 rounded-lg p-4 text-[var(--red)]">
          Could not connect to OpenQuant server at localhost:9000.
        </div>
      </div>
    );
  }

  return (
    <div className="p-6">
      <h1 className="text-lg font-semibold text-[var(--text-heading)] mb-5">
        Optimization Explorer
      </h1>

      {isLoading ? (
        <div className="space-y-2">
          {[...Array(3)].map((_, i) => (
            <div key={i} className="h-12 bg-[var(--bg-surface)] rounded animate-pulse" />
          ))}
        </div>
      ) : !sessions || sessions.length === 0 ? (
        <div className="text-center py-16 text-[var(--text-secondary)]">
          <p className="text-lg mb-2">No optimization sessions.</p>
          <p className="text-sm">
            Run <code className="text-[var(--blue)]">jesse optimize &lt;strategy&gt; ...</code>
          </p>
        </div>
      ) : (
        <div className="grid grid-cols-[300px_1fr] gap-6">
          {/* Session list */}
          <div className="space-y-2">
            {sessions.filter((s) => s.status === "finished" || s.status === "running").map((session) => {
              const completed = (session as any).completed_trials ?? 0;
              const total = (session as any).total_trials ?? 0;
              const bestScore = (session as any).best_score;
              const isRunning = session.status === "running";
              return (
              <button
                key={session.id}
                onClick={() => setSelectedId(session.id)}
                className={`w-full text-left p-3 rounded-lg border transition-colors ${
                  selectedId === session.id
                    ? "border-[var(--blue)] bg-[var(--blue)]/10"
                    : "border-[var(--border)] bg-[var(--bg-surface)] hover:border-[var(--text-secondary)]"
                }`}
              >
                <div className="flex items-center gap-2">
                  <span className="font-medium text-sm">{getStrategyName(session)}</span>
                  {isRunning && <span className="w-2 h-2 rounded-full bg-[var(--green)] animate-pulse" />}
                </div>
                <div className="text-xs text-[var(--text-secondary)] mt-1">
                  {completed}/{total} trials{bestScore != null ? ` · best: ${bestScore.toFixed(4)}` : ""}
                </div>
              </button>
              );
            ))}
          </div>

          {/* Detail panel */}
          <div>
            {!selected ? (
              <div className="text-[var(--text-secondary)] text-center py-16">
                Select an optimization session to explore.
              </div>
            ) : (
              <div className="space-y-4">
                <div className="grid grid-cols-4 gap-3">
                  <StatCard
                    label="Best Fitness"
                    value={selected.best_trials?.[0]?.fitness?.toFixed(3) ?? "—"}
                  />
                  <StatCard
                    label="Best Trial"
                    value={`#${selected.best_trials?.[0]?.rank ?? "—"}`}
                  />
                  <StatCard
                    label="Trials"
                    value={String(selected.best_trials?.length ?? 0)}
                  />
                  <StatCard
                    label="Duration"
                    value={
                      selected.execution_duration
                        ? `${Math.floor(selected.execution_duration / 60)}m`
                        : "—"
                    }
                  />
                </div>

                <div className="bg-[var(--bg-surface)] border border-[var(--border)] rounded-lg p-4">
                  <div className="text-[13px] font-semibold text-[var(--text-heading)] mb-3">
                    Top Trials Parameter Map
                  </div>
                  <TrialScatter trials={selected.best_trials ?? []} />
                </div>

                {/* Top trials table */}
                <div className="bg-[var(--bg-surface)] border border-[var(--border)] rounded-lg p-4">
                  <div className="text-[13px] font-semibold text-[var(--text-heading)] mb-3">
                    Top Trials
                  </div>
                  <table className="w-full text-xs">
                    <thead>
                      <tr>
                        <th className="text-left py-1.5 px-2 text-[var(--text-secondary)] font-medium border-b border-[var(--border)]">#</th>
                        <th className="text-left py-1.5 px-2 text-[var(--text-secondary)] font-medium border-b border-[var(--border)]">Fitness</th>
                        {Object.keys(selected.best_trials?.[0]?.parameters ?? {}).map((p) => (
                          <th key={p} className="text-left py-1.5 px-2 text-[var(--text-secondary)] font-medium border-b border-[var(--border)]">
                            {p}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {(selected.best_trials ?? []).slice(0, 10).map((trial, i) => (
                        <tr key={i} className="border-b border-[var(--bg-primary)]">
                          <td className="py-2 px-2">{trial.rank}</td>
                          <td className="py-2 px-2 text-[var(--green)]">
                            {trial.fitness.toFixed(3)}
                          </td>
                          {Object.values(trial.parameters).map((v, j) => (
                            <td key={j} className="py-2 px-2">
                              {typeof v === "number" ? v.toFixed(2) : String(v)}
                            </td>
                          ))}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
