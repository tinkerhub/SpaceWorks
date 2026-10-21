import { useState } from "react";

import { Button, Card, EmptyState, ErrorText, SectionHeading, Skeleton } from "../../components/ui";
import { EventCertificateActions } from "./EventCertificateActions";
import { useEventFeedbackResponses } from "./eventFeedbackApi";
import { eventErrorText } from "./eventUi";

export function EventFeedbackResponses({ eventId, makerspaceId, responseCount }: {
  eventId: number;
  makerspaceId: number;
  responseCount: number;
}) {
  const [page, setPage] = useState(1);
  const responses = useEventFeedbackResponses(eventId, page, true);
  const results = responses.data?.results ?? [];
  return (
    <div className="grid gap-3">
      <SectionHeading as="h3" title={`Responses (${responses.data?.count ?? responseCount})`} />
      {responses.isLoading ? <Skeleton className="h-24 w-full" /> : null}
      {responses.error ? <ErrorText message={eventErrorText(responses.error)} /> : null}
      {responses.data && !results.length ? <EmptyState title="No responses yet" description="Open responses after the event and attendees can answer from their event page." /> : null}
      {results.map((response) => (
        <Card as="article" key={response.id} padding="sm">
          <p className="text-label text-ink">{response.identity?.name ?? "Anonymous response"}</p>
          <p className="text-caption text-ink-muted">{new Date(response.created_at).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" })}</p>
          <dl className="mt-3 grid gap-2">
            {response.answers.answers.map((answer) => (
              <div key={answer.id}>
                <dt className="text-caption font-semibold text-ink-muted">{answer.label}</dt>
                <dd className="whitespace-pre-wrap text-body-ui text-ink">{Array.isArray(answer.value) ? answer.value.join(", ") : String(answer.value)}</dd>
              </div>
            ))}
          </dl>
          {response.certificate ? <EventCertificateActions certificate={response.certificate} eventId={eventId} makerspaceId={makerspaceId} /> : null}
        </Card>
      ))}
      {responses.data?.previous || responses.data?.next ? (
        <div className="flex flex-wrap items-center justify-end gap-2 text-body-ui text-ink-muted">
          <span className="mr-auto tabular-nums">Page {page}</span>
          <Button size="sm" disabled={!responses.data?.previous} onClick={() => setPage((value) => Math.max(1, value - 1))}>Previous</Button>
          <Button size="sm" disabled={!responses.data?.next} onClick={() => setPage((value) => value + 1)}>Next</Button>
        </div>
      ) : null}
    </div>
  );
}
