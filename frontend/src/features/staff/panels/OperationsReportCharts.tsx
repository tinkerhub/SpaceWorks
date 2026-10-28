import { formatNumber, type ChartRow } from "./OperationsReportState";

export const REPORT_CHART_COLORS = [
  "rgb(var(--color-accent))", "rgb(var(--color-warn))", "rgb(var(--color-success))",
  "rgb(var(--color-secondary))", "rgb(var(--color-danger))",
];

export function BarChart({ rows, valueLabel }: { rows: ChartRow[]; valueLabel?: string }) {
  const maxValue = Math.max(...rows.map((row) => row.value), 0);
  if (!rows.length || maxValue <= 0) return <p className="text-body-ui text-ink-muted">No chart data.</p>;
  // role="img" hides the rows from assistive technology, so the label carries the data.
  const description = rows.map((row) => `${row.label}: ${formatNumber(row.value)}`).join(", ");
  return (
    <div className="space-y-2" aria-label={`Bar chart of ${valueLabel ?? "values"}: ${description}`} role="img">
      {rows.map((row, index) => (
        <div key={`${row.label}-${index}`} className="grid grid-cols-[minmax(0,1fr)_minmax(4rem,2fr)_auto] items-center gap-2 text-body-ui sm:grid-cols-[minmax(7rem,11rem)_1fr_auto]">
          <span className="truncate text-ink" title={row.label}>{row.label}</span>
          <div className="h-2.5 overflow-hidden rounded-full bg-emphasis"><div className="h-full rounded-full" style={{ width: `${Math.max((row.value / maxValue) * 100, 4)}%`, backgroundColor: REPORT_CHART_COLORS[index % REPORT_CHART_COLORS.length] }} aria-hidden="true" /></div>
          <span className="min-w-14 text-right text-caption tabular-nums text-ink-muted">{formatNumber(row.value)} {valueLabel ?? ""}</span>
        </div>
      ))}
    </div>
  );
}

export function LineChart({ rows, valueLabel }: { rows: ChartRow[]; valueLabel?: string }) {
  const width = 640;
  const height = 180;
  const max = Math.max(...rows.map((row) => row.value), 0);
  if (!rows.length || max <= 0) return <p className="text-body-ui text-ink-muted">No chart data.</p>;
  const points = rows.map((row, index) => ({
    ...row,
    x: rows.length === 1 ? width / 2 : (index / (rows.length - 1)) * (width - 32) + 16,
    y: height - 16 - (row.value / max) * (height - 32),
  }));
  const description = points.map((point) => `${point.label}: ${formatNumber(point.value)}`).join(", ");
  return (
    <figure aria-label={`Line chart of ${valueLabel ?? "values"}: ${description}`}>
      <svg viewBox={`0 0 ${width} ${height}`} className="h-44 w-full" role="img">
        <title>{`Line chart of ${valueLabel ?? "values"}`}</title>
        <polyline fill="none" stroke={REPORT_CHART_COLORS[0]} strokeWidth="4" points={points.map((point) => `${point.x},${point.y}`).join(" ")} />
        {points.map((point, index) => <circle key={`${point.label}-${index}`} cx={point.x} cy={point.y} r="5" fill="rgb(var(--color-panel))" stroke={REPORT_CHART_COLORS[index % REPORT_CHART_COLORS.length]} strokeWidth="3" />)}
      </svg>
      <figcaption className="sr-only">{description}</figcaption>
    </figure>
  );
}

export type StackedChartRow = { label: string; segments: { label: string; value: number }[] };

export function StackedBarChart({ rows, valueLabel }: { rows: StackedChartRow[]; valueLabel?: string }) {
  const max = Math.max(...rows.map((row) => row.segments.reduce((sum, segment) => sum + segment.value, 0)), 0);
  if (!rows.length || max <= 0) return <p className="text-body-ui text-ink-muted">No chart data.</p>;
  const labels = [...new Set(rows.flatMap((row) => row.segments.map((segment) => segment.label)))];
  const description = rows.map((row) => `${row.label}: ${row.segments.map((segment) => `${segment.label} ${formatNumber(segment.value)}`).join(", ")}`).join("; ");
  return (
    <div role="img" aria-label={`Stacked bar chart of ${valueLabel ?? "values"}: ${description}`} className="space-y-3">
      {rows.map((row, index) => (
        <div key={`${row.label}-${index}`} className="grid grid-cols-[8rem_1fr] items-center gap-2 text-body-ui">
          <span className="truncate text-ink" title={row.label}>{row.label}</span>
          <div className="flex h-3 overflow-hidden rounded-full bg-emphasis">{row.segments.map((segment) => <span key={segment.label} title={`${segment.label}: ${segment.value}`} style={{ width: `${segment.value / max * 100}%`, backgroundColor: REPORT_CHART_COLORS[labels.indexOf(segment.label) % REPORT_CHART_COLORS.length] }} />)}</div>
        </div>
      ))}
      <ul className="flex flex-wrap gap-3 text-caption text-ink-muted">{labels.map((label, index) => <li key={label} className="flex items-center gap-1"><span aria-hidden="true" className="size-2.5 rounded-full" style={{ backgroundColor: REPORT_CHART_COLORS[index % REPORT_CHART_COLORS.length] }} />{label}</li>)}</ul>
    </div>
  );
}

export function PieChart({ rows, valueLabel }: { rows: ChartRow[]; valueLabel?: string }) {
  const data = rows.filter((row) => row.value > 0);
  const total = data.reduce((sum, row) => sum + row.value, 0);
  if (!data.length || total <= 0) return <p className="text-body-ui text-ink-muted">No chart data.</p>;
  let consumed = 0;
  const circumference = 2 * Math.PI * 60;
  return (
    <div className="flex flex-wrap items-center gap-4">
      <svg width="160" height="160" viewBox="0 0 160 160" role="img" aria-label={`Pie chart of ${valueLabel ?? "values"}`}><g transform="rotate(-90 80 80)">{data.map((row, index) => {
        const dash = row.value / total * circumference;
        const offset = -consumed;
        consumed += dash;
        return <circle key={`${row.label}-${index}`} cx="80" cy="80" r="60" fill="none" stroke={REPORT_CHART_COLORS[index % REPORT_CHART_COLORS.length]} strokeWidth="26" strokeDasharray={`${dash} ${circumference - dash}`} strokeDashoffset={offset} />;
      })}</g></svg>
      <ul className="min-w-0 flex-1 space-y-1.5 text-body-ui text-ink">{data.map((row, index) => <li key={`${row.label}-${index}`} className="flex items-center gap-2"><span aria-hidden="true" className="size-3 shrink-0 rounded-full" style={{ backgroundColor: REPORT_CHART_COLORS[index % REPORT_CHART_COLORS.length] }} />{row.label}<span className="ml-auto text-caption tabular-nums text-ink-muted">{formatNumber(row.value)} · {(row.value / total * 100).toFixed(0)}%</span></li>)}</ul>
    </div>
  );
}
