import { BarChart, DataState, ReportCard, ReportTable, ScopeGroup, StackedBarChart } from "./OperationsReportsParts";
import { moduleEnabled } from "../../../lib/modules";
import { type Makerspace, useStaffGet } from "./shared";

type PrinterMetric = {
  makerspace_id?: number; machine_id: number; machine_name: string; model: string;
  completed_hours: number; failed_partial_hours: number; manual_hours: number;
  consumed_grams: string; payment_due: string; payment_paid: string;
};
type PrinterReport = { printer_metrics: PrinterMetric[] };

export function OperationsReportsPrinterService({ makerspace, aggregate, canManageMachines, reportsEnabled, startDate, endDate, makerspaceName }: {
  makerspace: Makerspace; aggregate: boolean; canManageMachines: boolean; reportsEnabled: boolean;
  startDate: string; endDate: string; makerspaceName: (id: number) => string;
}) {
  const enabled = canManageMachines && reportsEnabled && (aggregate || moduleEnabled(makerspace.enabled_modules, "printing"));
  const base = aggregate ? "/admin/machine-service-report" : `/admin/makerspace/${makerspace.id}/machine-service-report`;
  const params = new URLSearchParams({ machine_type: "3d_printer" });
  if (startDate) params.set("start", startDate);
  if (endDate) params.set("end", endDate);
  const report = useStaffGet<PrinterReport>(
    ["printer-service-report", aggregate ? "all" : makerspace.id, startDate, endDate],
    `${base}?${params.toString()}`,
    enabled,
  );
  if (!enabled) return null;
  const rows = report.data?.printer_metrics ?? [];
  return (
    <ReportCard title="Printer service">
      <DataState loading={report.isLoading} error={report.error} empty={!rows.length}>
        {aggregate ? <div className="grid gap-6">{groups(rows).map(([id, metrics]) => (
          <ScopeGroup key={id} name={makerspaceName(id)}><PrinterMetrics rows={metrics} /></ScopeGroup>
        ))}</div> : <PrinterMetrics rows={rows} />}
      </DataState>
    </ReportCard>
  );
}

function PrinterMetrics({ rows }: { rows: PrinterMetric[] }) {
  return <>
    <div className="grid gap-5 lg:grid-cols-2">
      <StackedBarChart rows={rows.map((row) => ({ label: row.machine_name, segments: [
        { label: "Completed", value: row.completed_hours },
        { label: "Failed partial", value: row.failed_partial_hours },
        { label: "Manual", value: row.manual_hours },
      ] }))} valueLabel="hours" />
      <BarChart rows={rows.map((row) => ({ label: row.machine_name, value: Number(row.consumed_grams) }))} valueLabel="grams" />
      <StackedBarChart rows={rows.map((row) => ({ label: row.machine_name, segments: [
        { label: "Due", value: Number(row.payment_due) },
        { label: "Paid", value: Number(row.payment_paid) },
      ] }))} valueLabel="money" />
    </div>
    <ReportTable data={table(rows)} />
  </>;
}

function groups(rows: PrinterMetric[]) {
  const result = new Map<number, PrinterMetric[]>();
  for (const row of rows) {
    if (row.makerspace_id === undefined) continue;
    result.set(row.makerspace_id, [...(result.get(row.makerspace_id) ?? []), row]);
  }
  return [...result];
}

function table(rows: PrinterMetric[]) {
  if (!rows.length) return { rows: [] };
  return { rows: [Object.keys(rows[0]), ...rows.map((row) => Object.values(row))] };
}
