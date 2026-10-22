import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { Button, Dropdown, ErrorText, Field, Input, PasswordInput, SwitchRow, useToast } from "../../components/ui";
import { staffRequest } from "../../lib/api";
import {
  DESTINATIONS_KEY,
  EMPTY_SCOPE,
  type DestinationScope,
  type NotificationDestination,
} from "./notificationDestinationTypes";
import { ScopePicker, type ScopeOptions } from "./NotificationScopePicker";

export const CHANNELS = [
  { key: "slack", label: "Slack" },
  { key: "mattermost", label: "Mattermost" },
  { key: "discord", label: "Discord" },
  { key: "telegram", label: "Telegram" },
] as const;

/** Add or edit one room. The stored webhook can never be read back, only replaced. */
export function DestinationForm({
  basePath,
  channels,
  destination,
  makerspaceId,
  onDone,
  options,
}: {
  basePath: string;
  channels: readonly { key: string; label: string }[];
  destination?: NotificationDestination;
  makerspaceId: number;
  onDone: () => void;
  options: ScopeOptions;
}) {
  const queryClient = useQueryClient();
  const { showToast } = useToast();
  const [channel, setChannel] = useState(destination?.channel ?? channels[0]?.key ?? "slack");
  const [label, setLabel] = useState(destination?.label ?? "");
  const [webhookUrl, setWebhookUrl] = useState("");
  const [chatId, setChatId] = useState(destination?.telegram_chat_id ?? "");
  const [isActive, setIsActive] = useState(destination?.is_active ?? true);
  const [scope, setScope] = useState<DestinationScope>(destination?.scope ?? EMPTY_SCOPE);
  const [error, setError] = useState("");

  const save = useMutation({
    mutationFn: () =>
      staffRequest<NotificationDestination>(
        destination ? `${basePath}/${destination.id}` : basePath,
        {
          method: destination ? "PUT" : "POST",
          body: JSON.stringify({
            channel,
            label,
            // Blank on edit means "keep the stored credential" — it cannot be read back,
            // so requiring it to rename a room would force a re-entry.
            ...(webhookUrl ? { webhook_url: webhookUrl } : {}),
            telegram_chat_id: channel === "telegram" ? chatId : "",
            is_active: isActive,
            scope,
          }),
        },
      ),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: DESTINATIONS_KEY(makerspaceId) });
      showToast(destination ? "Room saved" : "Room added", { tone: "success" });
      onDone();
    },
    onError: (err: unknown) => {
      const message = err instanceof Error && err.message ? err.message : "Couldn't save this room.";
      setError(message);
      showToast(message, { tone: "error" });
    },
  });

  return (
    <form
      aria-label={destination ? `Edit ${destination.label}` : "New room"}
      className="grid gap-4 rounded-lg border border-line bg-subtle p-4"
      onSubmit={(event) => {
        event.preventDefault();
        setError("");
        save.mutate();
      }}
    >
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Channel">
          <Dropdown
            disabled={Boolean(destination)}
            onChange={(event) => setChannel(event.target.value as typeof channel)}
            value={channel}
          >
            {channels.map((option) => (
              <option key={option.key} value={option.key}>
                {option.label}
              </option>
            ))}
          </Dropdown>
        </Field>
        <Field label="Room name">
          <Input onChange={(event) => setLabel(event.target.value)} placeholder="Laser team" required value={label} />
        </Field>
      </div>

      {channel === "telegram" ? (
        <Field
          label="Telegram chat ID"
          helperText="Rooms share this makerspace's bot — add the same bot to each group."
        >
          <Input
            className="font-mono"
            onChange={(event) => setChatId(event.target.value)}
            placeholder="-1001234567890"
            required
            value={chatId}
          />
        </Field>
      ) : (
        <Field
          label="Incoming webhook URL"
          helperText={destination?.credential_set ? "Leave blank to keep the saved webhook." : "Stored encrypted and never shown again."}
        >
          <PasswordInput
            autoComplete="off"
            onChange={(event) => setWebhookUrl(event.target.value)}
            placeholder="https://hooks.example.com/…"
            showLabel="Show webhook URL"
            hideLabel="Hide webhook URL"
            value={webhookUrl}
          />
        </Field>
      )}

      <SwitchRow
        label="Deliver to this room"
        description="Turn off to pause deliveries without losing the room."
        checked={isActive}
        onCheckedChange={setIsActive}
      />

      <ScopePicker onChange={setScope} options={options} scope={scope} />

      <ErrorText message={error} />
      <div className="flex flex-wrap gap-2.5">
        <Button variant="primary" loading={save.isPending} loadingLabel="Saving…" type="submit">
          Save room
        </Button>
        <Button variant="secondary" onClick={onDone}>
          Cancel
        </Button>
      </div>
    </form>
  );
}
