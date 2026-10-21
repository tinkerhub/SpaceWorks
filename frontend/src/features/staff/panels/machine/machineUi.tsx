import { useMemo } from "react";

import { StatusChip, useToast, type StatusTone } from "../../../../components/ui";
import type { MachineStatus } from "../../machinesApi";

/* Shared presentation helpers for the machines console: status words + tones, one date
   formatter, and the toast pair every mutation reports through. */

const machineStatus: Record<MachineStatus, { label: string; tone: StatusTone }> = {
  idle: { label: "Idle", tone: "success" },
  running: { label: "Running", tone: "info" },
  reserved: { label: "Reserved", tone: "warning" },
  maintenance: { label: "Maintenance", tone: "warning" },
  offline: { label: "Offline", tone: "danger" },
};

export const MACHINE_STATUSES = Object.keys(machineStatus) as MachineStatus[];

export function machineStatusLabel(status: MachineStatus) {
  return machineStatus[status]?.label ?? status;
}

export function MachineStatusChip({ status, size = "sm" }: { status: MachineStatus; size?: "sm" | "md" }) {
  const entry = machineStatus[status] ?? { label: status, tone: "neutral" as const };
  return <StatusChip tone={entry.tone} size={size}>{entry.label}</StatusChip>;
}

const serviceStatus: Record<string, { label: string; tone: StatusTone }> = {
  pending: { label: "Pending", tone: "warning" },
  accepted: { label: "Accepted", tone: "info" },
  in_progress: { label: "In progress", tone: "info" },
  completed: { label: "Completed", tone: "success" },
  collected: { label: "Collected", tone: "neutral" },
  failed: { label: "Failed", tone: "danger" },
  rejected: { label: "Rejected", tone: "danger" },
  canceled: { label: "Cancelled", tone: "neutral" },
  cancelled: { label: "Cancelled", tone: "neutral" },
};

/** `in_progress` -> "In progress". */
export function humanize(value: string) {
  const words = value.replace(/_/g, " ");
  return words.charAt(0).toUpperCase() + words.slice(1);
}

export function ServiceStatusChip({ status }: { status: string }) {
  const entry = serviceStatus[status] ?? { label: humanize(status), tone: "neutral" as const };
  return <StatusChip tone={entry.tone} size="sm">{entry.label}</StatusChip>;
}

const dayFormat = new Intl.DateTimeFormat(undefined, { day: "numeric", month: "short", year: "numeric" });
const timeFormat = new Intl.DateTimeFormat(undefined, { hour: "numeric", minute: "2-digit" });

/** Relative for the last week ("2 min ago", "Yesterday"), otherwise "13 Oct 2026". */
export function formatWhen(value: string | null | undefined) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  const minutes = Math.round((Date.now() - date.getTime()) / 60000);
  if (minutes >= 0 && minutes < 1) return "Just now";
  if (minutes >= 0 && minutes < 60) return `${minutes} min ago`;
  const hours = Math.round(minutes / 60);
  if (minutes >= 0 && hours < 24) return `${hours} h ago`;
  const days = Math.round(hours / 24);
  if (minutes >= 0 && days === 1) return `Yesterday, ${timeFormat.format(date)}`;
  if (minutes >= 0 && days < 7) return `${days} days ago`;
  return dayFormat.format(date);
}

/** Absolute date + time, for a `title` beside a relative stamp. */
export function formatFull(value: string | null | undefined) {
  if (!value) return "";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : `${dayFormat.format(date)}, ${timeFormat.format(date)}`;
}

/** A calendar date stored as YYYY-MM-DD, read in local time. */
export function formatDay(value: string) {
  const date = new Date(`${value}T00:00:00`);
  return Number.isNaN(date.getTime()) ? value : dayFormat.format(date);
}

export function formatBytes(value: number) {
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / (1024 * 1024)).toFixed(1)} MB`;
}

/** Timestamp that reads relatively but keeps the exact moment on hover. */
export function When({ value }: { value: string | null | undefined }) {
  if (!value) return null;
  return <time dateTime={value} title={formatFull(value)}>{formatWhen(value)}</time>;
}

/** Success / failure toasts for mutations. Failures carry the server's reason when it has one. */
export function useNotify() {
  const { showToast } = useToast();
  return useMemo(() => ({
    success: (message: string) => showToast(message, { tone: "success" }),
    failure: (message: string, error?: unknown) => showToast(
      error instanceof Error && error.message ? `${message} ${error.message}` : message,
      { tone: "error" },
    ),
  }), [showToast]);
}
