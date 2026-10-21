import { StatusChip, type StatusTone } from "../../components/ui";
import type { WarrantyStatus } from "./warrantyApi";

const statusTone: Record<WarrantyStatus, StatusTone> = {
  unknown: "neutral",
  active: "success",
  expiring_soon: "warning",
  expired: "danger",
};

export const warrantyStatusLabel: Record<WarrantyStatus, string> = {
  unknown: "Uncovered / no warranty",
  active: "Active",
  expiring_soon: "Expiring soon",
  expired: "Expired",
};

/** Warranty state as a word + icon chip, so colour is never the only signal. */
export function WarrantyStatusBadge({ status }: { status: WarrantyStatus }) {
  return <StatusChip tone={statusTone[status]} size="sm">{warrantyStatusLabel[status]}</StatusChip>;
}
