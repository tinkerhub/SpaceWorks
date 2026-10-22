import { useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { MakerspaceSiteHeader } from "../../components/chrome/PublicHeaders";
import { PublicContainer, PublicShell } from "../../components/chrome/PublicShell";
import { EmptyState, PageHeader, SectionHeading, Skeleton, useToast } from "../../components/ui";
import type { ApiPath } from "../../generated/api";
import { StructuredApiError, tenantPublicRequest, tenantPublicRequestBlob } from "../../lib/api";
import { useModules } from "../../lib/modules";
import { PublicEventCard, type PublicEvent } from "./PublicEventCard";
import { PublicLoadError } from "./PublicInventoryParts";
import { useMakerspacePublic } from "./useMakerspacePublic";

const PUBLIC_EVENTS_PATH: ApiPath = "/api/v1/public/{makerspace_slug}/events/";

function publicEventsPath(slug: string) {
  return PUBLIC_EVENTS_PATH.replace("/api/v1", "").replace("{makerspace_slug}", encodeURIComponent(slug));
}

export function PublicEventsPage() {
  const space = useMakerspacePublic();
  const { makerspaceSlug } = space;
  const { moduleEnabled } = useModules();
  const { showToast } = useToast();
  const [activeToken, setActiveToken] = useState<string | null>(null);
  const [calendarToken, setCalendarToken] = useState<string | null>(null);
  const [calendarError, setCalendarError] = useState<{ token: string; message: string } | null>(null);
  const events = useQuery({
    queryKey: ["public-events", makerspaceSlug],
    queryFn: () => tenantPublicRequest<PublicEvent[]>(makerspaceSlug, publicEventsPath(makerspaceSlug)),
    retry: (count, error) => !(error instanceof StructuredApiError && error.status < 500) && count < 2,
  });
  const groupedEvents = (events.data ?? []).reduce<Array<{
    key: string; title: string | null; items: PublicEvent[];
  }>>((groups, item) => {
    const key = item.series?.public_token ?? item.public_token;
    const group = groups.find((candidate) => candidate.key === key);
    if (group) group.items.push(item);
    else groups.push({ key, title: item.series?.title ?? null, items: [item] });
    return groups;
  }, []);

  async function downloadCalendar(item: PublicEvent) {
    setCalendarToken(item.public_token);
    setCalendarError(null);
    try {
      const path = `${publicEventsPath(makerspaceSlug)}${item.public_token}/calendar.ics`;
      const blob = await tenantPublicRequestBlob(makerspaceSlug, path);
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `${item.title.replace(/[^A-Za-z0-9._-]+/g, "-") || "event"}.ics`;
      link.click();
      URL.revokeObjectURL(url);
    } catch (cause) {
      setCalendarError({ token: item.public_token, message: cause instanceof Error ? cause.message : "Could not download this calendar." });
      showToast("Calendar file didn't download", { tone: "error" });
    } finally {
      setCalendarToken(null);
    }
  }

  return (
    <PublicShell header={<MakerspaceSiteHeader {...space.header} moduleEnabled={moduleEnabled} page="Events" />}>
      <PublicContainer width="md">
        <PageHeader kicker="Public events" title="Upcoming events" description="Register for workshops, meetups and community sessions." />
        <div className="mt-8 grid gap-8">
          {events.isLoading ? (
            <div className="grid gap-5" aria-busy="true" aria-label="Loading events">
              {[0, 1, 2].map((item) => <Skeleton key={item} className="h-52 w-full rounded-lg" />)}
            </div>
          ) : null}
          {events.error ? <PublicLoadError error={events.error} noun="events" onRetry={() => events.refetch()} /> : null}
          {events.data && !events.data.length ? (
            <EmptyState title="No upcoming events" description="New public events will appear here when they are published." />
          ) : null}
          {groupedEvents.map((group) => (
            <section key={group.key} aria-label={group.title ?? undefined} className="grid gap-4">
              {group.title ? <SectionHeading title={group.title} description="Recurring series" className="[overflow-wrap:anywhere]" /> : null}
              {group.items.map((item) => {
                const open = activeToken === item.public_token;
                return (
                  <PublicEventCard
                    key={item.public_token}
                    event={item}
                    makerspaceSlug={makerspaceSlug}
                    open={open}
                    onToggle={() => setActiveToken(open ? null : item.public_token)}
                    calendarPending={calendarToken === item.public_token}
                    calendarError={calendarError?.token === item.public_token ? calendarError.message : undefined}
                    onDownloadCalendar={() => downloadCalendar(item)}
                  />
                );
              })}
            </section>
          ))}
        </div>
      </PublicContainer>
    </PublicShell>
  );
}
