import type { StatusTone } from "../../components/ui";

/** API status codes (`pending_approval`) as sentence-case words ("Pending approval"). */
export function statusLabel(status: string) {
  const words = status.replace(/_/g, " ").trim();
  return words ? words[0].toUpperCase() + words.slice(1) : status;
}

const TONES: Record<string, StatusTone> = {
  active: "success",
  paid: "success",
  succeeded: "success",
  registered: "success",
  attended: "success",
  confirmed: "success",
  completed: "success",
  approved: "success",
  pending: "warning",
  pending_approval: "warning",
  requested: "warning",
  waitlisted: "warning",
  queued: "info",
  in_progress: "info",
  failed: "danger",
  rejected: "danger",
  suspended: "danger",
  revoked: "danger",
  expired: "danger",
  cancelled: "neutral",
  canceled: "neutral",
  refunded: "neutral",
};

/** Status chip tone for a member-facing status code; unknown codes stay neutral. */
export function statusTone(status: string): StatusTone {
  return TONES[status] ?? "neutral";
}
