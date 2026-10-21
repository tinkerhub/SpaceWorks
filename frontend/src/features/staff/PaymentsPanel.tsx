import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  BulkActionToolbar,
  Button,
  Callout,
  ConfirmDialog,
  DataTable,
  Dropdown,
  Field,
  StatusChip,
  useToast,
  type DataTableColumn,
} from "../../components/ui";
import { StructuredApiError, staffRequest } from "../../lib/api";
import {
  PAYMENT_STATUSES,
  PAYMENT_SUBJECTS,
  formatMoney,
  invalidatePaymentViews,
  paymentListKey,
  paymentListPath,
  paymentStatusLabel,
  paymentStatusTone,
  reconcilePayment,
  type PaymentRow,
} from "./paymentsApi";
import { Panel, errorText } from "./panels/shared";

type Action = "mark-offline" | "waive";
type Run = { action: Action; ids: number[]; bulk: boolean };

export function PaymentsPanel({ makerspaceId }: { makerspaceId: number }) {
  const queryClient = useQueryClient();
  const { showToast } = useToast();
  const [status, setStatus] = useState("pending");
  const [subject, setSubject] = useState("");
  const [selected, setSelected] = useState<number[]>([]);
  const [conflict, setConflict] = useState("");
  const [waiving, setWaiving] = useState<Omit<Run, "action"> | null>(null);
  const payments = useQuery({
    queryKey: paymentListKey(makerspaceId, status, subject),
    queryFn: () => staffRequest<PaymentRow[]>(paymentListPath(makerspaceId, status, subject)),
  });
  const mutation = useMutation({
    mutationFn: ({ action, ids, bulk }: Run) => reconcilePayment(makerspaceId, action, ids, bulk),
    onSuccess: (_data, { action, ids }) => {
      setConflict("");
      setSelected([]);
      invalidatePaymentViews(queryClient, makerspaceId);
      const count = ids.length === 1 ? "Payment" : `${ids.length} payments`;
      showToast(action === "waive" ? `${count} waived` : `${count} marked as paid offline`, { tone: "success" });
    },
    onError: (error) => {
      if (error instanceof StructuredApiError && error.status === 409) {
        setConflict(error.message || "This payment was already reconciled.");
        void payments.refetch();
      }
      showToast(errorText(error, "Couldn't update the payment"), { tone: "error" });
    },
    onSettled: () => setWaiving(null),
  });
  const run = (action: Action, ids: number[], bulk: boolean) => {
    setConflict("");
    mutation.mutate({ action, ids, bulk });
  };
  const columns: DataTableColumn<PaymentRow>[] = [
    { key: "subject_label", header: "Subject", sortable: true },
    { key: "subject_type", header: "Type", render: (row) => labelFor(PAYMENT_SUBJECTS, row.subject_type) },
    {
      key: "status",
      header: "Status",
      render: (row) => <StatusChip tone={paymentStatusTone(row.status)} size="sm">{paymentStatusLabel(row.status)}</StatusChip>,
    },
    { key: "amount", header: "Amount", render: (row) => formatMoney(row.amount, row.currency), className: "font-semibold tabular-nums" },
    { key: "created_at", header: "Created", render: (row) => new Date(row.created_at).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" }) },
    {
      key: "actions",
      header: <span className="sr-only">Actions</span>,
      render: (row) => (
        <div className="flex flex-wrap justify-end gap-2">
          <Button size="sm" variant="secondary" disabled={mutation.isPending} onClick={() => run("mark-offline", [row.id], false)}>
            Mark offline
          </Button>
          <Button size="sm" variant="secondary" disabled={mutation.isPending} onClick={() => setWaiving({ ids: [row.id], bulk: false })}>
            Waive…
          </Button>
        </div>
      ),
    },
  ];
  const waiveCount = waiving?.ids.length ?? 0;

  return (
    <Panel title="Payments" description="Settle payments taken outside the app, or waive what nobody needs to pay.">
      <div className="grid gap-4">
        <div className="grid gap-3 sm:grid-cols-[minmax(0,220px)_minmax(0,220px)]">
          <Field label="Status">
            <Dropdown value={status} onChange={(event) => { setStatus(event.target.value); setSelected([]); }}>
              <option value="">All statuses</option>
              {PAYMENT_STATUSES.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
            </Dropdown>
          </Field>
          <Field label="Subject">
            <Dropdown value={subject} onChange={(event) => { setSubject(event.target.value); setSelected([]); }}>
              <option value="">All subjects</option>
              {PAYMENT_SUBJECTS.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
            </Dropdown>
          </Field>
        </div>
        <BulkActionToolbar
          selectedCount={selected.length}
          onClear={() => setSelected([])}
          actions={(
            <>
              <Button size="sm" variant="secondary" disabled={mutation.isPending} onClick={() => run("mark-offline", selected, true)}>Mark offline</Button>
              <Button size="sm" variant="secondary" disabled={mutation.isPending} onClick={() => setWaiving({ ids: selected, bulk: true })}>Waive…</Button>
            </>
          )}
        />
        {conflict ? <Callout tone="danger" role="alert">{conflict}</Callout> : null}
        {payments.error && !payments.data ? <Callout tone="danger" title="Couldn't load payments">{payments.error.message}</Callout> : null}
        {mutation.error && !conflict ? <Callout tone="danger" role="alert">{mutation.error.message}</Callout> : null}
        <DataTable
          columns={columns}
          data={payments.data ?? []}
          loading={payments.isLoading}
          skeletonCols={6}
          selectedIds={selected}
          onSelectionChange={(ids) => setSelected(ids.map(Number))}
          emptyTitle="No matching payments"
          emptyDescription={status || subject ? "Try another status or subject." : "Payments appear here when someone books, registers or pays dues."}
        />
      </div>
      <ConfirmDialog
        open={waiving !== null}
        title={waiveCount === 1 ? "Waive this payment?" : `Waive ${waiveCount} payments?`}
        message="Waived payments close and nobody is asked to pay them."
        confirmLabel={waiveCount === 1 ? "Waive payment" : "Waive payments"}
        pending={mutation.isPending}
        onConfirm={() => { if (waiving) run("waive", waiving.ids, waiving.bulk); }}
        onCancel={() => setWaiving(null)}
      />
    </Panel>
  );
}

function labelFor(options: readonly (readonly [string, string])[], value: string) {
  return options.find(([key]) => key === value)?.[1] ?? value.replace(/_/g, " ");
}
