import { BarChart, DataState, ReportTable, StatCards, ReportCard, ScopeGroup } from "./OperationsReportsParts";
import { groupReportByMakerspace, sum, useFablabReport, type FablabPanelProps, type MachineUsageRow, type ReportResponse } from "./operationsReportsFablabApi";

export function OperationsReportsMachineUsage(props: FablabPanelProps) {
  const query = useFablabReport<MachineUsageRow>("machine-usage", props);
  // A report for a switched-off module renders nothing rather than a placeholder.
  if (!props.enabled) return null;
  const rows = query.data?.typed_rows ?? [];
  const groups = groupReportByMakerspace(query.data);
  return (
    <ReportCard title="Machine usage">
      <DataState loading={query.isLoading} error={query.error} empty={!rows.length}>
        {props.aggregate ? <div className="grid gap-6">{groups.map((group) => (
          <ScopeGroup key={group.makerspaceId} name={props.makerspaceName(group.makerspaceId)}>
            <MachineUsageReport rows={group.rows} data={group.data} />
          </ScopeGroup>
        ))}</div> : <MachineUsageReport rows={rows} data={query.data} />}
      </DataState>
    </ReportCard>
  );
}

function MachineUsageReport({ rows, data }: { rows: MachineUsageRow[]; data?: ReportResponse<MachineUsageRow> }) {
  return <>
    <StatCards stats={[["Usage hours", sum(rows, "usage_hours")], ["Usage entries", sum(rows, "usage_entries")], ["Machines", rows.length], ["Active", rows.filter((row) => row.is_active).length]]} />
    <div className="mt-5"><BarChart rows={rows.slice(0, 10).map((row) => ({ label: row.machine_name, value: Number(row.usage_hours) }))} valueLabel="hours" /></div>
    <ReportTable data={data} />
  </>;
}
