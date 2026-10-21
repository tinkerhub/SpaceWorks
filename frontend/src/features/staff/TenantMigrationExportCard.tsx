import { Button, Callout, Card, Field, Textarea } from "../../components/ui";
import type { MigrationConfirm } from "./TenantMigrationConfirm";
import type { MigrationExportJob, Pairing } from "./tenantMigrationApi";
import { ErrorText, lifecycleWord, parseReceipt, StatusPill } from "./tenantMigrationUi";

/** One source export: digest, status, download, and the guarded cutover actions. */
export function TenantMigrationExportCard({
  job,
  detailError,
  pairing,
  tenantName,
  quiesced,
  abortReceiptText,
  onAbortReceiptChange,
  downloadPending,
  quiescePending,
  archivePending,
  recoverPending,
  onDownload,
  onConfirm,
}: {
  job: MigrationExportJob;
  detailError: unknown;
  pairing?: Pairing;
  tenantName: string;
  quiesced: boolean;
  abortReceiptText: string;
  onAbortReceiptChange: (pairingId: string, value: string) => void;
  downloadPending: boolean;
  quiescePending: boolean;
  archivePending: boolean;
  recoverPending: boolean;
  onDownload: () => void;
  onConfirm: (confirm: MigrationConfirm) => void;
}) {
  const abortReceipt = parseReceipt(abortReceiptText);
  const status = job.status ?? "pending";
  return (
    <Card as="article">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-title text-ink">Export <span className="font-mono text-sm">{job.id}</span></p>
          <p className="mt-1 break-all font-mono text-xs text-ink-muted">Archive digest: {job.archive_digest || "Pending"}</p>
        </div>
        <StatusPill tone={status === "failed" ? "danger" : status === "available" ? "success" : "warn"}>{lifecycleWord(status)}</StatusPill>
      </div>
      {job.failure_detail ? <p className="mt-2 text-caption text-danger-fg" role="alert">{job.failure_detail}</p> : null}
      <ErrorText error={detailError} />
      <p className="mt-2 text-caption text-ink-muted">{job.source_retention_notice}</p>
      {quiesced ? <Callout className="mt-3" tone="danger" role="status">Source writes are frozen for this cutover.</Callout> : null}
      {status === "available" ? (
        <div className="mt-4 flex flex-wrap gap-2">
          <Button size="sm" variant="secondary" disabled={downloadPending} onClick={onDownload}>Download one-use archive</Button>
          <Button size="sm" variant="danger" disabled={quiescePending} onClick={() => onConfirm({ kind: "quiesce", jobId: job.id })}>
            Quiesce {tenantName}…
          </Button>
          {pairing ? (
            <Button size="sm" variant="danger" disabled={archivePending} onClick={() => onConfirm({ kind: "archive", pairingId: pairing.id })}>
              Archive source {tenantName}…
            </Button>
          ) : null}
        </div>
      ) : null}
      {pairing ? (
        <div className="mt-4 grid gap-3 rounded-md bg-subtle p-4">
          <p className="text-caption text-ink-muted">Pinned pairing <span className="font-mono">{pairing.id}</span></p>
          <Field label="Target aborted receipt" helperText="Only for recovery after the target was aborted.">
            <Textarea className="min-h-24 font-mono text-xs" value={abortReceiptText} onChange={(event) => onAbortReceiptChange(pairing.id, event.target.value)} />
          </Field>
          <div>
            <Button
              size="sm"
              variant="danger"
              disabled={!abortReceipt || recoverPending}
              onClick={() => abortReceipt && onConfirm({ kind: "recover", pairingId: pairing.id, receipt: abortReceipt })}
            >
              Recover source {tenantName}…
            </Button>
          </div>
        </div>
      ) : null}
    </Card>
  );
}
