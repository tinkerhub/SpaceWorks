import { useMutation, useQueryClient } from "@tanstack/react-query";

import type { MachineServiceRequest, PrinterPool, TypedManualUsageResponse } from "../../../../generated/api";
import { ErrorBlock, SectionHeading } from "../../../../components/ui";
import { staffRequest } from "../../../../lib/api";
import { machineKeys } from "../../machinesApi";
import type { Machine, MachineType, MeteringUnit } from "../../machinesApi";
import { useStaffGet } from "../shared";
import { ManualUsage, blankManualUsage } from "./ManualUsage";
import { useNotify } from "./machineUi";
import { SERVICE_ACTION_COPY, ServiceQueue } from "./ServiceQueue";
import { clearedActionDraft } from "./serviceDrafts";
import type { ServiceActionName, ServiceDraft } from "./serviceDrafts";
import { poolQueryKey, poolUnits, unitLabels, usablePools } from "./servicePools";

type Props = {
  makerspaceId: number;
  canManage: boolean;
  machineType: MachineType;
  machines: Machine[];
  pools: PrinterPool[];
  draft: ServiceDraft;
  setDraft: (update: (draft: ServiceDraft) => ServiceDraft) => void;
};

export function MachineServiceConsole({ makerspaceId, canManage, machineType, machines, pools, draft, setDraft }: Props) {
  const queryClient = useQueryClient();
  const notify = useNotify();
  const meteringUnit = (machineType.capability_config?.metering_unit ?? "count") as MeteringUnit;
  const unitLabel = unitLabels[meteringUnit];
  const poolUnit = poolUnits[meteringUnit];
  // Filter by the stable machine-type ID, not the slug: slugs are not unique across the
  // global/tenant split, so a makerspace-local type sharing a built-in's slug would pull in
  // the other type's jobs and let a manager mutate them from the wrong section.
  const machineTypeFilter = `machine_type_id=${machineType.id}`;
  const requests = useStaffGet<MachineServiceRequest[]>(
    ["machine-service-requests", makerspaceId, machineType.id],
    `/admin/makerspaces/${makerspaceId}/machine-service/requests?${machineTypeFilter}`,
    canManage,
  );
  const manualUsage = useStaffGet<TypedManualUsageResponse[]>(
    ["machine-service-manual", makerspaceId, machineType.id],
    `/admin/makerspaces/${makerspaceId}/machine-service/typed-manual-usage?${machineTypeFilter}`,
    canManage,
  );
  const actionPools = usablePools(pools, poolUnit, draft.actionValues.machine_id, machines, makerspaceId);
  const manualPools = usablePools(pools, poolUnit, draft.manual.machine_id, machines, makerspaceId);

  const invalidate = () => void Promise.all([
    queryClient.invalidateQueries({ queryKey: ["machine-service-requests", makerspaceId, machineType.id] }),
    queryClient.invalidateQueries({ queryKey: ["machine-service-manual", makerspaceId, machineType.id] }),
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
        consumable_pool_id: poolUnit && draft.manual.consumable_pool_id ? Number(draft.manual.consumable_pool_id) : null,
        duration_minutes: Number(draft.manual.duration_minutes),
        quantity: poolUnit && draft.manual.quantity ? draft.manual.quantity : undefined,
        metering_unit: meteringUnit,
        outcome: draft.manual.outcome,
        percent_complete: Number(draft.manual.percent_complete),
        reason: draft.manual.reason || undefined,
        note: draft.manual.note || undefined,
      }),
    }),
    onSuccess: () => {
      notify.success("Usage logged");
      setDraft((current) => ({ ...current, manual: blankManualUsage }));
      invalidate();
    },
    onError: (error) => notify.failure("Couldn't log usage.", error),
  });
  const runAction = useMutation({
    mutationFn: (action: { id: number; name: ServiceActionName }) =>
      staffRequest(`/admin/machine-service/requests/${action.id}/${action.name}`, {
        method: "POST",
        body: JSON.stringify(actionBody(action.name, draft.actionValues, !!poolUnit)),
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
      <section className="grid gap-4">
        <SectionHeading
          title="Service queue"
          description={`This type is metered in ${unitLabel}. ${poolUnit ? "Choose a machine before selecting its consumable pool." : "Minutes-based services do not use consumable pools."}`}
        />
        <ServiceQueue
          requests={requests.data}
          loading={requests.isLoading}
          draft={draft}
          setDraft={setDraft}
          machines={machines}
          pools={actionPools}
          machineNoun="Machine"
          unitLabel={unitLabel}
          hasPool={!!poolUnit}
          meta={(request) => `Planned ${request.planned_quantity ?? "0"} ${unitLabel} · actual ${request.actual_consumed_quantity ?? "0"} ${unitLabel}`}
          pending={runAction.isPending}
          onSubmit={(action) => runAction.mutate(action)}
        />
      </section>
      <section className="grid gap-4">
        <SectionHeading title="Manual usage" description="Log a run that happened outside the queue." />
        <ManualUsage
          draft={draft}
          setDraft={setDraft}
          machines={machines}
          pools={manualPools}
          machineNoun="Machine"
          unitLabel={unitLabel}
          hasPool={!!poolUnit}
          pending={submitManual.isPending}
          onSubmit={() => submitManual.mutate()}
          rows={(manualUsage.data ?? []).map((entry) => ({
            id: entry.id,
            outcome: entry.outcome,
            used: `${entry.consumed_quantity} ${unitLabel}`,
            minutes: entry.duration_minutes,
            percent: entry.percent_complete,
          }))}
        />
      </section>
      <ErrorBlock error={[requests.error, manualUsage.error, submitManual.error, runAction.error].find((item) => item instanceof Error)} />
    </div>
  );
}

function actionBody(action: ServiceActionName, values: ServiceDraft["actionValues"], hasPool: boolean) {
  if (action === "accept") return { estimated_minutes: Number(values.estimated_minutes) };
  if (action === "start") return { machine_id: values.machine_id ? Number(values.machine_id) : null, consumable_pool_id: hasPool && values.consumable_pool_id ? Number(values.consumable_pool_id) : undefined, estimated_minutes: Number(values.estimated_minutes), planned_quantity: hasPool && values.planned_quantity ? values.planned_quantity : undefined };
  if (action === "complete") return { actual_minutes: Number(values.actual_minutes), actual_quantity: hasPool && values.actual_quantity ? values.actual_quantity : undefined };
  if (action === "fail") return { actual_minutes: Number(values.actual_minutes), actual_quantity: hasPool && values.actual_quantity ? values.actual_quantity : undefined, percent_complete: Number(values.percent_complete), reason: values.reason };
  return action === "reject" ? { reason: values.reason } : {};
}
