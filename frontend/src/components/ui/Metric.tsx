/** Compact label-over-value fact. Older sibling of StatTile, kept for dense staff grids. */
export function Metric({ label, value, danger = false }: {
  label: string;
  value?: string | number;
  danger?: boolean;
}) {
  return (
    <div className="min-w-0 rounded-lg border border-line bg-canvas p-3">
      <p className="text-sm text-ink-muted">{label}</p>
      <p className={`mt-0.5 font-display text-2xl font-extrabold leading-tight tracking-[-0.02em] ${danger ? "text-danger-fg" : "text-ink"}`}>
        {value ?? 0}
      </p>
    </div>
  );
}
