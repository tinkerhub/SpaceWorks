import { useMemo } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import type { MachineServiceRequest, PrinterPool, PrinterServiceReport, TypedManualUsageResponse } from "../../../../generated/api";
import { EmptyState, ErrorBlock, SectionHeading, Skeleton } from "../../../../components/ui";
import { staffRequest } from "../../../../lib/api";
import { machineKeys } from "../../machinesApi";
import type { Machine, MachineType } from "../../machinesApi";
import { useStaffGet } from "../shared";
import { ManualUsage, blankManualUsage } from "./ManualUsage";
import { useNotify } from "./machineUi";
import { SERVICE_ACTION_COPY, ServiceQueue } from "./ServiceQueue";
import { clearedActionDraft } from "./serviceDrafts";
import type { ServiceActionName, ServiceDraft } from "./serviceDrafts";
import { poolQueryKey, usablePools } from "./servicePools";

type Props = {
  makerspaceId: number;
  canManage: boolean;
  printingEnabled: boolean;
  reportsEnabled?: boolean;
  machineType: MachineType;
  machines: Machine[];
  pools: PrinterPool[];
  draft: ServiceDraft;
  setDraft: (update: (draft: ServiceDraft) => ServiceDraft) => void;
};

// Mirrors backend `printer_capabilities.PRINTER_SLUG`.
const PRINTER_SLUG = "3d_printer";

export function PrinterServiceConsole({ makerspaceId, canManage, printingEnabled, reportsEnabled = true, machineType, machines, pools, draft, setDraft }: Props) {
  const queryClient = useQueryClient();
  const notify = useNotify();
  // Filter by the stable machine-type ID, not the slug: slugs are not unique across the
  // global/tenant split, so a makerspace-local type sharing a built-in's slug would pull in
  // the other type's jobs and let a manager mutate them from the wrong section.
  const typeFilter = `machine_type_id=${machineType.id}`;
  const requests = useStaffGet<MachineServiceRequest[]>(
    ["machine-service-requests", makerspaceId, machineType.id],
    `/admin/makerspaces/${makerspaceId}/machine-service/requests?${typeFilter}`,
    canManage && printingEnabled,
  );
  const manualUsage = useStaffGet<TypedManualUsageResponse[]>(
    ["machine-service-manual", makerspaceId, machineType.id],
    `/admin/makerspaces/${makerspaceId}/machine-service/typed-manual-usage?${typeFilter}`,
    canManage,
  );
  const report = useStaffGet<PrinterServiceReport>(
    ["printer-service-report", makerspaceId, machineType.id],
    // The REPORT endpoint is a different contract: it discriminates on the `machine_type`
    // SLUG to decide whether to emit `printer_metrics`. Sending the id instead silently
    // returns the generic report, and the render below dereferences `printer_metrics`, so
    // the whole Machines panel dies in its error boundary. This console only ever mounts
    // for the global built-in printer, so the literal slug is exactly right here.
    `/admin/makerspace/${makerspaceId}/machine-service-report?machine_type=${PRINTER_SLUG}`,
    canManage && printingEnabled && reportsEnabled,
  );
  const printerUsage = useMemo(
    () => (manualUsage.data ?? []).filter((entry) => entry.metering_unit === "weight"),
    [manualUsage.data],
  );
  const actionPools = usablePools(pools, "grams", draft.actionValues.machine_id, machines, makerspaceId);
  const manualPools = usablePools(pools, "grams", draft.manual.machine_id, machines, makerspaceId);

  const invalidate = () => void Promise.all([
    queryClient.invalidateQueries({ queryKey: ["machine-service-requests", makerspaceId, machineType.id] }),
    queryClient.invalidateQueries({ queryKey: ["machine-service-manual", makerspaceId, machineType.id] }),
    queryClient.invalidateQueries({ queryKey: ["printer-service-report", makerspaceId, machineType.id] }),
    // A completed job lands on the front desk's handover list.
    queryClient.invalidateQueries({ queryKey: ["machine-service-handover", makerspaceId] }),
    queryClient.invalidateQueries({ queryKey: ["operations-report"] }),
    queryClient.invalidateQueries({ queryKey: poolQueryKey(makerspaceId) }),
    // Service transitions change the assigned machine's status, and manual usage its
    // usage hours; without this the integrated machine row and the status filter
    // stay stale until an unrelated refetch.
    queryClient.invalidateQueries({ queryKey: machineKeys.list(makerspaceId) }),
  ]);
  const submitManual = useMutation({
    mutationFn: () => staffRequest(`/admin/makerspaces/${makerspaceId}/machine-service/typed-manual-usage`, {
      method: "POST",
      body: JSON.stringify({
        machine_id: Number(draft.manual.machine_id),
        consumable_pool_id: draft.manual.consumable_pool_id ? Number(draft.manual.consumable_pool_id) : null,
        duration_minutes: Number(draft.manual.duration_minutes),
        grams: draft.manual.quantity || undefined,
        outcome: draft.manual.outcome,
        percent_complete: Number(draft.manual.percent_complete),
        reason: draft.manual.reason || undefined,
        note: draft.manual.note || undefined,
      }),
    }),
    onSuccess: () => {
      notify.success("Print logged");
      setDraft((current) => ({ ...current, manual: blankManualUsage }));
      invalidate();
    },
    onError: (error) => notify.failure("Couldn't log the print.", error),
  });
  const runAction = useMutation({
    mutationFn: (action: { id: number; name: ServiceActionName }) =>
      staffRequest(`/admin/machine-service/requests/${action.id}/${action.name}`, {
        method: "POST",
        body: JSON.stringify(actionBody(action.name, draft.actionValues)),
      }),
    onSuccess: (_result, action) => {
      notify.success(SERVICE_ACTION_COPY[action.name].done);
      setDraft(clearedActionDraft);
      invalidate();
    },
    onError: (error, action) => notify.failure(SERVICE_ACTION_COPY[action.name].failed, error),
  });

  if (!canManage) return null;
  return (
    <div className="grid gap-8">
      {printingEnabled ? (
        <section className="grid gap-4">
          <SectionHeading title="3D-printer queue" description="Accept jobs, reserve filament, start work, reconcile actual grams, then complete, fail, collect or reprint." />
          <ServiceQueue
            makerspaceId={makerspaceId}
            requests={requests.data}
            loading={requests.isLoading}
            draft={draft}
            setDraft={setDraft}
            machines={machines}
            pools={actionPools}
            machineNoun="Printer"
            unitLabel="grams"
            hasPool
            plannedOnAccept
            allowReprint
            meta={(request) => `Planned ${request.planned_grams}g`}
            pending={runAction.isPending}
            onSubmit={(action) => runAction.mutate(action)}
          />
        </section>
      ) : null}
      <section className="grid gap-4">
        <SectionHeading title="Manual usage" description="Log a print that happened outside the queue." />
        <ManualUsage
          draft={draft}
          setDraft={setDraft}
          machines={machines}
          pools={manualPools}
          machineNoun="Printer"
          unitLabel="grams"
          hasPool
          pending={submitManual.isPending}
          onSubmit={() => submitManual.mutate()}
          rows={printerUsage.map((entry) => ({
            id: entry.id,
            outcome: entry.outcome,
            used: `${entry.consumed_grams}g`,
            minutes: entry.duration_minutes,
            percent: entry.percent_complete,
          }))}
        />
      </section>
      {printingEnabled && reportsEnabled ? (
        <section className="grid gap-4">
          <SectionHeading title="Printer reports" description="Hours and filament per printer." />
          {report.isLoading ? <Skeleton className="h-20 w-full" /> : null}
          {report.data && report.data.printer_metrics.length === 0 ? (
            <EmptyState title="No completed printer activity yet" description="Finished, failed and manual prints are totted up here." />
          ) : null}
          {report.data?.printer_metrics.length ? (
            <ul className="grid gap-3 md:grid-cols-2">
              {report.data.printer_metrics.map((metric) => (
                <li className="grid gap-1 rounded-lg border border-line bg-canvas p-4" key={`${metric.makerspace_id ?? makerspaceId}:${metric.machine_id}`}>
                  <strong className="text-title text-ink">{metric.machine_name}</strong>
                  <span className="text-caption text-ink-muted">{metric.completed_hours}h complete · {metric.failed_partial_hours}h failed · {metric.manual_hours}h manual · {metric.consumed_grams}g used</span>
                </li>
              ))}
            </ul>
          ) : null}
        </section>
      ) : null}
      <ErrorBlock error={[requests.error, manualUsage.error, report.error, submitManual.error, runAction.error].find((item) => item instanceof Error)} />
    </div>
  );
}

function actionBody(action: ServiceActionName, values: ServiceDraft["actionValues"]) {
  if (action === "accept") return { estimated_minutes: Number(values.estimated_minutes), planned_grams: values.planned_quantity || undefined };
  if (action === "start") return { machine_id: values.machine_id ? Number(values.machine_id) : null, consumable_pool_id: values.consumable_pool_id ? Number(values.consumable_pool_id) : undefined, estimated_minutes: Number(values.estimated_minutes), planned_grams: values.planned_quantity || undefined };
  if (action === "complete") return { actual_minutes: Number(values.actual_minutes), actual_grams: values.actual_quantity || undefined };
  if (action === "fail") return { actual_minutes: Number(values.actual_minutes), actual_grams: values.actual_quantity || undefined, percent_complete: Number(values.percent_complete), reason: values.reason };
  return action === "reject" ? { reason: values.reason } : {};
}
