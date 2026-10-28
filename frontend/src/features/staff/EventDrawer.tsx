import { useEffect, useState } from "react";

import { Button, Chip, ConfirmDialog, DetailDrawer, EmptyState, ErrorText, SectionHeading, Skeleton, useToast } from "../../components/ui";
import { EventCollaborators } from "./EventCollaborators";
import { EventOrganizers } from "./EventOrganizers";
import { EventFields, emptyEventForm, payloadFor, valuesFor } from "./EventFormFields";
import { EventFeedbackPanel } from "./EventFeedbackPanel";
import { EventRegistrationRoster } from "./EventRegistrationRoster";
import { EventStatusChip } from "./EventStatusChip";
import { ImageUploader } from "./ImageUploader";
import {
  useCancelEvent,
  useCompleteEvent,
  useEvent,
  useEventInvalidation,
  usePublishEvent,
  useUpdateEvent,
} from "./eventsApi";
import type { EventPatch } from "./eventsApi";
import { eventDateTime, eventErrorText } from "./eventUi";
import { useMakerspaceCurrency } from "./paymentsApi";

type Action = "publish" | "cancel" | "complete";

const CONFIRM: Record<Action, { title: string; message: string; label: string; done: string }> = {
  publish: { title: "Publish event?", message: "The event opens for sign-ups and, if it is public, appears on the Events page.", label: "Publish event", done: "Event published" },
  complete: { title: "Mark the event as completed?", message: "Sign-ups close and the event becomes read-only.", label: "Complete event", done: "Event completed" },
  cancel: { title: "Cancel event?", message: "Sign-ups close and the event becomes read-only. This can't be undone.", label: "Cancel event", done: "Event cancelled" },
};

export function EventDrawer({ eventId, makerspaceId, onClose }: {
  eventId: number;
  makerspaceId: number;
  onClose: () => void;
}) {
  const { showToast } = useToast();
  const eventQuery = useEvent(eventId);
  const event = eventQuery.data;
  const [values, setValues] = useState(emptyEventForm);
  const [confirm, setConfirm] = useState<Action | null>(null);
  const update = useUpdateEvent(makerspaceId, eventId);
  const publish = usePublishEvent(makerspaceId, eventId);
  const cancel = useCancelEvent(makerspaceId, eventId);
  const complete = useCompleteEvent(makerspaceId, eventId);
  const invalidateEvent = useEventInvalidation(makerspaceId, eventId);
  const currency = useMakerspaceCurrency(makerspaceId);

  useEffect(() => { if (event) setValues(valuesFor(event)); }, [event?.updated_at]);
  const lifecycle = confirm === "publish" ? publish : confirm === "cancel" ? cancel : complete;
  const readOnly = event?.status === "cancelled" || event?.status === "completed";
  const actionError = update.error || publish.error || cancel.error || complete.error;
  const failed = (error: unknown) => showToast(eventErrorText(error), { tone: "error" });
  const saveOccurrence = () => {
    if (!event) return;
    const next = payloadFor(values);
    const current = payloadFor(valuesFor(event));
    const changed = Object.fromEntries(
      Object.entries(next).filter(([key, value]) => JSON.stringify(value) !== JSON.stringify(current[key as keyof typeof current])),
    ) as EventPatch;
    update.mutate(changed, { onSuccess: () => showToast("Event saved", { tone: "success" }), onError: failed });
  };
  const resetField = (field: string) => update.mutate({ inherit_fields: [field] }, {
    onSuccess: () => showToast(`${fieldLabel(field)} follows the series again`, { tone: "success" }),
    onError: failed,
  });
  const runLifecycle = () => {
    if (!confirm) return;
    const done = CONFIRM[confirm].done;
    lifecycle.mutate(undefined, {
      onSuccess: () => { setConfirm(null); showToast(done, { tone: "success" }); },
      onError: (error) => { setConfirm(null); failed(error); },
    });
  };

  return <>
    <DetailDrawer open title={event?.title ?? "Event details"} onClose={onClose}>
      {eventQuery.isLoading ? <Skeleton className="h-64 w-full" /> : null}
      {eventQuery.error ? <EmptyState tone="error" title="Couldn't load this event" description={eventErrorText(eventQuery.error)} /> : null}
      {event ? <div className="grid gap-6">
        <div className="grid gap-2">
          <div className="flex flex-wrap items-center gap-2">
            <EventStatusChip status={event.status} size="md" />
            {event.series_summary ? <Chip tone="secondary">Series · {event.series_summary.title}</Chip> : null}
          </div>
          <p className="text-body-ui text-ink-secondary">
            {event.capacity === 0 ? "Unlimited capacity" : `${event.capacity} places`} · Sign-ups {event.registration_open ? "open" : "closed"}
            {event.effective_registration_cutoff_at ? ` · Closes ${eventDateTime(event.effective_registration_cutoff_at)}` : ""}
          </p>
        </div>
        <ImageUploader endpoint={`/admin/events/${eventId}/image`} currentUrl={event.image_url} label="Event photo (shown publicly)" shape="wide" disabled={readOnly} onChanged={invalidateEvent} />
        <form className="grid gap-4" onSubmit={(e) => { e.preventDefault(); saveOccurrence(); }}>
          <SectionHeading as="h3" title={event.series_summary ? "Edit this date" : "Details"} description={event.series_summary ? "Changes here apply to this date only." : undefined} />
          <EventFields values={values} setValues={setValues} disabled={readOnly} approvalLocked={event.status !== "draft"} currency={currency} />
          {!readOnly ? (
            <div><Button variant={event.status === "draft" ? "secondary" : "primary"} type="submit" loading={update.isPending} loadingLabel="Saving…">Save changes</Button></div>
          ) : <p className="text-body-ui text-ink-muted">Completed and cancelled events are read-only.</p>}
        </form>
        {event.series_summary && event.series_override_fields.length && !readOnly ? (
          <section className="grid gap-3">
            <SectionHeading as="h3" title="Changed from the series" description="Reset a field so this date follows the series again." />
            <div className="flex flex-wrap gap-2">
              {event.series_override_fields.map((field) => (
                <Button key={field} size="sm" disabled={update.isPending} onClick={() => resetField(field)}>Reset {field.replace(/_/g, " ")}</Button>
              ))}
            </div>
          </section>
        ) : null}
        {event.status === "draft" || event.status === "published" ? (
          <div className="flex flex-wrap gap-2.5">
            {event.status === "draft" ? <Button variant="primary" onClick={() => setConfirm("publish")}>Publish</Button> : null}
            {event.status === "published" ? <>
              <Button onClick={() => setConfirm("complete")}>Complete</Button>
              <Button variant="danger" onClick={() => setConfirm("cancel")}>Cancel event…</Button>
            </> : null}
          </div>
        ) : null}
        <ErrorText message={actionError ? eventErrorText(actionError) : null} />
        <EventRegistrationRoster event={event} makerspaceId={makerspaceId} offlineCheckInEnabled={event.offline_checkin_enabled} />
        <EventFeedbackPanel eventId={eventId} makerspaceId={makerspaceId} />
        <EventOrganizers event={event} makerspaceId={makerspaceId} disabled={readOnly} />
        <EventCollaborators makerspaceId={makerspaceId} eventId={eventId} />
      </div> : null}
    </DetailDrawer>
    <ConfirmDialog
      open={confirm !== null}
      title={confirm ? CONFIRM[confirm].title : "Change event?"}
      message={confirm ? CONFIRM[confirm].message : undefined}
      confirmLabel={confirm ? CONFIRM[confirm].label : "Confirm"}
      cancelLabel={confirm === "cancel" ? "Keep event" : "Cancel"}
      tone={confirm === "cancel" ? "danger" : "default"}
      pending={lifecycle.isPending}
      onCancel={() => setConfirm(null)}
      onConfirm={runLifecycle}
    />
  </>;
}

function fieldLabel(field: string) {
  const words = field.replace(/_/g, " ");
  return words.charAt(0).toUpperCase() + words.slice(1);
}
