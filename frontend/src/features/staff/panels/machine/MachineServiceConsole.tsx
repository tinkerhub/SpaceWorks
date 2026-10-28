import { useMutation, useQueryClient } from "@tanstack/react-query";

import type { MachineServiceRequest, PrinterPool, TypedManualUsageResponse } from "../../../../generated/api";
import { ErrorBlock, SectionHeading } from "../../../../components/ui";
import { staffRequest } from "../../../../lib/api";
import { machineKeys } from "../../machinesApi";
import type { Machine, MachineType } from "../../machinesApi";
import { invalidatePaymentViews } from "../../paymentsApi";
import { useStaffGet } from "../shared";
import { ManualUsage, blankManualUsage } from "./ManualUsage";
import { manualPriceCell, useManualPrice } from "./manualPrice";
import { useNotify } from "./machineUi";
import { SERVICE_ACTION_COPY, ServiceQueue } from "./ServiceQueue";
import { clearedActionDraft } from "./serviceDrafts";
import type { ServiceActionName, ServiceDraft } from "./serviceDrafts";
import { poolQueryKey, quantityUnit, unitLabels, usablePools } from "./servicePools";
import { effectiveConfig, typePoolUnit } from "./typeConfig";

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
  const meteringUnit = effectiveConfig(machineType).metering_unit;
  const unitLabel = unitLabels[meteringUnit];
  const poolUnit = typePoolUnit(machineType);
  // Any non-minute type measures a quantity for pricing, consumables or not; only pools need poolUnit.
  const quantityLabel = quantityUnit(meteringUnit);
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
    // The Operations reports key by date range under these prefixes.
    queryClient.invalidateQueries({ queryKey: ["machine-service-report", makerspaceId] }),
    queryClient.invalidateQueries({ queryKey: ["printer-service-report", makerspaceId] }),
    queryClient.invalidateQueries({ queryKey: poolQueryKey(makerspaceId) }),
    // Service transitions change the assigned machine's status, and manual usage its
    // usage hours; without this the integrated machine row and the status filter
    // stay stale until an unrelated refetch.
    queryClient.invalidateQueries({ queryKey: machineKeys.list(makerspaceId) }),
  ]);
  const manualPrice = useManualPrice(makerspaceId, machineType, draft.manual);
  const submitManual = useMutation({
    mutationFn: () => staffRequest(`/admin/makerspaces/${makerspaceId}/machine-service/typed-manual-usage`, {
      method: "POST",
      body: JSON.stringify({
        machine_id: Number(draft.manual.machine_id),
        consumable_pool_id: poolUnit && draft.manual.consumable_pool_id ? Number(draft.manual.consumable_pool_id) : null,
        duration_minutes: Number(draft.manual.duration_minutes),
        quantity: quantityLabel && draft.manual.quantity ? draft.manual.quantity : undefined,
        metering_unit: meteringUnit,
        outcome: draft.manual.outcome,
        percent_complete: Number(draft.manual.percent_complete),
        reason: draft.manual.reason || undefined,
        note: draft.manual.note || undefined,
        price: draft.manual.price === "" ? undefined : draft.manual.price,
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
        body: JSON.stringify(actionBody(action.name, draft.actionValues, !!poolUnit, !!quantityLabel)),
      }),
    onSuccess: (_result, action) => {
      notify.success(SERVICE_ACTION_COPY[action.name].done);
      setDraft(clearedActionDraft);
      invalidate();
      if (action.name === "record-manual-payment") invalidatePaymentViews(queryClient, makerspaceId);
    },
    onError: (error, action) => notify.failure(SERVICE_ACTION_COPY[action.name].failed, error),
  });

  if (!canManage) return null;
  return (
    <div className="grid gap-8">
      <section className="grid gap-4">
        <SectionHeading
          title="Service queue"
          description={`This type is metered in ${unitLabel}. ${poolUnit ? "Choose a machine before selecting its consumable pool." : "This type does not use consumable pools."}`}
        />
        <ServiceQueue
          makerspaceId={makerspaceId}
          requests={requests.data}
          loading={requests.isLoading}
          draft={draft}
          setDraft={setDraft}
          machines={machines}
          pools={actionPools}
          machineNoun="Machine"
          unitLabel={quantityLabel}
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
          unitLabel={quantityLabel}
          hasPool={!!poolUnit}
          pending={submitManual.isPending}
          onSubmit={() => submitManual.mutate()}
          rows={(manualUsage.data ?? []).map((entry) => ({
            id: entry.id,
            outcome: entry.outcome,
            used: `${entry.consumed_quantity} ${unitLabel}`,
            minutes: entry.duration_minutes,
            percent: entry.percent_complete,
            price: manualPriceCell(entry.price, manualPrice.currency),
          }))}
          price={manualPrice}
        />
      </section>
      <ErrorBlock error={[requests.error, manualUsage.error, submitManual.error, runAction.error].find((item) => item instanceof Error)} />
    </div>
  );
}

function actionBody(action: ServiceActionName, values: ServiceDraft["actionValues"], hasPool: boolean, measured: boolean) {
  const quantity = (value: string) => (measured && value ? value : undefined);
  if (action === "accept") return { estimated_minutes: Number(values.estimated_minutes) };
  if (action === "start") return { machine_id: values.machine_id ? Number(values.machine_id) : null, consumable_pool_id: hasPool && values.consumable_pool_id ? Number(values.consumable_pool_id) : undefined, estimated_minutes: Number(values.estimated_minutes), planned_quantity: quantity(values.planned_quantity) };
  if (action === "complete") return { actual_minutes: Number(values.actual_minutes), actual_quantity: quantity(values.actual_quantity) };
  if (action === "fail") return { actual_minutes: Number(values.actual_minutes), actual_quantity: quantity(values.actual_quantity), percent_complete: Number(values.percent_complete), reason: values.reason };
  return action === "reject" ? { reason: values.reason } : {};
}
