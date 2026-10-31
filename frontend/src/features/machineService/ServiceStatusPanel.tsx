import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useLocation, useSearchParams } from "react-router-dom";
import { Button, Callout, Card } from "../../components/ui";
import { getSessionGeneration } from "../../lib/api";
import { usePublicSession } from "../inventory/usePublicSession";
import { validRequestToken, type CapabilityOutcome } from "../requests/requestCapabilities";
import { useAuthActionOwner } from "../auth/useAuthActionOwner";
import { StatusResult } from "../printing/PublicPrintRequestParts";
import { fetchServiceStatus } from "./publicApi";

export function useServiceStatus(slug: string, enabled: boolean, legacyPrinter: boolean, person = "") {
  usePublicSession(slug, false);
  const generation = getSessionGeneration();
  const [search] = useSearchParams();
  const location = useLocation();
  const urlToken = search.get("token") ?? "";
  const owner = useAuthActionOwner(JSON.stringify([slug, urlToken, legacyPrinter, person, enabled, location.key, location.pathname, location.search]));
  function initialStatus(): { context: typeof owner.context; token: string; submitted: boolean; persistence?: CapabilityOutcome } {
    const explicit = urlToken.trim();
    return { context: owner.context, token: validRequestToken(explicit) ? explicit : "", submitted: false };
  }
  const [stored, setActive] = useState(initialStatus);
  // Only a URL capability or this visit's admitted success opens private status.
  const active = stored.context === owner.context ? stored : initialStatus();
  if (stored.context !== owner.context) setActive(active);
  const { token } = active;
  const query = useQuery({
    queryKey: ["public-service-status", slug, token, generation],
    queryFn: () => fetchServiceStatus(token),
    enabled: enabled && Boolean(token),
    retry: false,
    refetchInterval: (state) => {
      if (!enabled || !token || state.state.error) return false;
      const status = state.state.data?.status;
      return status === "in_progress" ? 30_000 : status === "pending" || status === "accepted" ? 90_000 : false;
    },
  });
  return {
    query, token, submitted: active.submitted, persistence: active.persistence,
    retry: () => { if (owner.isContextCurrent()) void query.refetch(); },
    onSuccess: (nextToken: string, persistence?: CapabilityOutcome) => {
      if (owner.isContextCurrent()) setActive({ context: owner.context, token: nextToken, submitted: true, persistence });
    },
  };
}

export function ServiceStatusPanel({ tracker, statusPath, savedRequestsPath }: {
  tracker: ReturnType<typeof useServiceStatus>;
  statusPath: string;
  savedRequestsPath?: string;
}) {
  return <Card className="lg:sticky lg:top-20">
    <h2 className="text-h4 text-ink">Status tracker</h2>
    {tracker.submitted ? <Callout className="mt-4" tone="success" role="status" title="Request submitted">
      <p>Keep your private token link to check progress. Do not share it.</p>
      {tracker.persistence?.saved ? <p className="mt-2">Saved on this browser. Open My requests to reveal saved links.</p> : null}
      {tracker.persistence?.warning ? <p className="mt-2">{tracker.persistence.warning}</p> : null}
    </Callout> : null}
    {tracker.token ? <div className="mt-4 space-y-4">
      <Link to={`${statusPath}?token=${encodeURIComponent(tracker.token)}`} className="text-body-ui text-ink underline underline-offset-4">
        Your private status link
      </Link>
      <StatusResult status={tracker.query.data} error={tracker.query.error} isPending={tracker.query.isPending} />
      {tracker.query.isError ? <Button onClick={tracker.retry}
        disabled={tracker.query.isFetching} loading={tracker.query.isFetching} loadingLabel="Retrying status…">
        Retry status
      </Button> : null}
    </div> : <p className="mt-3 text-body-ui text-ink-muted">Submit a service request to track its progress here.</p>}
    {savedRequestsPath ? <Link className="mt-4 inline-block text-body-ui text-ink underline underline-offset-4"
      to={savedRequestsPath}>View saved requests</Link> : null}
  </Card>;
}
