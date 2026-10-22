import { BarChart, DataState, ReportCard, ReportTable, ScopeGroup, StatCards } from "./OperationsReportsParts";
import { moduleEnabled } from "../../../lib/modules";
import { type Makerspace, useStaffGet } from "./shared";

type Scoped = { makerspace_id?: number };
type Status = Scoped & { submitted: number; accepted: number; in_progress: number; completed: number; collected: number; rejected: number; failed: number };
type Machine = Scoped & { machine_id: number; machine_name: string; machine_type: string | null; request_count: number; completed_count: number; failed_count: number; completed_hours: number; failed_partial_hours: number; total_recorded_service_hours: number; failure_rate: number | null };
type Consumption = Scoped & { machine_id: number; machine_name: string; measurement: "count" | "grams"; product_id: number | null; product_label: string; completed_amount: string; failed_partial_amount: string; total_used: string };
type Failure = Scoped & { machine_id: number; machine_name: string; outcome: string; failed_count: number; failed_partial_hours: number; failed_count_amount: string; failed_grams_amount: string };
type Report = { status_totals: Status[]; machines: Machine[]; consumption: Consumption[]; failure_summary: Failure[] };

export function OperationsReportsMachineService({ makerspace, aggregate, canManageMachines, reportsEnabled, startDate, endDate, makerspaceName }: {
  makerspace: Makerspace;
  aggregate: boolean;
  canManageMachines: boolean;
  reportsEnabled: boolean;
  startDate: string;
  endDate: string;
  makerspaceName: (id: number) => string;
}) {
  const enabled = canManageMachines && reportsEnabled && (aggregate || moduleEnabled(makerspace.enabled_modules, "machine_service"));
  const base = aggregate ? "/admin/machine-service-report" : `/admin/makerspace/${makerspace.id}/machine-service-report`;
  const query = new URLSearchParams();
  if (startDate) query.set("start", startDate);
  if (endDate) query.set("end", endDate);
  const report = useStaffGet<Report>(["machine-service-report", aggregate ? "all" : makerspace.id, startDate, endDate], `${base}${query.size ? `?${query}` : ""}`, enabled);
  if (!enabled) return null;
  const hasRows = Boolean(report.data?.status_totals.length || report.data?.machines.length || report.data?.consumption.length);
  const groups = aggregate ? groupsFor(report.data) : [];
  return (
    <ReportCard title="Machine service">
      <DataState loading={report.isLoading} error={report.error} empty={!hasRows}>
        {aggregate ? <div className="grid gap-6">{groups.map((group) => (
          <ScopeGroup key={group.id} name={makerspaceName(group.id)}>
            <MachineServiceReport report={group.report} />
          </ScopeGroup>
        ))}</div> : <MachineServiceReport report={report.data!} />}
      </DataState>
    </ReportCard>
  );
}

function MachineServiceReport({ report }: { report: Report }) {
  const status = report.status_totals[0];
  const machines = report.machines;
  const consumption = report.consumption;
  const failures = report.failure_summary;
  return <>
    {status ? <StatCards stats={[["Submitted", status.submitted], ["Completed", status.completed + status.collected], ["Failed", status.failed], ["In progress", status.in_progress]]} /> : null}
    <div className="mt-5 grid gap-5 lg:grid-cols-2">
      <div><h3 className="text-label text-ink">Recorded service hours</h3><div className="mt-2"><BarChart rows={machines.slice(0, 10).map((row) => ({ label: row.machine_name, value: row.total_recorded_service_hours }))} valueLabel="hours" /></div></div>
      <div><h3 className="text-label text-ink">Failures</h3><div className="mt-2"><BarChart rows={failures.slice(0, 10).map((row) => ({ label: row.machine_name, value: row.failed_count }))} valueLabel="requests" /></div></div>
    </div>
    <ReportTable data={table(machines)} />
    {consumption.length ? <><h3 className="mt-6 text-label text-ink">Consumables</h3><ReportTable data={table(consumption)} /></> : null}
  </>;
}

function groupsFor(report?: Report) {
  if (!report) return [];
  const ids = new Set<number>();
  for (const rows of [report.status_totals, report.machines, report.consumption, report.failure_summary]) for (const row of rows) if (row.makerspace_id !== undefined) ids.add(row.makerspace_id);
  return [...ids].sort((a, b) => a - b).map((id) => ({ id, report: {
    status_totals: report.status_totals.filter((row) => row.makerspace_id === id),
    machines: report.machines.filter((row) => row.makerspace_id === id),
    consumption: report.consumption.filter((row) => row.makerspace_id === id),
    failure_summary: report.failure_summary.filter((row) => row.makerspace_id === id),
  }}));
}

function table<T extends object>(rows: T[]) {
  if (!rows.length) return { rows: [], typed_rows: [] };
  return { rows: [Object.keys(rows[0] as object), ...rows.map((row) => Object.values(row as object))], typed_rows: rows };
}
