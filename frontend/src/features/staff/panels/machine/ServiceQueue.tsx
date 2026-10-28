import type { ReactNode } from "react";

import { Button, Chip, Dropdown, EmptyState, Field, Input, Skeleton, type ChipTone } from "../../../../components/ui";
import type { MachineServiceRequest, PrinterPool } from "../../../../generated/api";
import type { Machine } from "../../machinesApi";
import { formatMoney } from "../../paymentsApi";
import { ServiceStatusChip } from "./machineUi";
import type { ServiceActionName, ServiceDraft } from "./serviceDrafts";
import { paymentState } from "./servicePaymentState";
import { poolLabel } from "./servicePools";
import { useConsoleModule } from "./useConsoleModule";

/** Button, confirm and toast copy for each service transition. */
export const SERVICE_ACTION_COPY: Record<ServiceActionName, { confirm: string; done: string; failed: string; danger?: boolean }> = {
  accept: { confirm: "Accept job", done: "Job accepted", failed: "Couldn't accept the job." },
  reject: { confirm: "Reject job", done: "Job rejected", failed: "Couldn't reject the job.", danger: true },
  start: { confirm: "Start job", done: "Job started", failed: "Couldn't start the job." },
  complete: { confirm: "Complete job", done: "Job completed", failed: "Couldn't complete the job." },
  fail: { confirm: "Mark as failed", done: "Job marked as failed", failed: "Couldn't mark the job as failed.", danger: true },
  "record-manual-payment": { confirm: "Record payment", done: "Payment recorded", failed: "Couldn't record the payment." },
  collect: { confirm: "Mark collected", done: "Job collected", failed: "Couldn't mark the job collected." },
  reprint: { confirm: "Queue reprint", done: "Reprint queued", failed: "Couldn't queue the reprint." },
};

export function paymentTone(request: Pick<MachineServiceRequest, "payment" | "payment_status" | "payment_amount">): ChipTone {
  const state = paymentState(request);
  if (state.startsWith("owed")) return "warning";
  if (state.startsWith("paid")) return "success";
  return "neutral";
}

// With `payments` off no charge is ever raised, so "Payment free" on every job is copy about a
// module that is not there. A real charge row (or a legacy amount) still shows either way.
export function showPaymentChip(request: Pick<MachineServiceRequest, "payment" | "payment_status" | "payment_amount">, paymentsOn: boolean) {
  return paymentsOn || paymentState(request) !== "free";
}

type Options = {
  /** "Machine" or "Printer": the start form's machine picker label. */
  machineNoun: string;
  /** Short unit the quantity fields are labelled in ("g", "items"); omitted for a minutes
   *  type, which has no quantity to type. A type without consumables still measures one. */
  unitLabel?: string;
  /** Show the pool picker: only types that use consumables have pools. */
  hasPool: boolean;
  /** The printer flow also plans grams at accept time and offers reprint after a failure. */
  plannedOnAccept?: boolean;
  allowReprint?: boolean;
};

type Props = Options & {
  makerspaceId: number;
  requests: MachineServiceRequest[] | undefined;
  loading: boolean;
  draft: ServiceDraft;
  setDraft: (update: (draft: ServiceDraft) => ServiceDraft) => void;
  machines: Machine[];
  pools: PrinterPool[];
  meta: (request: MachineServiceRequest) => ReactNode;
  pending: boolean;
  onSubmit: (action: NonNullable<ServiceDraft["action"]>) => void;
};

export function ServiceQueue({ makerspaceId, requests, loading, draft, setDraft, machines, pools, meta, pending, onSubmit, ...options }: Props) {
  const paymentsOn = useConsoleModule(makerspaceId, "payments");
  const choose = (request: MachineServiceRequest, name: ServiceActionName) =>
    setDraft((current) => ({ ...current, action: { id: request.id, name } }));
  const form = draft.action ? (
    <ServiceActionForm
      {...options}
      action={draft.action}
      values={draft.actionValues}
      setValues={(actionValues) => setDraft((current) => ({ ...current, actionValues }))}
      machines={machines}
      pools={pools}
      pending={pending}
      onSubmit={onSubmit}
      onCancel={() => setDraft((current) => ({ ...current, action: null }))}
    />
  ) : null;
  const formIsInline = Boolean(draft.action && requests?.some((request) => request.id === draft.action?.id));

  if (loading) {
    return (
      <div className="grid gap-2" role="status" aria-label="Loading service queue">
        <Skeleton className="h-24 w-full" />
        <Skeleton className="h-24 w-full" />
      </div>
    );
  }
  return (
    <div className="grid gap-2">
      {requests && !requests.length ? (
        <EmptyState title="The queue is clear" description="New service requests show up here." />
      ) : null}
      {requests?.map((request) => (
        <article className="grid gap-3 rounded-lg border border-line bg-canvas p-4" key={request.id}>
          <div className="flex flex-wrap items-start justify-between gap-2">
            <strong className="min-w-0 text-title text-ink">{request.title}</strong>
            <span className="flex flex-wrap items-center gap-1.5">
              <ServiceStatusChip status={request.status} />
              {showPaymentChip(request, paymentsOn) ? <Chip size="sm" tone={paymentTone(request)}>Payment {paymentState(request)}</Chip> : null}
            </span>
          </div>
          <p className="text-caption text-ink-muted">{meta(request)}</p>
          <div className="flex flex-wrap gap-2">
            <ServiceActions request={request} allowReprint={options.allowReprint} onAction={(name) => choose(request, name)} />
          </div>
          {draft.action?.id === request.id ? form : null}
        </article>
      ))}
      {/* A draft whose job left the list (it moved on elsewhere) still shows, so typing is not lost. */}
      {form && !formIsInline ? form : null}
    </div>
  );
}

function ServiceActions({ request, allowReprint, onAction }: { request: MachineServiceRequest; allowReprint?: boolean; onAction: (name: ServiceActionName) => void }) {
  if (request.status === "pending") {
    return <><Button size="sm" onClick={() => onAction("accept")}>Accept</Button><Button size="sm" variant="danger-quiet" onClick={() => onAction("reject")}>Reject…</Button></>;
  }
  if (request.status === "accepted") return <Button size="sm" onClick={() => onAction("start")}>Start</Button>;
  if (request.status === "in_progress") {
    return <><Button size="sm" onClick={() => onAction("complete")}>Complete</Button><Button size="sm" variant="danger-quiet" onClick={() => onAction("fail")}>Fail…</Button></>;
  }
  if (request.status === "completed" && request.payment?.status === "pending") {
    return <Button size="sm" onClick={() => onAction("record-manual-payment")}>Record payment · {formatMoney(request.payment.amount, request.payment.currency)}</Button>;
  }
  if (request.status === "completed") return <Button size="sm" onClick={() => onAction("collect")}>Collect</Button>;
  return allowReprint && request.status === "failed" ? <Button size="sm" onClick={() => onAction("reprint")}>Reprint</Button> : null;
}

function ServiceActionForm({ action, values, setValues, machines, pools, machineNoun, unitLabel, hasPool, plannedOnAccept, pending, onSubmit, onCancel }: Options & {
  action: NonNullable<ServiceDraft["action"]>;
  values: ServiceDraft["actionValues"];
  setValues: (values: ServiceDraft["actionValues"]) => void;
  machines: Machine[];
  pools: PrinterPool[];
  pending: boolean;
  onSubmit: (action: NonNullable<ServiceDraft["action"]>) => void;
  onCancel: () => void;
}) {
  const copy = SERVICE_ACTION_COPY[action.name];
  const input = (key: keyof typeof values, label: string, numeric = true) => (
    <Field label={label}>
      <Input inputMode={numeric ? "decimal" : undefined} value={values[key]} onChange={(event) => setValues({ ...values, [key]: event.target.value })} />
    </Field>
  );
  const name = action.name;
  const planned = unitLabel ? input("planned_quantity", `Planned quantity (${unitLabel})`) : null;
  return (
    <form
      className="grid gap-3 rounded-lg border border-line bg-subtle p-4"
      onSubmit={(event) => { event.preventDefault(); onSubmit(action); }}
    >
      <div className="grid gap-3 sm:grid-cols-2 md:grid-cols-3">
        {name === "accept" ? <>{input("estimated_minutes", "Estimated minutes")}{plannedOnAccept ? planned : null}</> : null}
        {name === "start" ? (
          <>
            <Field label={machineNoun}>
              <Dropdown aria-label={machineNoun} value={values.machine_id} onChange={(event) => setValues({ ...values, machine_id: event.target.value, consumable_pool_id: "" })}>
                <option value="">Any idle {machineNoun.toLowerCase()}</option>
                {machines.map((machine) => <option key={machine.id} value={String(machine.id)}>{machine.name}</option>)}
              </Dropdown>
            </Field>
            {hasPool ? (
              <Field label="Pool" helperText={values.machine_id ? undefined : `Choose a ${machineNoun.toLowerCase()} to see its pools.`}>
                <Dropdown aria-label="Pool" value={values.consumable_pool_id} onChange={(event) => setValues({ ...values, consumable_pool_id: event.target.value })}>
                  <option value="">No pool</option>
                  {pools.map((pool) => <option key={pool.id} value={String(pool.id)}>{poolLabel(pool)}</option>)}
                </Dropdown>
              </Field>
            ) : null}
            {input("estimated_minutes", "Estimated minutes")}
            {planned}
          </>
        ) : null}
        {name === "complete" || name === "fail" ? (
          <>
            {input("actual_minutes", "Actual minutes")}
            {unitLabel ? input("actual_quantity", `Actual quantity (${unitLabel})`) : null}
            {name === "fail" ? <>{input("percent_complete", "Percent complete")}{input("reason", "Reason", false)}</> : null}
          </>
        ) : null}
        {name === "reject" ? input("reason", "Reason", false) : null}
      </div>
      {name === "record-manual-payment" || name === "collect" || name === "reprint" ? (
        <p className="text-body-ui text-ink-secondary">
          {name === "collect" ? "Confirm the requester has their finished job." : name === "reprint" ? "This creates a new, already accepted copy of the job, ready to start." : "Confirm the payment was taken at the desk."}
        </p>
      ) : null}
      <div className="flex flex-wrap gap-2">
        <Button type="submit" variant={copy.danger ? "danger" : "primary"} size="sm" loading={pending} loadingLabel="Saving…">{copy.confirm}</Button>
        <Button size="sm" variant="quiet" onClick={onCancel} disabled={pending}>Cancel</Button>
      </div>
    </form>
  );
}
