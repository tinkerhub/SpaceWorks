import type { ReactNode } from "react";

import { Button, Card, CardHeader, ErrorText } from "../../components/ui";
import { EventStatusChip } from "./EventStatusChip";

export type InboxRow = { id: number; title: string; meta: ReactNode; status: string };

/** Invitations another makerspace sent this one: Accept / Decline per row. */
export function InvitationInboxCard({ title, description, rows, pending, onRespond, error }: {
  title: string;
  description: string;
  rows: InboxRow[];
  pending: boolean;
  onRespond: (id: number, accept: boolean) => void;
  error: string | null;
}) {
  return (
    <Card as="section" aria-label={title}>
      <CardHeader title={title} description={description} />
      <ul className="divide-y divide-line overflow-hidden rounded-lg border border-line">
        {rows.map((row) => (
          <li key={row.id} className="flex flex-wrap items-center justify-between gap-3 px-4 py-3">
            <span className="min-w-0">
              <span className="block font-semibold text-ink">{row.title}</span>
              <span className="block text-caption text-ink-muted">{row.meta}</span>
            </span>
            {row.status === "invited" ? (
              <span className="flex gap-2">
                <Button size="sm" disabled={pending} onClick={() => onRespond(row.id, false)}>Decline</Button>
                <Button size="sm" variant="primary" disabled={pending} onClick={() => onRespond(row.id, true)}>Accept</Button>
              </span>
            ) : (
              <EventStatusChip status={row.status} />
            )}
          </li>
        ))}
      </ul>
      {error ? <div className="mt-3"><ErrorText message={error} /></div> : null}
    </Card>
  );
}
