import { useState } from "react";

import {
  Card,
  CardHeader,
  ConfirmDialog,
  EmptyState,
  ErrorBlock,
  SectionHeading,
  Skeleton,
  SkeletonRows,
  StatusChip,
  Table,
  TBody,
  TD,
  TH,
  THead,
  TR,
} from "../../components/ui";
import { ApiClientRow, formatDate } from "./ApiClientRow";
import type { ApiClient, ApiClientScopeOption, ApiKeyRequest } from "./apiClientsApi";

type Props = {
  canManageMakerspace: boolean;
  clients: ApiClient[] | undefined;
  clientsLoading: boolean;
  clientsError: Error | null;
  requests: ApiKeyRequest[] | undefined;
  requestsLoading?: boolean;
  deletePending: boolean;
  deleteError: Error | null;
  rotatePending: boolean;
  rotateError: Error | null;
  scopeOptions: ApiClientScopeOption[];
  scopesLoading: boolean;
  scopesError: Error | null;
  scopeUpdatePending: boolean;
  scopeUpdateError: Error | null;
  /** Resolve when the request settles, so the confirmation can close. */
  onDelete: (clientId: number) => Promise<unknown> | void;
  onRotate: (clientId: number) => Promise<unknown> | void;
  onScopesUpdate: (clientId: number, scopes: string[]) => void;
};

type PendingAction = { kind: "rotate" | "delete"; client: ApiClient };

export function ApiClientListCard(props: Props) {
  const { canManageMakerspace, clients, clientsLoading, clientsError, requests, requestsLoading = false } = props;
  const [confirm, setConfirm] = useState<PendingAction | null>(null);

  if (!canManageMakerspace) {
    return (
      <Card as="section">
        <CardHeader title="Your requests" description="Requests you've sent for API access and what was decided." />
        {!requestsLoading && requests?.length === 0 ? (
          <EmptyState title="No API access requests yet" description="Fill in the request form to ask a superadmin for a key." />
        ) : (
          <Table label="API access requests">
            <THead><TR><TH>Request</TH><TH>Sent</TH><TH>Status</TH></TR></THead>
            <TBody>
              {requestsLoading ? <SkeletonRows rows={2} cols={3} /> : null}
              {requests?.map((request) => (
                <TR key={request.id}>
                  <TD>
                    <span className="font-semibold">{request.label}</span>
                    {request.resolution_note ? <span className="block text-caption text-ink-muted">{request.resolution_note}</span> : null}
                  </TD>
                  <TD className="whitespace-nowrap text-ink-secondary">{formatDate(request.created_at)}</TD>
                  <TD><StatusChip tone={requestTone(request.status)} size="sm">{sentence(request.status)}</StatusChip></TD>
                </TR>
              ))}
            </TBody>
          </Table>
        )}
      </Card>
    );
  }

  const pending = confirm?.kind === "delete" ? props.deletePending : props.rotatePending;
  const runConfirmed = () => {
    if (!confirm) return;
    const action = confirm.kind === "delete" ? props.onDelete : props.onRotate;
    void Promise.resolve(action(confirm.client.id)).finally(() => setConfirm(null));
  };

  return (
    <section className="grid gap-4" aria-labelledby="api-clients-title">
      <SectionHeading title={<span id="api-clients-title">Clients</span>} description="Every client that can call this makerspace's API." />
      {clientsLoading ? <Skeleton className="h-40 w-full" /> : null}
      {!clientsLoading && clients?.length === 0 ? (
        <EmptyState title="No API clients yet" description="Create a client above to give another system scoped access." />
      ) : null}
      {clients?.map((client) => (
        <ApiClientRow
          key={client.id}
          client={client}
          scopeOptions={props.scopeOptions}
          scopesLoading={props.scopesLoading}
          updatePending={props.scopeUpdatePending}
          deletePending={props.deletePending}
          rotatePending={props.rotatePending}
          onDelete={() => setConfirm({ kind: "delete", client })}
          onRotate={() => setConfirm({ kind: "rotate", client })}
          onScopesUpdate={props.onScopesUpdate}
        />
      ))}
      <ErrorBlock error={clientsError} />
      <ErrorBlock error={props.scopesError} />
      <ErrorBlock error={props.scopeUpdateError} />
      <ErrorBlock error={props.deleteError} />
      <ErrorBlock error={props.rotateError} />
      <ConfirmDialog
        open={confirm !== null}
        tone="danger"
        title={confirm?.kind === "delete" ? `Delete ${confirm.client.label}?` : `Rotate the secret for ${confirm?.client.label ?? "this client"}?`}
        message={confirm?.kind === "delete"
          ? "The client stops working at once and can't be restored."
          : "The current secret stops working at once. The new one is shown a single time."}
        confirmLabel={confirm?.kind === "delete" ? "Delete client" : "Rotate secret"}
        pending={pending}
        onConfirm={runConfirmed}
        onCancel={() => setConfirm(null)}
      />
    </section>
  );
}

function requestTone(status: ApiKeyRequest["status"]) {
  if (status === "approved") return "success" as const;
  if (status === "rejected") return "danger" as const;
  if (status === "pending") return "warning" as const;
  return "neutral" as const;
}

function sentence(value: string) {
  const words = value.replace(/_/g, " ");
  return words.charAt(0).toUpperCase() + words.slice(1);
}
