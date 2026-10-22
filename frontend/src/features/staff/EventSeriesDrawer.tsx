import { useEffect, useState, type FormEvent } from "react";

import { Button, Callout, ConfirmDialog, DetailDrawer, EmptyState, ErrorText, SectionHeading, Skeleton, useToast } from "../../components/ui";
import { EventSeriesCollaborators } from "./EventSeriesCollaborators";
import { EventStatusChip } from "./EventStatusChip";
import { ImageUploader } from "./ImageUploader";
import { EventSeriesFields, emptySeriesForm, seriesPayload, valuesForSeries } from "./EventSeriesForm";
import {
  useEventSeries,
  useEventSeriesAction,
  useEventSeriesOccurrences,
  useUpdateEventSeries,
} from "./eventSeriesApi";
import { eventDateTime, eventErrorText } from "./eventUi";

type Action = "publish" | "cancel" | "complete" | "extend";

const CONFIRM: Record<Action, { title: string; message: string; label: string; done: string }> = {
  publish: { title: "Publish series?", message: "Every upcoming date opens for sign-ups.", label: "Publish series", done: "Series published" },
  extend: { title: "Add upcoming dates now?", message: "New dates are created from the current schedule straight away.", label: "Extend now", done: "Upcoming dates added" },
  complete: { title: "Complete series?", message: "No new dates are created and upcoming dates close.", label: "Complete series", done: "Series completed" },
  cancel: { title: "Cancel series?", message: "The series and its upcoming dates are cancelled. This can't be undone.", label: "Cancel series", done: "Series cancelled" },
};

export function EventSeriesDrawer({ seriesId, makerspaceId, onClose, onSelectOccurrence }: {
  seriesId: number; makerspaceId: number; onClose: () => void;
  onSelectOccurrence: (eventId: number) => void;
}) {
  const { showToast } = useToast();
  const query = useEventSeries(seriesId);
  const occurrences = useEventSeriesOccurrences(seriesId);
  const update = useUpdateEventSeries(makerspaceId, seriesId);
  const [values, setValues] = useState(emptySeriesForm);
  const [confirm, setConfirm] = useState<Action | null>(null);
  const publish = useEventSeriesAction(makerspaceId, seriesId, "publish");
  const cancel = useEventSeriesAction(makerspaceId, seriesId, "cancel");
  const complete = useEventSeriesAction(makerspaceId, seriesId, "complete");
  const extend = useEventSeriesAction(makerspaceId, seriesId, "extend");
  const action = confirm === "publish" ? publish : confirm === "cancel" ? cancel : confirm === "complete" ? complete : extend;
  useEffect(() => { if (query.data) setValues(valuesForSeries(query.data)); }, [query.data?.updated_at]);
  const series = query.data;
  const terminal = series?.status === "cancelled" || series?.status === "completed";
  const submit = (event: FormEvent) => {
    event.preventDefault();
    const payload = seriesPayload(values);
    update.mutate({ ...payload, ...(series?.status === "published" ? { effective_from: new Date().toISOString() } : {}) }, {
      onSuccess: () => showToast("Series saved for upcoming dates", { tone: "success" }),
      onError: (error) => showToast(eventErrorText(error), { tone: "error" }),
    });
  };
  const runAction = () => {
    if (!confirm) return;
    const done = CONFIRM[confirm].done;
    action.mutate(undefined, {
      onSuccess: () => showToast(done, { tone: "success" }),
      onError: (error) => showToast(eventErrorText(error), { tone: "error" }),
      onSettled: () => setConfirm(null),
    });
  };

  return <>
    <DetailDrawer open title={series?.title ?? "Series"} onClose={onClose}>
      {query.isLoading ? <Skeleton className="h-64 w-full" /> : null}
      {query.error ? <EmptyState tone="error" title="Couldn't load this series" description={eventErrorText(query.error)} /> : null}
      {series ? <div className="grid gap-6">
        <div className="flex flex-wrap items-center gap-2">
          <EventStatusChip status={series.status} size="md" />
          <span className="text-body-ui text-ink-secondary">{series.future_occurrence_count} upcoming dates · revision {series.revision}</span>
        </div>
        {series.last_generation_error_code ? (
          <Callout tone="danger" role="alert" title="New dates couldn't be added automatically.">
            Correct the schedule, then use Extend now. Code: <span className="font-mono">{series.last_generation_error_code}</span>
          </Callout>
        ) : null}
        <ImageUploader endpoint={`/admin/event-series/${seriesId}/image`} currentUrl={series.image_url} label="Series photo (inherited by occurrences)" shape="wide" disabled={terminal} onChanged={() => query.refetch()} />
        <form className="grid gap-4" onSubmit={submit}>
          <SectionHeading as="h3" title="Edit upcoming dates" description="Changes apply to every date that hasn't started yet." />
          <EventSeriesFields values={values} setValues={setValues} disabled={terminal} />
          {!terminal ? (
            <div><Button variant={series.status === "draft" ? "secondary" : "primary"} type="submit" loading={update.isPending} loadingLabel="Saving…">Save future occurrences</Button></div>
          ) : null}
        </form>
        {series.status === "draft" || series.status === "published" ? (
          <div className="flex flex-wrap gap-2.5">
            {series.status === "draft" ? <Button variant="primary" onClick={() => setConfirm("publish")}>Publish series</Button> : null}
            {series.status === "published" ? <>
              <Button onClick={() => setConfirm("extend")}>Extend now</Button>
              <Button onClick={() => setConfirm("complete")}>Complete series</Button>
              <Button variant="danger" onClick={() => setConfirm("cancel")}>Cancel series…</Button>
            </> : null}
          </div>
        ) : null}
        <ErrorText message={update.error || action.error ? eventErrorText(update.error || action.error) : null} />
        <section className="grid gap-3">
          <SectionHeading as="h3" title="Dates" description="Choose one date to edit or cancel only that date." />
          {occurrences.isLoading ? <Skeleton className="h-24 w-full" /> : null}
          {occurrences.data && !occurrences.data.results.length ? <EmptyState title="No dates yet" description="Publish the series to create its upcoming dates." /> : null}
          {occurrences.data?.results.length ? (
            <ul className="divide-y divide-line overflow-hidden rounded-lg border border-line">
              {occurrences.data.results.map((row) => (
                <li key={row.id}>
                  <button
                    className="flex w-full items-center justify-between gap-3 px-4 py-3 text-left text-body-ui text-ink transition-colors hover:bg-subtle focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-focus"
                    type="button"
                    onClick={() => onSelectOccurrence(row.id)}
                  >
                    <span>{eventDateTime(row.starts_at)}</span>
                    <EventStatusChip status={row.status} />
                  </button>
                </li>
              ))}
            </ul>
          ) : null}
        </section>
        <EventSeriesCollaborators seriesId={seriesId} makerspaceId={makerspaceId} />
      </div> : null}
    </DetailDrawer>
    <ConfirmDialog
      open={confirm !== null}
      title={confirm ? CONFIRM[confirm].title : "Change series?"}
      message={confirm ? CONFIRM[confirm].message : undefined}
      confirmLabel={confirm ? CONFIRM[confirm].label : "Confirm"}
      cancelLabel={confirm === "cancel" ? "Keep series" : "Cancel"}
      tone={confirm === "cancel" ? "danger" : "default"}
      pending={action.isPending}
      onCancel={() => setConfirm(null)}
      onConfirm={runAction}
    />
  </>;
}
