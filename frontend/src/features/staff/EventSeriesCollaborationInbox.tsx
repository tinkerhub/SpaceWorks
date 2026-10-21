import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { useToast } from "../../components/ui";
import { staffRequest } from "../../lib/api";
import { InvitationInboxCard } from "./InvitationInboxCard";
import { eventDateTime, eventErrorText } from "./eventUi";
import { organizedEventKeys } from "./organizedEventsApi";

type SeriesInvitation = {
  id: number;
  series_id: number;
  series_title: string;
  host_name: string;
  host_slug: string;
  status: "invited" | "accepted" | "declined";
  next_occurrence_at: string | null;
};

const inboxKey = (makerspaceId: number) => [
  "events", makerspaceId, "series-collaboration-inbox",
] as const;

export function EventSeriesCollaborationInbox({ makerspaceId }: { makerspaceId: number }) {
  const client = useQueryClient();
  const { showToast } = useToast();
  const inbox = useQuery({
    queryKey: inboxKey(makerspaceId),
    queryFn: () => staffRequest<SeriesInvitation[]>(
      `/admin/makerspaces/${makerspaceId}/event-series-collaborations/`,
    ),
  });
  const respond = useMutation({
    mutationFn: ({ id, accept }: { id: number; accept: boolean }) =>
      staffRequest(`/admin/event-series-collaborations/${id}/respond/`, {
        method: "POST", body: JSON.stringify({ accept }),
      }),
    onSuccess: () => Promise.all([
      client.invalidateQueries({ queryKey: inboxKey(makerspaceId) }),
      client.invalidateQueries({ queryKey: organizedEventKeys.all }),
      client.invalidateQueries({ queryKey: ["member"] }),
    ]),
  });
  const rows = inbox.data ?? [];
  if (!rows.length) return null;

  return (
    <InvitationInboxCard
      title="Series invitations"
      description="Accept once to make every current and future date in the series available to your members."
      rows={rows.map((row) => ({
        id: row.id,
        title: row.series_title,
        meta: `Hosted by ${row.host_name}${row.next_occurrence_at ? ` · Next ${eventDateTime(row.next_occurrence_at)}` : ""}`,
        status: row.status,
      }))}
      pending={respond.isPending}
      onRespond={(id, accept) => respond.mutate({ id, accept }, {
        onSuccess: () => showToast(accept ? "Series invitation accepted" : "Series invitation declined", { tone: "success" }),
        onError: (error) => showToast(eventErrorText(error), { tone: "error" }),
      })}
      error={respond.error ? "Could not respond to the series invitation." : null}
    />
  );
}
