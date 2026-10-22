import { useState } from "react";

import { Button, Card, CardHeader, Chip, ConfirmDialog } from "../../components/ui";
import type { RestoreOperation } from "./backupApi";

type Decision = "proceed" | "reset" | "abort";

/** The quiesced restore's all-table report and the time-boxed decision. */
export function BackupRestoreDecision({ operation, pending, onDecide }: {
  operation: RestoreOperation;
  pending: boolean;
  /** Resolve when the request settles, so the confirmation can close. */
  onDecide: (value: Decision) => Promise<unknown>;
}) {
  const [confirm, setConfirm] = useState<"reset" | "abort" | null>(null);
  const waiting = operation.stage === "quiesced" && operation.decision === "pending" && operation.decision_deadline_at;
  const seconds = waiting ? Math.max(0, Math.ceil((new Date(operation.decision_deadline_at!).getTime() - Date.now()) / 1000)) : 0;
  const stage = operation.stage.replace(/_/g, " ");

  return (
    <Card as="section" className="border-[1.5px] border-danger-border">
      <CardHeader
        title={`Restore ${stage}`}
        titleAs="h3"
        description={`${operation.restore_diff.tables_compared ?? 0} tables compared; ${operation.restore_diff.tables_changed ?? 0} differ.`}
        action={waiting ? <Chip tone="warning">Decide within {seconds}s</Chip> : null}
      />
      <div className="grid max-h-72 gap-2 overflow-auto">
        {operation.restore_diff.tables?.map((table) => (
          <details key={table.table} className="rounded-md border border-line bg-subtle p-3">
            <summary className="cursor-pointer text-body-ui text-ink">
              <span className="font-mono">{table.table}</span> · {table.live.row_count} live / {table.archive.row_count} archived
              {table.security_relevant ? " · security-relevant" : ""}{table.noisy ? " · noisy" : ""}
            </summary>
            {table.row_diff ? <pre className="mt-2 overflow-auto font-mono text-xs text-ink-muted">{JSON.stringify(table.row_diff, null, 2)}</pre> : null}
          </details>
        ))}
      </div>
      {waiting ? (
        <div className="mt-4 grid gap-3">
          <p className="text-body-ui text-ink-secondary">
            Proceed only after reviewing the all-table report. &ldquo;Reset authority&rdquo; quarantines every principal and invalidates restored credentials.
          </p>
          <div className="flex flex-wrap gap-2">
            <Button variant="primary" disabled={pending} onClick={() => void onDecide("proceed")}>Proceed</Button>
            <Button variant="secondary" disabled={pending} onClick={() => setConfirm("reset")}>Proceed and reset authority…</Button>
            <Button variant="danger" disabled={pending} onClick={() => setConfirm("abort")}>Abort safely…</Button>
          </div>
        </div>
      ) : null}
      <ConfirmDialog
        open={confirm !== null}
        tone="danger"
        title={confirm === "abort" ? "Abort this restore?" : "Proceed and reset authority?"}
        message={confirm === "abort"
          ? "The restore stops and live data stays as it is."
          : "The restore is committed, every principal is quarantined and restored credentials stop working."}
        confirmLabel={confirm === "abort" ? "Abort restore" : "Proceed and reset"}
        pending={pending}
        onConfirm={() => {
          if (confirm) void onDecide(confirm).finally(() => setConfirm(null));
        }}
        onCancel={() => setConfirm(null)}
      />
    </Card>
  );
}
