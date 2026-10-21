import { useEffect, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { Button, Callout, Card, CardHeader, ConfirmDialog, ErrorText, Field, Input, PasswordInput, SettingsRow, Skeleton, useToast } from "../../components/ui";
import { staffRequest } from "../../lib/api";
import { errorText, type Makerspace, useStaffGet } from "./panels/shared";

type ApiSettings = {
  telegram_group_chat_id: string;
  telegram_bot_token_set: boolean;
};

type TelegramSettingsForm = {
  telegram_group_chat_id: string;
  telegram_bot_token: string;
};

export function ApiClientsTelegramSettings({ makerspace }: { makerspace: Makerspace }) {
  const queryClient = useQueryClient();
  const { showToast } = useToast();
  const [confirmClear, setConfirmClear] = useState(false);
  const [settingsForm, setSettingsForm] = useState<TelegramSettingsForm>({
    telegram_group_chat_id: "",
    telegram_bot_token: "",
  });

  const settings = useStaffGet<ApiSettings>(
    ["api-settings", makerspace.id],
    `/admin/makerspace/${makerspace.id}/api-settings`,
  );

  useEffect(() => {
    if (!settings.data) return;
    setSettingsForm({
      telegram_group_chat_id: settings.data.telegram_group_chat_id ?? "",
      telegram_bot_token: "",
    });
  }, [settings.data]);

  const saveSettings = useMutation({
    mutationFn: () =>
      staffRequest<ApiSettings>(`/admin/makerspace/${makerspace.id}/api-settings`, {
        method: "PATCH",
        body: JSON.stringify(settingsPayload(settingsForm)),
      }),
    onSuccess: () => {
      setSettingsForm((current) => ({
        ...current,
        telegram_bot_token: "",
      }));
      queryClient.invalidateQueries({ queryKey: ["api-settings", makerspace.id] });
      showToast("Telegram settings saved", { tone: "success" });
    },
    onError: (error) => showToast(errorText(error, "Couldn't save the Telegram settings"), { tone: "error" }),
  });

  const clearTelegramToken = useMutation({
    mutationFn: () =>
      staffRequest<ApiSettings>(`/admin/makerspace/${makerspace.id}/api-settings`, {
        method: "PATCH",
        body: JSON.stringify({ telegram_bot_token: "" }),
      }),
    onSuccess: () => {
      setSettingsForm((current) => ({ ...current, telegram_bot_token: "" }));
      setConfirmClear(false);
      queryClient.invalidateQueries({ queryKey: ["api-settings", makerspace.id] });
      showToast("Telegram token cleared", { tone: "success" });
    },
    onError: (error) => showToast(errorText(error, "Couldn't clear the Telegram token"), { tone: "error" }),
  });
  const testTelegram = useMutation({
    mutationFn: () =>
      staffRequest<{ delivered: boolean; detail?: string }>("/integrations/telegram/test-alert", {
        method: "POST",
        body: JSON.stringify({
          makerspace_id: makerspace.id,
          message: `Test alert from ${makerspace.name}`,
        }),
      }),
    onSuccess: (result) =>
      showToast(result.delivered ? "Test alert delivered" : "Test alert wasn't delivered", { tone: result.delivered ? "success" : "warning" }),
    onError: (error) => showToast(errorText(error, "Couldn't send the test alert"), { tone: "error" }),
  });

  return (
    <Card as="section" aria-labelledby="telegram-settings-title">
      <CardHeader
        title={<span id="telegram-settings-title">Telegram alerts</span>}
        description="Send request alerts to a Telegram group. Outbound only: decisions stay in the console."
        action={(
          <Button
            variant="secondary"
            size="sm"
            disabled={!settings.isSuccess}
            loading={testTelegram.isPending}
            loadingLabel="Sending…"
            onClick={() => testTelegram.mutate()}
          >
            Send Telegram test alert
          </Button>
        )}
      />
      {settings.isLoading ? <Skeleton className="h-20 w-full" /> : null}
      <ErrorText message={settings.error?.message} />
      <SettingsRow title="Group" description="The chat that receives alerts.">
        <Field label="Telegram group chat ID">
          <Input
            className="font-mono"
            value={settingsForm.telegram_group_chat_id}
            onChange={(event) =>
              setSettingsForm({ ...settingsForm, telegram_group_chat_id: event.target.value })
            }
          />
        </Field>
      </SettingsRow>
      <SettingsRow title="Bot" description="Leave blank to keep the saved token. It is never shown again.">
        <div className="grid gap-3">
          <Field label="Telegram bot token">
            <PasswordInput
              autoComplete="new-password"
              showLabel="Show bot token"
              hideLabel="Hide bot token"
              placeholder={settings.data?.telegram_bot_token_set ? "Telegram bot token set" : undefined}
              value={settingsForm.telegram_bot_token}
              onChange={(event) =>
                setSettingsForm({ ...settingsForm, telegram_bot_token: event.target.value })
              }
            />
          </Field>
          <div>
            <Button
              variant="danger-quiet"
              size="sm"
              disabled={!settings.data?.telegram_bot_token_set || clearTelegramToken.isPending}
              onClick={() => setConfirmClear(true)}
            >
              Clear Telegram token…
            </Button>
          </div>
        </div>
      </SettingsRow>
      <div className="flex justify-end pt-4">
        <Button
          variant="primary"
          disabled={!settings.isSuccess}
          loading={saveSettings.isPending}
          loadingLabel="Saving…"
          onClick={() => saveSettings.mutate()}
        >
          Save integration settings
        </Button>
      </div>
      <div className="mt-3 grid gap-2">
        <ErrorText message={saveSettings.error?.message} />
        <ErrorText message={clearTelegramToken.error?.message} />
        {testTelegram.data ? (
          testTelegram.data.delivered ? (
            <Callout tone="success" role="status">Telegram delivered: yes</Callout>
          ) : (
            <Callout tone="danger" role="alert" title="Telegram delivered: no">
              {testTelegram.data.detail ?? null}
            </Callout>
          )
        ) : null}
        <ErrorText message={testTelegram.error?.message} />
      </div>
      <ConfirmDialog
        open={confirmClear}
        title="Clear the Telegram token?"
        message="Alerts stop until you save a new bot token."
        confirmLabel="Clear token"
        tone="danger"
        pending={clearTelegramToken.isPending}
        onConfirm={() => clearTelegramToken.mutate()}
        onCancel={() => setConfirmClear(false)}
      />
    </Card>
  );
}

function settingsPayload(form: TelegramSettingsForm) {
  const payload: Record<string, string> = {
    telegram_group_chat_id: form.telegram_group_chat_id,
  };
  if (form.telegram_bot_token) payload.telegram_bot_token = form.telegram_bot_token;
  return payload;
}
