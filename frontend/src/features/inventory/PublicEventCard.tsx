import { CalendarPlus, MapPin } from "lucide-react";

import { Button, Chip, StatusChip, type StatusTone } from "../../components/ui";
import type { CustomFormSchema } from "../forms/customFormTypes";
import { EventRegistrationForm } from "./EventRegistrationForm";

export type PublicEvent = {
  public_token: string;
  title: string;
  description: string;
  starts_at: string;
  ends_at: string;
  location: string;
  capacity: number | null;
  availability: "Available" | "Limited" | "Full";
  registration_requires_approval: boolean;
  effective_registration_cutoff_at: string | null;
  registration_open: boolean;
  image_url: string | null;
  status: "published";
  custom_form: CustomFormSchema;
  series: { public_token: string; title: string } | null;
};

export const AVAILABILITY_TONE: Record<PublicEvent["availability"], StatusTone> = {
  Available: "success",
  Limited: "warning",
  Full: "danger",
};

function eventTime(event: PublicEvent) {
  const options: Intl.DateTimeFormatOptions = { dateStyle: "medium", timeStyle: "short" };
  return `${new Date(event.starts_at).toLocaleString(undefined, options)} – ${new Date(event.ends_at).toLocaleString(undefined, options)}`;
}

/** Month band over the day number. Decorative: the full date is printed beside it. */
function DateBlock({ iso }: { iso: string }) {
  const date = new Date(iso);
  return (
    <div aria-hidden="true" className="w-14 shrink-0 overflow-hidden rounded-md border border-line bg-canvas text-center">
      <div className="bg-accent py-0.5 text-[11px] font-bold uppercase tracking-[0.08em] text-on-accent">
        {date.toLocaleString(undefined, { month: "short" })}
      </div>
      <div className="py-1 font-display text-2xl font-extrabold leading-tight text-ink">{date.getDate()}</div>
    </div>
  );
}

type PublicEventCardProps = {
  event: PublicEvent;
  makerspaceSlug: string;
  signInHref?: string;
  open: boolean;
  onToggle: () => void;
  calendarPending: boolean;
  calendarError?: string;
  onDownloadCalendar: () => void;
};

/** Event card: cover, date block, title and meta, availability, then register / calendar. */
export function PublicEventCard({ event, makerspaceSlug, signInHref, open, onToggle, calendarPending, calendarError, onDownloadCalendar }: PublicEventCardProps) {
  const unlimited = event.capacity === 0 || event.capacity === null;
  const waitlist = event.availability === "Full";
  const actionLabel = event.registration_requires_approval ? "Apply" : waitlist ? "Join waitlist" : "Register";

  return (
    <article className="min-w-0 overflow-hidden rounded-lg border border-line bg-canvas">
      {/* Decorative: the title beside it already names the event, so alt is empty
          rather than a duplicate announcement for screen-reader users. */}
      {event.image_url ? <img src={event.image_url} alt="" loading="lazy" className="aspect-[16/7] w-full border-b border-line object-cover" /> : null}
      <div className="min-w-0 p-5 [overflow-wrap:anywhere] sm:p-6">
        <div className="flex items-start gap-4">
          <DateBlock iso={event.starts_at} />
          <div className="min-w-0 flex-1">
            <h3 className="text-h4 text-ink">{event.title}</h3>
            <p className="mt-1 text-body-ui text-ink-secondary">
              <time dateTime={event.starts_at}>{eventTime(event)}</time>
            </p>
            {event.location ? (
              <p className="mt-0.5 inline-flex items-center gap-1.5 text-body-ui text-ink-muted">
                <MapPin aria-hidden="true" className="size-4 shrink-0" />
                {event.location}
              </p>
            ) : null}
          </div>
        </div>

        <div className="mt-4 flex flex-wrap gap-2">
          <StatusChip tone={AVAILABILITY_TONE[event.availability]} size="sm">{event.availability}</StatusChip>
          <Chip size="sm">{unlimited ? "Unlimited capacity" : `Capacity ${event.capacity}`}</Chip>
          {event.registration_requires_approval ? <Chip size="sm" tone="info">Approval required</Chip> : null}
        </div>

        {event.description ? <p className="mt-4 whitespace-pre-wrap text-body-ui text-ink-secondary">{event.description}</p> : null}
        {!event.registration_open ? (
          <p className="mt-4 text-label text-ink-muted">
            Registration closed{event.effective_registration_cutoff_at ? ` · ${new Date(event.effective_registration_cutoff_at).toLocaleString()}` : ""}
          </p>
        ) : null}

        <div className="mt-5 flex flex-wrap gap-2.5">
          <Button disabled={!event.registration_open} aria-expanded={open} onClick={onToggle}>
            {open ? "Close form" : actionLabel}
          </Button>
          <Button variant="quiet" startIcon={<CalendarPlus />} loading={calendarPending} loadingLabel="Preparing…" onClick={onDownloadCalendar}>
            Add to calendar
          </Button>
        </div>
        {calendarError ? <p className="mt-2 text-caption text-danger-fg" role="alert">{calendarError}</p> : null}
        {open && event.registration_open ? (
          <div className="mt-5">
            <EventRegistrationForm
              key={event.public_token}
              makerspaceSlug={makerspaceSlug}
              signInHref={signInHref}
              publicToken={event.public_token}
              waitlist={waitlist}
              approvalRequired={event.registration_requires_approval}
              customForm={event.custom_form}
            />
          </div>
        ) : null}
      </div>
    </article>
  );
}
