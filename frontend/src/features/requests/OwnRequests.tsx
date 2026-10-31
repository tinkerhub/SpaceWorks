import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Button, Card, EmptyState, Skeleton } from "../../components/ui";
import { useAuthActionOwner } from "../auth/useAuthActionOwner";
import type { RequestKind } from "./requestCapabilities";
import { fetchOwnRequests, ownRequestsKey } from "./requestsApi";
import { requestError, RequestSummary, RequestsPagination } from "./RequestsListParts";

type Props = { slug: string; generation: number; basePath: string; hardwareOn: boolean; machineOn: boolean };
export function OwnRequests(props: Props) {
  return <section aria-label="Account requests" className="space-y-6">
    <div><h2 className="text-h3 text-ink">Filed under your account</h2>
      <p className="mt-2 text-body-ui text-ink-secondary">Requests made using check-in names or without an account are available through their private links.</p></div>
    {props.hardwareOn ? <OwnRequestBranch key={`hardware-${props.slug}-${props.generation}`} {...props} kind="hardware" /> : null}
    {props.machineOn ? <OwnRequestBranch key={`machine-${props.slug}-${props.generation}`} {...props} kind="machine" /> : null}
  </section>;
}
function OwnRequestBranch({ slug, generation, basePath, kind }: Props & { kind: RequestKind }) {
  const [page, setPage] = useState(1);
  const owner = useAuthActionOwner(JSON.stringify([slug, generation, kind, page]));
  const query = useQuery({
    queryKey: ownRequestsKey(slug, generation, kind, page),
    queryFn: async ({ signal }) => {
      if (!owner.isContextCurrent()) throw new Error("Request context changed.");
      const result = await fetchOwnRequests(slug, kind, page, signal);
      if (signal.aborted || !owner.isContextCurrent()) throw new Error("Request context changed.");
      return result;
    },
    retry: false,
    refetchOnWindowFocus: false,
  });
  const title = kind === "hardware" ? "Hardware requests" : "Machine service requests";
  return <section aria-label={title} className="space-y-4">
    <h3 className="text-h4 text-ink">{title}</h3>
    {query.isPending ? <Card aria-busy="true" aria-label={`Loading ${title.toLowerCase()}`}><Skeleton className="h-24 w-full" /></Card>
      : query.isError ? <EmptyState tone="error" title={`${title} didn't load`} description={requestError(query.error)}
        action={<div className="flex flex-wrap gap-3">
          <Button disabled={query.isFetching} onClick={() => { if (owner.isContextCurrent()) void query.refetch(); }}>Try again</Button>
          {page > 1 ? <Button variant="quiet" onClick={() => { if (owner.isContextCurrent()) setPage(page - 1); }}>Previous page</Button> : null}
        </div>} />
        : query.data ? <>
          {query.data.results.length ? <ul className="space-y-4">
            {query.data.results.map((data) => <li key={data.public_token}><Card>
              <RequestSummary kind={kind} data={data} token={data.public_token} basePath={basePath} />
            </Card></li>)}
          </ul> : <EmptyState title={`No ${title.toLowerCase()} yet`} description="Requests filed under this account in this makerspace will appear here." />}
          <RequestsPagination page={page} count={query.data.count} size={24} hasNext={Boolean(query.data.next)}
            busy={query.isFetching} onPage={(next) => { if (owner.isContextCurrent()) setPage(next); }} />
        </> : null}
  </section>;
}
