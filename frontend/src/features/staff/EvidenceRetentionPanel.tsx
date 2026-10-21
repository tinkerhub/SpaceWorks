import { useEffect, useState, type FormEvent } from "react";

import { Button, Callout, Card, CardHeader, EmptyState, Field, Input, Skeleton, useToast } from "../../components/ui";
import { StructuredApiError } from "../../lib/api";
import {
  useEvidenceRetentionPolicy,
  useEvidenceRetentionPreview,
  useUpdateEvidenceRetention,
} from "./evidenceRetentionApi";


const bytes = (value: number) => new Intl.NumberFormat(undefined, {
  style: "unit",
  unit: "megabyte",
  maximumFractionDigits: 1,
}).format(value / 1_048_576);

const errorText = (error: unknown) =>
  error instanceof StructuredApiError
    ? error.detail ?? error.message
    : "Unable to load evidence retention settings.";

/** Embedded settings card: how long evidence photo bytes are kept before they expire. */
export function EvidenceRetentionPanel({ makerspaceId }: { makerspaceId: number }) {
  const { showToast } = useToast();
  const policy = useEvidenceRetentionPolicy(makerspaceId);
  const update = useUpdateEvidenceRetention(makerspaceId);
  const effectiveDays = policy.data?.effective_days ?? 0;
  const preview = useEvidenceRetentionPreview(makerspaceId, effectiveDays, Boolean(policy.data));
  const [days, setDays] = useState("");

  useEffect(() => {
    if (policy.data) setDays(String(policy.data.effective_days));
  }, [policy.data?.effective_days]);

  const save = (value: number | null) => update.mutate(value, {
    onSuccess: () => showToast(value === null ? "Using the platform default" : "Retention saved", { tone: "success" }),
    onError: (error) => showToast(errorText(error), { tone: "error" }),
  });
  const submit = (event: FormEvent) => {
    event.preventDefault();
    save(Number(days));
  };

  if (policy.isLoading) return <Skeleton className="mb-5 h-40 w-full" />;
  if (policy.error) return (
    <EmptyState
      tone="error"
      className="mb-5"
      title="Unable to load evidence retention"
      description={errorText(policy.error)}
      action={<Button variant="secondary" onClick={() => policy.refetch()}>Retry</Button>}
    />
  );
  if (!policy.data) return null;

  return (
    <Card as="section" className="mb-5" aria-labelledby="evidence-retention-title">
      <CardHeader
        title={<span id="evidence-retention-title">Evidence photo retention</span>}
        description="Photo metadata and audit history remain immutable. Stored image bytes expire after the effective window."
      />
      <div className="grid gap-4">
        <div role="note">
          <Callout tone="warning">
            Expiry is irreversible in live storage; older backups may still contain historical photos.
          </Callout>
        </div>
        <form className="flex flex-wrap items-end gap-3" onSubmit={submit}>
          <Field label="Retention days" helperText="Between 30 and 3650 days." className="w-44">
            <Input type="number" min="30" max="3650" value={days} onChange={(event) => setDays(event.target.value)} required />
          </Field>
          <div className="flex flex-wrap gap-2 pb-6">
            <Button type="submit" variant="primary" loading={update.isPending && update.variables !== null} loadingLabel="Saving…" disabled={update.isPending}>
              Save override
            </Button>
            <Button variant="secondary" disabled={update.isPending || policy.data.override_days === null} onClick={() => save(null)}>
              Use platform default
            </Button>
          </div>
        </form>
        <p className="text-caption text-ink-muted">
          {policy.data.override_days === null
            ? `Inherited platform default: ${policy.data.platform_default_days} days.`
            : `Tenant override: ${policy.data.override_days} days (platform default ${policy.data.platform_default_days}).`}
          {` Automatic expiry is ${policy.data.object_expiry_enabled ? "enabled" : "disabled"}.`}
        </p>
        {update.error ? <p className="text-caption text-danger-fg" role="alert">{errorText(update.error)}</p> : null}
        <div className="rounded-md bg-subtle p-3 text-body-ui text-ink">
          {preview.isLoading ? <span className="text-ink-muted">Calculating preview…</span> : null}
          {preview.error ? <span className="text-danger-fg">{errorText(preview.error)}</span> : null}
          {preview.data ? (
            <p>
              <span className="font-semibold">Preview:</span>{` ${preview.data.object_candidates} photo objects (${bytes(preview.data.candidate_bytes)}) are eligible as of ${new Date(preview.data.as_of).toLocaleString()}.`}
              {preview.data.has_more ? " The first sweep will continue in bounded batches." : ""}
            </p>
          ) : null}
        </div>
      </div>
    </Card>
  );
}
