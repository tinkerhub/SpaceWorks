import type { StatusTone } from "../../components/ui";
import { StructuredApiError } from "../../lib/api";

export function eventErrorText(error: unknown) {
  if (!(error instanceof Error)) return "Something went wrong.";
  if (error instanceof StructuredApiError && error.code) {
    return `${error.message} (${error.code})`;
  }
  return error.message;
}

const EVENT_STATUS_TONES: Record<string, StatusTone> = {
  draft: "neutral",
  published: "success",
  completed: "info",
  cancelled: "danger",
  invited: "warning",
  accepted: "success",
  declined: "neutral",
};

/** Tone for an event, series, occurrence or collaboration status word. */
export function eventStatusTone(status: string): StatusTone {
  return EVENT_STATUS_TONES[status.toLowerCase()] ?? "neutral";
}

/** "pending_approval" -> "Pending approval". */
export function eventStatusLabel(status: string) {
  const words = status.replace(/_/g, " ");
  return words.charAt(0).toUpperCase() + words.slice(1);
}

/** Short local date + time without seconds, e.g. "Wed 14 Oct, 9:30 AM". */
export function eventDateTime(value: string) {
  return new Date(value).toLocaleString(undefined, {
    weekday: "short", day: "numeric", month: "short", hour: "numeric", minute: "2-digit",
  });
}
