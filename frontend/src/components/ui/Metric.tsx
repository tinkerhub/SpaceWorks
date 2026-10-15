export function Metric({ label, value, danger = false }: {
  label: string;
  value?: string | number;
  danger?: boolean;
}) {
  return (
    <div className="rounded-lg border border-line bg-surface p-3 shadow-brutal-sm">
      <p className="eyebrow">{label}</p>
      <p className={`mt-1 text-lg font-semibold ${danger ? "text-danger" : "text-ink"}`}>{value ?? 0}</p>
    </div>
  );
}
