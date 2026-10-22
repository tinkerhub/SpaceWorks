import { useState } from "react";
import { Plus } from "lucide-react";

import {
  Button,
  EmptyState,
  ErrorText,
  SkeletonRows,
  TBody,
  TD,
  TH,
  THead,
  TR,
  Table,
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from "../../components/ui";
import { StructuredApiError } from "../../lib/api";
import { CollaborationInbox } from "./CollaborationInbox";
import { EventCreateDialog } from "./EventCreateDialog";
import { EventDrawer } from "./EventDrawer";
import { EventSeriesDrawer } from "./EventSeriesDrawer";
import { EventSeriesCollaborationInbox } from "./EventSeriesCollaborationInbox";
import { EventStatusChip } from "./EventStatusChip";
import { eventDateTime, eventErrorText } from "./eventUi";
import { useEvents, type StaffEvent } from "./eventsApi";
import { useEventSeriesList } from "./eventSeriesApi";
import { Panel } from "./panels/shared";

export { EventDrawer };

const DESCRIPTION = "Create events and series, review applications and record attendance.";
const ROW_LINK =
  "text-left font-semibold text-ink underline-offset-4 hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus";

function dateRange(event: StaffEvent) {
  return `${eventDateTime(event.starts_at)} – ${eventDateTime(event.ends_at)}`;
}

export function EventsPanel({ makerspaceId }: { makerspaceId: number }) {
  const [page, setPage] = useState(1);
  const events = useEvents(makerspaceId, page);
  const series = useEventSeriesList(makerspaceId);
  const [view, setView] = useState("events");
  const [creating, setCreating] = useState(false);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [selectedSeriesId, setSelectedSeriesId] = useState<number | null>(null);

  const apiError = events.error instanceof StructuredApiError ? events.error : null;
  if (apiError?.status === 403) {
    return <Panel title="Events" description={DESCRIPTION}><EmptyState title="Permission required" description="Event management access is required." /></Panel>;
  }
  if (apiError?.status === 400) {
    return <Panel title="Events" description={DESCRIPTION}><EmptyState title="Events module unavailable" description={apiError.message} /></Panel>;
  }

  const newEvent = <Button variant="primary" startIcon={<Plus />} onClick={() => setCreating(true)}>New event</Button>;
  const createAgain = <Button onClick={() => setCreating(true)}>New event</Button>;

  return <Panel title="Events" description={DESCRIPTION} actions={newEvent}>
    <div className="grid gap-6">
      <CollaborationInbox makerspaceId={makerspaceId} />
      <EventSeriesCollaborationInbox makerspaceId={makerspaceId} />
      <Tabs value={view} onValueChange={setView}>
        <TabsList aria-label="Event views">
          <TabsTrigger value="events">Events</TabsTrigger>
          <TabsTrigger value="series">Series</TabsTrigger>
        </TabsList>
        <TabsContent value="events" className="grid gap-3">
          {events.error ? (
            <EmptyState tone="error" title="Couldn't load events" description={eventErrorText(events.error)} action={<Button onClick={() => events.refetch()}>Try again</Button>} />
          ) : null}
          {events.data && !events.data.results.length ? (
            <EmptyState title="No events yet" description="Create a draft event, then publish it when it is ready for sign-ups." action={createAgain} />
          ) : null}
          {events.isLoading || events.data?.results.length ? (
            <Table label="Events">
              <caption className="sr-only">Events in chronological order</caption>
              <THead><TR><TH>Event</TH><TH>Status</TH><TH>Capacity</TH><TH>Registrations</TH></TR></THead>
              <TBody aria-busy={events.isLoading || undefined}>
                {events.isLoading ? <SkeletonRows rows={3} cols={4} /> : null}
                {events.data?.results.map((item) => (
                  <TR key={item.id}>
                    <TD>
                      <button className={ROW_LINK} type="button" onClick={() => setSelectedId(item.id)}>{item.title}</button>
                      <span className="mt-0.5 block text-caption text-ink-muted">{dateRange(item)}{item.location ? ` · ${item.location}` : ""}</span>
                    </TD>
                    <TD><EventStatusChip status={item.status} /></TD>
                    <TD className="tabular-nums">{item.capacity === 0 ? "Unlimited" : item.capacity}</TD>
                    <TD className="tabular-nums">
                      {item.registration_counts.registered + item.registration_counts.attended} confirmed · {item.registration_counts.pending_approval} pending
                    </TD>
                  </TR>
                ))}
              </TBody>
            </Table>
          ) : null}
          {events.data && (events.data.previous || events.data.next) ? (
            <div className="flex flex-wrap items-center justify-end gap-2 text-sm text-ink-muted">
              <span className="mr-auto tabular-nums">{events.data.count} events</span>
              <Button size="sm" disabled={!events.data.previous} onClick={() => setPage((current) => Math.max(1, current - 1))}>Previous</Button>
              <span className="px-1 tabular-nums">Page {page}</span>
              <Button size="sm" disabled={!events.data.next} onClick={() => setPage((current) => current + 1)}>Next</Button>
            </div>
          ) : null}
        </TabsContent>
        <TabsContent value="series" className="grid gap-3">
          <ErrorText message={series.error ? eventErrorText(series.error) : null} />
          {series.data && !series.data.results.length ? (
            <EmptyState title="No series yet" description="A series repeats on a schedule, like a weekly class. Choose Series under New event to start one." action={createAgain} />
          ) : null}
          {series.isLoading || series.data?.results.length ? (
            <Table label="Series">
              <THead><TR><TH>Series</TH><TH>Status</TH><TH>Next date</TH><TH>Upcoming dates</TH></TR></THead>
              <TBody aria-busy={series.isLoading || undefined}>
                {series.isLoading ? <SkeletonRows rows={2} cols={4} /> : null}
                {series.data?.results.map((row) => (
                  <TR key={row.id}>
                    <TD><button className={ROW_LINK} type="button" onClick={() => setSelectedSeriesId(row.id)}>{row.title}</button></TD>
                    <TD><EventStatusChip status={row.status} /></TD>
                    <TD className="text-ink-secondary">{row.next_occurrence_at ? eventDateTime(row.next_occurrence_at) : "No future date"}</TD>
                    <TD className="tabular-nums">{row.future_occurrence_count}</TD>
                  </TR>
                ))}
              </TBody>
            </Table>
          ) : null}
        </TabsContent>
      </Tabs>
    </div>
    <EventCreateDialog
      makerspaceId={makerspaceId}
      open={creating}
      onClose={() => setCreating(false)}
      onCreatedEvent={(id) => { setCreating(false); setView("events"); setSelectedId(id); }}
      onCreatedSeries={(id) => { setCreating(false); setView("series"); setSelectedSeriesId(id); }}
    />
    {selectedId !== null ? <EventDrawer key={selectedId} eventId={selectedId} makerspaceId={makerspaceId} onClose={() => setSelectedId(null)} /> : null}
    {selectedSeriesId !== null ? (
      <EventSeriesDrawer
        key={selectedSeriesId}
        seriesId={selectedSeriesId}
        makerspaceId={makerspaceId}
        onClose={() => setSelectedSeriesId(null)}
        onSelectOccurrence={(eventId) => { setSelectedSeriesId(null); setSelectedId(eventId); }}
      />
    ) : null}
  </Panel>;
}
