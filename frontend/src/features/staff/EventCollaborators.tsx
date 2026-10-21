import { useState } from "react";

import { useToast } from "../../components/ui";
import { CollaboratorList, type CollaboratorRow } from "./CollaboratorList";
import {
  useEventCollaborators,
  useRemoveEventCollaborator,
  useReplaceEventCollaborators,
} from "./eventCollaborationsApi";
import { eventErrorText } from "./eventUi";

/** Host-side collaborator management for one event.
 *
 * Invitation is by SLUG, not a picker, and that is deliberate rather than lazy: a host has
 * no authority to enumerate other makerspaces, so offering a browsable list would leak the
 * existence and names of spaces it does not administer. The partner then has to accept
 * before any of its members become eligible, so one space cannot attach itself — or be
 * attached — to another's event unilaterally.
 */
export function EventCollaborators({
  makerspaceId,
  eventId,
}: {
  makerspaceId: number;
  eventId: number;
}) {
  const { showToast } = useToast();
  const [slug, setSlug] = useState("");
  const collaborators = useEventCollaborators(eventId);
  const replace = useReplaceEventCollaborators(makerspaceId, eventId);
  const remove = useRemoveEventCollaborator(makerspaceId, eventId);
  const rows: CollaboratorRow[] = collaborators.data ?? [];
  const error = replace.error || remove.error || collaborators.error;

  const invite = () => {
    const wanted = slug.trim().toLowerCase();
    if (!wanted) return;
    // The endpoint REPLACES the set, so send every slug that should remain plus the new
    // one; sending only the addition would silently remove every existing partner. Declined
    // rows are included so they are NOT deleted -- the service preserves their answer, so
    // adding one partner cannot reopen somebody else's refusal.
    const slugs = Array.from(
      new Set([...rows.map((row) => row.makerspace_slug), wanted]),
    );
    replace.mutate(slugs, {
      onSuccess: () => { setSlug(""); showToast("Invitation sent", { tone: "success" }); },
      onError: (failure) => showToast(eventErrorText(failure), { tone: "error" }),
    });
  };

  return (
    <CollaboratorList
      title="Partner makerspaces"
      description="Invite another makerspace by its slug and its members can register for this event, even when the event is not public. They must accept the invitation first. You invite by slug because makerspaces are not browsable from here."
      rows={rows}
      loading={collaborators.isLoading}
      slug={slug}
      onSlugChange={setSlug}
      onInvite={invite}
      inviting={replace.isPending}
      removing={remove.isPending}
      onRemove={(row, done) => remove.mutate(row.id, {
        onSuccess: () => { done(); showToast(`${row.makerspace_name} removed`, { tone: "success" }); },
        onError: (failure) => { done(); showToast(eventErrorText(failure), { tone: "error" }); },
      })}
      error={error ? (error instanceof Error ? error.message : "Could not update partners.") : null}
    />
  );
}
