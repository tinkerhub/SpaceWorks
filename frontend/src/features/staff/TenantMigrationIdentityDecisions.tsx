import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  listImportIdentities,
  submitIdentityDecisions,
  tenantMigrationKeys,
  type ImportIdentityDecision,
  type ImportJob,
} from "./tenantMigrationApi";
import { Button, Dropdown, Field, Input, Skeleton, useToast } from "../../components/ui";
import { ErrorText, migrationError } from "./tenantMigrationUi";

type DraftDecision = Omit<ImportIdentityDecision, "source_user_id">;

const defaultDecision: DraftDecision = {
  identity_resolution: "create_walk_in",
  membership_disposition: "import_membership",
  target_user_id: null,
};

export function TenantMigrationIdentityDecisions({ job }: { job: ImportJob }) {
  const client = useQueryClient();
  const { showToast } = useToast();
  const [drafts, setDrafts] = useState<Record<string, DraftDecision>>({});
  const identities = useQuery({
    queryKey: tenantMigrationKeys.identities(job.id),
    queryFn: () => listImportIdentities(job.id),
    enabled: job.status === "awaiting_identity" || job.status === "ready",
  });
  const submit = useMutation({
    mutationFn: () => submitIdentityDecisions(job.id, {
      decisions: (identities.data ?? []).map((identity) => ({
        source_user_id: String(identity.id),
        ...(drafts[String(identity.id)] ?? defaultDecision),
      })),
    }),
    onSuccess: (next) => {
      client.setQueryData(tenantMigrationKeys.import(job.id), next);
      client.invalidateQueries({ queryKey: tenantMigrationKeys.imports });
      showToast("Identity decisions submitted", { tone: "success" });
    },
    onError: (error) => showToast(migrationError(error, "decisions"), { tone: "error" }),
  });
  const decisionFor = (id: number) => drafts[String(id)] ?? defaultDecision;
  const choicesAvailable = job.status === "awaiting_identity" || Boolean(submit.data);
  const update = (id: number, patch: Partial<DraftDecision>) => setDrafts((current) => ({
    ...current,
    [String(id)]: { ...decisionFor(id), ...patch },
  }));

  return (
    <section className="mt-4 grid gap-3 border-t border-line pt-4" aria-labelledby={`identity-title-${job.id}`}>
      <h4 className="text-title text-ink" id={`identity-title-${job.id}`}>Per-person identity decisions</h4>
      <p className="text-body-ui text-ink-muted">Review every mapping before starting materialization. Linking preserves an existing target account; walk-in creates a non-login identity for attribution.</p>
      {identities.isLoading ? <Skeleton className="h-16 w-full" /> : null}
      <ErrorText error={identities.error} />
      <div className="grid gap-3">
        {(identities.data ?? []).map((identity) => {
          const decision = decisionFor(identity.id);
          return (
            <article className="rounded-md border border-line p-4" key={identity.id}>
              <p className="text-label text-ink">{identity.display_name || identity.username}</p>
              <p className="break-words text-caption text-ink-muted">{identity.email || "No email"} · {identity.phone || "No phone"} · source user {identity.id}</p>
              {choicesAvailable ? <div className="mt-3 grid gap-3 md:grid-cols-3">
                <Field label="Identity resolution">
                  <Dropdown
                    aria-label={`Identity resolution for ${identity.display_name || identity.username}`}
                    value={decision.identity_resolution}
                    onChange={(event) => update(identity.id, {
                      identity_resolution: event.target.value as DraftDecision["identity_resolution"],
                      target_user_id: event.target.value === "link_existing" ? decision.target_user_id : null,
                    })}
                  >
                    <option value="create_walk_in">Create walk-in</option>
                    <option value="link_existing">Link existing account</option>
                  </Dropdown>
                </Field>
                {decision.identity_resolution === "link_existing" ? (
                  <Field label="Target user ID">
                    <Input
                      aria-label={`Target user ID for ${identity.display_name || identity.username}`}
                      min="1"
                      type="number"
                      value={decision.target_user_id ?? ""}
                      onChange={(event) => update(identity.id, { target_user_id: event.target.value ? Number(event.target.value) : null })}
                    />
                  </Field>
                ) : null}
                <Field label="Membership">
                  <Dropdown
                    aria-label={`Membership for ${identity.display_name || identity.username}`}
                    value={decision.membership_disposition}
                    onChange={(event) => update(identity.id, { membership_disposition: event.target.value as DraftDecision["membership_disposition"] })}
                  >
                    <option value="import_membership">Import membership</option>
                    <option value="no_membership">Do not import membership</option>
                  </Dropdown>
                </Field>
              </div> : null}
            </article>
          );
        })}
      </div>
      {job.status === "awaiting_identity" ? (
        <div>
          <Button
            variant="primary"
            loading={submit.isPending}
            loadingLabel="Submitting decisions…"
            disabled={!identities.data || identities.data.some((identity) => {
              const decision = decisionFor(identity.id);
              return decision.identity_resolution === "link_existing" && !decision.target_user_id;
            })}
            onClick={() => submit.mutate()}
          >
            Submit all identity decisions
          </Button>
        </div>
      ) : submit.data ? <p className="text-body-ui font-semibold text-success-fg" role="status">Identity decisions accepted. Review the choices above before running the import.</p> : (
        <p className="text-body-ui text-warning-fg">Decisions were accepted in an earlier session. The API returns the exact people but not the saved mapping choices; verify the prior review record before running.</p>
      )}
      <ErrorText error={submit.error} field="decisions" />
    </section>
  );
}
