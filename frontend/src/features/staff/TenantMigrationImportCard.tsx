import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { Button, Callout, Card, CheckboxField, Field, Input, Skeleton, StatTile, Textarea, useToast } from "../../components/ui";
import { TenantMigrationConfirm, type MigrationConfirm } from "./TenantMigrationConfirm";
import { TenantMigrationIdentityDecisions } from "./TenantMigrationIdentityDecisions";
import {
  abortTarget,
  activateTarget,
  getImport,
  getVerification,
  runImport,
  tenantMigrationKeys,
  type ImportJob,
  type Pairing,
  type ReceiptEnvelope,
  type VerificationReport,
} from "./tenantMigrationApi";
import { ErrorText, lifecycleWord, migrationError, parseReceipt, ReceiptOutput, StatusPill } from "./tenantMigrationUi";

export function TenantMigrationImportCard({ job: listedJob, pairing }: { job: ImportJob; pairing?: Pairing }) {
  const client = useQueryClient();
  const { showToast } = useToast();
  const [targetName, setTargetName] = useState("");
  const [targetSlug, setTargetSlug] = useState("");
  const [reviewedIdentities, setReviewedIdentities] = useState(false);
  const [sourceReceiptText, setSourceReceiptText] = useState("");
  const [confirm, setConfirm] = useState<MigrationConfirm | null>(null);
  const detail = useQuery({
    queryKey: tenantMigrationKeys.import(listedJob.id),
    queryFn: () => getImport(listedJob.id),
    refetchInterval: (query) => importRunning((query.state.data as ImportJob | undefined) ?? listedJob) ? 1500 : false,
  });
  const job = detail.data ?? listedJob;
  const sourceReceipt = parseReceipt(sourceReceiptText);
  const tenantName = targetName.trim() || job.source_makerspace_name || "imported tenant";
  const verification = useQuery({
    queryKey: tenantMigrationKeys.verification(job.id),
    queryFn: () => getVerification(job.id),
    enabled: job.status === "completed",
    retry: false,
  });
  const failed = (field?: string) => (error: Error) => showToast(migrationError(error, field), { tone: "error" });
  const refreshJob = (next?: ImportJob) => {
    if (next) client.setQueryData(tenantMigrationKeys.import(job.id), next);
    client.invalidateQueries({ queryKey: tenantMigrationKeys.imports });
    client.invalidateQueries({ queryKey: tenantMigrationKeys.import(job.id) });
  };
  const run = useMutation({
    mutationFn: () => runImport(job.id, {
      target_identity: {
        ...(targetName.trim() ? { name: targetName.trim() } : {}),
        ...(targetSlug.trim() ? { slug: targetSlug.trim() } : {}),
      },
    }),
    onSuccess: (next) => { refreshJob(next); showToast("Import started", { tone: "success" }); },
    onError: failed("target_identity"),
  });
  const activate = useMutation({
    mutationFn: (receipt: ReceiptEnvelope) => activateTarget(job.id, pairing!.id, { receipt }),
    onSuccess: async () => {
      await Promise.all([
        client.invalidateQueries({ queryKey: tenantMigrationKeys.imports }),
        client.invalidateQueries({ queryKey: tenantMigrationKeys.import(job.id) }),
        client.invalidateQueries({ queryKey: tenantMigrationKeys.verification(job.id) }),
        client.invalidateQueries({ queryKey: ["staff", "makerspaces"] }),
      ]);
      showToast(`${tenantName} is active`, { tone: "success" });
    },
    onError: failed("receipt"),
  });
  const abort = useMutation({
    mutationFn: () => abortTarget(job.id, pairing!.id),
    onSuccess: async () => {
      await Promise.all([
        client.invalidateQueries({ queryKey: tenantMigrationKeys.imports }),
        client.invalidateQueries({ queryKey: tenantMigrationKeys.import(job.id) }),
        client.invalidateQueries({ queryKey: ["staff", "makerspaces"] }),
      ]);
      showToast(`${tenantName} is aborted`, { tone: "success" });
    },
    onError: failed("receipt"),
  });
  const cutoverPending = activate.isPending || abort.isPending;
  const importFinalizing = job.status === "materializing" || job.status === "finalizing";
  const lifecycle = job.target_lifecycle_state?.toUpperCase()
    ?? (importFinalizing ? "IMPORTING" : (job.status ?? "pending").toUpperCase());
  const tone: "success" | "danger" | "warn" = lifecycle === "ACTIVE" ? "success" : lifecycle === "ABORTED" || job.status === "failed" ? "danger" : "warn";
  const runConfirmed = () => {
    const done = { onSettled: () => setConfirm(null) };
    if (confirm?.kind === "activate") activate.mutate(confirm.receipt, done);
    if (confirm?.kind === "abort") abort.mutate(undefined, done);
  };

  return (
    <Card as="article">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-title text-ink">{job.source_makerspace_name || "Pending archive inspection"}</p>
          <p className="mt-1 font-mono text-xs text-ink-muted">Import {job.id}</p>
        </div>
        <StatusPill tone={tone}>{lifecycleWord(lifecycle)}</StatusPill>
      </div>
      {lifecycle === "IMPORTING" ? <p className="mt-2 text-body-ui text-warning-fg">{importFinalizing ? "Import finalization is still running. The tenant is not active." : "Materialized and verified, but not activated. The tenant is still importing."}</p> : null}
      {lifecycle === "ACTIVE" ? <p className="mt-2 text-body-ui text-success-fg">Target is active. The source cutover receipt was consumed.</p> : null}
      {lifecycle === "ABORTED" ? <p className="mt-2 text-body-ui text-danger-fg">Target is aborted. Transfer its signed abort receipt to recover the archived source.</p> : null}
      {job.failure_detail ? <p className="mt-2 text-caption text-danger-fg" role="alert">{job.failure_detail}</p> : null}
      <ErrorText error={detail.error} />
      <p className="mt-2 text-caption text-ink-muted">{job.source_retention_notice}</p>
      {job.source_deployment_identity && typeof job.source_deployment_identity === "object" ? (
        <div className="mt-3">
          <p className="text-label text-ink">Archived source deployment identity</p>
          <pre className="mt-1 overflow-auto rounded-md bg-subtle p-3 font-mono text-xs text-ink-muted">{JSON.stringify(job.source_deployment_identity, null, 2)}</pre>
        </div>
      ) : null}

      {job.status === "awaiting_identity" || job.status === "ready" ? <TenantMigrationIdentityDecisions job={job} /> : null}
      {job.status === "ready" ? (
        <section className="mt-4 grid gap-4 border-t border-line pt-4" aria-label="Materialize target">
          <h4 className="text-title text-ink">Materialize target</h4>
          <div className="grid gap-4 md:grid-cols-2">
            <Field label="Target tenant name" optional><Input value={targetName} onChange={(event) => setTargetName(event.target.value)} /></Field>
            <Field label="Target tenant slug" optional><Input value={targetSlug} onChange={(event) => setTargetSlug(event.target.value)} /></Field>
          </div>
          <CheckboxField
            checked={reviewedIdentities}
            onCheckedChange={(checked) => setReviewedIdentities(checked === true)}
            label="I reviewed every per-person identity decision shown above or in its prior review record."
          />
          <div>
            <Button variant="primary" disabled={!reviewedIdentities} loading={run.isPending} loadingLabel="Starting materialization…" onClick={() => run.mutate()}>Run reviewed import</Button>
          </div>
          <ErrorText error={run.error} field="target_identity" />
        </section>
      ) : null}

      {job.status === "completed" ? <VerificationReportView report={verification.data} loading={verification.isLoading} error={verification.error} /> : null}
      {job.status === "completed" && pairing && lifecycle === "IMPORTING" ? (
        <section className="mt-4 grid gap-3 rounded-lg border-[1.5px] border-danger-border p-4" aria-label="One-way target cutover">
          <h4 className="text-title text-danger-fg">One-way target cutover</h4>
          <p className="text-body-ui text-ink-secondary">Activation and abort are mutually exclusive. Activation cannot be undone from this screen.</p>
          <Field label="Source cutover receipt">
            <Textarea className="min-h-28 font-mono text-xs" value={sourceReceiptText} onChange={(event) => setSourceReceiptText(event.target.value)} />
          </Field>
          <div className="flex flex-wrap gap-2">
            <Button variant="danger" disabled={!sourceReceipt || !verification.data || cutoverPending} onClick={() => sourceReceipt && setConfirm({ kind: "activate", receipt: sourceReceipt })}>
              Activate target {tenantName}…
            </Button>
            <Button variant="danger" disabled={cutoverPending} onClick={() => setConfirm({ kind: "abort" })}>
              Abort target {tenantName}…
            </Button>
          </div>
        </section>
      ) : null}
      {job.status === "completed" && !pairing ? <Callout className="mt-4" tone="warning">Pin the matching deployment pairing before cutover actions become available.</Callout> : null}
      <ErrorText error={activate.error ?? abort.error} field="receipt" />
      <ReceiptOutput label="Target abort receipt — transfer to source" receipt={abort.data?.receipt} />
      <TenantMigrationConfirm confirm={confirm} tenantName={tenantName} pending={cutoverPending} onConfirm={runConfirmed} onCancel={() => setConfirm(null)} />
    </Card>
  );
}

function VerificationReportView({ report, loading, error }: { report?: VerificationReport; loading: boolean; error: unknown }) {
  return (
    <section className="mt-4 grid gap-3 border-t border-line pt-4" aria-label="Import verification report">
      <h4 className="text-title text-ink">Verification report</h4>
      {loading ? <Skeleton className="h-20 w-full" /> : null}
      <ErrorText error={error} />
      {report ? <>
        <p className="text-body-ui text-ink-secondary">Target makerspace {report.target_makerspace_id} · {report.identities_linked} linked · {report.identities_created} walk-ins · {report.external_references_created} external references</p>
        <div className="grid gap-3 sm:grid-cols-3">
          <StatTile label="Linked accounts" value={report.identities_linked} />
          <StatTile label="Walk-ins created" value={report.identities_created} />
          <StatTile label="External references" value={report.external_references_created} />
        </div>
        <div className="grid gap-2 md:grid-cols-3">
          {(["imported", "resolved", "dropped"] as const).map((key) => (
            <div className="rounded-md bg-subtle p-3" key={key}>
              <p className="text-label text-ink">{key.charAt(0).toUpperCase() + key.slice(1)}</p>
              <pre className="mt-1 overflow-auto font-mono text-xs text-ink-muted">{JSON.stringify(report[key], null, 2)}</pre>
            </div>
          ))}
        </div>
      </> : null}
    </section>
  );
}

function importRunning(job: ImportJob) {
  return job.status === "pending" || job.status === "materializing" || job.status === "finalizing";
}
