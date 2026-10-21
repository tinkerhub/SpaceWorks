import { useState } from "react";
import type { Query } from "@tanstack/react-query";
import { useMutation, useQueries, useQuery, useQueryClient } from "@tanstack/react-query";

import { Button, Card, CardHeader, Dropdown, EmptyState, Field, Input, Skeleton, useToast } from "../../components/ui";
import { TenantMigrationExportCard } from "./TenantMigrationExportCard";
import {
  archiveSource,
  createMigrationExport,
  getMigrationExport,
  issueMigrationDownload,
  listDisclosureApprovals,
  listMigrationExports,
  quiesceSource,
  recoverSource,
  tenantMigrationKeys,
  type MigrationExportJob,
  type Pairing,
  type ReceiptEnvelope,
} from "./tenantMigrationApi";
import { ErrorText, migrationError, openDownload, ReceiptOutput } from "./tenantMigrationUi";
import { TenantMigrationConfirm, type MigrationConfirm } from "./TenantMigrationConfirm";

export function TenantMigrationExports({
  makerspaceId,
  tenantName,
  closureDigest,
  pairings,
}: {
  makerspaceId: number;
  tenantName: string;
  closureDigest?: string;
  pairings: Pairing[];
}) {
  const client = useQueryClient();
  const { showToast } = useToast();
  const [approvalId, setApprovalId] = useState("");
  const [recipient, setRecipient] = useState("");
  const [abortReceipts, setAbortReceipts] = useState<Record<string, string>>({});
  const [confirm, setConfirm] = useState<MigrationConfirm | null>(null);
  const failed = (field?: string) => (error: Error) => showToast(migrationError(error, field), { tone: "error" });
  const approvals = useQuery({
    queryKey: tenantMigrationKeys.approvals(makerspaceId),
    queryFn: () => listDisclosureApprovals(makerspaceId),
  });
  const exportsQuery = useQuery({
    queryKey: tenantMigrationKeys.exports(makerspaceId),
    queryFn: () => listMigrationExports(makerspaceId),
  });
  const exportDetails = useQueries({
    queries: (exportsQuery.data ?? []).map((job) => ({
      queryKey: tenantMigrationKeys.export(makerspaceId, job.id),
      queryFn: () => getMigrationExport(makerspaceId, job.id),
      // `useQueries` with a computed array loses per-entry inference in Query v5,
      // so the callback argument is annotated rather than left implicitly `any`.
      refetchInterval: (query: Query) => exportRunning((query.state.data as MigrationExportJob | undefined) ?? job) ? 1500 : false,
    })),
  });
  const validApprovals = approvals.data?.filter(
    (item) => !item.revoked_at && item.closure_digest === closureDigest,
  ) ?? [];
  const selectedApproval = approvalId || validApprovals[0]?.id || "";
  const createExport = useMutation({
    mutationFn: () => createMigrationExport(makerspaceId, {
      approval_id: selectedApproval,
      target_age_recipient: recipient.trim(),
    }),
    onSuccess: () => {
      client.invalidateQueries({ queryKey: tenantMigrationKeys.exports(makerspaceId) });
      showToast("Encrypted export requested", { tone: "success" });
    },
    onError: failed("target_age_recipient"),
  });
  const download = useMutation({
    mutationFn: (jobId: string) => issueMigrationDownload(makerspaceId, jobId),
    onSuccess: ({ url }) => { showToast("Download starting", { tone: "info" }); openDownload(url); },
    onError: failed(),
  });
  const quiesce = useMutation({
    mutationFn: (jobId: string) => quiesceSource(makerspaceId, jobId),
    onSuccess: (_data, jobId) => {
      client.invalidateQueries({ queryKey: tenantMigrationKeys.exports(makerspaceId) });
      client.invalidateQueries({ queryKey: tenantMigrationKeys.export(makerspaceId, jobId) });
      showToast(`${tenantName} is quiesced`, { tone: "success" });
    },
    onError: failed(),
  });
  const archive = useMutation({
    mutationFn: (pairingId: string) => archiveSource(makerspaceId, pairingId),
    onSuccess: () => {
      client.invalidateQueries({ queryKey: ["staff", "makerspaces"] });
      showToast(`${tenantName} is archived`, { tone: "success" });
    },
    onError: failed("receipt"),
  });
  const recover = useMutation({
    mutationFn: ({ pairingId, receipt }: { pairingId: string; receipt: ReceiptEnvelope }) =>
      recoverSource(makerspaceId, pairingId, { receipt }),
    onSuccess: () => {
      client.invalidateQueries({ queryKey: ["staff", "makerspaces"] });
      showToast(`${tenantName} is recovered`, { tone: "success" });
    },
    onError: failed("receipt"),
  });

  const runConfirmed = () => {
    if (!confirm) return;
    const done = { onSettled: () => setConfirm(null) };
    if (confirm.kind === "quiesce") quiesce.mutate(confirm.jobId, done);
    if (confirm.kind === "archive") archive.mutate(confirm.pairingId, done);
    if (confirm.kind === "recover") recover.mutate({ pairingId: confirm.pairingId, receipt: confirm.receipt }, done);
  };
  const jobs = exportsQuery.data ?? [];

  return (
    <Card as="section" aria-labelledby="migration-export-title">
      <CardHeader
        title={<span id="migration-export-title">Encrypted migration exports</span>}
        description={`Source deployment. Quiescing freezes writes to ${tenantName}; archiving the source is a one-way cutover.`}
      />
      <p className="text-body-ui text-ink-secondary">
        The target age recipient encrypts the portable archive for one target deployment. The source tenant is archived, not deleted, at cutover; archives are outside the purge guarantee.
      </p>

      <div className="mt-5 grid gap-4 md:grid-cols-2">
        <Field label="Approved closure">
          <Dropdown value={selectedApproval} onChange={(event) => setApprovalId(event.target.value)}>
            {validApprovals.length === 0 ? <option value="">Approve the current closure first</option> : null}
            {validApprovals.map((approval) => <option key={approval.id} value={approval.id}>{approval.approved_count}/{approval.identity_count} disclosed · {approval.id}</option>)}
          </Dropdown>
        </Field>
        <Field label="Target age recipient">
          <Input className="font-mono" value={recipient} onChange={(event) => setRecipient(event.target.value)} placeholder="age1…" />
        </Field>
      </div>
      <Button
        className="mt-4"
        variant="primary"
        disabled={!selectedApproval || !recipient.trim()}
        loading={createExport.isPending}
        loadingLabel="Requesting encrypted export…"
        onClick={() => createExport.mutate()}
      >
        Create encrypted migration export
      </Button>
      <ErrorText error={createExport.error} field="target_age_recipient" />

      <div className="mt-6 grid gap-3">
        {exportsQuery.isLoading ? <Skeleton className="h-24 w-full" /> : null}
        <ErrorText error={exportsQuery.error} />
        {!exportsQuery.isLoading && !exportsQuery.error && jobs.length === 0 ? (
          <EmptyState title="No migration exports yet" description="Approve the closure, add the target's age recipient, then create an export." />
        ) : null}
        {jobs.map((listedJob, index) => {
          const job = exportDetails[index]?.data ?? listedJob;
          const pairing = pairings.find((item) => item.archive_digest === job.archive_digest);
          return (
            <TenantMigrationExportCard
              key={job.id}
              job={job}
              detailError={exportDetails[index]?.error}
              pairing={pairing}
              tenantName={tenantName}
              quiesced={quiesce.isSuccess && quiesce.variables === job.id}
              abortReceiptText={pairing ? abortReceipts[pairing.id] ?? "" : ""}
              onAbortReceiptChange={(pairingId, value) => setAbortReceipts((current) => ({ ...current, [pairingId]: value }))}
              downloadPending={download.isPending}
              quiescePending={quiesce.isPending}
              archivePending={archive.isPending}
              recoverPending={recover.isPending}
              onDownload={() => download.mutate(job.id)}
              onConfirm={setConfirm}
            />
          );
        })}
      </div>
      <ErrorText error={download.error ?? quiesce.error ?? archive.error ?? recover.error} field="receipt" />
      <ReceiptOutput label="Source cutover receipt — transfer to target" receipt={archive.data?.receipt} />
      {recover.data ? <p className="mt-3 text-body-ui text-success-fg" role="status">{recover.data.message}</p> : null}
      <TenantMigrationConfirm
        confirm={confirm}
        tenantName={tenantName}
        pending={quiesce.isPending || archive.isPending || recover.isPending}
        onConfirm={runConfirmed}
        onCancel={() => setConfirm(null)}
      />
    </Card>
  );
}

function exportRunning(job: MigrationExportJob) {
  return job.status === "pending" || job.status === "running";
}
