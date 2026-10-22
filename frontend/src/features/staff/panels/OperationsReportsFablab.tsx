import { StatusChip } from "../../../components/ui";
import { DataState, EmptyReport, PerMakerspaceTables, ReportCard, ReportTable, StatCards } from "./OperationsReportsParts";
import { OperationsReportsBookings } from "./OperationsReportsBookings";
import { OperationsReportsEvents } from "./OperationsReportsEvents";
import { OperationsReportsMachineUsage } from "./OperationsReportsMachineUsage";
import { OperationsReportsMaintenance } from "./OperationsReportsMaintenance";
import { moduleEnabled as listHas } from "../../../lib/modules";
import type { Makerspace } from "./shared";
import { useFablabReport, type FabLabHealthRow, type FablabPanelProps } from "./operationsReportsFablabApi";

export function OperationsReportsFablab({
  makerspace, aggregate, canViewAudit, startDate, endDate, makerspaceName,
}: {
  makerspace: Makerspace;
  aggregate: boolean;
  canViewAudit: boolean;
  startDate: string;
  endDate: string;
  makerspaceName: (id: number) => string;
}) {
  const modules = makerspace.enabled_modules;
  const reportsEnabled = aggregate || listHas(modules, "reports");
  const base: FablabPanelProps = {
    makerspaceId: makerspace.id, aggregate, startDate, endDate, makerspaceName,
    enabled: canViewAudit && reportsEnabled,
  };
  const moduleEnabled = (module: string) => base.enabled && (aggregate || listHas(modules, module));
  // The health strip covers four optional modules; with none of them on it has nothing to say.
  const sections = FABLAB_SECTIONS.filter(([key]) => moduleEnabled(key)).map(([, label]) => label);
  const anyFablabModule = sections.length > 0;
  const health = useFablabReport<FabLabHealthRow>("fablab-health", { ...base, enabled: base.enabled && anyFablabModule });
  if (!canViewAudit) return null;

  const healthRow = health.data?.typed_rows[0];
  const healthStats: [string, number | undefined][] = [];
  if (healthRow?.events_available) healthStats.push(["Events in period", healthRow.events_in_period ?? 0], ["Registrations", healthRow.events_registrations ?? 0]);
  if (healthRow?.machines_available) healthStats.push(["Usage hours", Number(healthRow.machines_usage_hours ?? 0)]);
  if (healthRow?.maintenance_available) healthStats.push(["Maintenance logs", healthRow.maintenance_logs ?? 0], ["Overdue schedules (snapshot)", healthRow.maintenance_overdue_schedules ?? 0]);
  if (healthRow?.bookings_available) healthStats.push(["Upcoming bookings", healthRow.bookings_upcoming ?? 0]);
  return (
    <section className="grid gap-6" aria-label="FabLab analytics">
      {anyFablabModule ? <ReportCard title="FabLab health" description={`${sentenceList(sections)} at a glance.`}>
        {!reportsEnabled ? <EmptyReport /> : (
          <DataState loading={health.isLoading} error={health.error} empty={!health.data?.typed_rows.length}>
            {aggregate ? (
              <PerMakerspaceTables data={health.data} nameOf={makerspaceName} />
            ) : healthRow ? (
              <>
                {healthStats.length ? <StatCards stats={healthStats} /> : null}
                <ul className="mt-5 grid gap-2 sm:grid-cols-2 lg:grid-cols-4" aria-label="Module data">
                  {moduleEnabled("events") && healthRow.events_enabled ? <HealthState label="Events" enabled available={healthRow.events_available} /> : null}
                  {moduleEnabled("bookings") && healthRow.bookings_enabled ? <HealthState label="Bookings" enabled available={healthRow.bookings_available} /> : null}
                  {moduleEnabled("machines") && healthRow.machines_enabled ? <HealthState label="Machines" enabled available={healthRow.machines_available} /> : null}
                  {moduleEnabled("maintenance") && healthRow.maintenance_enabled ? <HealthState label="Maintenance" enabled available={healthRow.maintenance_available} /> : null}
                </ul>
                <ReportTable data={health.data} />
              </>
            ) : null}
          </DataState>
        )}
      </ReportCard> : null}
      <OperationsReportsMachineUsage {...base} enabled={moduleEnabled("machines")} />
      <OperationsReportsEvents {...base} enabled={moduleEnabled("events")} />
      <OperationsReportsBookings {...base} enabled={moduleEnabled("bookings")} />
      <OperationsReportsMaintenance {...base} enabled={moduleEnabled("machines") && moduleEnabled("maintenance")} />
    </section>
  );
}

// The health strip's optional sections, in display order. Copy names only the ones that are on.
const FABLAB_SECTIONS: [string, string][] = [
  ["events", "events"], ["bookings", "bookings"], ["machines", "machines"], ["maintenance", "maintenance"],
];

function sentenceList(items: string[]) {
  const text = items.length > 1 ? `${items.slice(0, -1).join(", ")} and ${items[items.length - 1]}` : items[0] ?? "";
  return text.charAt(0).toUpperCase() + text.slice(1);
}

function HealthState({ label, enabled, available }: { label: string; enabled: boolean; available: boolean }) {
  const state = !enabled ? "Module disabled" : available ? "Available" : "Data unavailable";
  return (
    <li className="flex items-center justify-between gap-2 rounded-md bg-subtle px-3 py-2">
      <span className="text-label text-ink">{label}</span>
      <StatusChip size="sm" tone={!enabled ? "neutral" : available ? "success" : "warning"}>{state}</StatusChip>
    </li>
  );
}
