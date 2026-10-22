import { useState } from "react";

import { MakerspaceSiteHeader } from "../../components/chrome/PublicHeaders";
import { PublicContainer, PublicShell } from "../../components/chrome/PublicShell";
import { Button, Chip, EmptyState, PageHeader, Skeleton } from "../../components/ui";
import { useModules } from "../../lib/modules";
import { PublicLoadError } from "../inventory/PublicInventoryParts";
import { useMakerspacePublic } from "../inventory/useMakerspacePublic";
import { PublicBookingForm } from "./PublicBookingForm";
import { usePublicSpaces, type PublicBookableSpace } from "./publicBookingsApi";

const KIND_LABELS: Record<PublicBookableSpace["kind"], string> = {
  dev_room: "Development room",
  bench: "Bench",
  meeting: "Meeting room",
  other: "Other",
};

export function PublicBookingsPage() {
  const space = useMakerspacePublic();
  const { makerspaceSlug } = space;
  const modules = useModules();
  const spaces = usePublicSpaces(makerspaceSlug);
  const [activeToken, setActiveToken] = useState<string | null>(null);

  return (
    <PublicShell header={<MakerspaceSiteHeader {...space.header} moduleEnabled={modules.moduleEnabled} page="Bookings" />}>
      <PublicContainer width="md">
        <PageHeader kicker="Space bookings" title="Book a makerspace" description="Choose a public space, check published bookings and request a time." />
        <div className="mt-8 grid gap-5">
          {spaces.isLoading ? (
            <div className="grid gap-5" aria-busy="true" aria-label="Loading spaces">
              {[0, 1, 2].map((item) => <Skeleton key={item} className="h-64 w-full rounded-lg" />)}
            </div>
          ) : null}
          {spaces.error ? <PublicLoadError error={spaces.error} noun="bookings" onRetry={() => spaces.refetch()} /> : null}
          {spaces.data && !spaces.data.length ? (
            <EmptyState title="No spaces available" description="Public bookable spaces will appear here when they are enabled." />
          ) : null}
          {spaces.data?.map((item) => {
            const open = activeToken === item.public_token;
            return (
              <article key={item.public_token} className="min-w-0 overflow-hidden rounded-lg border border-line bg-canvas">
                {item.image_url ? <img className="aspect-[16/7] w-full border-b border-line object-cover" src={item.image_url} alt="" loading="lazy" /> : null}
                <div className="min-w-0 p-5 [overflow-wrap:anywhere] sm:p-6">
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div className="min-w-0">
                      <h2 className="text-h4 text-ink">{item.name}</h2>
                      {item.location ? <p className="mt-1 text-body-ui text-ink-muted">{item.location}</p> : null}
                    </div>
                    <Chip size="sm">{KIND_LABELS[item.kind]}</Chip>
                  </div>
                  {item.description ? <p className="mt-4 whitespace-pre-wrap text-body-ui text-ink-secondary">{item.description}</p> : null}
                  <dl className="mt-4 grid gap-3 rounded-lg bg-subtle p-4 sm:grid-cols-2">
                    <div>
                      <dt className="text-caption text-ink-muted">Capacity</dt>
                      <dd className="mt-0.5 text-label text-ink">{item.capacity === 0 ? "Not specified" : item.capacity}</dd>
                    </div>
                    <div>
                      <dt className="text-caption text-ink-muted">Confirmation</dt>
                      <dd className="mt-0.5 text-label text-ink">{item.approval_mode === "approve" ? "Staff approval required" : "Instant when available"}</dd>
                    </div>
                  </dl>
                  <p className="mt-3 text-caption text-ink-muted">
                    {item.approval_mode === "approve" ? "Your request stays pending until makerspace staff review it." : "A non-overlapping slot is confirmed immediately."}
                  </p>
                  <Button className="mt-4" aria-expanded={open} onClick={() => setActiveToken(open ? null : item.public_token)}>
                    {open ? "Close booking form" : "Choose a time"}
                  </Button>
                  {open ? <div className="mt-5"><PublicBookingForm key={item.public_token} makerspaceSlug={makerspaceSlug} space={item} /></div> : null}
                </div>
              </article>
            );
          })}
        </div>
      </PublicContainer>
    </PublicShell>
  );
}
