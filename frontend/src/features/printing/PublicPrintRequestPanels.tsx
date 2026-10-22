import { Link } from "react-router-dom";

import { Callout, Card, EmptyState, Skeleton, buttonClasses } from "../../components/ui";
import { StatusResult } from "./PublicPrintRequestParts";
import type { PrintStatus } from "./publicApi";

type StatusProps = { submitted: boolean; tokenStatus?: PrintStatus; tokenStatusPending: boolean; tokenStatusError: Error | null };

export function PrintStatusPanel({ submitted, tokenStatus, tokenStatusPending, tokenStatusError }: StatusProps) {
  const empty = !tokenStatus && !tokenStatusPending && !tokenStatusError;
  return (
    <Card className="lg:sticky lg:top-20">
      <h2 className="text-h4 text-ink">Status tracker</h2>
      {submitted ? (
        <Callout className="mt-4" tone="success" role="status" title="Request submitted">
          This browser keeps its private token; do not share the link.
        </Callout>
      ) : null}
      {empty ? (
        <p className="mt-3 text-body-ui text-ink-muted">Submit a print request and its progress shows up here.</p>
      ) : (
        <div className="mt-4">
          <StatusResult error={tokenStatusError} isPending={tokenStatusPending} status={tokenStatus} />
        </div>
      )}
    </Card>
  );
}

export function PrintAccessLoadingPanel() {
  return (
    <Card aria-busy="true" aria-label="Loading printer service" className="space-y-3">
      <Skeleton className="h-6 w-1/3" />
      <Skeleton className="h-11 w-full" />
      <Skeleton className="h-24 w-full" />
    </Card>
  );
}

export function PrintAccessErrorPanel() {
  return <EmptyState tone="error" title="Printer service didn't load" description="Could not load printer service. Try again in a moment." />;
}

export function PrintUnavailablePanel({ catalogPath, tokenStatus, tokenStatusPending, tokenStatusError }: { catalogPath: string; tokenStatus?: PrintStatus; tokenStatusPending: boolean; tokenStatusError: Error | null }) {
  return (
    <div className="grid gap-4">
      <EmptyState
        title="Printer service is not currently available."
        description="Check back later, or browse the inventory in the meantime."
        action={<Link className={buttonClasses({ variant: "secondary" })} to={catalogPath}>Back to inventory</Link>}
      />
      {tokenStatus || tokenStatusPending || tokenStatusError ? (
        <Card>
          <h2 className="text-h4 text-ink">Your last request</h2>
          <div className="mt-4">
            <StatusResult error={tokenStatusError} isPending={tokenStatusPending} status={tokenStatus} />
          </div>
        </Card>
      ) : null}
    </div>
  );
}
