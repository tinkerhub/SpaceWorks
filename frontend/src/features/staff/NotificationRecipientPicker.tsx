import { useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { Card, CardHeader, Dropdown, EmptyState, ErrorBlock, Field, Skeleton } from "../../components/ui";
import { staffRequest } from "../../lib/api";
import { EventRecipients } from "./NotificationRecipientEvent";
import { useScopeOptions } from "./NotificationScopePicker";
import type { RecipientRulesResponse } from "./notificationDestinationTypes";

const FEATURE_LABELS: Record<string, string> = {
  events: "Events",
  bookings: "Bookings",
  maintenance: "Maintenance",
  members: "Members",
};

const RECIPIENTS_KEY = (makerspaceId: number) =>
  ["notification-recipient-rules", makerspaceId] as const;

/** Who hears about one lifecycle event. Empty means the action-based default. */
export function NotificationRecipientPicker({
  makerspaceId,
  delegated = false,
  machinesOn = true,
}: {
  makerspaceId: number;
  delegated?: boolean;
  machinesOn?: boolean;
}) {
  const path = `/admin/makerspace/${makerspaceId}/notification-recipient-rules`;
  const data = useQuery({
    queryKey: RECIPIENTS_KEY(makerspaceId),
    queryFn: () => staffRequest<RecipientRulesResponse>(path),
  });
  const [selected, setSelected] = useState<{ feature: string; event: string } | null>(null);
  const broadOptions = useScopeOptions(makerspaceId, !delegated, machinesOn);
  const options = delegated && data.data
    ? {
        machineTypes: data.data.scope_options.machine_types,
        machines: data.data.scope_options.machines,
        categories: data.data.scope_options.categories,
      }
    : broadOptions;
  const features = data.data?.features ?? [];
  const current = selected ?? (features[0]
    ? { feature: features[0].key, event: features[0].events[0] }
    : null);
  const events = features.find((item) => item.key === current?.feature)?.events ?? [];

  return (
    <Card as="section" aria-labelledby="notification-recipients-heading">
      <CardHeader
        title={<span id="notification-recipients-heading">Who gets notified</span>}
        description={delegated
          ? "Pick recipients for maintenance alerts within your machine scope. Every rule must name at least one reachable machine or machine type."
          : "Pick recipients per event. Leave an event empty to notify everyone whose role covers it, which is the default. Someone who has turned notifications off is never emailed, even when selected."}
      />

      {data.isLoading ? (
        <div className="grid gap-3 sm:grid-cols-2" aria-busy="true" aria-label="Loading recipients">
          <Skeleton className="h-11 w-full" />
          <Skeleton className="h-11 w-full" />
        </div>
      ) : null}
      <ErrorBlock error={data.error} />
      {!data.isLoading && !data.error && features.length === 0 ? (
        <EmptyState
          title="Nothing to set up yet"
          description="None of the modules with selectable recipients are installed."
        />
      ) : null}

      {current ? (
        <div className="grid gap-4">
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Area">
              <Dropdown
                onChange={(changed) => {
                  const feature = changed.target.value;
                  const first = features.find((item) => item.key === feature)?.events[0] ?? "";
                  setSelected({ feature, event: first });
                }}
                value={current.feature}
              >
                {features.map((feature) => (
                  <option key={feature.key} value={feature.key}>
                    {FEATURE_LABELS[feature.key] ?? feature.key}
                  </option>
                ))}
              </Dropdown>
            </Field>
            <Field label="Event">
              <Dropdown
                onChange={(changed) => setSelected({ feature: current.feature, event: changed.target.value })}
                value={current.event}
              >
                {events.map((event) => (
                  <option key={event} value={event}>{sentence(event)}</option>
                ))}
              </Dropdown>
            </Field>
          </div>

          {data.data ? (
            <EventRecipients
              data={data.data}
              delegated={delegated}
              event={current.event}
              feature={current.feature}
              makerspaceId={makerspaceId}
              options={options}
              path={path}
            />
          ) : null}
        </div>
      ) : null}
    </Card>
  );
}

function sentence(value: string) {
  const words = value.replace(/_/g, " ");
  return words.charAt(0).toUpperCase() + words.slice(1);
}
