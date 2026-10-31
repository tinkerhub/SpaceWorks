import { useState } from "react";
import { Link } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Button, Callout, Card, EmptyState, Skeleton } from "../../components/ui";
import { useAuthActionOwner } from "../auth/useAuthActionOwner";
import {
  forgetRequestCapabilities, revealRequestCapabilities,
  type CapabilityOutcome, type RequestCapability,
} from "./requestCapabilities";
import { fetchSavedRequest, savedRequestKey } from "./requestsApi";
import { requestError, RequestSummary, RequestsPagination } from "./RequestsListParts";

type Props = { slug: string; generation: number; basePath: string; hardwareOn: boolean; machineOn: boolean };
export function SavedRequests({ slug, generation, basePath, hardwareOn, machineOn }: Props) {
  const client = useQueryClient();
  const owner = useAuthActionOwner(JSON.stringify([slug, generation]));
  const [revealed, setRevealed] = useState<CapabilityOutcome | null>(null);
  const [page, setPage] = useState(1);
  const records = revealed?.records.filter((row) => row.kind === "hardware" ? hardwareOn : machineOn) ?? [];
  const visible = records.slice((page - 1) * 6, page * 6);
  function forget(target?: RequestCapability) {
    if (!owner.isContextCurrent()) return;
    const result = forgetRequestCapabilities(slug, target);
    const removed = target ? [target] : revealed?.records ?? [];
    // These keys identify one tenant/session/capability, never another account's history.
    for (const record of removed) {
      client.removeQueries({ queryKey: savedRequestKey(slug, generation, record.kind, record.token), exact: true });
      client.removeQueries({ queryKey: [record.kind === "hardware" ? "public-request-status" : "public-service-status", slug, record.token], exact: true });
      if (record.kind === "machine") client.removeQueries({ queryKey: ["public-service-status", slug, record.token, generation], exact: true });
    }
    if (result.saved) { setRevealed(result); setPage(1); }
    else setRevealed((current) => current ? { ...current, warning: result.warning } : result);
  }
  return <section aria-label="Saved on this browser" className="space-y-4">
    <Card className="space-y-4">
      <div><h2 className="text-h3 text-ink">Saved on this browser</h2>
        <p className="mt-2 text-body-ui text-ink-secondary">These private links let anyone holding them view a request. On a shared browser, they may belong to someone else. A check-in name does not prove ownership.</p></div>
      <p className="text-caption text-ink-muted">This browser keeps up to 50 links per makerspace, replacing the oldest when full. Forgetting a link removes it from this browser; it does not cancel the request.</p>
      {!revealed ? <Button variant="secondary" onClick={() => {
        if (owner.isContextCurrent()) setRevealed(revealRequestCapabilities(slug));
      }}>Show requests saved on this browser</Button> : <div className="flex flex-wrap gap-3">
        <Button variant="quiet" onClick={() => { if (owner.isContextCurrent()) { setRevealed(null); setPage(1); } }}>Hide saved requests</Button>
        <Button variant="quiet" onClick={() => forget()}>Forget all saved links</Button>
      </div>}
      {revealed?.warning ? <Callout tone="warning" role="status">{revealed.warning}</Callout> : null}
    </Card>
    {revealed ? <>
      {visible.length ? <ul className="space-y-4">{visible.map((record) => <li key={`${record.kind}-${record.token}`}>
        <SavedRequestRow record={record} slug={slug} generation={generation} basePath={basePath} onForget={() => forget(record)} />
      </li>)}</ul> : <EmptyState title="No saved links for the available request types" description="Keep the private link after submitting a request to find it again here." />}
      {records.length ? <RequestsPagination page={page} count={records.length} size={6}
        hasNext={page * 6 < records.length} onPage={setPage} /> : null}
    </> : null}
  </section>;
}

function SavedRequestRow({ record, slug, generation, basePath, onForget }: {
  record: RequestCapability; slug: string; generation: number; basePath: string; onForget: () => void;
}) {
  const owner = useAuthActionOwner(JSON.stringify([slug, generation, record.kind, record.token]));
  const query = useQuery({
    queryKey: savedRequestKey(slug, generation, record.kind, record.token),
    queryFn: async ({ signal }) => {
      if (!owner.isContextCurrent()) throw new Error("Request context changed.");
      const result = await fetchSavedRequest(slug, record.kind, record.token, signal);
      if (signal.aborted || !owner.isContextCurrent()) throw new Error("Request context changed.");
      return result;
    },
    retry: false,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
  });
  return <Card className="space-y-4">
    <p className="text-overline text-ink-muted">{record.kind === "hardware" ? "Hardware" : "Machine service"}</p>
    {query.isPending ? <div aria-busy="true" aria-label="Loading saved request"><Skeleton className="h-20 w-full" /></div>
      : query.isError ? <Callout tone="warning" role="status">{requestError(query.error)}</Callout>
        : query.data ? <RequestSummary kind={record.kind} data={query.data} token={record.token} basePath={basePath} showLink={false} /> : null}
    <Link className="inline-block text-body-ui text-ink underline underline-offset-4"
      to={`${basePath}/${record.kind === "hardware" ? "request" : "machine-service"}?token=${encodeURIComponent(record.token)}`}>Open private status link</Link>
    <div className="flex flex-wrap gap-3">
      {query.isError ? <Button variant="quiet" disabled={query.isFetching} onClick={() => { if (owner.isContextCurrent()) void query.refetch(); }}>Retry status</Button> : null}
      <Button variant="quiet" onClick={onForget}>Forget this link</Button>
    </div>
  </Card>;
}
