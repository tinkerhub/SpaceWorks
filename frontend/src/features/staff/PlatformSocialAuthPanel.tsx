import { useEffect, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { Button, Callout, Card, CardHeader, Field, Input, SettingsRow, StatusChip, Textarea, useToast } from "../../components/ui";
import { staffRequest } from "../../lib/api";
import { errorText, useStaffGet } from "./panels/shared";

type SocialSettings = {
  google_web_client_id: string;
  google_ios_client_id: string;
  google_android_client_id: string;
  apple_service_id: string;
  apple_native_app_ids: string[];
  apple_team_id: string;
  apple_key_id: string;
  apple_private_key_set: boolean;
};

type SocialForm = {
  google_web_client_id: string;
  google_ios_client_id: string;
  google_android_client_id: string;
  apple_service_id: string;
  apple_native_app_ids: string;
  apple_team_id: string;
  apple_key_id: string;
  apple_private_key: string;
};

export function PlatformSocialAuthPanel() {
  const queryClient = useQueryClient();
  const { showToast } = useToast();
  const settings = useStaffGet<SocialSettings>(["platform-social-auth"], "/admin/platform/social-auth-settings");
  const [form, setForm] = useState<SocialForm>({
    google_web_client_id: "",
    google_ios_client_id: "",
    google_android_client_id: "",
    apple_service_id: "",
    apple_native_app_ids: "",
    apple_team_id: "",
    apple_key_id: "",
    apple_private_key: "",
  });

  useEffect(() => {
    if (!settings.data) return;
    setForm({
      google_web_client_id: settings.data.google_web_client_id,
      google_ios_client_id: settings.data.google_ios_client_id,
      google_android_client_id: settings.data.google_android_client_id,
      apple_service_id: settings.data.apple_service_id,
      apple_native_app_ids: settings.data.apple_native_app_ids.join("\n"),
      apple_team_id: settings.data.apple_team_id,
      apple_key_id: settings.data.apple_key_id,
      apple_private_key: "",
    });
  }, [settings.data]);

  const save = useMutation({
    mutationFn: () => staffRequest<SocialSettings>("/admin/platform/social-auth-settings", {
      method: "PATCH",
      body: JSON.stringify({
        ...form,
        apple_native_app_ids: form.apple_native_app_ids.split(/[,\n]/).map((item) => item.trim()).filter(Boolean),
        ...(form.apple_private_key ? {} : { apple_private_key: undefined }),
      }),
    }),
    onSuccess: () => {
      setForm((current) => ({ ...current, apple_private_key: "" }));
      void queryClient.invalidateQueries({ queryKey: ["platform-social-auth"] });
      showToast("Sign-in settings saved", { tone: "success" });
    },
    onError: (error) => showToast(errorText(error, "Couldn't save sign-in settings"), { tone: "error" }),
  });
  const disabled = settings.isLoading || save.isPending;
  const set = (patch: Partial<SocialForm>) => setForm((current) => ({ ...current, ...patch }));
  const text = (label: string, key: keyof SocialForm) => (
    <Field label={label}>
      <Input autoComplete="off" value={form[key]} onChange={(event) => set({ [key]: event.target.value })} />
    </Field>
  );
  const googleOn = Boolean(settings.data?.google_web_client_id);
  const appleOn = Boolean(settings.data?.apple_service_id);

  return (
    <Card as="section" aria-label="Google and Apple sign-in">
      <CardHeader
        title="Google and Apple sign-in"
        description="Platform-wide identities link to global accounts. Makerspace permissions still come from each membership."
      />
      {settings.error || save.error ? (
        <Callout tone="danger" role="alert" className="mb-2">{(settings.error ?? save.error)?.message}</Callout>
      ) : null}
      <fieldset disabled={disabled} className="min-w-0">
        <legend className="sr-only">Sign-in providers</legend>
        <SettingsRow
          title="Google OAuth clients"
          description={<StatusChip tone={googleOn ? "success" : "neutral"} size="sm">{googleOn ? "On" : "Off"}</StatusChip>}
        >
          <div className="grid gap-4">
            {text("Web client ID", "google_web_client_id")}
            <div className="grid gap-4 sm:grid-cols-2">
              {text("iOS client ID", "google_ios_client_id")}
              {text("Android client ID", "google_android_client_id")}
            </div>
          </div>
        </SettingsRow>
        <SettingsRow
          title="Apple Sign in"
          description={<StatusChip tone={appleOn ? "success" : "neutral"} size="sm">{appleOn ? "On" : "Off"}</StatusChip>}
        >
          <div className="grid gap-4">
            {text("Web Service ID", "apple_service_id")}
            <Field label="Native app audiences" helperText="One audience per line.">
              <Textarea rows={3} value={form.apple_native_app_ids} onChange={(event) => set({ apple_native_app_ids: event.target.value })} placeholder="One audience per line" />
            </Field>
            <div className="grid gap-4 sm:grid-cols-2">
              {text("Team ID", "apple_team_id")}
              {text("Key ID", "apple_key_id")}
            </div>
            <Field
              label="Apple private key (.p8)"
              helperText={settings.data?.apple_private_key_set ? "A key is saved and never shown. Paste a new one to replace it." : "Paste the key you downloaded from Apple."}
            >
              <Textarea
                rows={4}
                className="font-mono text-sm"
                autoComplete="off"
                spellCheck={false}
                value={form.apple_private_key}
                onChange={(event) => set({ apple_private_key: event.target.value })}
                placeholder={settings.data?.apple_private_key_set ? "Private key set — leave blank to keep it" : "Paste the private key"}
              />
            </Field>
          </div>
        </SettingsRow>
      </fieldset>
      <div className="flex justify-end border-t border-line pt-5">
        <Button variant="primary" disabled={settings.isLoading} loading={save.isPending} loadingLabel="Saving…" onClick={() => save.mutate()}>
          Save social sign-in settings
        </Button>
      </div>
    </Card>
  );
}
