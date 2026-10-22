import { useState } from "react";

import { Button, ConfirmDialog, ErrorText, Field, Input, SectionHeading, Skeleton } from "../../components/ui";
import { EventStatusChip } from "./EventStatusChip";

export type CollaboratorRow = { id: number; makerspace_name: string; makerspace_slug: string; status: string };

const STATUS_HINT: Record<string, string> = {
  invited: "Waiting for them to accept",
  accepted: "Their members can register",
  declined: "They declined the invitation",
};

/** Partner makerspaces of an event or series: invite by slug, remove with a confirmation. */
export function CollaboratorList({
  title, description, rows, loading, slug, onSlugChange, onInvite, inviting, removing, onRemove, error,
}: {
  title: string;
  description: string;
  rows: CollaboratorRow[];
  loading: boolean;
  slug: string;
  onSlugChange: (value: string) => void;
  onInvite: () => void;
  inviting: boolean;
  removing: boolean;
  /** Remove a partner; call `done` once the request settles to close the dialog. */
  onRemove: (row: CollaboratorRow, done: () => void) => void;
  error: string | null;
}) {
  const [pending, setPending] = useState<CollaboratorRow | null>(null);
  return (
    <section aria-label={title} className="grid gap-3">
      <SectionHeading as="h3" title={title} description={description} />
      {loading ? <Skeleton className="h-14 w-full" /> : null}
      {!loading && !rows.length ? (
        <p className="rounded-lg border-[1.5px] border-dashed border-line-strong px-4 py-3 text-body-ui text-ink-muted">No partner makerspaces yet.</p>
      ) : null}
      {rows.length ? (
        <ul className="divide-y divide-line overflow-hidden rounded-lg border border-line">
          {rows.map((row) => (
            <li key={row.id} className="flex flex-wrap items-center justify-between gap-3 px-4 py-3">
              <span className="min-w-0">
                <span className="font-semibold text-ink">{row.makerspace_name}</span>{" "}
                <span className="font-mono text-caption text-ink-muted">{row.makerspace_slug}</span>
                <span className="mt-1 flex flex-wrap items-center gap-2 text-caption text-ink-muted">
                  <EventStatusChip status={row.status} />
                  {STATUS_HINT[row.status] ?? null}
                </span>
              </span>
              <Button variant="danger-quiet" size="sm" disabled={removing} onClick={() => setPending(row)}>Remove…</Button>
            </li>
          ))}
        </ul>
      ) : null}
      <form
        className="flex flex-wrap items-end gap-2"
        onSubmit={(event) => { event.preventDefault(); onInvite(); }}
      >
        <Field label="Makerspace slug" className="min-w-48 flex-1">
          <Input className="font-mono" value={slug} onChange={(event) => onSlugChange(event.target.value)} placeholder="partner-space" />
        </Field>
        <Button type="submit" disabled={!slug.trim()} loading={inviting} loadingLabel="Inviting…">Invite</Button>
      </form>
      <ErrorText message={error} />
      <ConfirmDialog
        open={pending !== null}
        title={pending ? `Remove ${pending.makerspace_name}?` : "Remove partner?"}
        message="Their members can no longer register through this partnership. You can invite them again later."
        confirmLabel="Remove partner"
        tone="danger"
        pending={removing}
        onCancel={() => setPending(null)}
        onConfirm={() => { if (pending) onRemove(pending, () => setPending(null)); }}
      />
    </section>
  );
}
