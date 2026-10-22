import { StatusChip, type StatusTone } from "../../components/ui";
import type { Availability } from "../../types/inventory";

function toneForAvailability(label: NonNullable<Availability>["label"]): StatusTone {
  if (label === "Limited") return "warning";
  if (label === "Unavailable") return "danger";
  if (label === "Available") return "success";
  return "neutral";
}

function textForAvailability(availability: NonNullable<Availability>): string {
  const label = availability.label;
  if (availability.mode === "exact_count" && availability.count != null) {
    if (label === "Unavailable") return "Unavailable";
    if (label === "Limited") return `${availability.count} limited`;
    return `${availability.count} available`;
  }
  return label ?? "Available";
}

/** Availability as a word + icon on its status tone. Hidden-count items show nothing. */
export function AvailabilityBadge({ availability, size = "sm", className }: {
  availability: Availability;
  size?: "sm" | "md";
  className?: string;
}) {
  if (availability === null) return null;
  return (
    <StatusChip tone={toneForAvailability(availability.label)} size={size} className={className}>
      {textForAvailability(availability)}
    </StatusChip>
  );
}
