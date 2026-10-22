import { BarChart, DataState, LineChart, PieChart, ReportTable, StatCards, ReportCard, ScopeGroup } from "./OperationsReportsParts";
import { groupReportByMakerspace, sum, useFablabReport, type EventAttendanceRow, type FablabPanelProps, type ReportResponse } from "./operationsReportsFablabApi";

export function OperationsReportsEvents(props: FablabPanelProps) {
  const query = useFablabReport<EventAttendanceRow>("event-attendance", props);
  // A report for a switched-off module renders nothing rather than a placeholder.
  if (!props.enabled) return null;
  const rows = query.data?.typed_rows ?? [];
  const groups = groupReportByMakerspace(query.data);
  return (
    <ReportCard title="Events attendance">
      <DataState loading={query.isLoading} error={query.error} empty={!rows.length}>
        {props.aggregate ? <div className="grid gap-6">{groups.map((group) => (
          <ScopeGroup key={group.makerspaceId} name={props.makerspaceName(group.makerspaceId)}>
            <EventsReport rows={group.rows} data={group.data} />
          </ScopeGroup>
        ))}</div> : <EventsReport rows={rows} data={query.data} />}
      </DataState>
    </ReportCard>
  );
}

function EventsReport({ rows, data }: { rows: EventAttendanceRow[]; data?: ReportResponse<EventAttendanceRow> }) {
  const statusRows = ["pending_approval", "registered", "waitlisted", "rejected", "cancelled", "attended"].map((key) => ({ label: key, value: sum(rows, key) }));
  return <>
    <StatCards stats={[["Events", rows.length], ["Registrations", sum(rows, "registrations")], ["Confirmed", sum(rows, "confirmed")], ["Attended", sum(rows, "attended")]]} />
    <div className="mt-5 grid gap-5 lg:grid-cols-2">
      <PieChart rows={statusRows} valueLabel="registrations" />
      <BarChart rows={rows.filter((row) => row.attendance_rate_percent !== null).map((row) => ({ label: row.title, value: row.attendance_rate_percent ?? 0 }))} valueLabel="% attended" />
      <LineChart rows={[...rows].sort((a, b) => a.starts_at.localeCompare(b.starts_at)).map((row) => ({ label: row.starts_at, value: row.registrations }))} valueLabel="registrations" />
    </div>
    <ReportTable data={data} />
  </>;
}
