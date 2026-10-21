import type { MemberPayment } from "../../generated/api";
import { Button, StatusChip, buttonClasses } from "../../components/ui";
import { statusLabel, statusTone } from "./memberUi";

export type { MemberPayment };

export function MemberPaymentRows({
  payments,
  checkoutPaymentId,
  onCheckout,
}: {
  payments: MemberPayment[];
  checkoutPaymentId?: number;
  onCheckout: (paymentId: number) => void;
}) {
  return (
    <ul className="divide-y divide-line rounded-lg border border-line">
      {payments.map((payment) => (
        <li key={payment.id} className="flex flex-col gap-3 px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex min-w-0 flex-wrap items-center gap-2">
            <span className="min-w-0 font-semibold text-ink">{payment.subject_label}</span>
            <StatusChip size="sm" tone={statusTone(payment.status ?? "")}>{statusLabel(payment.status ?? "unknown")}</StatusChip>
          </div>
          {payment.checkout_url ? (
            <a className={buttonClasses({ variant: "primary", size: "sm", className: "self-start sm:self-auto" })} href={payment.checkout_url}>
              Pay now
            </a>
          ) : payment.status === "pending" ? (
            <Button
              size="sm"
              className="self-start sm:self-auto"
              disabled={checkoutPaymentId !== undefined}
              loading={checkoutPaymentId === payment.id}
              onClick={() => onCheckout(payment.id)}
            >
              Generate payment link
            </Button>
          ) : null}
        </li>
      ))}
    </ul>
  );
}
