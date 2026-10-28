import { useQuery, type QueryClient } from "@tanstack/react-query";

import { staffRequest, type StaffAuthUser } from "../../lib/api";
import { bookingKeys } from "./bookingsApi";
import { eventKeys } from "./eventsApiTypes";

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
  // Every screen that shows a payment chip or a "Record payment" button for one subject.
  queryClient.invalidateQueries({ queryKey: ["machine-service-handover", makerspaceId] });
  queryClient.invalidateQueries({ queryKey: ["machine-service-requests", makerspaceId] });
  queryClient.invalidateQueries({ queryKey: ["members", makerspaceId] });
  queryClient.invalidateQueries({ queryKey: eventKeys.all(makerspaceId) });
  queryClient.invalidateQueries({ queryKey: bookingKeys.all(makerspaceId) });
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

/** The cached `/auth/me` payload; the staff session seeds it on sign-in. */
export const staffMeKey = ["staff", "me"] as const;

/**
 * The makerspace's payment currency, upper-cased, or "" while it is unknown. Every staff
 * member's auth payload carries it per makerspace; only a superadmin looking at a makerspace
 * they are not a member of has no entry, and they can read the payment settings instead.
 */
export function useMakerspaceCurrency(makerspaceId: number) {
  const me = useQuery({ queryKey: staffMeKey, queryFn: () => staffRequest<StaffAuthUser>("/auth/me") });
  const fromAuth = me.data?.makerspaces?.find(({ id }) => id === makerspaceId)?.currency;
  const settings = useQuery({
    queryKey: ["payment-settings", makerspaceId],
    queryFn: () => staffRequest<{ default_currency: string }>(`/admin/makerspace/${makerspaceId}/payment-settings`),
    enabled: !me.isPending && !fromAuth,
    // A 403 is an answer here, not a fault.
    retry: false,
    retryOnMount: false,
  });
  return (fromAuth ?? settings.data?.default_currency ?? "").toUpperCase();
}

/** "Booking price (INR)" -- or the bare label when the currency is unknown. */
export function withCurrency(label: string, currency: string) {
  return currency ? `${label} (${currency})` : label;
}
