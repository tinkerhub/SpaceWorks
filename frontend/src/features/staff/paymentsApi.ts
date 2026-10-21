import type { QueryClient } from "@tanstack/react-query";

import { staffRequest } from "../../lib/api";

export const PAYMENT_SUBJECTS = [
  ["machine_service_request", "Machine service"],
  ["booking", "Booking"],
  ["event_registration", "Event registration"],
  ["makerspace_membership", "Membership dues"],
] as const;

export const PAYMENT_STATUSES = [
  ["pending", "Pending"],
  ["paid_online", "Paid online"],
  ["paid_offline", "Paid offline"],
  ["waived", "Waived"],
  ["canceled", "Canceled"],
] as const;

export type PaymentRow = {
  id: number;
  subject_type: (typeof PAYMENT_SUBJECTS)[number][0];
  subject_id: number;
  subject_label: string;
  status: (typeof PAYMENT_STATUSES)[number][0];
  amount: string;
  currency: string;
  created_at: string;
  updated_at: string;
};

export function paymentListKey(makerspaceId: number, status: string, subject: string) {
  return ["payments", makerspaceId, status, subject] as const;
}

export function paymentListPath(makerspaceId: number, status: string, subject: string) {
  const query = new URLSearchParams();
  if (status) query.set("status", status);
  if (subject) query.set("subject_type", subject);
  const suffix = query.toString();
  return `/admin/makerspace/${makerspaceId}/payments${suffix ? `?${suffix}` : ""}`;
}

export function reconcilePayment(
  makerspaceId: number,
  action: "mark-offline" | "waive",
  ids: number[],
  bulk: boolean,
) {
  const base = `/admin/makerspace/${makerspaceId}/payments`;
  const path = bulk ? `${base}/bulk/${action}` : `${base}/${ids[0]}/${action}`;
  return staffRequest<PaymentRow | PaymentRow[]>(path, {
    method: "POST",
    ...(bulk ? { body: JSON.stringify({ ids }) } : {}),
  });
}

export function invalidatePaymentViews(queryClient: QueryClient, makerspaceId: number) {
  queryClient.invalidateQueries({ queryKey: ["payments", makerspaceId] });
  queryClient.invalidateQueries({ queryKey: ["operations-report", "payment-reconciliation"] });
  queryClient.invalidateQueries({ queryKey: ["dashboard", makerspaceId] });
}

/** Chip tone for a payment status: settled = success, open = warning, written off = neutral. */
export function paymentStatusTone(status: string): "success" | "warning" | "neutral" {
  if (status === "paid_online" || status === "paid_offline") return "success";
  if (status === "pending") return "warning";
  return "neutral";
}

export function paymentStatusLabel(status: string) {
  return PAYMENT_STATUSES.find(([key]) => key === status)?.[1] ?? status.replace(/_/g, " ");
}

export function formatMoney(amount: string, currency: string) {
  try {
    return new Intl.NumberFormat(undefined, { style: "currency", currency: currency.toUpperCase() }).format(Number(amount));
  } catch {
    return `${currency.toUpperCase()} ${amount}`;
  }
}
