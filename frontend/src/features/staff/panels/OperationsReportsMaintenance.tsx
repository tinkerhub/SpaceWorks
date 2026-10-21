import { BarChart, DataState, ReportTable, StatCards, ReportCard, ScopeGroup } from "./OperationsReportsParts";
import { groupReportByMakerspace, sum, useFablabReport, type FablabPanelProps, type MaintenanceActivityRow, type ReportResponse } from "./operationsReportsFablabApi";

export function OperationsReportsMaintenance(props: FablabPanelProps) {
  const query = useFablabReport<MaintenanceActivityRow>("maintenance-activity", props);
  // A report for a switched-off module renders nothing rather than a placeholder.
  if (!props.enabled) return null;
  const rows = query.data?.typed_rows ?? [];
  const groups = groupReportByMakerspace(query.data);
  return (
    <ReportCard title="Maintenance activity">
      <DataState loading={query.isLoading} error={query.error} empty={!rows.length}>
        {props.aggregate ? <>
          <p className="mb-4 text-caption text-ink-muted">Recorded costs remain per makerspace and are never combined across makerspaces.</p>
          <div className="grid gap-6">{groups.map((group) => (
            <ScopeGroup key={group.makerspaceId} name={props.makerspaceName(group.makerspaceId)}>
              <MaintenanceReport rows={group.rows} data={group.data} />
            </ScopeGroup>
          ))}</div>
        </> : <MaintenanceReport rows={rows} data={query.data} />}
      </DataState>
    </ReportCard>
  );
}

function MaintenanceReport({ rows, data }: { rows: MaintenanceActivityRow[]; data?: ReportResponse<MaintenanceActivityRow> }) {
  return <>
    <StatCards stats={[["Logs", sum(rows, "log_count")], ["Recorded cost", sum(rows, "total_cost")], ["Overdue schedules (snapshot)", sum(rows, "overdue_schedules")], ["Active schedules (snapshot)", sum(rows, "active_schedules")]]} />
    <div className="mt-5 grid gap-5 lg:grid-cols-2">
      <BarChart rows={rows.map((row) => ({ label: row.machine_name, value: row.log_count }))} valueLabel="logs" />
      <BarChart rows={rows.map((row) => ({ label: row.machine_name, value: Number(row.total_cost) }))} valueLabel="recorded cost" />
    </div>
    <ReportTable data={data} />
  </>;
}
