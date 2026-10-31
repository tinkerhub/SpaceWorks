import { useState } from "react";

import {
  Button,
  ConfirmDialog,
  EmptyState,
  SkeletonRows,
  StatusChip,
  Table,
  TBody,
  TD,
  TH,
  THead,
  TR,
  type StatusTone,
} from "../../components/ui";
import { backupFormat, type BackupArchive } from "./backupApi";

type RestoreKind = "rollback_in_place" | "disaster";

const statusTones: Record<BackupArchive["status"], StatusTone> = {
  available: "success",
  failed: "danger",
  expired: "neutral",
  pending: "info",
  running: "info",
  promoting: "info",
};

const statusWords: Record<BackupArchive["status"], string> = {
  available: "Available",
  failed: "Failed",
  expired: "Expired",
  pending: "Queued",
  running: "Running",
  promoting: "Finishing",
};

/** Archives as a table; restores (deployment only) confirm first. */
export function BackupArchiveTable({ label, rows, loading, downloadPending, onDownload, onRestore, restorePending = false }: {
  label: string;
  rows: BackupArchive[];
  loading: boolean;
  downloadPending: boolean;
  onDownload: (id: string) => void;
  /** Resolve when the request settles, so the confirmation can close. */
  onRestore?: (id: string, kind: RestoreKind) => Promise<unknown>;
  restorePending?: boolean;
}) {
  const [confirm, setConfirm] = useState<{ id: string; kind: RestoreKind } | null>(null);
  if (!loading && rows.length === 0) {
    return <EmptyState title="No backup archives yet" description="Create an archive and it will appear here when it's ready." />;
  }
  return (
    <>
      <Table label={label}>
        <THead>
          <TR><TH>Archive</TH><TH>Created</TH><TH>Size</TH><TH>Status</TH><TH><span className="sr-only">Actions</span></TH></TR>
        </THead>
        <TBody>
          {loading ? <SkeletonRows rows={2} cols={5} /> : null}
          {rows.map((row) => (
            <TR key={row.id}>
              <TD>
                <span className="font-semibold">{row.scope === "deployment"
                  ? backupFormat(row) === "full" ? "Signed full deployment"
                    : backupFormat(row) === "compound" ? "B1 compound deployment"
                      : backupFormat(row) === "legacy" ? "Historical full deployment" : "Deployment archive"
                  : "Makerspace"}</span>
                {row.failure_detail ? <span className="mt-0.5 block text-caption text-danger-fg">{row.failure_detail}</span> : null}
              </TD>
              <TD className="whitespace-nowrap text-ink-secondary">{formatDate(row.created_at)}</TD>
              <TD className="whitespace-nowrap text-ink-secondary">{formatBytes(row.size_bytes)}</TD>
              <TD><StatusChip tone={statusTones[row.status] ?? "neutral"} size="sm">{statusWords[row.status] ?? row.status}</StatusChip></TD>
              <TD>
                {row.status === "available" ? (
                  <div className="flex flex-wrap justify-end gap-2">
                    <Button size="sm" variant="secondary" disabled={downloadPending} onClick={() => onDownload(row.id)}>Download</Button>
                    {onRestore && ["full", "legacy"].includes(backupFormat(row)) ? (
                      <>
                        <Button size="sm" variant="secondary" onClick={() => setConfirm({ id: row.id, kind: "rollback_in_place" })}>Rollback here…</Button>
                        <Button size="sm" variant="danger" onClick={() => setConfirm({ id: row.id, kind: "disaster" })}>Disaster restore…</Button>
                      </>
                    ) : onRestore ? (
                      <span className="text-caption text-ink-secondary">
                        {backupFormat(row) === "compound"
                          ? "Restore unavailable: this host has no sovereign compound restore coordinator."
                          : "Restore unavailable: unsupported archive format."}
                      </span>
                    ) : null}
                  </div>
                ) : null}
              </TD>
            </TR>
          ))}
        </TBody>
      </Table>
      <ConfirmDialog
        open={confirm !== null}
        tone="danger"
        title={confirm?.kind === "disaster" ? "Record a disaster restore intent?" : "Record a rollback intent?"}
        message={confirm?.kind === "disaster"
          ? "This replaces deployment data from the archive and resets authority. A privileged host operator must run the recorded restore intent."
          : "Live data is rolled back to this archive in place. You'll review an all-table report and decide before anything is committed."}
        confirmLabel={confirm?.kind === "disaster" ? "Record disaster restore intent" : "Record rollback intent"}
        pending={restorePending}
        onConfirm={() => {
          if (!confirm || !onRestore) return;
          void onRestore(confirm.id, confirm.kind).finally(() => setConfirm(null));
        }}
        onCancel={() => setConfirm(null)}
      />
    </>
  );
}

export function formatDate(value?: string | null) {
  return value ? new Date(value).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" }) : "Never";
}

function formatBytes(value: number) {
  return value ? `${(value / 1024 / 1024).toFixed(1)} MB` : "—";
}
