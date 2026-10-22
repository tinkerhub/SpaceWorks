import { useEffect, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { Download } from "lucide-react";

import { Button, useToast } from "../../../components/ui";
import { downloadStaffFile } from "../../../lib/api";
import { moduleEnabled } from "../../../lib/modules";
import { BarChart, DataState, EmptyReport, ReportCard, ReportTable, StatCards } from "./OperationsReportsParts";
import { OperationsReportsExports, type ExportFormat } from "./OperationsReportsExports";
import { OperationsReportsFilters } from "./OperationsReportsFilters";
import { OperationsReportsFablab } from "./OperationsReportsFablab";
import { OperationsReportsHardware } from "./OperationsReportsHardware";
import { OperationsReportsMachineService } from "./OperationsReportsMachineService";
import { OperationsReportsMembers } from "./OperationsReportsMembers";
import { OperationsReportsPayments } from "./OperationsReportsPayments";
import { OperationsReportsPrinterService } from "./OperationsReportsPrinterService";
import { OperationsReportsCoverage } from "./OperationsReportsCoverage";
import { errorText, Panel, type Makerspace, useStaffGet } from "./shared";
import {
  loadSavedReportViews,
  newSavedViewId,
  reportTitle,
  savedViewsStorageKey,
  type ReportCatalog,
  type ReportKey,
  type SavedReportView,
} from "./operationsReportsConfig";

type Summary = {
  products: number; assets: number; active_loans: number;
  available_quantity: number; issued_quantity: number;
  damaged_quantity: number; missing_quantity: number;
};

export function OperationsReports({
  makerspace,
  makerspaces,
  isSuperadmin,
  printingOnly = false,
  canViewAudit,
  canManageMachines,
  canManageMakerspace,
  singleTenantLocked = false,
}: {
  makerspace: Makerspace;
  makerspaces: Makerspace[];
  isSuperadmin: boolean;
  printingOnly?: boolean;
  canViewAudit: boolean;
  canManageMachines: boolean;
  canManageMakerspace: boolean;
  /** Origin-locked (single-tenant) site: the cross-makerspace aggregate routes are refused there. */
  singleTenantLocked?: boolean;
}) {
  const { showToast } = useToast();
  const [allMakerspaces, setAllMakerspaces] = useState(false);
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");
  const [grain, setGrain] = useState("day");
  const [selectedReport, setSelectedReport] = useState<ReportKey>("most-lent");
  const [presetName, setPresetName] = useState("");
  const [savedViews, setSavedViews] = useState<SavedReportView[]>(loadSavedReportViews);
  useEffect(() => {
    window.localStorage.setItem(savedViewsStorageKey, JSON.stringify(savedViews));
  }, [savedViews]);
  const canAggregate = isSuperadmin && !singleTenantLocked;
  const aggregate = canAggregate && allMakerspaces;
  const scopeKey = aggregate ? "all" : makerspace.id;
  const analyticsBase = aggregate ? "/admin/analytics" : `/admin/makerspace/${makerspace.id}/analytics`;
  const reportsBase = aggregate ? "/admin/reports" : `/admin/makerspace/${makerspace.id}/reports`;
  const dateQuery = [startDate ? `start=${encodeURIComponent(startDate)}` : "", endDate ? `end=${encodeURIComponent(endDate)}` : ""].filter(Boolean).join("&");
  const dateSuffix = dateQuery ? `&${dateQuery}` : "";
  // Panels for switched-off modules render nothing. The all-makerspaces aggregate spans
  // spaces with different switches, so the server's per-space rows decide there instead.
  const moduleOn = (key: string) => aggregate || moduleEnabled(makerspace.enabled_modules, key);
  const reportsEnabled = moduleOn("reports");
  const catalog = useStaffGet<ReportCatalog>(
    ["report-catalog", scopeKey],
    aggregate ? "/admin/reports/catalog" : `/admin/makerspace/${makerspace.id}/reports/catalog`,
    reportsEnabled,
  );
  // Off means absent: an entry the server marks unavailable is dropped, never shown disabled.
  const catalogEntries = (catalog.data?.results ?? []).filter(
    (report) => report.available !== false && (report.required_modules ?? []).every(moduleOn),
  );
  useEffect(() => {
    if (!catalog.data || catalogEntries.some((item) => item.key === selectedReport && item.available !== false)) return;
    const firstAvailable = catalogEntries.find((item) => item.available !== false);
    if (firstAvailable) setSelectedReport(firstAvailable.key);
  }, [catalog.data, catalogEntries, selectedReport]);
  const hardwareEnabled = canViewAudit && reportsEnabled;
  const summary = useStaffGet<Summary>(["operations-report", "summary", scopeKey, startDate, endDate], `${analyticsBase}/summary?${dateQuery}`, hardwareEnabled);

  const scopeLabel = aggregate ? "all makerspaces" : makerspace.name;
  const currentScope: SavedReportView["scope"] = aggregate ? "all" : `makerspace:${makerspace.id}`;
  const makerspaceName = (id: number) => makerspaces.find((space) => space.id === id)?.name ?? `#${id}`;
  const availableExports = reportsEnabled
    ? catalogEntries.filter((report) => report.exportable && report.available !== false)
    : [];
  const saveCurrentView = () => {
    const name = presetName.trim() || `${reportTitle(selectedReport, catalogEntries)} - ${scopeLabel}`;
    const view: SavedReportView = {
      id: newSavedViewId(),
      name,
      startDate,
      endDate,
      scope: currentScope,
      scopeLabel,
      selectedReport,
    };
    setSavedViews((existing) => [view, ...existing.filter((item) => item.name !== name)].slice(0, 12));
    setPresetName("");
    showToast("View saved", { tone: "success" });
  };

  const applySavedView = (view: SavedReportView) => {
    setStartDate(view.startDate);
    setEndDate(view.endDate);
    setSelectedReport(view.selectedReport);
    setAllMakerspaces(view.scope === "all" && canAggregate);
  };

  const removeSavedView = (id: string) => {
    setSavedViews((existing) => existing.filter((view) => view.id !== id));
  };

  const exportReport = useMutation({
    mutationFn: ({ report, format }: { report: string; format: ExportFormat }) =>
      downloadStaffFile(
        `${reportsBase}/${report}/export?format=${format}${dateSuffix}&grain=${encodeURIComponent(grain)}`,
        `${aggregate ? "all-makerspaces-" : ""}${report}.${format}`,
      ),
    onSuccess: (_data, { format }) => showToast(`Report downloaded as ${format.toUpperCase()}`, { tone: "success" }),
    onError: (error) => showToast(errorText(error, "We couldn't export that report"), { tone: "error" }),
  });

  const selectedExport = availableExports.find((report) => report.key === selectedReport);
  const runExport = (report: ReportKey, format: ExportFormat) => {
    setSelectedReport(report);
    exportReport.mutate({ report, format });
  };

  return (
    <Panel
      title="Reports"
      description={printingOnly
        ? `3D printing for ${scopeLabel}: print jobs, printer hours and filament usage.`
        : `Operations for ${scopeLabel}: inventory movement, borrower activity, exceptions and print usage.`}
      actions={!printingOnly && selectedExport ? (
        <Button variant="primary" startIcon={<Download />} loading={exportReport.isPending} loadingLabel="Exporting…" onClick={() => runExport(selectedExport.key, "csv")}>
          Export CSV
        </Button>
      ) : undefined}
    >
      <div className="grid gap-6">
        <OperationsReportsFilters
          startDate={startDate}
          endDate={endDate}
          onStartDate={setStartDate}
          onEndDate={setEndDate}
          selectedReport={selectedReport}
          onSelectReport={setSelectedReport}
          catalogEntries={catalogEntries}
          catalogLoading={catalog.isLoading}
          catalogError={catalog.error}
          grain={grain}
          onGrain={setGrain}
          showAllMakerspaces={canAggregate}
          allMakerspaces={allMakerspaces}
          onAllMakerspaces={setAllMakerspaces}
          presetName={presetName}
          onPresetName={setPresetName}
          presetPlaceholder={`${reportTitle(selectedReport)} - ${scopeLabel}`}
          onSaveView={saveCurrentView}
          savedViews={savedViews}
          isActiveView={(view) => view.startDate === startDate && view.endDate === endDate && view.selectedReport === selectedReport && view.scope === currentScope}
          describeView={(view) => `${reportTitle(view.selectedReport, catalogEntries)} / ${view.scopeLabel}`}
          onApplyView={applySavedView}
          onRemoveView={removeSavedView}
        />

        {!printingOnly ? (
          <ReportCard title="Inventory summary" description="Stock and loans across the selected scope.">
            {reportsEnabled ? (
              <DataState loading={summary.isLoading} error={summary.error} empty={!summary.data}>
                <StatCards
                  stats={[
                    ["Products", summary.data?.products],
                    ["Assets", summary.data?.assets],
                    ["Active loans", summary.data?.active_loans],
                    ["Available", summary.data?.available_quantity],
                    ["Issued", summary.data?.issued_quantity],
                    ["Damaged", summary.data?.damaged_quantity],
                    ["Missing", summary.data?.missing_quantity],
                  ]}
                />
                <div className="mt-5">
                  <BarChart rows={[
                    { label: "Available", value: summary.data?.available_quantity ?? 0 },
                    { label: "Issued", value: summary.data?.issued_quantity ?? 0 },
                    { label: "Damaged", value: summary.data?.damaged_quantity ?? 0 },
                    { label: "Missing", value: summary.data?.missing_quantity ?? 0 },
                  ]} valueLabel="units" />
                </div>
                <ReportTable data={{ rows: [
                  ["metric", "value"],
                  ["products", summary.data?.products ?? 0],
                  ["assets", summary.data?.assets ?? 0],
                  ["active_loans", summary.data?.active_loans ?? 0],
                  ["available_quantity", summary.data?.available_quantity ?? 0],
                  ["issued_quantity", summary.data?.issued_quantity ?? 0],
                  ["damaged_quantity", summary.data?.damaged_quantity ?? 0],
                  ["missing_quantity", summary.data?.missing_quantity ?? 0],
                ] }} />
              </DataState>
            ) : <EmptyReport reason="The reports module is switched off for this makerspace." />}
          </ReportCard>
        ) : null}

      {!printingOnly ? (
      <>
      <OperationsReportsExports
        exports={availableExports}
        selectedReport={selectedReport}
        pending={exportReport.isPending}
        error={exportReport.error}
        onExport={runExport}
      />

      <OperationsReportsHardware analyticsBase={analyticsBase} scopeKey={scopeKey} startDate={startDate} endDate={endDate} enabled={hardwareEnabled} aggregate={aggregate} makerspaceName={makerspaceName} />
      <OperationsReportsCoverage catalog={catalogEntries} analyticsBase={analyticsBase} scopeKey={scopeKey} startDate={startDate} endDate={endDate} grain={grain} aggregate={aggregate} makerspaceName={makerspaceName} />
      <OperationsReportsMembers makerspaceId={makerspace.id} aggregate={aggregate} startDate={startDate} endDate={endDate} enabled={hardwareEnabled && moduleOn("membership")} />
      {canManageMakerspace && moduleOn("payments") ? <OperationsReportsPayments analyticsBase={analyticsBase} scopeKey={scopeKey} startDate={startDate} endDate={endDate} enabled={reportsEnabled} makerspaceName={makerspaceName} /> : null}
      </>
      ) : null}

      {!printingOnly ? <OperationsReportsFablab makerspace={makerspace} aggregate={aggregate} canViewAudit={canViewAudit} startDate={startDate} endDate={endDate} makerspaceName={makerspaceName} /> : null}

      <OperationsReportsPrinterService makerspace={makerspace} aggregate={aggregate} canManageMachines={canManageMachines} reportsEnabled={reportsEnabled} startDate={startDate} endDate={endDate} makerspaceName={makerspaceName} />
      <OperationsReportsMachineService makerspace={makerspace} aggregate={aggregate} canManageMachines={canManageMachines} reportsEnabled={reportsEnabled} startDate={startDate} endDate={endDate} makerspaceName={makerspaceName} />
      </div>
    </Panel>
  );
}
