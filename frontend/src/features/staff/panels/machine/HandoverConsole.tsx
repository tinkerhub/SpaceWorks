import { useMutation, useQueryClient } from "@tanstack/react-query";

import type { MachineServiceRequest } from "../../../../generated/api";
import { Button, Chip, EmptyState, PageHeader, SkeletonRows, Table, TBody, TD, TH, THead, TR } from "../../../../components/ui";
import { staffRequest } from "../../../../lib/api";
import { useStaffGet } from "../shared";
import { useNotify, When } from "./machineUi";
import { paymentTone } from "./ServiceQueue";
import { paymentState } from "./servicePaymentState";

/**
 * Front-desk handover of finished machine jobs.
 *
 * Deliberately not a slimmed-down MachineServiceConsole. That one is the machine
 * lifecycle -- queues, pools, manual usage, accept/start/complete -- and the whole reason
 * `collect_service_request` exists is that handing a member their finished print should
 * not require any of it. So this asks only what is waiting and offers the two narrow
 * desk actions: settle a manual debt, then hand the finished job over.
 *
 * The backend narrows a collect-only actor's queryset to completed jobs by itself, so the
 * `status=completed` filter here is what a *manager* sees too rather than a client-side
 * permission check. Nothing on this screen is trusted to enforce anything.
 */

type Props = { makerspaceId: number; enabled: boolean };

export function HandoverConsole({ makerspaceId, enabled }: Props) {
  const queryClient = useQueryClient();
  const notify = useNotify();
  const queryKey = ["machine-service-handover", makerspaceId];
  const waiting = useStaffGet<MachineServiceRequest[]>(
    queryKey,
    `/admin/makerspaces/${makerspaceId}/machine-service/requests?status=completed`,
    enabled,
  );
  // Invalidate rather than filter locally: collecting is the one thing that removes a row
  // from this list, and a refetch also picks up jobs finished since the page loaded. The
  // per-type service queues on the Machines tab show the same jobs, so they refresh too --
  // otherwise a job handed over here still offers Collect there until a reload.
  const refresh = () => Promise.all([
    queryClient.invalidateQueries({ queryKey }),
    queryClient.invalidateQueries({ queryKey: ["machine-service-requests", makerspaceId] }),
    queryClient.invalidateQueries({ queryKey: ["operations-report"] }),
  ]);
  const collect = useMutation({
    mutationFn: (row: MachineServiceRequest) =>
      staffRequest(`/admin/machine-service/requests/${row.id}/collect`, { method: "POST", body: "{}" }),
    onSuccess: async (_result, row) => {
      notify.success(`${row.title} handed over`);
      await refresh();
    },
    onError: () => notify.failure("Couldn't mark that job collected. It may have been handed over already."),
  });
  const recordPayment = useMutation({
    mutationFn: (row: MachineServiceRequest) =>
      staffRequest(`/admin/machine-service/requests/${row.id}/record-manual-payment`, {
        method: "POST",
        body: "{}",
      }),
    onSuccess: async (_result, row) => {
      notify.success(`Payment recorded for ${row.title}`);
      await refresh();
    },
    onError: () => notify.failure("Couldn't record that payment. It may have been settled already."),
  });

  if (!enabled) return null;

  const rows = waiting.data ?? [];

  return (
    <section className="grid min-w-0 gap-6">
      <PageHeader title="Awaiting collection" description="Finished jobs waiting at the desk. Settle anything owed, then hand the job over." />

      {waiting.isError ? (
        <EmptyState tone="error" title="Could not load finished jobs." description="Check your connection and reload the page." />
      ) : null}
      {!waiting.isLoading && !waiting.isError && rows.length === 0 ? (
        <EmptyState title="Nothing is waiting to be handed over." description="Jobs appear here as soon as they are marked complete." />
      ) : null}

      {waiting.isLoading || rows.length > 0 ? (
        <Table label="Jobs awaiting collection">
          <THead>
            <tr><TH>Job</TH><TH>Finished</TH><TH>Payment</TH><TH><span className="sr-only">Actions</span></TH></tr>
          </THead>
          <TBody>
            {waiting.isLoading ? <SkeletonRows rows={3} cols={4} /> : null}
            {rows.map((row) => {
              const manualPayment =
                row.status === "completed" && row.payment?.status === "pending"
                  ? row.payment
                  : null;
              const busy = (collect.isPending && collect.variables?.id === row.id) || (recordPayment.isPending && recordPayment.variables?.id === row.id);
              return (
                <TR key={row.id}>
                  <TD className="min-w-48">
                    <p className="font-semibold text-ink">{row.title}</p>
                    <p className="text-caption text-ink-muted">
                      {row.requester_name || row.requester?.username || "Unknown requester"}
                      {row.machine?.name ? ` · ${row.machine.name}` : ""}
                    </p>
                  </TD>
                  <TD className="whitespace-nowrap text-ink-secondary">{row.completed_at ? <When value={row.completed_at} /> : "—"}</TD>
                  <TD><Chip size="sm" tone={paymentTone(row)}>Payment {paymentState(row)}</Chip></TD>
                  <TD>
                    {/* Both actions, never either/or. Settlement carries Payment's own
                        authority, so a handout-only desk role may mark a job collected but is
                        refused 403 on recording cash. Hiding "Hand over" behind a pending
                        payment stranded exactly that role until another staff member settled. */}
                    <div className="flex flex-wrap items-center justify-end gap-2">
                      {manualPayment ? (
                        <Button size="sm" disabled={busy} loading={recordPayment.isPending && recordPayment.variables?.id === row.id} onClick={() => recordPayment.mutate(row)}>
                          Record payment · {manualPayment.currency.toUpperCase()} {manualPayment.amount}
                        </Button>
                      ) : null}
                      <Button size="sm" disabled={busy} loading={collect.isPending && collect.variables?.id === row.id} onClick={() => collect.mutate(row)}>
                        Hand over
                      </Button>
                    </div>
                  </TD>
                </TR>
              );
            })}
          </TBody>
        </Table>
      ) : null}

      {collect.isError ? (
        <p className="text-caption text-danger-fg" role="alert">
          Could not mark that job collected. It may have been handed over already.
        </p>
      ) : null}
      {recordPayment.isError ? (
        <p className="text-caption text-danger-fg" role="alert">
          Could not record that payment. It may have been settled already.
        </p>
      ) : null}
    </section>
  );
}
