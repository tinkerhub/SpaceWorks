import { Download } from "lucide-react";

import { Button, Card, CardHeader, EmptyState, ErrorText } from "../../../components/ui";
import { cn } from "../../../lib/cn";
import type { ReportCatalogItem, ReportKey } from "./operationsReportsConfig";

export type ExportFormat = "csv" | "xlsx";

/** Every exportable report as a row with CSV and Excel downloads for the current filters. */
export function OperationsReportsExports({ exports, selectedReport, pending, error, onExport }: {
  exports: ReportCatalogItem[];
  selectedReport: ReportKey;
  pending: boolean;
  error: unknown;
  onExport: (report: ReportKey, format: ExportFormat) => void;
}) {
  return (
    <Card as="section">
      <CardHeader title="Exports" description="Download any report for the dates above as a spreadsheet." />
      {exports.length ? (
        <ul className="grid gap-1 md:grid-cols-2 md:gap-x-6">
          {exports.map((definition) => (
            <li
              key={definition.key}
              className={cn(
                "flex flex-wrap items-center justify-between gap-2 rounded-md px-3 py-2",
                selectedReport === definition.key ? "bg-emphasis" : "hover:bg-subtle",
              )}
            >
              <span className="min-w-0 text-body-ui font-semibold text-ink">{definition.title}</span>
              <span className="flex gap-2">
                <Button size="sm" variant="secondary" startIcon={<Download />} disabled={pending} aria-label={`${definition.title} as CSV`} onClick={() => onExport(definition.key, "csv")}>
                  CSV
                </Button>
                <Button size="sm" variant="secondary" startIcon={<Download />} disabled={pending} aria-label={`${definition.title} as XLSX`} onClick={() => onExport(definition.key, "xlsx")}>
                  XLSX
                </Button>
              </span>
            </li>
          ))}
        </ul>
      ) : (
        <EmptyState title="No exports available" description="Exportable reports appear here once the report list loads." />
      )}
      {error ? (
        <div className="mt-4">
          <ErrorText message={error instanceof Error ? error.message : "We couldn't export that report. Try again."} />
        </div>
      ) : null}
    </Card>
  );
}
