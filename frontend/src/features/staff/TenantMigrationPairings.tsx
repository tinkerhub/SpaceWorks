import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  createPairing,
  getDeploymentIdentity,
  tenantMigrationKeys,
  type DeploymentIdentity,
  type Pairing,
} from "./tenantMigrationApi";
import { Button, Card, CardHeader, EmptyState, ErrorText as Alert, Field, Input, Skeleton, Table, TBody, TD, TH, THead, TR, Textarea, useToast } from "../../components/ui";
import { ErrorText, migrationError } from "./tenantMigrationUi";

export function TenantMigrationPairings({ pairings }: { pairings: Pairing[] }) {
  const client = useQueryClient();
  const { showToast } = useToast();
  const [migrationId, setMigrationId] = useState("");
  const [sourceTenantId, setSourceTenantId] = useState("");
  const [archiveDigest, setArchiveDigest] = useState("");
  const [sourceText, setSourceText] = useState("");
  const [targetText, setTargetText] = useState("");
  const [localError, setLocalError] = useState("");
  const identity = useQuery({
    queryKey: tenantMigrationKeys.deploymentIdentity,
    queryFn: getDeploymentIdentity,
  });
  const localPairingIdentity = identity.data ? pairingIdentity(identity.data) : null;
  const effectiveTarget = targetText || (localPairingIdentity ? JSON.stringify(localPairingIdentity, null, 2) : "");
  const create = useMutation({
    mutationFn: (payload: Parameters<typeof createPairing>[0]) => createPairing(payload),
    onSuccess: () => {
      client.invalidateQueries({ queryKey: tenantMigrationKeys.pairings });
      showToast("Deployment pairing pinned", { tone: "success" });
    },
    onError: (error) => showToast(migrationError(error, "source"), { tone: "error" }),
  });

  const submit = () => {
    try {
      const source = JSON.parse(sourceText) as Record<string, unknown>;
      const target = JSON.parse(effectiveTarget) as Record<string, unknown>;
      setLocalError("");
      create.mutate({
        migration_id: migrationId.trim(),
        source_tenant_id: sourceTenantId.trim(),
        archive_digest: archiveDigest.trim(),
        source,
        target,
      });
    } catch {
      setLocalError("Source and target deployment identities must be valid JSON objects.");
    }
  };

  const blocked = !migrationId.trim() || !sourceTenantId.trim() || !archiveDigest.trim() || !sourceText.trim() || !effectiveTarget.trim();
  return (
    <Card as="section" aria-labelledby="migration-pairing-title">
      <CardHeader
        title={<span id="migration-pairing-title">Pin source and target identities</span>}
        description="Two-deployment protocol: a receipt from an identity outside this pinned pair is refused."
      />
      <p className="text-body-ui text-ink-secondary">
        Compare fingerprints out of band before pinning. Create the same pairing on both deployments.
      </p>
      {identity.isLoading ? <Skeleton className="mt-4 h-32 w-full" /> : null}
      <ErrorText error={identity.error} />
      {identity.data ? (
        <div className="mt-4 grid gap-3 rounded-lg bg-subtle p-4">
          <div className="min-w-0">
            <p className="text-label text-ink">This deployment: {identity.data.deployment_id}</p>
            <p className="mt-1 break-all font-mono text-xs text-ink-muted">Fingerprint: {identity.data.fingerprint}</p>
            <p className="mt-1 break-all font-mono text-xs text-ink-muted">Age recipient: {identity.data.age_recipient}</p>
          </div>
          <Field label="This deployment identity JSON">
            <Textarea readOnly className="min-h-32 font-mono text-xs" value={JSON.stringify(localPairingIdentity, null, 2)} />
          </Field>
          <div>
            <Button size="sm" variant="secondary" onClick={() => setSourceText(JSON.stringify(localPairingIdentity, null, 2))}>Use this deployment as source</Button>
          </div>
        </div>
      ) : null}

      <div className="mt-5 grid gap-4 md:grid-cols-3">
        <Field label="Migration/import job ID"><Input className="font-mono" value={migrationId} onChange={(event) => setMigrationId(event.target.value)} /></Field>
        <Field label="Source tenant ID"><Input className="font-mono" value={sourceTenantId} onChange={(event) => setSourceTenantId(event.target.value)} /></Field>
        <Field label="Archive digest"><Input className="font-mono" value={archiveDigest} onChange={(event) => setArchiveDigest(event.target.value)} /></Field>
      </div>
      <div className="mt-4 grid gap-4 md:grid-cols-2">
        <Field label="Source deployment identity JSON"><Textarea className="min-h-40 font-mono text-xs" value={sourceText} onChange={(event) => setSourceText(event.target.value)} /></Field>
        <Field label="Target deployment identity JSON"><Textarea className="min-h-40 font-mono text-xs" value={effectiveTarget} onChange={(event) => setTargetText(event.target.value)} /></Field>
      </div>
      <Button className="mt-4" variant="primary" disabled={blocked} loading={create.isPending} loadingLabel="Pinning identities…" onClick={submit}>
        Pin this deployment pairing
      </Button>
      <div className="mt-2"><Alert message={localError} /></div>
      <ErrorText error={create.error} field="source" />

      <div className="mt-6">
        {pairings.length === 0 ? (
          <EmptyState title="No pairings pinned yet" description="No migration pairings are pinned on this deployment. Pin one above on both deployments." />
        ) : (
          <Table label="Pinned deployment pairings">
            <THead><TR><TH>Pairing</TH><TH>Migration</TH><TH>Fingerprints</TH></TR></THead>
            <TBody>
              {pairings.map((pairing) => (
                <TR key={pairing.id}>
                  <TD className="font-mono text-xs">{pairing.id}</TD>
                  <TD className="text-caption"><span className="block break-all font-mono">{pairing.migration_id}</span><span className="block break-all text-ink-muted">archive {pairing.archive_digest}</span></TD>
                  <TD className="break-all font-mono text-xs text-ink-muted">{pairing.source_fingerprint} → {pairing.target_fingerprint}</TD>
                </TR>
              ))}
            </TBody>
          </Table>
        )}
      </div>
    </Card>
  );
}

function pairingIdentity(identity: DeploymentIdentity) {
  const { algorithm, deployment_id, public_key, fingerprint } = identity;
  return { algorithm, deployment_id, public_key, fingerprint };
}
