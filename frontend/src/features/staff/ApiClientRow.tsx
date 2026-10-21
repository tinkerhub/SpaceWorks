import { useEffect, useMemo, useState } from "react";

import { Button, Callout, Card, Chip, Skeleton, StatusChip } from "../../components/ui";
import { ApiClientScopePicker } from "./ApiClientScopePicker";
import { scopeOptionsForClient, type ApiClient, type ApiClientScopeOption } from "./apiClientsApi";

/** One API client: identity and status, its scopes (editable), and rotate/delete. */
export function ApiClientRow({ client, scopeOptions, scopesLoading, updatePending, deletePending, rotatePending, onDelete, onRotate, onScopesUpdate }: {
  client: ApiClient;
  scopeOptions: ApiClientScopeOption[];
  scopesLoading: boolean;
  updatePending: boolean;
  deletePending: boolean;
  rotatePending: boolean;
  onDelete: () => void;
  onRotate: () => void;
  onScopesUpdate: (clientId: number, scopes: string[]) => void;
}) {
  const [selected, setSelected] = useState<string[]>(client.scopes);
  useEffect(() => setSelected(client.scopes), [client.scopes]);
  const clientScopeOptions = useMemo(
    () => scopeOptionsForClient(scopeOptions, client.client_type),
    [client.client_type, scopeOptions],
  );
  const grantable = useMemo(
    () => selected.filter((scope) => clientScopeOptions.some((option) => option.value === scope && option.grantable)),
    [clientScopeOptions, selected],
  );
  const hasLegacy = client.scopes.includes("legacy:v1");
  const changed = grantable.join("\0") !== client.scopes.join("\0");

  return (
    <Card as="article" padding="none" className="divide-y divide-line">
      <div className="flex flex-col gap-3 p-5 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="text-title text-ink">{client.label}</h3>
            <StatusChip tone={client.is_active ? "success" : "warning"} size="sm">{client.is_active ? "Active" : "Inactive"}</StatusChip>
            <Chip tone="outline" size="sm">{client.client_type === "browser" ? "Browser" : "Server"}</Chip>
          </div>
          <p className="mt-1 break-all font-mono text-sm text-ink-secondary">{client.client_id}</p>
          <p className="mt-1 text-caption text-ink-muted">
            Created {formatDate(client.created_at)} · {client.last_seen_at ? `last used ${formatDate(client.last_seen_at)}` : "never used"}
          </p>
        </div>
        <div className="flex shrink-0 flex-wrap gap-2">
          <Button variant="secondary" size="sm" disabled={rotatePending} onClick={onRotate}>Rotate secret…</Button>
          <Button variant="danger" size="sm" disabled={deletePending} onClick={onDelete}>Delete…</Button>
        </div>
      </div>
      <div className="grid gap-1 p-5 text-body-ui">
        <p className="text-label text-ink">Browser origins</p>
        <p className="break-all text-ink-secondary">
          {client.allowed_origins.length ? client.allowed_origins.join(", ") : "No browser origins configured."}
        </p>
        <p className="mt-2 text-caption text-ink-muted">Current scopes: {client.scopes.join(", ")}</p>
      </div>
      <div className="grid gap-4 p-5">
        {hasLegacy ? (
          <Callout tone="warning">
            Legacy v1 access preserves the frozen cutover capability. Select explicit replacement scopes and save; viewing this client never changes it.
          </Callout>
        ) : null}
        {scopesLoading ? <Skeleton className="h-24 w-full" /> : null}
        {!scopesLoading && clientScopeOptions.length ? (
          <ApiClientScopePicker options={clientScopeOptions} selected={selected} onChange={setSelected} disabled={updatePending} />
        ) : null}
        <div>
          <Button
            variant="secondary"
            size="sm"
            disabled={updatePending || !grantable.length || !changed}
            loading={updatePending}
            loadingLabel="Saving…"
            onClick={() => onScopesUpdate(client.id, grantable)}
          >
            Save scopes
          </Button>
        </div>
      </div>
    </Card>
  );
}

export function formatDate(value: string) {
  return new Date(value).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}
