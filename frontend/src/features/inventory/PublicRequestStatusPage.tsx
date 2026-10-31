import { useState, type FormEvent } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useSearchParams } from "react-router-dom";

import { MakerspaceSiteHeader } from "../../components/chrome/PublicHeaders";
import { PublicContainer, PublicShell } from "../../components/chrome/PublicShell";
import { Button, Card, EmptyState, Field, Input, PageHeader, Skeleton, StatusBadge, buttonClasses } from "../../components/ui";
import { StructuredApiError } from "../../lib/api";
import { useModules } from "../../lib/modules";
import { HardwareRequestItems } from "../requests/HardwareRequestItems";
import { fetchRequestStatus } from "./api";
import { useMakerspacePublic } from "./useMakerspacePublic";

const STATUS_COPY: Record<string, string> = {
  draft: "The request has not been sent yet.",
  pending_approval: "Waiting for staff to review it.",
  accepted: "Approved. Collect it from the desk.",
  rejected: "Staff could not approve this request.",
  cancelled: "This request has been cancelled.",
  issued: "Handed over. Return it when you are done.",
  partially_returned: "Some items are back; the rest are still out.",
  returned: "Everything has been returned.",
  closed_with_issue: "Closed with an issue. Staff will be in touch.",
};

export function PublicRequestStatusPage() {
  const space = useMakerspacePublic();
  const { makerspaceSlug, tenantPath } = space;
  const { moduleEnabled } = useModules();
  const [searchParams, setSearchParams] = useSearchParams();
  const urlToken = searchParams.get("token") ?? "";
  const token = urlToken.trim();
  const status = useQuery({
    queryKey: ["public-request-status", makerspaceSlug, token],
    queryFn: () => fetchRequestStatus(makerspaceSlug, token),
    enabled: Boolean(makerspaceSlug && token),
    retry: false,
  });
  const notFound = status.error instanceof StructuredApiError && status.error.status === 404;

  return (
    <PublicShell header={<MakerspaceSiteHeader {...space.header} moduleEnabled={moduleEnabled} page="Request status" />}>
      <PublicContainer width="sm">
        <PageHeader
          kicker="Borrow request"
          title="Check a request"
          description="Enter the reference you saved when you submitted the request."
        />
        <ReferenceLookup key={JSON.stringify([makerspaceSlug, urlToken])} token={token} pending={status.isFetching}
          onLookup={(reference) => setSearchParams({ token: reference })} />

        <div className="mt-6" aria-live="polite">
          {status.isLoading ? (
            <Card aria-busy="true" aria-label="Loading request status" className="space-y-3">
              <Skeleton className="h-6 w-1/3" />
              <Skeleton className="h-16 w-full" />
            </Card>
          ) : notFound ? (
            <EmptyState title="No request matches that reference" description="Check the reference and try again, or ask staff at the desk." />
          ) : status.isError ? (
            <EmptyState tone="error" title="Request status didn't load" description="Try again in a moment." />
          ) : status.data ? (
            <Card className="space-y-4">
              <div className="flex flex-wrap items-center gap-3">
                <StatusBadge status={status.data.status} />
                <p className="text-caption text-ink-muted">Submitted {new Date(status.data.created_at).toLocaleString()}</p>
              </div>
              {STATUS_COPY[status.data.status] ? <p className="text-body-ui text-ink-secondary">{STATUS_COPY[status.data.status]}</p> : null}
              <HardwareRequestItems items={status.data.items} />
            </Card>
          ) : null}
        </div>

        <Link className={buttonClasses({ variant: "quiet", className: "mt-6" })} to={tenantPath()}>Back to inventory</Link>
      </PublicContainer>
    </PublicShell>
  );
}

function ReferenceLookup({ token, pending, onLookup }: {
  token: string; pending: boolean; onLookup: (reference: string) => void;
}) {
  const [draft, setDraft] = useState(token);
  function lookup(event: FormEvent) {
    event.preventDefault();
    if (draft.trim()) onLookup(draft.trim());
  }
  return <form className="mt-8 flex flex-col gap-3 sm:flex-row sm:items-end" onSubmit={lookup}>
    <Field label="Request reference" className="min-w-0 flex-1">
      <Input value={draft} onChange={(event) => setDraft(event.target.value)} autoComplete="off" spellCheck={false} />
    </Field>
    <Button type="submit" variant="primary" disabled={!draft.trim()} loading={pending} loadingLabel="Checking…">
      Check status
    </Button>
  </form>;
}
