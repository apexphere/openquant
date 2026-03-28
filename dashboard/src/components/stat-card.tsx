interface StatCardProps {
  label: string;
  value: string;
  className?: string;
}

export function StatCard({ label, value, className = "" }: StatCardProps) {
  return (
    <div className="bg-[var(--bg-surface)] border border-[var(--border)] rounded-lg px-4 py-3.5">
      <div className="text-[11px] text-[var(--text-secondary)] uppercase tracking-wider mb-1">
        {label}
      </div>
      <div className={`text-xl font-semibold ${className}`} aria-label={`${label}: ${value}`}>
        {value}
      </div>
    </div>
  );
}
