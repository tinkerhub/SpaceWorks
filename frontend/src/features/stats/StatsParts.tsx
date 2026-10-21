import type { ReactNode } from "react";

import { Card, SectionHeading } from "../../components/ui";

type ChartRow = { label: string; value: number };

/** A titled block of the stats page: section heading over its tiles and cards. */
export function Section({ title, description, children }: { title: string; description?: string; children: ReactNode }) {
  return (
    <section className="space-y-4">
      <SectionHeading title={title} description={description} />
      {children}
    </section>
  );
}

/** One flat card inside a section, with a small title. */
export function Panel({ title, children, className }: { title: string; children: ReactNode; className?: string }) {
  return (
    <Card className={className}>
      <h3 className="text-title text-ink">{title}</h3>
      {children}
    </Card>
  );
}

export function CompactList({
  rows,
  empty,
}: {
  rows: { label: string; value: string }[];
  empty: string;
}) {
  if (!rows.length) {
    return <p className="mt-3 text-body-ui text-ink-muted">{empty}</p>;
  }

  return (
    <ul className="mt-3 divide-y divide-line">
      {rows.map((row) => (
        <li className="flex min-w-0 items-start gap-3 py-2 first:pt-0 last:pb-0" key={`${row.label}-${row.value}`}>
          <span className="min-w-0 flex-1 truncate text-body-ui text-ink" title={row.label}>
            {row.label}
          </span>
          <span className="min-w-0 max-w-full text-right text-caption text-ink-muted [overflow-wrap:anywhere]">{row.value}</span>
        </li>
      ))}
    </ul>
  );
}

export function BarChart({
  rows,
  valueLabel,
}: {
  rows: ChartRow[];
  valueLabel: string;
}) {
  const maxValue = Math.max(...rows.map((row) => row.value), 0);
  if (!rows.length || maxValue <= 0) {
    return <p className="text-body-ui text-ink-muted">No chart data yet.</p>;
  }

  return (
    <div className="space-y-2.5">
      {rows.map((row) => {
        const width = `${Math.max((row.value / maxValue) * 100, 4)}%`;
        return (
          <div
            className="grid grid-cols-[minmax(0,1fr)_minmax(4rem,2fr)_auto] items-center gap-3 text-body-ui sm:grid-cols-[minmax(7rem,11rem)_1fr_auto]"
            key={row.label}
          >
            <span className="truncate text-ink" title={row.label}>
              {row.label}
            </span>
            <div className="h-2 overflow-hidden rounded-full bg-emphasis" aria-hidden="true">
              <div className="h-full rounded-full bg-accent-ink" style={{ width }} />
            </div>
            <span className="min-w-14 text-right text-caption tabular-nums text-ink-muted">
              {formatNumber(row.value)} {valueLabel}
            </span>
          </div>
        );
      })}
    </div>
  );
}

export function formatNumber(value: number) {
  return new Intl.NumberFormat(undefined, { maximumFractionDigits: 1 }).format(value);
}

export function formatDate(value: string) {
  return new Date(value).toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}
