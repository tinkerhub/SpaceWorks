import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { Button, Callout, Card, CardHeader, CheckboxCard, CheckboxField, ConfirmDialog, Skeleton, useToast } from "../../components/ui";
import {
  approveDisclosure,
  getDisclosureClosure,
  listDisclosureApprovals,
  revokeDisclosure,
  tenantMigrationKeys,
} from "./tenantMigrationApi";
import { ErrorText, migrationError, StatusPill } from "./tenantMigrationUi";

export function TenantMigrationDisclosure({ makerspaceId }: { makerspaceId: number }) {
  const client = useQueryClient();
  const { showToast } = useToast();
  const [confirmRevoke, setConfirmRevoke] = useState(false);
  const [review, setReview] = useState<{ digest: string; decisions: Record<number, boolean>; acknowledged: boolean }>({
    digest: "", decisions: {}, acknowledged: false,
  });
  const closure = useQuery({
    queryKey: tenantMigrationKeys.closure(makerspaceId),
    queryFn: () => getDisclosureClosure(makerspaceId),
  });
  const approvals = useQuery({
    queryKey: tenantMigrationKeys.approvals(makerspaceId),
    queryFn: () => listDisclosureApprovals(makerspaceId),
  });
  const refresh = () => client.invalidateQueries({ queryKey: tenantMigrationKeys.approvals(makerspaceId) });
  const approve = useMutation({
    mutationFn: () => approveDisclosure(makerspaceId, {
      digest: closure.data!.digest,
      decisions: closure.data!.identities.map((identity) => ({
        user_id: identity.id,
        approved: decisions[identity.id] ?? false,
      })),
    }),
    onSuccess: () => { refresh(); showToast("Closure approved", { tone: "success" }); },
    onError: (error) => showToast(migrationError(error, "digest"), { tone: "error" }),
  });
  const revoke = useMutation({
    mutationFn: (approvalId: string) => revokeDisclosure(makerspaceId, approvalId),
    onSuccess: () => { refresh(); showToast("Approval revoked", { tone: "success" }); },
    onError: (error) => showToast(migrationError(error), { tone: "error" }),
    onSettled: () => setConfirmRevoke(false),
  });
  const activeApproval = approvals.data?.find(
    (item) => !item.revoked_at && item.closure_digest === closure.data?.digest,
  );
  const voidApprovals = approvals.data?.filter(
    (item) => !item.revoked_at && item.closure_digest !== closure.data?.digest,
  ) ?? [];
  const reviewMatches = review.digest === closure.data?.digest;
  const decisions = reviewMatches ? review.decisions : {};
  const acknowledged = reviewMatches && review.acknowledged;
  const setDecision = (id: number, approved: boolean) => setReview((current) => ({
    digest: closure.data!.digest,
    acknowledged: current.digest === closure.data!.digest && current.acknowledged,
    decisions: { ...(current.digest === closure.data!.digest ? current.decisions : {}), [id]: approved },
  }));

  return (
    <Card as="section" aria-labelledby="migration-disclosure-title">
      <CardHeader
        title={<span id="migration-disclosure-title">Disclosure closure review</span>}
        description="Safety gate: the selected people's email, name and phone travel to the target deployment."
        action={activeApproval ? <StatusPill tone="success">Approved</StatusPill> : <StatusPill tone="warn">Review required</StatusPill>}
      />
      <p className="text-body-ui text-ink-secondary">
        Review every identity and decide whether it may travel in this exact export closure.
      </p>

      {closure.isLoading || approvals.isLoading ? <Skeleton className="mt-4 h-24 w-full" /> : null}
      <ErrorText error={closure.error ?? approvals.error} />
      {voidApprovals.map((approval) => (
        <Callout className="mt-4" tone="danger" role="status" key={approval.id} title="Void — disclosure closure changed after approval">
          Previously approved digest: <span className="break-all font-mono">{approval.closure_digest}</span>
        </Callout>
      ))}

      {closure.data ? (
        <div className="mt-4 grid gap-4">
          <div>
            <p className="text-label text-ink-secondary">Exact closure digest</p>
            <p className="mt-1 break-all font-mono text-xs text-ink" data-testid="closure-digest">{closure.data.digest}</p>
          </div>
          <div className="grid gap-2">
            {closure.data.identities.length === 0 ? <p className="text-body-ui text-ink-muted">This closure contains no identities.</p> : null}
            {closure.data.identities.map((identity) => (
              <CheckboxCard
                key={identity.id}
                checked={decisions[identity.id] ?? false}
                disabled={Boolean(activeApproval)}
                onCheckedChange={(checked) => setDecision(identity.id, checked === true)}
                label={identity.display_name || identity.username}
                description={(
                  <>
                    <span className="block break-words">{identity.email || "No email"} · {identity.phone || "No phone"}</span>
                    <span className="block">{identity.first_name} {identity.last_name} · @{identity.username} · user {identity.id}</span>
                    <span className="block">Joined {new Date(identity.date_joined).toLocaleString()}</span>
                    <span className="mt-1 block font-semibold text-ink">{decisions[identity.id] ? "Disclose this identity" : "Withhold this identity"}</span>
                  </>
                )}
              />
            ))}
          </div>
          {activeApproval ? (
            <div className="flex flex-wrap items-center gap-3">
              <p className="text-body-ui text-success-fg">{activeApproval.approved_count} of {activeApproval.identity_count} identities approved for this digest.</p>
              <Button variant="danger" size="sm" disabled={revoke.isPending} onClick={() => setConfirmRevoke(true)}>Revoke approval…</Button>
            </div>
          ) : (
            <div className="grid gap-3">
              <CheckboxField
                checked={acknowledged}
                onCheckedChange={(checked) => setReview((current) => ({
                  digest: closure.data!.digest,
                  acknowledged: checked === true,
                  decisions: current.digest === closure.data!.digest ? current.decisions : {},
                }))}
                label="I reviewed every person and understand the approved fields leave this deployment."
              />
              <div>
                <Button variant="primary" disabled={!acknowledged} loading={approve.isPending} loadingLabel="Approving exact closure…" onClick={() => approve.mutate()}>
                  Approve exact closure
                </Button>
              </div>
            </div>
          )}
          <ErrorText error={approve.error} field="digest" />
          <ErrorText error={revoke.error} />
        </div>
      ) : null}
      <ConfirmDialog
        open={confirmRevoke && Boolean(activeApproval)}
        tone="danger"
        title="Revoke this approval?"
        message="Exports can't use this closure until the people in it are reviewed and approved again."
        confirmLabel="Revoke approval"
        pending={revoke.isPending}
        onConfirm={() => activeApproval && revoke.mutate(activeApproval.id)}
        onCancel={() => setConfirmRevoke(false)}
      />
    </Card>
  );
}
