import { useEffect, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { Button, Callout, Card, CardHeader, CheckboxField, Field, Input, PasswordInput, SettingsRow, StatusChip, useToast } from "../../components/ui";
import { staffRequest } from "../../lib/api";
import { errorText, useStaffGet } from "./panels/shared";

type PlatformEmailSettings = {
  id: number;
  smtp_host: string;
  smtp_port: number;
  smtp_username: string;
  smtp_password_set: boolean;
  smtp_use_tls: boolean;
  smtp_use_ssl: boolean;
  from_email: string;
  updated_at: string;
};

type PlatformEmailForm = {
  smtp_host: string;
  smtp_port: string;
  smtp_username: string;
  smtp_password: string;
  smtp_use_tls: boolean;
  smtp_use_ssl: boolean;
  from_email: string;
};

export function PlatformEmailPanel() {
  const queryClient = useQueryClient();
  const { showToast } = useToast();
  const settings = useStaffGet<PlatformEmailSettings>(
    ["platform-email"],
    "/admin/platform/email-settings",
  );
  const [form, setForm] = useState<PlatformEmailForm>({
    smtp_host: "",
    smtp_port: "587",
    smtp_username: "",
    smtp_password: "",
    smtp_use_tls: true,
    smtp_use_ssl: false,
    from_email: "",
  });

  useEffect(() => {
    if (!settings.data) return;
    setForm({
      smtp_host: settings.data.smtp_host ?? "",
      smtp_port: String(settings.data.smtp_port ?? 587),
      smtp_username: settings.data.smtp_username ?? "",
      smtp_password: "",
      smtp_use_tls: settings.data.smtp_use_tls,
      smtp_use_ssl: settings.data.smtp_use_ssl,
      from_email: settings.data.from_email ?? "",
    });
  }, [settings.data]);

  const save = useMutation({
    mutationFn: () =>
      staffRequest<PlatformEmailSettings>("/admin/platform/email-settings", {
        method: "PATCH",
        body: JSON.stringify(platformEmailPayload(form)),
      }),
    onSuccess: () => {
      setForm((current) => ({ ...current, smtp_password: "" }));
      queryClient.invalidateQueries({ queryKey: ["platform-email"] });
      showToast("Platform email saved", { tone: "success" });
    },
    onError: (error) => showToast(errorText(error, "Couldn't save platform email"), { tone: "error" }),
  });

  const formDisabled = settings.isLoading || save.isPending;
  const set = (patch: Partial<PlatformEmailForm>) => setForm((current) => ({ ...current, ...patch }));

  return (
    <Card as="section" aria-label="Platform email">
      <CardHeader
        title="Platform email"
        description="Instance-wide SMTP for password resets, and for makerspace notifications when a makerspace has no SMTP of its own."
        action={settings.data ? (
          <StatusChip tone={settings.data.smtp_host ? "success" : "neutral"} size="sm">
            {settings.data.smtp_host ? "Configured" : "Not set up"}
          </StatusChip>
        ) : null}
      />
      {settings.error ? <Callout tone="danger" role="alert" title="Couldn't load platform email">{settings.error.message}</Callout> : null}
      <SettingsRow title="Mail server" description="The SMTP host and port your provider gave you.">
        <div className="grid gap-4 sm:grid-cols-[minmax(0,1fr)_140px]">
          <Field label="SMTP host"><Input disabled={formDisabled} value={form.smtp_host} onChange={(event) => set({ smtp_host: event.target.value })} /></Field>
          <Field label="SMTP port"><Input disabled={formDisabled} inputMode="numeric" value={form.smtp_port} onChange={(event) => set({ smtp_port: event.target.value })} /></Field>
        </div>
      </SettingsRow>
      <SettingsRow title="Sign-in" description="A saved password is never shown. Leave it blank to keep it.">
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="SMTP username"><Input disabled={formDisabled} autoComplete="off" value={form.smtp_username} onChange={(event) => set({ smtp_username: event.target.value })} /></Field>
          <Field
            label="SMTP password"
            helperText={settings.data?.smtp_password_set ? "A password is saved." : undefined}
          >
            <PasswordInput
              disabled={formDisabled}
              autoComplete="new-password"
              placeholder={settings.data?.smtp_password_set ? "SMTP password set" : undefined}
              value={form.smtp_password}
              onChange={(event) => set({ smtp_password: event.target.value })}
            />
          </Field>
        </div>
      </SettingsRow>
      <SettingsRow title="Sender" description="The address people see emails come from.">
        <Field label="From email"><Input type="email" disabled={formDisabled} value={form.from_email} onChange={(event) => set({ from_email: event.target.value })} /></Field>
      </SettingsRow>
      <SettingsRow title="Encryption" description="Port 587 usually uses STARTTLS; port 465 uses implicit SSL.">
        <div className="grid gap-3">
          <CheckboxField label="Use STARTTLS (587)" disabled={formDisabled} checked={form.smtp_use_tls} onCheckedChange={(checked) => set({ smtp_use_tls: checked === true })} />
          <CheckboxField label="Use implicit SSL (465)" disabled={formDisabled} checked={form.smtp_use_ssl} onCheckedChange={(checked) => set({ smtp_use_ssl: checked === true })} />
        </div>
      </SettingsRow>
      <div className="flex flex-col gap-3 border-t border-line pt-5 sm:flex-row sm:items-center sm:justify-end">
        {save.error ? <p className="text-caption text-danger-fg sm:mr-auto">{save.error.message}</p> : null}
        <Button variant="primary" disabled={settings.isLoading} loading={save.isPending} loadingLabel="Saving…" onClick={() => save.mutate()}>
          Save platform email settings
        </Button>
      </div>
    </Card>
  );
}

function platformEmailPayload(form: PlatformEmailForm) {
  const payload: Record<string, string | number | boolean> = {
    smtp_host: form.smtp_host,
    smtp_port: Number(form.smtp_port) || 587,
    smtp_username: form.smtp_username,
    smtp_use_tls: form.smtp_use_tls,
    smtp_use_ssl: form.smtp_use_ssl,
    from_email: form.from_email,
  };
  if (form.smtp_password) payload.smtp_password = form.smtp_password;
  return payload;
}
