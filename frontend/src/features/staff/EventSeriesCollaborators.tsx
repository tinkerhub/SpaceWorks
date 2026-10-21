import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { useToast } from "../../components/ui";
import { staffRequest } from "../../lib/api";
import { CollaboratorList, type CollaboratorRow } from "./CollaboratorList";
import { eventSeriesKeys } from "./eventSeriesApi";
import { eventKeys } from "./eventsApi";
import { eventErrorText } from "./eventUi";
import { organizedEventKeys } from "./organizedEventsApi";

export function EventSeriesCollaborators({ seriesId, makerspaceId }: { seriesId: number; makerspaceId: number }) {
  const client = useQueryClient();
  const { showToast } = useToast();
  const [slug, setSlug] = useState("");
  const path = `/admin/event-series/${seriesId}/collaborators/`;
  const query = useQuery({
    queryKey: eventSeriesKeys.collaborators(seriesId),
    queryFn: () => staffRequest<CollaboratorRow[]>(path),
  });
  const invalidate = () => Promise.all([
    client.invalidateQueries({ queryKey: eventSeriesKeys.collaborators(seriesId) }),
    client.invalidateQueries({ queryKey: eventSeriesKeys.occurrences(seriesId) }),
    client.invalidateQueries({ queryKey: eventKeys.list(makerspaceId) }),
    client.invalidateQueries({ queryKey: organizedEventKeys.all }),
    client.invalidateQueries({ queryKey: ["member"] }),
  ]);
  const replace = useMutation({
    mutationFn: (slugs: string[]) => staffRequest<CollaboratorRow[]>(path, {
      method: "PUT", body: JSON.stringify({ slugs }),
    }), onSuccess: invalidate,
  });
  const remove = useMutation({
    mutationFn: (id: number) => staffRequest<void>(`/admin/event-series-collaborations/${id}/remove/`, { method: "POST" }),
    onSuccess: invalidate,
  });
  const rows = query.data ?? [];
  const failed = (error: unknown) => showToast(eventErrorText(error), { tone: "error" });
  const invite = () => {
    const wanted = slug.trim().toLowerCase();
    if (!wanted) return;
    // Replaces the whole set: keep every existing partner (declined included) plus the new one.
    replace.mutate(Array.from(new Set([...rows.map((row) => row.makerspace_slug), wanted])), {
      onSuccess: () => { setSlug(""); showToast("Invitation sent", { tone: "success" }); },
      onError: failed,
    });
  };

  return (
    <CollaboratorList
      title="Series partners"
      description="One accepted invitation applies to every current and future date in the series."
      rows={rows}
      loading={query.isLoading}
      slug={slug}
      onSlugChange={setSlug}
      onInvite={invite}
      inviting={replace.isPending}
      removing={remove.isPending}
      onRemove={(row, done) => remove.mutate(row.id, {
        onSuccess: () => { done(); showToast(`${row.makerspace_name} removed`, { tone: "success" }); },
        onError: (error) => { done(); failed(error); },
      })}
      error={query.error || replace.error || remove.error ? "Could not update series partners." : null}
    />
  );
}
