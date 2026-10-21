import { BarChart, DataState, ReportTable, StatCards, ReportCard, ScopeGroup } from "./OperationsReportsParts";
import { groupReportByMakerspace, sum, useFablabReport, type BookingUtilizationRow, type FablabPanelProps, type ReportResponse } from "./operationsReportsFablabApi";

export function OperationsReportsBookings(props: FablabPanelProps) {
  const query = useFablabReport<BookingUtilizationRow>("booking-utilization", props);
  // A report for a switched-off module renders nothing rather than a placeholder.
  if (!props.enabled) return null;
  const rows = query.data?.typed_rows ?? [];
  const groups = groupReportByMakerspace(query.data);
  return (
    <ReportCard title="Bookable space utilization" description="Utilization needs both a start and an end date. It measures calendar reservations, not who was physically there.">
      <DataState loading={query.isLoading} error={query.error} empty={!rows.length}>
        {props.aggregate ? <div className="grid gap-6">{groups.map((group) => (
          <ScopeGroup key={group.makerspaceId} name={props.makerspaceName(group.makerspaceId)}>
            <BookingsReport rows={group.rows} data={group.data} />
          </ScopeGroup>
        ))}</div> : <BookingsReport rows={rows} data={query.data} />}
      </DataState>
    </ReportCard>
  );
}

function BookingsReport({ rows, data }: { rows: BookingUtilizationRow[]; data?: ReportResponse<BookingUtilizationRow> }) {
  return <>
    <StatCards stats={[["Reserved hours", sum(rows, "reserved_hours")], ["Completed hours", sum(rows, "completed_hours")], ["Upcoming", sum(rows, "upcoming")], ["No-shows", sum(rows, "no_show")]]} />
    <div className="mt-5 grid gap-5 lg:grid-cols-2">
      <BarChart rows={rows.filter((row) => row.reservation_utilization_percent !== null).map((row) => ({ label: row.space_name, value: row.reservation_utilization_percent ?? 0 }))} valueLabel="% reserved" />
      <BarChart rows={rows.filter((row) => row.no_show_rate_percent !== null).map((row) => ({ label: row.space_name, value: row.no_show_rate_percent ?? 0 }))} valueLabel="% no-show" />
    </div>
    <ReportTable data={data} />
  </>;
}
