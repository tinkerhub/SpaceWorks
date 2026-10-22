import { useToast } from "../../components/ui";
import { InvitationInboxCard } from "./InvitationInboxCard";
import {
  useCollaborationInbox,
  useRespondToCollaboration,
} from "./eventCollaborationsApi";
import { eventDateTime, eventErrorText } from "./eventUi";

/** Invitations this makerspace has received to co-host another space's event.
 *
 * The collaborator side of invite → accept, and the reason it exists as its own surface: a
 * host cannot accept on a partner's behalf, so without this the partner's members could
 * never become eligible. Renders nothing at all when the inbox is empty, so a space that
 * never collaborates sees no new UI.
 */
export function CollaborationInbox({ makerspaceId }: { makerspaceId: number }) {
  const { showToast } = useToast();
  const inbox = useCollaborationInbox(makerspaceId);
  const respond = useRespondToCollaboration(makerspaceId);
  const rows = inbox.data ?? [];

  if (!rows.length) return null;

  return (
    <InvitationInboxCard
      title="Invitations from other makerspaces"
      description="Accepting lets your members register for that makerspace's event. The host still owns and runs the event."
      rows={rows.map((row) => ({
        id: row.id,
        title: row.event_title,
        meta: `Hosted by ${row.host_name} · ${eventDateTime(row.starts_at)}`,
        status: row.status,
      }))}
      pending={respond.isPending}
      onRespond={(id, accept) => respond.mutate({ id, accept }, {
        onSuccess: () => showToast(accept ? "Invitation accepted" : "Invitation declined", { tone: "success" }),
        onError: (error) => showToast(eventErrorText(error), { tone: "error" }),
      })}
      error={respond.error ? (respond.error instanceof Error ? respond.error.message : "Could not respond.") : null}
    />
  );
}
