import type React from "react";

import { Card, CardHeader, EmptyState, ErrorText, Skeleton, SkeletonRows, StatTile, Table, TBody } from "../../../components/ui";

export type ReportCell = string | number | boolean | null;
export type TypedReportRow = Record<string, ReportCell | undefined>;
export type ReportRows = {
  report_key?: string;
  rows: ReportCell[][];
  typed_rows?: TypedReportRow[];
  meta?: { source?: string; grain?: string; rollup_through?: string | null };
};
export type ChartRow = { label: string; value: number };

export function reportRows(data?: ReportRows) {
  return data?.rows?.slice(1) ?? [];
}

export function reportHeaders(data?: ReportRows) {
  return (data?.rows?.[0] ?? []).map(String);
}

export function typedRows(data?: ReportRows) {
  return data?.typed_rows ?? [];
}

export function chartRows(data: ReportRows | undefined, labelKey: string, valueKey: string): ChartRow[] {
  const typed = typedRows(data);
  if (typed.length) {
    return typed.map((row) => ({ label: String(row[labelKey] ?? "Unknown"), value: Number(row[valueKey] ?? 0) }));
  }
  const header = reportHeaders(data);
  return reportRows(data).map((row) => ({
    label: String(row[header.indexOf(labelKey)] ?? "Unknown"),
    value: Number(row[header.indexOf(valueKey)] ?? 0),
  }));
}

/** One report section: a flat card with an h2 title and an optional one-line description. */
export function ReportCard({ title, description, children }: {
  title: string;
  description?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <Card as="section">
      <CardHeader title={title} description={description} />
      {children}
    </Card>
  );
}

/** A per-makerspace block inside an all-makerspaces report. */
export function ScopeGroup({ name, children }: { name: string; children: React.ReactNode }) {
  return (
    <section className="border-t border-line pt-4 first:border-t-0 first:pt-0">
      <h3 className="text-title text-ink">{name}</h3>
      <div className="mt-3">{children}</div>
    </section>
  );
}

export function DataState(props: { loading: boolean; error: unknown; empty: boolean; children: React.ReactNode }) {
  if (props.loading) return <ReportSkeleton />;
  if (props.error) return <ErrorText message={props.error instanceof Error ? props.error.message : "We couldn't load this report. Try again in a moment."} />;
  if (props.empty) return <EmptyState title="No records yet" description="Nothing happened in this period. Try a wider date range." />;
  return <>{props.children}</>;
}

/** A report the catalog lists but this makerspace cannot run (its module is off, or data is missing). */
export function EmptyReport({ reason }: { reason?: string | null }) {
  return <EmptyState title="Report unavailable" description={reason || "This report needs a module that is switched off for this makerspace."} />;
}

function ReportSkeleton() {
  return (
    <div className="grid gap-3" aria-hidden="true">
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {Array.from({ length: 4 }, (_, index) => (
          <div key={index} className="rounded-lg border border-line p-4">
            <Skeleton className="h-3 w-24" /><Skeleton className="mt-3 h-7 w-16" />
          </div>
        ))}
      </div>
      <Table><TBody><SkeletonRows rows={4} cols={4} /></TBody></Table>
    </div>
  );
}

export function StatCards({ stats }: { stats: [string, number | undefined][] }) {
  return (
    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
      {stats.map(([label, value]) => (
        <StatTile key={label} label={label} value={formatNumber(value ?? 0)} />
      ))}
    </div>
  );
}

export function formatReportCell(value: ReportCell | undefined) {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "number") return formatNumber(value);
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (/^\d{4}-\d{2}-\d{2}T/.test(value)) {
    return new Date(value).toLocaleString(undefined, { day: "numeric", month: "short", year: "numeric", hour: "numeric", minute: "2-digit" });
  }
  return value;
}

export function formatNumber(value: number) {
  return new Intl.NumberFormat(undefined, { maximumFractionDigits: 1 }).format(value);
}

/** `damaged_quantity` → "Damaged quantity". */
export function columnLabel(key: string) {
  const words = key.replace(/_/g, " ");
  return words.charAt(0).toUpperCase() + words.slice(1);
}
