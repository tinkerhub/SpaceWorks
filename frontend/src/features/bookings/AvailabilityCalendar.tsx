import { useMemo, useState } from "react";

import { ChevronLeft, ChevronRight } from "lucide-react";

import { Button, Skeleton } from "../../components/ui";
import { usePublicAvailability } from "./publicBookingsApi";

const WINDOW_DAYS = 14;

function windowDates(offset: number) {
  const start = new Date();
  start.setHours(0, 0, 0, 0);
  start.setDate(start.getDate() + offset * WINDOW_DAYS);
  const end = new Date(start);
  end.setDate(end.getDate() + WINDOW_DAYS);
  return { startsAt: start.toISOString(), endsAt: end.toISOString() };
}

function rangeLabel(startsAt: string, endsAt: string) {
  const format = new Intl.DateTimeFormat(undefined, { dateStyle: "medium" });
  const inclusiveEnd = new Date(new Date(endsAt).getTime() - 1);
  return `${format.format(new Date(startsAt))} – ${format.format(inclusiveEnd)}`;
}

function intervalLabel(startsAt: string, endsAt: string) {
  const format = new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" });
  return `${format.format(new Date(startsAt))} – ${format.format(new Date(endsAt))}`;
}

export function AvailabilityCalendar({ makerspaceSlug, publicToken }: {
  makerspaceSlug: string;
  publicToken: string;
}) {
  const [offset, setOffset] = useState(0);
  const window = useMemo(() => windowDates(offset), [offset]);
  const availability = usePublicAvailability(makerspaceSlug, publicToken, window.startsAt, window.endsAt);

  return (
    <section className="min-w-0 rounded-lg border border-line bg-canvas p-4 [overflow-wrap:anywhere] sm:p-5" aria-labelledby={"availability-" + publicToken}>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="min-w-0 max-w-full">
          <h3 id={"availability-" + publicToken} className="text-title text-ink">Published availability</h3>
          <p className="mt-0.5 text-caption text-ink-muted">{rangeLabel(window.startsAt, window.endsAt)}</p>
        </div>
        <div className="flex min-w-0 flex-wrap gap-2">
          <Button size="sm" startIcon={<ChevronLeft />} disabled={offset === 0} onClick={() => setOffset((value) => Math.max(0, value - 1))}>Previous 14 days</Button>
          <Button size="sm" endIcon={<ChevronRight />} onClick={() => setOffset((value) => value + 1)}>Next 14 days</Button>
        </div>
      </div>
      {availability.isLoading ? (
        <div className="mt-3 grid gap-2" aria-live="polite" aria-busy="true">
          <span className="sr-only">Checking confirmed bookings…</span>
          <Skeleton className="h-10 w-full" />
          <Skeleton className="h-10 w-full" />
        </div>
      ) : null}
      {availability.error ? (
        <div className="mt-3 flex flex-wrap items-center gap-2" role="alert">
          <p className="text-body-ui text-danger-fg">Availability could not be checked. This does not mean the space is free.</p>
          <Button size="sm" onClick={() => availability.refetch()}>Retry</Button>
        </div>
      ) : null}
      {availability.data?.availability === null ? (
        <p className="mt-3 text-body-ui text-ink-muted">Availability is not published. You may still submit your selected time for the makerspace to check.</p>
      ) : null}
      {availability.data?.availability?.length === 0 ? (
        <p className="mt-3 rounded-md border-[1.5px] border-dashed border-line-strong px-3 py-3 text-body-ui text-ink-muted">No confirmed bookings are published in this window.</p>
      ) : null}
      {availability.data?.availability?.length ? (
        <ul className="mt-3 divide-y divide-line rounded-md border border-line">
          {availability.data.availability.map((interval) => (
            <li className="flex flex-wrap items-center gap-x-3 gap-y-1 px-3 py-2.5 text-body-ui text-ink" key={interval.starts_at + interval.ends_at}>
              <span className="inline-flex items-center gap-2 rounded-full bg-warning-bg px-2.5 py-0.5 text-xs font-semibold text-warning-fg">Booked</span>
              <time dateTime={interval.starts_at}>{intervalLabel(interval.starts_at, interval.ends_at)}</time>
              {interval.booker_name !== null ? <span className="font-semibold">{interval.booker_name}</span> : null}
            </li>
          ))}
        </ul>
      ) : null}
    </section>
  );
}
