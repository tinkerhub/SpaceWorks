import { StatusChip } from "../../components/ui";
import { eventStatusLabel, eventStatusTone } from "./eventUi";

/** Event / series / collaboration status as a word + icon chip. */
export function EventStatusChip({ status, size = "sm" }: { status: string; size?: "sm" | "md" }) {
  return <StatusChip tone={eventStatusTone(status)} size={size}>{eventStatusLabel(status)}</StatusChip>;
}
