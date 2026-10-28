import { useState, type FormEvent } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useSearchParams } from "react-router-dom";

import { MakerspaceSiteHeader } from "../../components/chrome/PublicHeaders";
import { PublicContainer, PublicShell } from "../../components/chrome/PublicShell";
import { Button, Card, EmptyState, Field, Input, PageHeader, Skeleton, StatusBadge, buttonClasses } from "../../components/ui";
import { StructuredApiError } from "../../lib/api";
import { useModules } from "../../lib/modules";
import { fetchRequestStatus } from "./api";
import { useMakerspacePublic } from "./useMakerspacePublic";

const STATUS_COPY: Record<string, string> = {
  draft: "The request has not been sent yet.",
  pending_approval: "Waiting for staff to review it.",
  accepted: "Approved. Collect it from the desk.",
  rejected: "Staff could not approve this request.",
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
  const token = searchParams.get("token")?.trim() ?? "";
  const [draft, setDraft] = useState(token);
  const status = useQuery({
    queryKey: ["public-request-status", makerspaceSlug, token],
    queryFn: () => fetchRequestStatus(makerspaceSlug, token),
    enabled: Boolean(makerspaceSlug && token),
    retry: false,
  });
  const notFound = status.error instanceof StructuredApiError && status.error.status === 404;

  const lookup = (event: FormEvent) => {
    event.preventDefault();
    if (draft.trim()) setSearchParams({ token: draft.trim() });
  };

  return (
    <PublicShell header={<MakerspaceSiteHeader {...space.header} moduleEnabled={moduleEnabled} page="Request status" />}>
      <PublicContainer width="sm">
        <PageHeader
          kicker="Borrow request"
          title="Check a request"
          description="Enter the reference you saved when you submitted the request."
        />
        <form className="mt-8 flex flex-col gap-3 sm:flex-row sm:items-end" onSubmit={lookup}>
          <Field label="Request reference" className="min-w-0 flex-1">
            <Input value={draft} onChange={(event) => setDraft(event.target.value)} autoComplete="off" spellCheck={false} />
          </Field>
          <Button type="submit" variant="primary" disabled={!draft.trim()} loading={status.isFetching} loadingLabel="Checking…">
            Check status
          </Button>
        </form>

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
              <ul className="divide-y divide-line">
                {status.data.items.map((item, index) => (
                  <li key={`${item.product_name}-${index}`} className="flex justify-between gap-3 py-2 text-body-ui text-ink">
                    <span className="min-w-0 break-words">{item.product_name}</span>
                    <span className="shrink-0 text-ink-muted">× {item.requested_quantity}</span>
                  </li>
                ))}
              </ul>
            </Card>
          ) : null}
        </div>

        <Link className={buttonClasses({ variant: "quiet", className: "mt-6" })} to={tenantPath()}>Back to inventory</Link>
      </PublicContainer>
    </PublicShell>
  );
}
