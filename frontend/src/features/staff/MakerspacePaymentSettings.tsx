import { useEffect, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { Button, Card, CardHeader, ConfirmDialog, ErrorText, Field, Input, PasswordInput, SettingsRow, StatusChip, useToast } from "../../components/ui";
import { staffRequest } from "../../lib/api";
import { errorText, type Makerspace, useStaffGet } from "./panels/shared";

type PaymentSettings = {
  default_currency: string;
  stripe_publishable_key_set: boolean;
  stripe_secret_key_set: boolean;
  stripe_webhook_secret_set: boolean;
  effective_mode: "raw" | "connect" | "unavailable";
  connect_account_id?: string | null;
  connect_status: "unconnected" | "pending" | "active" | "restricted" | "disconnected";
  connect_charges_enabled: boolean;
  connect_payouts_enabled: boolean;
};

export function MakerspacePaymentSettings({ makerspace }: { makerspace: Makerspace }) {
  const queryClient = useQueryClient();
  const { showToast } = useToast();
  const queryKey = ["payment-settings", makerspace.id];
  const path = `/admin/makerspace/${makerspace.id}/payment-settings`;
  const settings = useStaffGet<PaymentSettings>(queryKey, path);
  const [publishableKey, setPublishableKey] = useState("");
  const [secretKey, setSecretKey] = useState("");
  const [webhookSecret, setWebhookSecret] = useState("");
  const [currency, setCurrency] = useState("usd");
  const [confirmClear, setConfirmClear] = useState(false);

  useEffect(() => {
    if (settings.data) setCurrency(settings.data.default_currency);
  }, [settings.data]);

  const refresh = () => queryClient.invalidateQueries({ queryKey });
  const save = useMutation({
    mutationFn: () =>
      staffRequest<PaymentSettings>(path, {
        method: "PATCH",
        body: JSON.stringify({
          default_currency: currency,
          ...(publishableKey ? { stripe_publishable_key: publishableKey } : {}),
          ...(secretKey ? { stripe_secret_key: secretKey } : {}),
          ...(webhookSecret ? { stripe_webhook_secret: webhookSecret } : {}),
        }),
      }),
    onSuccess: () => {
      setPublishableKey("");
      setSecretKey("");
      setWebhookSecret("");
      refresh();
      showToast("Payment settings saved", { tone: "success" });
    },
    onError: (error) => showToast(errorText(error, "Couldn't save the payment settings"), { tone: "error" }),
  });
  const clear = useMutation({
    mutationFn: () =>
      staffRequest<PaymentSettings>(path, {
        method: "PATCH",
        body: JSON.stringify({
          stripe_publishable_key: "",
          stripe_secret_key: "",
          stripe_webhook_secret: "",
        }),
      }),
    onSuccess: () => {
      setConfirmClear(false);
      refresh();
      showToast("Stripe keys cleared", { tone: "success" });
    },
    onError: (error) => showToast(errorText(error, "Couldn't clear the Stripe keys"), { tone: "error" }),
  });
  const onboard = useMutation({
    mutationFn: () =>
      staffRequest<{ authorize_url: string }>(`${path}/connect/onboard`, {
        method: "POST",
      }),
    onSuccess: ({ authorize_url }) => window.location.assign(authorize_url),
    onError: (error) => showToast(errorText(error, "Couldn't start Stripe Connect"), { tone: "error" }),
  });
  const busy = settings.isLoading || save.isPending || clear.isPending || onboard.isPending;
  const hasRawKeys = Boolean(
    settings.data?.stripe_publishable_key_set
    || settings.data?.stripe_secret_key_set
    || settings.data?.stripe_webhook_secret_set,
  );
  const mode = settings.data?.effective_mode;
  const error = settings.error || save.error || clear.error || onboard.error;

  return (
    <Card as="section" aria-labelledby="payment-settings-title">
      <CardHeader
        title={<span id="payment-settings-title">Stripe payments</span>}
        description="Secret credentials are encrypted; saved keys are never shown again."
        action={<StatusChip tone={mode === "unavailable" || !mode ? "neutral" : "success"}>{modeLabel(mode)}</StatusChip>}
      />
      <SettingsRow title="Stripe keys" description="Leave a field blank to keep the saved value.">
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Stripe publishable key">
            <PasswordInput
              autoComplete="new-password"
              showLabel="Show publishable key"
              hideLabel="Hide publishable key"
              placeholder={settings.data?.stripe_publishable_key_set ? "Stripe publishable key set" : undefined}
              value={publishableKey}
              onChange={(event) => setPublishableKey(event.target.value)}
            />
          </Field>
          <Field label="Stripe secret key">
            <PasswordInput
              autoComplete="new-password"
              showLabel="Show secret key"
              hideLabel="Hide secret key"
              placeholder={settings.data?.stripe_secret_key_set ? "Stripe secret key set" : undefined}
              value={secretKey}
              onChange={(event) => setSecretKey(event.target.value)}
            />
          </Field>
          <Field label="Stripe webhook secret" className="sm:col-span-2">
            <PasswordInput
              autoComplete="new-password"
              showLabel="Show webhook secret"
              hideLabel="Hide webhook secret"
              placeholder={settings.data?.stripe_webhook_secret_set ? "Stripe webhook secret set" : undefined}
              value={webhookSecret}
              onChange={(event) => setWebhookSecret(event.target.value)}
            />
          </Field>
        </div>
      </SettingsRow>
      <SettingsRow title="Currency" description="Three-letter ISO code, such as usd or inr.">
        <Field label="Default payment currency" className="max-w-40">
          <Input maxLength={3} value={currency} onChange={(event) => setCurrency(event.target.value.toLowerCase())} />
        </Field>
      </SettingsRow>
      {makerspace.platform_hosting ? (
        <SettingsRow
          title="Stripe Connect"
          description="A complete raw credential pair takes precedence over Connect; clearing it restores the Connect fallback."
        >
          <div className="flex flex-wrap items-center gap-3">
            <span className="text-body-ui text-ink-secondary">Status:</span>
            <StatusChip tone={connectTone(settings.data?.connect_status)}>{connectLabel(settings.data?.connect_status)}</StatusChip>
            <Button variant="secondary" size="sm" disabled={busy} onClick={() => onboard.mutate()}>
              {settings.data?.connect_status === "unconnected" ? "Connect Stripe" : "Reconnect Stripe"}
            </Button>
          </div>
        </SettingsRow>
      ) : null}
      <div className="flex flex-wrap items-center justify-between gap-3 pt-4">
        <Button variant="danger" size="sm" disabled={busy || !hasRawKeys} onClick={() => setConfirmClear(true)}>
          Clear raw configuration…
        </Button>
        <Button variant="primary" disabled={busy} loading={save.isPending} loadingLabel="Saving…" onClick={() => save.mutate()}>
          Save payment settings
        </Button>
      </div>
      {error ? <div className="mt-3"><ErrorText message={error.message} /></div> : null}
      <ConfirmDialog
        open={confirmClear}
        title="Clear the Stripe keys?"
        message="The publishable key, secret key and webhook secret are removed. Payments fall back to Stripe Connect where it is set up, otherwise they stop."
        confirmLabel="Clear keys"
        tone="danger"
        pending={clear.isPending}
        onConfirm={() => clear.mutate()}
        onCancel={() => setConfirmClear(false)}
      />
    </Card>
  );
}

function modeLabel(mode?: PaymentSettings["effective_mode"]) {
  return mode === "raw" ? "Raw credentials" : mode === "connect" ? "Stripe Connect" : "Unavailable";
}

function connectLabel(status?: PaymentSettings["connect_status"]) {
  const value = status ?? "unconnected";
  return value === "unconnected" ? "Not connected" : value.charAt(0).toUpperCase() + value.slice(1);
}

function connectTone(status?: PaymentSettings["connect_status"]) {
  if (status === "active") return "success" as const;
  if (status === "pending") return "info" as const;
  if (status === "restricted" || status === "disconnected") return "warning" as const;
  return "neutral" as const;
}
