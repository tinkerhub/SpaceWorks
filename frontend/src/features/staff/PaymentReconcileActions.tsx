import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { Button, ConfirmDialog, StatusChip, useToast } from "../../components/ui";
import { errorText } from "./panels/shared";
import {
  formatMoney,
  invalidatePaymentViews,
  paymentStatusLabel,
  paymentStatusTone,
  reconcilePayment,
} from "./paymentsApi";

export type PaymentSummary = {
  id: number;
  status: "pending" | "paid_online" | "paid_offline" | "waived" | "canceled";
  amount: string;
  currency: string;
};

type Action = "mark-offline" | "waive";

export function PaymentReconcileActions({
  makerspaceId,
  payment,
  invalidateKeys = [],
}: {
  makerspaceId: number;
  payment: PaymentSummary | null;
  invalidateKeys?: readonly (readonly unknown[])[];
}) {
  const queryClient = useQueryClient();
  const { showToast } = useToast();
  const [confirmWaive, setConfirmWaive] = useState(false);
  const mutation = useMutation({
    mutationFn: (action: Action) =>
      reconcilePayment(makerspaceId, action, [payment!.id], false),
    onSuccess: (_data, action) => {
      invalidatePaymentViews(queryClient, makerspaceId);
      for (const queryKey of invalidateKeys) {
        queryClient.invalidateQueries({ queryKey });
      }
      showToast(action === "waive" ? "Payment waived" : "Marked as paid offline", { tone: "success" });
    },
    onError: (error) => showToast(errorText(error, "Couldn't update the payment"), { tone: "error" }),
    onSettled: () => setConfirmWaive(false),
  });

  if (!payment) return null;
  const amount = formatMoney(payment.amount, payment.currency);
  return (
    <div className="mt-3 flex flex-wrap items-center gap-2 text-body-ui">
      <span className="font-semibold text-ink">Payment {amount}</span>
      <StatusChip tone={paymentStatusTone(payment.status)} size="sm">{paymentStatusLabel(payment.status)}</StatusChip>
      {payment.status === "pending" ? (
        <>
          <Button size="sm" variant="secondary" disabled={mutation.isPending} loading={mutation.isPending && mutation.variables === "mark-offline"} onClick={() => mutation.mutate("mark-offline")}>
            Mark offline
          </Button>
          <Button size="sm" variant="secondary" disabled={mutation.isPending} onClick={() => setConfirmWaive(true)}>
            Waive…
          </Button>
        </>
      ) : null}
      {mutation.error ? (
        <span className="text-caption text-danger-fg" role="alert">{mutation.error.message}</span>
      ) : null}
      <ConfirmDialog
        open={confirmWaive}
        title={`Waive ${amount}?`}
        message="The payment closes as waived and nobody is asked to pay it."
        confirmLabel="Waive payment"
        pending={mutation.isPending}
        onConfirm={() => mutation.mutate("waive")}
        onCancel={() => setConfirmWaive(false)}
      />
    </div>
  );
}
