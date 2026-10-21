import { useEffect, useMemo, useState } from "react";

import { Button, CheckboxCard, ErrorText, SectionHeading, Skeleton, useToast } from "../../components/ui";
import type { StaffEvent } from "./eventsApi";
import { useReplaceEventOrganizers } from "./eventsApi";
import { eventErrorText } from "./eventUi";
import { useOrganizations } from "./organizationsApi";

export function EventOrganizers({ event, makerspaceId, disabled }: {
  event: StaffEvent;
  makerspaceId: number;
  disabled: boolean;
}) {
  const { showToast } = useToast();
  const organizations = useOrganizations();
  const [selected, setSelected] = useState<number[]>(event.organizers.map((item) => item.id));
  const replace = useReplaceEventOrganizers(makerspaceId, event.id);
  useEffect(() => setSelected(event.organizers.map((item) => item.id)), [event.organizers]);
  const assignable = organizations.data?.results ?? [];
  const assignableIds = useMemo(() => new Set(assignable.map((item) => item.id)), [assignable]);
  const retained = event.organizers.filter((item) => !assignableIds.has(item.id));

  function toggle(id: number) {
    setSelected((values) => values.includes(id) ? values.filter((item) => item !== id) : [...values, id]);
  }

  const save = () => replace.mutate(selected, {
    onSuccess: () => showToast("Organizers saved", { tone: "success" }),
    onError: (error) => showToast(eventErrorText(error), { tone: "error" }),
  });

  return (
    <section className="grid gap-3" aria-label="Organization organizers">
      <SectionHeading as="h3" title="Organization organizers" description="Attribution and event-specific authority only. The host makerspace remains the owner." />
      {organizations.isLoading ? <Skeleton className="h-16 w-full" /> : null}
      <ErrorText message={organizations.error ? organizations.error.message : null} />
      {assignable.length || retained.length ? (
        <div className="grid gap-2 sm:grid-cols-2">
          {assignable.map((organization) => (
            <CheckboxCard
              key={organization.id}
              label={organization.name}
              description={<span className="font-mono">{organization.slug}</span>}
              checked={selected.includes(organization.id)}
              disabled={disabled}
              onCheckedChange={() => toggle(organization.id)}
            />
          ))}
          {retained.map((organization) => (
            <CheckboxCard key={organization.id} label={organization.name} description="Retained co-organizer" checked disabled />
          ))}
        </div>
      ) : null}
      {!assignable.length && !retained.length && !organizations.isLoading ? (
        <p className="rounded-lg border-[1.5px] border-dashed border-line-strong px-4 py-3 text-body-ui text-ink-muted">No active organization memberships are available to assign.</p>
      ) : null}
      {!disabled ? <div><Button onClick={save} loading={replace.isPending} loadingLabel="Saving…">Save organizers</Button></div> : null}
      <ErrorText message={replace.error ? replace.error.message : null} />
    </section>
  );
}
