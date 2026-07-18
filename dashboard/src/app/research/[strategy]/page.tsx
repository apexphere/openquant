"use client";

import { useParams } from "next/navigation";
import Link from "next/link";
import { useStrategyResearchNotes } from "@/hooks/use-research-notes";
import type { ResearchNote } from "@/lib/types";

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

function NoteRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="mt-1.5">
      <span className="text-[var(--text-secondary)] text-xs">{label}: </span>
      <span className="text-[var(--text-primary)] text-xs">{value}</span>
    </div>
  );
}

export default function StrategyResearchPage() {
  const params = useParams();
  const strategyName =
    typeof params.strategy === "string"
      ? decodeURIComponent(params.strategy)
      : null;
  const { data: notes, isLoading } = useStrategyResearchNotes(strategyName);

  return (
    <div className="p-6 space-y-5">
      <div>
        <Link
          href="/research"
          className="text-sm text-[var(--text-secondary)] hover:text-[var(--text-primary)] transition-colors"
        >
          &larr; All Strategies
        </Link>
        <h1 className="text-lg font-semibold text-[var(--text-heading)] mt-1">
          {strategyName}
        </h1>
        <p className="text-sm text-[var(--text-secondary)]">
          Research timeline &middot; {notes?.length ?? 0} notes
        </p>
      </div>

      {isLoading ? (
        <div className="space-y-3">
          {[...Array(3)].map((_, i) => (
            <div
              key={i}
              className="h-32 bg-[var(--bg-surface)] rounded animate-pulse"
            />
          ))}
        </div>
      ) : notes && notes.length > 0 ? (
        <div className="relative">
          {/* Timeline line */}
          <div className="absolute left-[15px] top-4 bottom-4 w-px bg-[var(--border)]" />

          <div className="space-y-4">
            {notes.map((note: ResearchNote) => (
              <div key={note.id} className="relative pl-10">
                {/* Timeline dot */}
                <div className="absolute left-[11px] top-4 w-[9px] h-[9px] rounded-full bg-[var(--blue)] border-2 border-[var(--bg-primary)]" />

                <div className="bg-[var(--bg-surface)] border border-[var(--border)] rounded-lg p-4">
                  {/* Header */}
                  <div className="flex items-center gap-2 text-xs text-[var(--text-secondary)] mb-2">
                    <span className="font-medium text-[var(--text-heading)]">
                      Round {note.round_number ?? "?"}
                    </span>
                    <span>&middot;</span>
                    <span>{formatDate(note.created_at)}</span>
                    <span>&middot;</span>
                    <span>{note.author ?? "human"}</span>
                    {note.session_id && (
                      <>
                        <span>&middot;</span>
                        <Link
                          href={`/backtests/${note.session_id}`}
                          className="text-[var(--blue)] hover:underline"
                        >
                          {note.session_id.slice(0, 8)}...
                        </Link>
                      </>
                    )}
                    {note.tags.length > 0 && (
                      <div className="flex gap-1 ml-1">
                        {note.tags.map((tag) => (
                          <span
                            key={tag}
                            className="px-1.5 py-0.5 bg-[var(--border)] rounded text-[10px]"
                          >
                            {tag}
                          </span>
                        ))}
                      </div>
                    )}
                  </div>

                  {/* Content */}
                  <div>
                    {note.hypothesis && (
                      <NoteRow label="Hypothesis" value={note.hypothesis} />
                    )}
                    {note.result_summary && (
                      <NoteRow label="Result" value={note.result_summary} />
                    )}
                    {note.regime_quality && (
                      <NoteRow label="Regime quality" value={note.regime_quality} />
                    )}
                    {note.diagnosis && (
                      <NoteRow label="Diagnosis" value={note.diagnosis} />
                    )}
                    {note.next_steps && (
                      <NoteRow label="Next steps" value={note.next_steps} />
                    )}
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      ) : (
        <div className="text-center py-16 text-[var(--text-secondary)]">
          <p className="text-sm">No research notes for {strategyName}.</p>
        </div>
      )}
    </div>
  );
}
