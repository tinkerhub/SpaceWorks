import type React from "react";

import { Field, StatusChip, Textarea } from "../../components/ui";
import { StructuredApiError } from "../../lib/api";
import type { ReceiptEnvelope } from "./tenantMigrationApi";

function flatten(value: unknown): string[] {
  if (typeof value === "string") return value.trim() ? [value.trim()] : [];
  if (Array.isArray(value)) return value.flatMap(flatten);
  if (value && typeof value === "object") return Object.values(value).flatMap(flatten);
  return [];
}

export function migrationError(error: unknown, field?: string) {
  if (!(error instanceof StructuredApiError)) {
    return error instanceof Error ? error.message : "The tenant migration request failed.";
  }
  // Field names do not survive StructuredApiError.message: it deliberately flattens
  // Object.values(body). Boundary errors therefore have to be read from body[field].
  const fieldMessages = field ? flatten(error.body[field]) : [];
  const detail = typeof error.body.detail === "string" ? error.body.detail : error.detail;
  const message = fieldMessages[0] ?? detail ?? flatten(error.body)[0] ?? "The request failed.";
  return error.code ? `${message} (${error.code})` : message;
}

export function ErrorText({ error, field }: { error: unknown; field?: string }) {
  if (!error) return null;
  return <p className="mt-2 text-caption text-danger-fg" role="alert">{migrationError(error, field)}</p>;
}

/** Status as a word + icon chip (sentence case). */
export function StatusPill({ children, tone = "neutral" }: {
  children: React.ReactNode;
  tone?: "neutral" | "success" | "danger" | "warn";
}) {
  return <StatusChip tone={tone === "warn" ? "warning" : tone} size="sm">{children}</StatusChip>;
}

export function parseReceipt(value: string): ReceiptEnvelope | null {
  try {
    const parsed = JSON.parse(value) as Partial<ReceiptEnvelope>;
    if (!parsed.payload || typeof parsed.payload !== "object" || Array.isArray(parsed.payload) ||
        typeof parsed.signer_fingerprint !== "string" || typeof parsed.signature !== "string") {
      return null;
    }
    return parsed as ReceiptEnvelope;
  } catch {
    return null;
  }
}

export function ReceiptOutput({ label, receipt }: { label: string; receipt?: ReceiptEnvelope }) {
  if (!receipt) return null;
  return (
    <Field label={label} className="mt-3" helperText="Copy this signed receipt to the other deployment.">
      <Textarea readOnly className="min-h-32 font-mono text-xs" value={JSON.stringify(receipt, null, 2)} />
    </Field>
  );
}

/** Lifecycle word for a chip: IMPORTING -> Importing. */
export function lifecycleWord(value: string) {
  const words = value.replace(/_/g, " ").toLowerCase();
  return words.charAt(0).toUpperCase() + words.slice(1);
}

export function openDownload(url: string) {
  const link = document.createElement("a");
  link.href = url;
  link.rel = "noopener";
  document.body.appendChild(link);
  link.click();
  link.remove();
}
