import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { Callout, Card, CardHeader, ErrorBlock, Switch, Table, TBody, TD, TH, THead, TR, useToast } from "../../components/ui";
import { staffRequest } from "../../lib/api";
import { DELIVERY_SETTINGS_KEY } from "./MakerspaceWebhookSettings";
import type {
  NotificationPreferenceCell,
  NotificationRulesResponse,
  PreferenceChange,
} from "./notificationRuleTypes";

type DeliverySettings = {
  slack_webhook_url_set: boolean;
  mattermost_webhook_url_set: boolean;
  discord_webhook_url_set: boolean;
  telegram_bot_token_set: boolean;
  telegram_group_chat_id: string;
};

type Props = {
  makerspaceId: number;
  rules: NotificationRulesResponse;
};

export function NotificationChannelPreferences({ makerspaceId, rules }: Props) {
  const queryClient = useQueryClient();
  const { showToast } = useToast();
  const rulesPath = `/admin/makerspace/${makerspaceId}/notification-rules`;
  const queryKey = ["notification-rules", makerspaceId] as const;
  const settings = useQuery({
    queryKey: DELIVERY_SETTINGS_KEY(makerspaceId),
    queryFn: () =>
      staffRequest<DeliverySettings>(`/admin/makerspace/${makerspaceId}/api-settings`),
  });

  const updatePreference = useMutation({
    mutationFn: (change: PreferenceChange) =>
      staffRequest<NotificationRulesResponse>(rulesPath, {
        method: "PATCH",
        body: JSON.stringify({ preferences: [change] }),
      }),
    onMutate: async (change) => {
      await queryClient.cancelQueries({ queryKey });
      const previous = queryClient.getQueryData<NotificationRulesResponse>(queryKey);
      queryClient.setQueryData<NotificationRulesResponse>(queryKey, (current) =>
        current
          ? {
              ...current,
              preferences: applyPreferenceChange(current.preferences, change),
            }
          : current,
      );
      return { previous };
    },
    onSuccess: () => showToast("Channel setting saved", { tone: "success" }),
    onError: (error, _change, context) => {
      if (context?.previous !== undefined) {
        queryClient.setQueryData(queryKey, context.previous);
      }
      showToast(error.message || "Couldn't save the channel setting", { tone: "error" });
    },
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey });
    },
  });

  const warnings = deliveryWarnings(rules.preferences, settings.data);

  return (
    <Card as="section" aria-labelledby="notification-channel-heading">
      <CardHeader
        title={<span id="notification-channel-heading">Notification channels</span>}
        description="Turn each channel on or off per feature. The staff email switch and per-member recipient toggles affect staff email only, not Telegram, Slack or Mattermost."
      />
      <Table label="Notification channels by feature">
        <caption className="sr-only">Switches enable each notification channel for a feature.</caption>
        <THead>
          <tr>
            <TH>Feature</TH>
            {rules.channels.map((channel) => (
              <TH key={channel.key} className="text-center">{channel.label}</TH>
            ))}
          </tr>
        </THead>
        <TBody>
          {rules.features.map((feature) => (
            <TR key={feature.key}>
              <TH scope="row" className="text-label text-ink">{feature.label}</TH>
              {rules.channels.map((channel) => {
                const cell = preferenceCell(rules.preferences, feature.key, channel.key);
                const checked = cell?.enabled ?? false;
                return (
                  <TD key={channel.key} className="text-center">
                    <Switch
                      aria-label={`${checked ? "Disable" : "Enable"} ${channel.label} for ${feature.label}`}
                      checked={checked}
                      disabled={updatePreference.isPending}
                      onCheckedChange={(enabled) =>
                        updatePreference.mutate({ feature: feature.key, channel: channel.key, enabled })
                      }
                    />
                  </TD>
                );
              })}
            </TR>
          ))}
        </TBody>
      </Table>
      {warnings.length ? (
        <Callout tone="warning" role="status" title="Delivery setup needed" className="mt-4">
          <ul className="mt-1 list-disc pl-5">
            {warnings.map((warning) => (
              <li key={warning}>{warning}</li>
            ))}
          </ul>
        </Callout>
      ) : null}
      {settings.error ? (
        <p className="mt-3 text-sm text-danger-fg">Couldn't check channel setup: {settings.error.message}</p>
      ) : null}
      <ErrorBlock error={updatePreference.error} className="mt-3" />
    </Card>
  );
}

function preferenceCell(
  preferences: NotificationPreferenceCell[],
  feature: string,
  channel: string,
) {
  return preferences.find((cell) => cell.feature === feature && cell.channel === channel);
}

function applyPreferenceChange(
  preferences: NotificationPreferenceCell[],
  change: PreferenceChange,
) {
  const changed = preferences.some(
    (cell) => cell.feature === change.feature && cell.channel === change.channel,
  );
  if (!changed) return [...preferences, { ...change, source: "override" as const }];
  return preferences.map((cell) =>
    cell.feature === change.feature && cell.channel === change.channel
      ? { ...cell, enabled: change.enabled, source: "override" as const }
      : cell,
  );
}

function deliveryWarnings(
  preferences: NotificationPreferenceCell[],
  settings: DeliverySettings | undefined,
) {
  if (!settings) return [];
  const enabled = (channel: string) =>
    preferences.some((cell) => cell.channel === channel && cell.enabled);
  const warnings: string[] = [];
  if (enabled("slack") && !settings.slack_webhook_url_set) {
    warnings.push("Slack is enabled but its incoming webhook is not configured.");
  }
  if (enabled("mattermost") && !settings.mattermost_webhook_url_set) {
    warnings.push("Mattermost is enabled but its incoming webhook is not configured.");
  }
  if (enabled("discord") && !settings.discord_webhook_url_set) {
    warnings.push("Discord is enabled but its incoming webhook is not configured.");
  }
  if (
    enabled("telegram") &&
    (!settings.telegram_bot_token_set || !settings.telegram_group_chat_id?.trim())
  ) {
    warnings.push("Telegram is enabled but its bot token or group chat ID is not configured.");
  }
  return warnings;
}
