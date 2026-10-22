import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  Button,
  Card,
  CardHeader,
  Chip,
  ConfirmDialog,
  EmptyState,
  ErrorBlock,
  Skeleton,
  StatusChip,
  useToast,
} from "../../components/ui";
import { staffRequest } from "../../lib/api";
import { CHANNELS, DestinationForm } from "./NotificationDestinationForm";
import { DESTINATIONS_KEY, type NotificationDestination } from "./notificationDestinationTypes";
import { useScopeOptions, type ScopeOptions } from "./NotificationScopePicker";

export { DESTINATIONS_KEY } from "./notificationDestinationTypes";
export { ScopePicker, useScopeOptions } from "./NotificationScopePicker";

/**
 * Rooms a makerspace posts alerts into.
 *
 * Console parity is mandatory here rather than nice to have: `/control/` is not proxied
 * on the public frontend port, so without this panel a space manager has no way to add a
 * room, change its webhook, or scope it to a machine.
 */
export function NotificationDestinations({
  makerspaceId,
  availableChannels,
}: {
  makerspaceId: number;
  /** Channels whose module is installed. A room on an uninstalled channel would accept
   *  the credential and then skip every send, so those options are omitted entirely. */
  availableChannels: string[];
}) {
  const queryClient = useQueryClient();
  const { showToast } = useToast();
  const basePath = `/admin/makerspace/${makerspaceId}/notification-destinations`;
  const [creating, setCreating] = useState(false);
  const [pendingRemove, setPendingRemove] = useState<NotificationDestination | null>(null);

  const destinations = useQuery({
    queryKey: DESTINATIONS_KEY(makerspaceId),
    queryFn: () => staffRequest<NotificationDestination[]>(basePath),
  });
  const options = useScopeOptions(makerspaceId, true, availableChannels.includes("machines"));

  const remove = useMutation({
    mutationFn: (id: number) => staffRequest(`${basePath}/${id}`, { method: "DELETE" }),
    onSuccess: () => {
      setPendingRemove(null);
      showToast("Room removed", { tone: "success" });
    },
    onError: (error) =>
      showToast(error instanceof Error && error.message ? error.message : "Couldn't remove the room", { tone: "error" }),
    onSettled: () =>
      queryClient.invalidateQueries({ queryKey: DESTINATIONS_KEY(makerspaceId) }),
  });

  const usable = CHANNELS.filter((channel) => availableChannels.includes(channel.key));
  const rows = destinations.data ?? [];

  return (
    <Card as="section" aria-labelledby="notification-destinations-heading">
      <CardHeader
        title={<span id="notification-destinations-heading">Rooms</span>}
        description="Each room is one chat destination. A room with nothing selected receives everything; narrow it to send laser faults to the laser team and printer faults to the print room."
        action={
          creating ? null : (
            <Button variant="secondary" size="sm" disabled={usable.length === 0} onClick={() => setCreating(true)}>
              Add a room
            </Button>
          )
        }
      />

      <div className="grid gap-3">
        {destinations.isLoading ? (
          <div className="grid gap-2" aria-busy="true" aria-label="Loading rooms">
            <Skeleton className="h-14 w-full" />
            <Skeleton className="h-14 w-full" />
          </div>
        ) : null}
        <ErrorBlock error={destinations.error} />

        {rows.length ? (
          <ul className="grid gap-2">
            {rows.map((destination) => (
              <li key={destination.id}>
                <DestinationRow
                  basePath={basePath}
                  destination={destination}
                  makerspaceId={makerspaceId}
                  onDelete={() => setPendingRemove(destination)}
                  options={options}
                />
              </li>
            ))}
          </ul>
        ) : null}

        {destinations.data?.length === 0 && !creating ? (
          <EmptyState
            title="No rooms yet"
            description="Until you add a room, alerts go to the chat saved under Integrations."
          />
        ) : null}

        {creating ? (
          <DestinationForm
            basePath={basePath}
            channels={usable}
            makerspaceId={makerspaceId}
            onDone={() => setCreating(false)}
            options={options}
          />
        ) : null}
        {usable.length === 0 ? (
          <p className="text-caption text-ink-muted">No chat modules are installed for this makerspace.</p>
        ) : null}
      </div>

      <ConfirmDialog
        open={pendingRemove !== null}
        title="Remove room?"
        message={pendingRemove ? `${pendingRemove.label} stops receiving alerts and its stored webhook is deleted.` : undefined}
        confirmLabel="Remove room"
        tone="danger"
        pending={remove.isPending}
        onConfirm={() => {
          if (pendingRemove) remove.mutate(pendingRemove.id);
        }}
        onCancel={() => setPendingRemove(null)}
      />
    </Card>
  );
}

function DestinationRow({
  basePath,
  destination,
  makerspaceId,
  onDelete,
  options,
}: {
  basePath: string;
  destination: NotificationDestination;
  makerspaceId: number;
  onDelete: () => void;
  options: ScopeOptions;
}) {
  const [editing, setEditing] = useState(false);
  const scopeCount =
    destination.scope.machine_ids.length +
    destination.scope.machine_type_ids.length +
    destination.scope.category_ids.length;
  const channelLabel = CHANNELS.find((item) => item.key === destination.channel)?.label ?? destination.channel;

  if (editing) {
    return (
      <DestinationForm
        basePath={basePath}
        channels={CHANNELS.filter((channel) => channel.key === destination.channel)}
        destination={destination}
        makerspaceId={makerspaceId}
        onDone={() => setEditing(false)}
        options={options}
      />
    );
  }

  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-2 rounded-lg border border-line bg-canvas px-4 py-3">
      <div className="min-w-0 flex-1">
        <p className="text-label text-ink">{destination.label}</p>
        <p className="text-caption text-ink-muted">
          {channelLabel} · {scopeCount === 0 ? "Everything" : `${scopeCount} scoped`}
        </p>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        {destination.credential_set ? (
          <StatusChip tone="success" size="sm">Configured</StatusChip>
        ) : (
          <StatusChip tone="danger" size="sm">No credential</StatusChip>
        )}
        {destination.is_active ? null : <Chip tone="neutral" size="sm">Paused</Chip>}
      </div>
      <div className="flex gap-2">
        <Button size="sm" variant="secondary" onClick={() => setEditing(true)}>
          Edit
        </Button>
        <Button size="sm" variant="danger" onClick={onDelete} aria-label={`Remove ${destination.label}`}>
          Remove…
        </Button>
      </div>
    </div>
  );
}
