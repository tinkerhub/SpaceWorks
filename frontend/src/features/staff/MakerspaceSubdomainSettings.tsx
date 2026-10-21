import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { Button, Card, CardHeader, ErrorText, Field, Input, SettingsRow, Skeleton, StatusChip, useToast } from "../../components/ui";
import { staffRequest } from "../../lib/api";
import { errorText, type Makerspace, useStaffGet } from "./panels/shared";

type Props = {
  makerspace: Makerspace;
  settings?: Makerspace;
};

type SubdomainRequest = {
  id: number;
  requested_label: string;
  status: "pending" | "approved" | "rejected";
  note: string;
  created_at: string;
};

type SubdomainRequestResponse = { results: SubdomainRequest[] };

export function MakerspaceSubdomainSettings({ makerspace, settings }: Props) {
  const queryClient = useQueryClient();
  const { showToast } = useToast();
  const [requestedLabel, setRequestedLabel] = useState("");
  const managed = settings?.platform_hosting ?? makerspace.platform_hosting ?? false;
  const requests = useStaffGet<SubdomainRequestResponse>(
    ["subdomain-requests", makerspace.id],
    `/admin/makerspace/${makerspace.id}/subdomain-request`,
    managed,
  );

  const submitRequest = useMutation({
    mutationFn: () =>
      staffRequest<SubdomainRequest>(`/admin/makerspace/${makerspace.id}/subdomain-request`, {
        method: "POST",
        body: JSON.stringify({ requested_label: requestedLabel.trim() }),
      }),
    onSuccess: () => {
      setRequestedLabel("");
      queryClient.invalidateQueries({ queryKey: ["subdomain-requests", makerspace.id] });
      queryClient.invalidateQueries({ queryKey: ["makerspace-settings", makerspace.id] });
      showToast("Subdomain request sent", { tone: "success" });
    },
    onError: (error) => showToast(errorText(error, "Couldn't send the subdomain request"), { tone: "error" }),
  });

  if (!managed) return null;

  const history = requests.data?.results ?? [];
  const pendingRequest = history.find((request) => request.status === "pending");
  const currentDomain = settings?.frontend_domain ?? makerspace.frontend_domain;
  // Active state derives from the backend's authoritative is_platform_subdomain flag
  // (frontend_domain is a VERIFIED platform-suffix subdomain), NOT request history or
  // the presence of a TXT record — managed mode returns a TXT record for every domain,
  // so absence-of-record can't distinguish a provisioned subdomain.
  const hasActiveSubdomain =
    settings?.is_platform_subdomain ?? makerspace.is_platform_subdomain ?? false;
  const activeSubdomain = currentDomain;
  const submitDisabled =
    requests.isLoading || submitRequest.isPending || Boolean(pendingRequest) || !requestedLabel.trim();

  return (
    <Card as="section" aria-labelledby="subdomain-title">
      <CardHeader
        title={<span id="subdomain-title">Request a subdomain</span>}
        description="Ask the platform team to set up a dedicated subdomain for this makerspace."
        action={hasActiveSubdomain ? <StatusChip tone="success">Active</StatusChip> : null}
      />
      <SettingsRow
        title={hasActiveSubdomain ? "Active subdomain" : "Desired subdomain"}
        description={hasActiveSubdomain ? "Your makerspace is served here." : "Lowercase letters, numbers and dashes."}
      >
        {hasActiveSubdomain ? (
          <p className="text-body-ui text-ink">
            Active subdomain: <span className="font-mono font-semibold">{activeSubdomain}</span>
          </p>
        ) : (
          <form
            className="grid min-w-0 max-w-xl gap-3 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-end"
            onSubmit={(event) => {
              event.preventDefault();
              if (!submitDisabled) submitRequest.mutate();
            }}
          >
            <Field label="Desired subdomain label" id="subdomain-label">
              <Input
                placeholder="alpha"
                value={requestedLabel}
                disabled={requests.isLoading || Boolean(pendingRequest)}
                onChange={(event) => setRequestedLabel(event.target.value)}
              />
            </Field>
            <Button variant="primary" type="submit" disabled={submitDisabled} loading={submitRequest.isPending} loadingLabel="Sending…">
              Submit request
            </Button>
          </form>
        )}
        {pendingRequest && !hasActiveSubdomain ? (
          <p className="mt-2 text-caption text-ink-muted">Request pending review</p>
        ) : null}
        <div className="mt-2 grid gap-2">
          <ErrorText message={submitRequest.error?.message} />
          <ErrorText message={requests.error?.message} />
        </div>
      </SettingsRow>
      {requests.isLoading ? <Skeleton className="h-16 w-full" /> : null}
      {history.length > 0 ? (
        <SettingsRow title="Request history">
          <ul className="grid gap-2">
            {history.map((request) => (
              <li className="flex flex-wrap items-center gap-2 rounded-md border border-line p-3 text-body-ui" key={request.id}>
                <span className="font-mono font-semibold text-ink">{request.requested_label}</span>
                <StatusChip tone={statusTone(request.status)} size="sm">{statusLabel(request.status)}</StatusChip>
                {request.note ? <span className="text-ink-muted">{request.note}</span> : null}
                <time className="text-caption text-ink-muted" dateTime={request.created_at}>
                  {new Date(request.created_at).toLocaleString()}
                </time>
              </li>
            ))}
          </ul>
        </SettingsRow>
      ) : null}
    </Card>
  );
}

function statusTone(status: SubdomainRequest["status"]) {
  return status === "approved" ? "success" : status === "rejected" ? "danger" : "warning";
}

function statusLabel(status: SubdomainRequest["status"]) {
  return status.charAt(0).toUpperCase() + status.slice(1);
}
