import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useSearchParams } from "react-router-dom";
import { Button, Callout, Card } from "../../components/ui";
import { readStorage, writeStorage } from "../../lib/safeStorage";
import { StatusResult } from "../printing/PublicPrintRequestParts";
import { fetchServiceStatus } from "./publicApi";

export function useServiceStatus(slug: string, enabled: boolean, legacyPrinter: boolean) {
  const [search] = useSearchParams();
  const urlToken = search.get("token")?.trim() ?? "";
  const [active, setActive] = useState({ slug: "", token: "", submitted: false });
  const storageKey = `tinkerspace.serviceStatus.${slug}`;
  const token = active.slug === slug ? active.token : "";
  useEffect(() => {
    const saved = readStorage(storageKey).trim();
    const legacy = legacyPrinter ? readStorage(`tinkerspace.printStatus.${slug}`).trim() : "";
    setActive({ slug, token: urlToken || saved || legacy, submitted: false });
  }, [slug, urlToken, storageKey, legacyPrinter]);
  useEffect(() => {
    if (slug && token) writeStorage(storageKey, token);
  }, [slug, storageKey, token]);
  const query = useQuery({
    queryKey: ["public-service-status", slug, token],
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
    query, token, submitted: active.slug === slug && active.submitted,
    onSuccess: (nextToken: string) => setActive({ slug, token: nextToken, submitted: true }),
  };
}

export function ServiceStatusPanel({ tracker, statusPath }: {
  tracker: ReturnType<typeof useServiceStatus>;
  statusPath: string;
}) {
  return <Card className="lg:sticky lg:top-20">
    <h2 className="text-h4 text-ink">Status tracker</h2>
    {tracker.submitted ? <Callout className="mt-4" tone="success" role="status" title="Request submitted">
      Keep your private token link to check progress. Do not share it.
    </Callout> : null}
    {tracker.token ? <div className="mt-4 space-y-4">
      <Link to={`${statusPath}?token=${encodeURIComponent(tracker.token)}`} className="text-body-ui text-ink underline underline-offset-4">
        Your private status link
      </Link>
      <StatusResult status={tracker.query.data} error={tracker.query.error} isPending={tracker.query.isPending} />
      {tracker.query.isError ? <Button onClick={() => { void tracker.query.refetch(); }}
        disabled={tracker.query.isFetching} loading={tracker.query.isFetching} loadingLabel="Retrying status…">
        Retry status
      </Button> : null}
    </div> : <p className="mt-3 text-body-ui text-ink-muted">Submit a service request to track its progress here.</p>}
  </Card>;
}
