import { Link } from "react-router-dom";
import { Button, StatusBadge } from "../../components/ui";
import { StructuredApiError } from "../../lib/api";
import { StatusResult } from "../printing/PublicPrintRequestParts";
import type { RequestKind } from "./requestCapabilities";
import type { RequestStatus } from "./requestsApi";
import { HardwareRequestItems } from "./HardwareRequestItems";

export function RequestSummary({ data, kind, token, basePath, showLink = true }: {
  data: RequestStatus; kind: RequestKind; token: string; basePath: string; showLink?: boolean;
}) {
  return <div className="space-y-3">
    {kind === "hardware" && "items" in data ? <>
      <div className="flex flex-wrap items-center gap-3">
        <StatusBadge status={data.status} />
        <p className="text-caption text-ink-muted">Submitted {new Date(data.created_at).toLocaleString()}</p>
      </div>
      <HardwareRequestItems items={data.items} />
    </> : null}
    {kind === "machine" && "title" in data ? <StatusResult isPending={false} error={null} status={data} /> : null}
    {showLink ? <Link className="inline-block text-body-ui font-semibold text-ink underline underline-offset-4"
      to={`${basePath}/${kind === "hardware" ? "request" : "machine-service"}?token=${encodeURIComponent(token)}`}>
      Open private status link
    </Link> : null}
  </div>;
}

export function requestError(error: unknown) {
  if (error instanceof StructuredApiError) {
    if (error.status === 401) return "Sign in with the account that made these requests.";
    if (error.status === 403) return "This account cannot access this request history.";
    if (error.status === 404) return "These requests are unavailable here.";
  }
  return "Requests could not be loaded. Please try again.";
}

export function RequestsPagination({ page, count, size, busy = false, hasNext, onPage }: {
  page: number; count: number; size: number; busy?: boolean; hasNext: boolean; onPage: (page: number) => void;
}) {
  return <nav aria-label="Request pages" className="flex flex-wrap items-center justify-between gap-3">
    <p className="text-caption text-ink-muted">{count} requests · Page {page} · Up to {size} per page</p>
    <div className="flex gap-2">
      <Button variant="quiet" disabled={busy || page <= 1} onClick={() => onPage(page - 1)}>Previous</Button>
      <Button variant="quiet" disabled={busy || !hasNext} onClick={() => onPage(page + 1)}>Next</Button>
    </div>
  </nav>;
}
