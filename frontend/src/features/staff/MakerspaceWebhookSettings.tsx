import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { Button, Card, CardHeader, ConfirmDialog, ErrorText, Field, PasswordInput, SettingsRow, Skeleton, StatusChip, useToast } from "../../components/ui";
import { staffRequest } from "../../lib/api";
import { moduleEnabled } from "../../lib/modules";
import { errorText, type Makerspace, useStaffGet } from "./panels/shared";

type ApiSettings = {
  slack_webhook_url_set: boolean;
  mattermost_webhook_url_set: boolean;
  discord_webhook_url_set: boolean;
};

type Provider = "slack" | "mattermost" | "discord";

type ProviderRowProps = {
  configured: boolean;
  label: string;
  makerspaceId: number;
  provider: Provider;
};

// Read webhook state under a dedicated cache key (same endpoint) so saving/clearing a
// webhook never invalidates the shared ["api-settings", id] query that the SMTP form and
// its unsaved edits depend on. The notification channel matrix reads the same key, so its
// configuration warnings still refresh immediately after a webhook is saved.
export const DELIVERY_SETTINGS_KEY = (makerspaceId: number) => [
  "api-settings",
  makerspaceId,
  "delivery",
];

const PROVIDERS: { provider: Provider; label: string }[] = [
  { provider: "slack", label: "Slack" },
  { provider: "mattermost", label: "Mattermost" },
  { provider: "discord", label: "Discord" },
];

export function MakerspaceWebhookSettings({ makerspace }: { makerspace: Makerspace }) {
  const settings = useStaffGet<ApiSettings>(
    DELIVERY_SETTINGS_KEY(makerspace.id),
    `/admin/makerspace/${makerspace.id}/api-settings`,
  );

  return (
    <Card as="section" aria-labelledby="chat-webhooks-title">
      <CardHeader
        title={<span id="chat-webhooks-title">Chat webhooks</span>}
        description="Incoming webhook URLs for Slack, Mattermost or Discord. Saving one sets up the destination; turn delivery on in the notification channels below."
      />
      {settings.isLoading ? <Skeleton className="h-24 w-full" /> : null}
      <ErrorText message={settings.error?.message} />
      {PROVIDERS.filter(({ provider }) => moduleEnabled(makerspace.enabled_modules, provider)).map(({ provider, label }) => (
        <ProviderRow
          key={provider}
          configured={settings.data?.[`${provider}_webhook_url_set` as const] ?? false}
          label={label}
          makerspaceId={makerspace.id}
          provider={provider}
        />
      ))}
    </Card>
  );
}

function ProviderRow({ configured, label, makerspaceId, provider }: ProviderRowProps) {
  const queryClient = useQueryClient();
  const { showToast } = useToast();
  const [webhookUrl, setWebhookUrl] = useState("");
  const [confirmClear, setConfirmClear] = useState(false);
  const field = `${provider}_webhook_url`;
  const path = `/admin/makerspace/${makerspaceId}/api-settings`;

  const invalidate = () =>
    queryClient.invalidateQueries({ queryKey: DELIVERY_SETTINGS_KEY(makerspaceId) });

  const saveWebhook = useMutation({
    mutationFn: (value: string) =>
      staffRequest<ApiSettings>(path, {
        method: "PATCH",
        body: JSON.stringify({ [field]: value }),
      }),
    onSuccess: () => {
      setWebhookUrl("");
      invalidate();
      showToast(`${label} webhook saved`, { tone: "success" });
    },
    onError: (error) => showToast(errorText(error, `Couldn't save the ${label} webhook`), { tone: "error" }),
  });

  const clearWebhook = useMutation({
    mutationFn: () =>
      staffRequest<ApiSettings>(path, {
        method: "PATCH",
        body: JSON.stringify({ [field]: "" }),
      }),
    onSuccess: () => {
      setWebhookUrl("");
      setConfirmClear(false);
      invalidate();
      showToast(`${label} webhook cleared`, { tone: "success" });
    },
    onError: (error) => showToast(errorText(error, `Couldn't clear the ${label} webhook`), { tone: "error" }),
  });

  const pending = saveWebhook.isPending || clearWebhook.isPending;

  return (
    <SettingsRow
      title={(
        <span className="flex flex-wrap items-center gap-2">
          {label}
          <StatusChip tone={configured ? "success" : "neutral"} size="sm">{configured ? "Configured" : "Not configured"}</StatusChip>
        </span>
      )}
      description="Paste an incoming webhook URL. The saved URL is never shown again."
    >
      <div className="grid gap-3">
        <Field label={`${label} incoming webhook URL`}>
          <PasswordInput
            autoComplete="new-password"
            showLabel="Show webhook URL"
            hideLabel="Hide webhook URL"
            value={webhookUrl}
            onChange={(event) => setWebhookUrl(event.target.value)}
          />
        </Field>
        <div className="flex flex-wrap gap-2">
          <Button
            variant="secondary"
            size="sm"
            disabled={!webhookUrl.trim() || pending}
            loading={saveWebhook.isPending}
            loadingLabel="Saving…"
            onClick={() => saveWebhook.mutate(webhookUrl.trim())}
          >
            {`Save ${label} webhook`}
          </Button>
          <Button variant="danger-quiet" size="sm" disabled={!configured || pending} onClick={() => setConfirmClear(true)}>
            {`Clear ${label} webhook…`}
          </Button>
        </div>
        <ErrorText message={saveWebhook.error?.message} />
        <ErrorText message={clearWebhook.error?.message} />
      </div>
      <ConfirmDialog
        open={confirmClear}
        title={`Clear the ${label} webhook?`}
        message={`${label} stops receiving notifications from this makerspace until you add a webhook again.`}
        confirmLabel="Clear webhook"
        tone="danger"
        pending={clearWebhook.isPending}
        onConfirm={() => clearWebhook.mutate()}
        onCancel={() => setConfirmClear(false)}
      />
    </SettingsRow>
  );
}
