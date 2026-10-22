import { useEffect, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { Button, Callout, Card, CardHeader, ConfirmDialog, Field, Input, PasswordInput, SettingsRow, StatusChip, useToast } from "../../components/ui";
import { staffRequest } from "../../lib/api";
import { errorText, useStaffGet } from "./panels/shared";

type PlatformPaymentSettings = {
  id: number;
  stripe_publishable_key_set: boolean;
  stripe_secret_key_set: boolean;
  stripe_webhook_secret_set: boolean;
  stripe_connect_client_id: string;
  application_fee_bps: number;
  updated_at: string;
};

type RevocableCredential =
  | "stripe_publishable_key"
  | "stripe_secret_key"
  | "stripe_webhook_secret";

const CREDENTIALS: { key: RevocableCredential; label: string; short: string; set: keyof PlatformPaymentSettings }[] = [
  { key: "stripe_publishable_key", label: "Platform publishable key", short: "publishable key", set: "stripe_publishable_key_set" },
  { key: "stripe_secret_key", label: "Platform secret key", short: "secret key", set: "stripe_secret_key_set" },
  { key: "stripe_webhook_secret", label: "Platform webhook secret", short: "webhook secret", set: "stripe_webhook_secret_set" },
];

export function PlatformStripeConnectPanel() {
  const queryClient = useQueryClient();
  const { showToast } = useToast();
  const settings = useStaffGet<PlatformPaymentSettings>(
    ["platform-payment-settings"],
    "/admin/platform/payment-settings",
  );
  const [secrets, setSecrets] = useState<Record<RevocableCredential, string>>({
    stripe_publishable_key: "",
    stripe_secret_key: "",
    stripe_webhook_secret: "",
  });
  const [clientId, setClientId] = useState("");
  const [feeBps, setFeeBps] = useState("0");
  const [clearing, setClearing] = useState<RevocableCredential | null>(null);

  useEffect(() => {
    if (!settings.data) return;
    setClientId(settings.data.stripe_connect_client_id ?? "");
    setFeeBps(String(settings.data.application_fee_bps ?? 0));
  }, [settings.data]);

  const save = useMutation({
    mutationFn: () =>
      staffRequest<PlatformPaymentSettings>("/admin/platform/payment-settings", {
        method: "PATCH",
        body: JSON.stringify({
          stripe_connect_client_id: clientId,
          application_fee_bps: Number(feeBps) || 0,
          ...(secrets.stripe_publishable_key ? { stripe_publishable_key: secrets.stripe_publishable_key } : {}),
          ...(secrets.stripe_secret_key ? { stripe_secret_key: secrets.stripe_secret_key } : {}),
          ...(secrets.stripe_webhook_secret ? { stripe_webhook_secret: secrets.stripe_webhook_secret } : {}),
        }),
      }),
    onSuccess: () => {
      setSecrets({ stripe_publishable_key: "", stripe_secret_key: "", stripe_webhook_secret: "" });
      queryClient.invalidateQueries({ queryKey: ["platform-payment-settings"] });
      showToast("Stripe Connect settings saved", { tone: "success" });
    },
    onError: (error) => showToast(errorText(error, "Couldn't save Stripe Connect settings"), { tone: "error" }),
  });
  const clearCredential = useMutation({
    mutationFn: (credential: RevocableCredential) =>
      staffRequest<PlatformPaymentSettings>("/admin/platform/payment-settings", {
        method: "PATCH",
        body: JSON.stringify({ [credential]: "" }),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["platform-payment-settings"] });
      showToast("Credential cleared", { tone: "success" });
    },
    onError: (error) => showToast(errorText(error, "Couldn't clear the credential"), { tone: "error" }),
    onSettled: () => setClearing(null),
  });
  const busy = settings.isLoading || save.isPending || clearCredential.isPending;
  const pendingClear = CREDENTIALS.find((item) => item.key === clearing);
  const error = settings.error || save.error || clearCredential.error;

  return (
    <Card as="section" aria-label="Platform Stripe Connect">
      <CardHeader
        title="Platform Stripe Connect"
        description="Platform credentials authorise direct charges into each makerspace's connected account."
        action={settings.data ? (
          <StatusChip tone={settings.data.stripe_secret_key_set ? "success" : "neutral"} size="sm">
            {settings.data.stripe_secret_key_set ? "Connected" : "Not connected"}
          </StatusChip>
        ) : null}
      />
      {error ? <Callout tone="danger" role="alert" className="mb-2">{error.message}</Callout> : null}
      <SettingsRow title="API keys" description="Saved keys are never returned. Leave a field blank to keep what is saved.">
        <div className="grid gap-4">
          {CREDENTIALS.map((item) => {
            const isSet = Boolean(settings.data?.[item.set]);
            return (
              <div key={item.key} className="grid gap-2 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-end">
                <Field label={item.label} helperText={isSet ? "Saved." : "Not set."}>
                  <PasswordInput
                    autoComplete="new-password"
                    showLabel={`Show ${item.short}`}
                    hideLabel={`Hide ${item.short}`}
                    placeholder={isSet ? `${item.label} set` : undefined}
                    value={secrets[item.key]}
                    onChange={(event) => setSecrets((current) => ({ ...current, [item.key]: event.target.value }))}
                  />
                </Field>
                <Button
                  variant="danger-quiet"
                  size="sm"
                  className="sm:mb-7"
                  disabled={!isSet || busy}
                  onClick={() => setClearing(item.key)}
                >
                  Clear {item.short}…
                </Button>
              </div>
            );
          })}
        </div>
      </SettingsRow>
      <SettingsRow title="Connect" description="The client ID of your Connect platform, and the fee taken from each charge.">
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Stripe Connect client ID"><Input autoComplete="off" value={clientId} onChange={(event) => setClientId(event.target.value)} /></Field>
          <Field
            label="Application fee (basis points)"
            helperText={`Saved: ${settings.data?.application_fee_bps ?? 0} basis points. 100 basis points = 1%.`}
          >
            <Input inputMode="numeric" min={0} max={10000} type="number" value={feeBps} onChange={(event) => setFeeBps(event.target.value)} />
          </Field>
        </div>
      </SettingsRow>
      <div className="flex justify-end border-t border-line pt-5">
        <Button variant="primary" disabled={busy && !save.isPending} loading={save.isPending} loadingLabel="Saving…" onClick={() => save.mutate()}>
          Save Stripe Connect settings
        </Button>
      </div>
      <ConfirmDialog
        open={pendingClear !== undefined}
        title={`Clear the ${pendingClear?.short ?? "credential"}?`}
        message="Payments that need this credential stop working until a new one is saved."
        confirmLabel={`Clear ${pendingClear?.short ?? "credential"}`}
        tone="danger"
        pending={clearCredential.isPending}
        onConfirm={() => { if (clearing) clearCredential.mutate(clearing); }}
        onCancel={() => setClearing(null)}
      />
    </Card>
  );
}
