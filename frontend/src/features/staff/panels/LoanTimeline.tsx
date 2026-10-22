import { useState } from "react";

import { Button, ErrorBlock, SectionHeading, Skeleton } from "../../../components/ui";
import { StatusWord, useStaffGet } from "./shared";

type Actor = { username: string; role: string };
type TimelineEvent = {
  kind: string;
  at: string;
  actor: Actor | null;
  detail: Record<string, unknown>;
  evidence_id: number | null;
};
type RequestTimelineResponse = { request_id: number; limit: number; truncated: boolean; events: TimelineEvent[] };
type AssetGroup = { asset_id: number | null; asset_tag: string; serial_number: string; status: string; events: TimelineEvent[] };
type QuantitySummary = {
  loan_count: number;
  direct_loan_count: number;
  issued_quantity: number;
  returned_quantity: number;
  damaged_quantity: number;
  missing_quantity: number;
  active_quantity: number;
};
type ChainResponse = {
  product_id: number;
  product_name: string;
  tracking_mode: string;
  limit: number;
  truncated: boolean;
  events: TimelineEvent[];
  asset_groups: AssetGroup[];
  quantity_summary: QuantitySummary | null;
};

export function RequestTimelineBlock({ requestId }: { requestId: number }) {
  const timeline = useStaffGet<RequestTimelineResponse>(["request-timeline", requestId], `/admin/requests/${requestId}/timeline?limit=200`);
  return (
    <section className="mt-3 grid gap-2 rounded-lg border border-line bg-canvas p-4">
      <h4 className="text-label text-ink">Loan timeline</h4>
      <QueryState loading={timeline.isLoading} error={timeline.error} empty={!timeline.data?.events.length} emptyLabel="No timeline events yet." />
      {timeline.data ? <EventList events={timeline.data.events} truncated={timeline.data.truncated} /> : null}
    </section>
  );
}

export function ChainOfCustodyBlock({ productId }: { productId: number }) {
  const [open, setOpen] = useState(false);
  const chain = useStaffGet<ChainResponse>(["chain-of-custody", productId], `/admin/inventory/${productId}/chain-of-custody?limit=200`, open);
  return (
    <section className="grid gap-3 border-t border-line pt-5">
      <SectionHeading
        as="h3"
        title="Chain of custody"
        description="Every handover, return and scan for this item."
        action={<Button variant="quiet" size="sm" aria-expanded={open} onClick={() => setOpen((value) => !value)}>{open ? "Hide" : "Open"}</Button>}
      />
      {open ? <QueryState loading={chain.isLoading} error={chain.error} empty={!chain.data?.events.length} emptyLabel="No custody events yet." /> : null}
      {open && chain.data?.quantity_summary ? <QuantitySummaryView summary={chain.data.quantity_summary} /> : null}
      {open && chain.data?.asset_groups.length ? <AssetGroups groups={chain.data.asset_groups} /> : null}
      {open && chain.data ? <EventList events={chain.data.events} truncated={chain.data.truncated} /> : null}
    </section>
  );
}

function QueryState({ loading, error, empty, emptyLabel }: { loading: boolean; error: unknown; empty: boolean; emptyLabel: string }) {
  if (loading) return <Skeleton className="h-12 w-full" />;
  if (error) return <ErrorBlock error={error} />;
  if (empty) return <p className="text-body-ui text-ink-muted">{emptyLabel}</p>;
  return null;
}

function AssetGroups({ groups }: { groups: AssetGroup[] }) {
  return (
    <div className="grid gap-2">
      {groups.map((group) => (
        <div key={group.asset_id ?? group.asset_tag} className="grid gap-1 rounded-md border border-line px-3 py-2 text-caption">
          <p className="flex flex-wrap items-center gap-2">
            <span className="font-mono font-semibold text-ink">{group.asset_tag || `Asset #${group.asset_id}`}</span>
            <StatusWord status={group.status} />
          </p>
          <p className="text-ink-muted">{group.events.map((event) => humanize(String(event.detail.outcome ?? event.kind))).join(" · ")}</p>
        </div>
      ))}
    </div>
  );
}

function QuantitySummaryView({ summary }: { summary: QuantitySummary }) {
  const parts: [string, number][] = [
    ["Reviewed loans", summary.loan_count],
    ["Direct loans", summary.direct_loan_count],
    ["Issued", summary.issued_quantity],
    ["Returned", summary.returned_quantity],
    ["Damaged", summary.damaged_quantity],
    ["Missing", summary.missing_quantity],
    ["Active", summary.active_quantity],
  ];
  return (
    <dl className="grid grid-cols-2 gap-2 sm:grid-cols-4">
      {parts.map(([label, value]) => (
        <div key={label} className="rounded-md bg-subtle px-3 py-2">
          <dt className="text-caption text-ink-muted">{label}</dt>
          <dd className="font-semibold tabular-nums text-ink">{value}</dd>
        </div>
      ))}
    </dl>
  );
}

function EventList({ events, truncated }: { events: TimelineEvent[]; truncated: boolean }) {
  if (!events.length) return null;
  return (
    <ol className="grid divide-y divide-line rounded-md border border-line text-caption text-ink-secondary">
      {events.map((event, index) => (
        <li key={`${event.kind}-${String(event.detail.id ?? index)}-${event.at}`} className="px-3 py-2">
          <span className="font-semibold text-ink">{humanize(event.kind)}</span> on {formatDate(event.at)}
          {event.actor ? ` by ${formatActor(event.actor)}` : ""}
          {event.evidence_id ? <> · evidence <span className="font-mono">#{event.evidence_id}</span></> : null}
          <DetailText detail={event.detail} />
        </li>
      ))}
      {truncated ? <li className="px-3 py-2 text-ink-muted">Older history is hidden. Only the latest events are shown.</li> : null}
    </ol>
  );
}

function DetailText({ detail }: { detail: Record<string, unknown> }) {
  const parts = ["product_name", "asset_tag", "outcome", "context", "issue_type", "quantity", "remark", "note"]
    .map((key) => detail[key])
    .filter((value) => value !== undefined && value !== null && value !== "")
    .map(String);
  return parts.length ? <span> · {parts.join(" · ")}</span> : null;
}

function formatActor(actor: Actor) {
  return actor.role ? `${actor.username} (${actor.role})` : actor.username;
}

function humanize(value: string) {
  return value.replace(/_/g, " ").replace(/^\w/, (match) => match.toUpperCase());
}

function formatDate(value: string) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}
