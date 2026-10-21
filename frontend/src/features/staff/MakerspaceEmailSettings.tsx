import { useEffect, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { Button, Card, CardHeader, CheckboxField, EmptyState, ErrorText, Field, Input, PasswordInput, SettingsRow, Skeleton, useToast } from "../../components/ui";
import { staffRequest } from "../../lib/api";
import { errorText, type Makerspace, useStaffGet } from "./panels/shared";

type ApiSettings = {
  smtp_host: string;
  smtp_port: number;
  smtp_username: string;
  smtp_password_set: boolean;
  smtp_use_tls: boolean;
  smtp_use_ssl: boolean;
  smtp_from_email: string;
};

type SmtpSettingsForm = {
  smtp_host: string;
  smtp_port: string;
  smtp_username: string;
  smtp_password: string;
  smtp_use_tls: boolean;
  smtp_use_ssl: boolean;
  smtp_from_email: string;
};

type NotificationRecipient = {
  id: number;
  username: string;
  email: string;
  role: "space_manager" | "inventory_manager" | "machine_manager";
  receives_notifications: boolean;
};

export function MakerspaceEmailSettings({ makerspace }: { makerspace: Makerspace }) {
  const queryClient = useQueryClient();
  const { showToast } = useToast();
  const [smtpForm, setSmtpForm] = useState<SmtpSettingsForm>({
    smtp_host: "",
    smtp_port: "587",
    smtp_username: "",
    smtp_password: "",
    smtp_use_tls: true,
    smtp_use_ssl: false,
    smtp_from_email: "",
  });
  const [recipientChecks, setRecipientChecks] = useState<Record<number, boolean>>({});
  const [recipientsDirty, setRecipientsDirty] = useState(false);

  const settings = useStaffGet<ApiSettings>(
    ["api-settings", makerspace.id],
    `/admin/makerspace/${makerspace.id}/api-settings`,
  );
  const recipients = useStaffGet<NotificationRecipient[]>(
    ["notification-recipients", makerspace.id],
    `/admin/makerspace/${makerspace.id}/notification-recipients`,
  );

  useEffect(() => {
    if (!settings.data) return;
    setSmtpForm({
      smtp_host: settings.data.smtp_host ?? "",
      smtp_port: String(settings.data.smtp_port ?? 587),
      smtp_username: settings.data.smtp_username ?? "",
      smtp_password: "",
      smtp_use_tls: settings.data.smtp_use_tls,
      smtp_use_ssl: settings.data.smtp_use_ssl,
      smtp_from_email: settings.data.smtp_from_email ?? "",
    });
  }, [settings.data]);

  useEffect(() => {
    if (!recipients.data) return;
    setRecipientChecks(
      Object.fromEntries(
        recipients.data.map((recipient) => [recipient.id, recipient.receives_notifications]),
      ),
    );
    setRecipientsDirty(false);
  }, [recipients.data]);

  const saveSmtpSettings = useMutation({
    mutationFn: () =>
      staffRequest<ApiSettings>(`/admin/makerspace/${makerspace.id}/api-settings`, {
        method: "PATCH",
        body: JSON.stringify(smtpPayload(smtpForm)),
      }),
    onSuccess: () => {
      setSmtpForm((current) => ({ ...current, smtp_password: "" }));
      queryClient.invalidateQueries({ queryKey: ["api-settings", makerspace.id] });
      showToast("Email settings saved", { tone: "success" });
    },
    onError: (error) => showToast(errorText(error, "Couldn't save the email settings"), { tone: "error" }),
  });

  const clearSmtpPassword = useMutation({
    mutationFn: () =>
      staffRequest<ApiSettings>(`/admin/makerspace/${makerspace.id}/api-settings`, {
        method: "PATCH",
        body: JSON.stringify({ smtp_password: "" }),
      }),
    onSuccess: () => {
      setSmtpForm((current) => ({ ...current, smtp_password: "" }));
      queryClient.invalidateQueries({ queryKey: ["api-settings", makerspace.id] });
      showToast("SMTP password cleared", { tone: "success" });
    },
    onError: (error) => showToast(errorText(error, "Couldn't clear the SMTP password"), { tone: "error" }),
  });
  const saveRecipients = useMutation({
    mutationFn: () =>
      staffRequest<NotificationRecipient[]>(
        `/admin/makerspace/${makerspace.id}/notification-recipients`,
        {
          method: "PATCH",
          body: JSON.stringify({
            recipients: (recipients.data ?? []).map((recipient) => ({
              id: recipient.id,
              receives_notifications:
                recipientChecks[recipient.id] ?? recipient.receives_notifications,
            })),
          }),
        },
      ),
    onSuccess: (updated) => {
      setRecipientChecks(
        Object.fromEntries(
          updated.map((recipient) => [recipient.id, recipient.receives_notifications]),
        ),
      );
      setRecipientsDirty(false);
      queryClient.invalidateQueries({ queryKey: ["notification-recipients", makerspace.id] });
      showToast("Recipients saved", { tone: "success" });
    },
    onError: (error) => showToast(errorText(error, "Couldn't save the recipients"), { tone: "error" }),
  });

  const set = (patch: Partial<SmtpSettingsForm>) => setSmtpForm((current) => ({ ...current, ...patch }));

  return (
    <>
      <Card as="section" aria-labelledby="smtp-settings-title">
        <CardHeader
          title={<span id="smtp-settings-title">Email (SMTP)</span>}
          description="The sender used for staff lifecycle notifications."
          action={(
            <>
              <Button
                variant="secondary"
                size="sm"
                disabled={!settings.data?.smtp_password_set}
                loading={clearSmtpPassword.isPending}
                loadingLabel="Clearing…"
                onClick={() => clearSmtpPassword.mutate()}
              >
                Clear SMTP password
              </Button>
              <Button
                variant="primary"
                size="sm"
                disabled={!settings.isSuccess}
                loading={saveSmtpSettings.isPending}
                loadingLabel="Saving…"
                onClick={() => saveSmtpSettings.mutate()}
              >
                Save email settings
              </Button>
            </>
          )}
        />
        {settings.isLoading ? <Skeleton className="h-32 w-full" /> : null}
        <ErrorText message={settings.error?.message} />
        <SettingsRow title="Server" description="Host and port of your mail provider.">
          <div className="grid gap-4 sm:grid-cols-[minmax(0,1fr)_140px]">
            <Field label="SMTP host"><Input value={smtpForm.smtp_host} onChange={(event) => set({ smtp_host: event.target.value })} /></Field>
            <Field label="SMTP port"><Input inputMode="numeric" value={smtpForm.smtp_port} onChange={(event) => set({ smtp_port: event.target.value })} /></Field>
          </div>
        </SettingsRow>
        <SettingsRow title="Sign-in" description="Leave the password blank to keep the saved one.">
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="SMTP username"><Input value={smtpForm.smtp_username} onChange={(event) => set({ smtp_username: event.target.value })} /></Field>
            <Field label="SMTP password" helperText={settings.data?.smtp_password_set ? "A password is saved." : undefined}>
              <PasswordInput
                autoComplete="new-password"
                placeholder={settings.data?.smtp_password_set ? "SMTP password set" : undefined}
                value={smtpForm.smtp_password}
                onChange={(event) => set({ smtp_password: event.target.value })}
              />
            </Field>
          </div>
        </SettingsRow>
        <SettingsRow title="Sender" description="The address staff emails come from.">
          <Field label="SMTP from email"><Input type="email" value={smtpForm.smtp_from_email} onChange={(event) => set({ smtp_from_email: event.target.value })} /></Field>
        </SettingsRow>
        <SettingsRow title="Encryption" description="Pick one. Most providers use STARTTLS on port 587.">
          <div className="grid gap-3">
            <CheckboxField
              label="Use STARTTLS (587)"
              checked={smtpForm.smtp_use_tls}
              onCheckedChange={(value) => {
                const checked = value === true;
                set({ smtp_use_tls: checked, smtp_use_ssl: checked ? false : smtpForm.smtp_use_ssl });
              }}
            />
            <CheckboxField
              label="Use implicit SSL (465)"
              checked={smtpForm.smtp_use_ssl}
              onCheckedChange={(value) => {
                const checked = value === true;
                set({ smtp_use_ssl: checked, smtp_use_tls: checked ? false : smtpForm.smtp_use_tls });
              }}
            />
          </div>
        </SettingsRow>
        <div className="grid gap-2">
          <ErrorText message={saveSmtpSettings.error?.message} />
          <ErrorText message={clearSmtpPassword.error?.message} />
        </div>
      </Card>

      <Card as="section" aria-labelledby="notification-recipients-title">
        <CardHeader
          title={<span id="notification-recipients-title">Notification recipients</span>}
          description="Unticked managers won't get hardware and printing lifecycle emails for this makerspace."
          action={(
            <Button
              variant="primary"
              size="sm"
              disabled={!recipients.isSuccess || !recipientsDirty || !recipients.data?.length}
              loading={saveRecipients.isPending}
              loadingLabel="Saving…"
              onClick={() => saveRecipients.mutate()}
            >
              Save recipients
            </Button>
          )}
        />
        {recipients.isLoading ? <Skeleton className="h-20 w-full" /> : null}
        <div className="grid gap-2">
          {recipients.data?.map((recipient) => (
            <CheckboxField
              key={recipient.id}
              className="rounded-md border border-line p-3"
              label={<span className="font-semibold">{recipient.username}</span>}
              description={`${recipient.email} · ${roleLabel(recipient.role)}`}
              checked={recipientChecks[recipient.id] ?? recipient.receives_notifications}
              onCheckedChange={(value) => {
                setRecipientChecks({ ...recipientChecks, [recipient.id]: value === true });
                setRecipientsDirty(true);
              }}
            />
          ))}
        </div>
        {!recipients.isLoading && recipients.data?.length === 0 ? (
          <EmptyState title="No managers to notify yet" description="Managers appear here once they have a staff role in this makerspace." />
        ) : null}
        <div className="mt-3 grid gap-2">
          <ErrorText message={recipients.error?.message} />
          <ErrorText message={saveRecipients.error?.message} />
        </div>
      </Card>
    </>
  );
}

function smtpPayload(form: SmtpSettingsForm) {
  const payload: Record<string, string | number | boolean> = {
    smtp_host: form.smtp_host,
    smtp_port: Number(form.smtp_port) || 587,
    smtp_username: form.smtp_username,
    smtp_use_tls: form.smtp_use_tls,
    smtp_use_ssl: form.smtp_use_ssl,
    smtp_from_email: form.smtp_from_email,
  };
  if (form.smtp_password) payload.smtp_password = form.smtp_password;
  return payload;
}

function roleLabel(role: NotificationRecipient["role"]) {
  return {
    space_manager: "Space manager",
    inventory_manager: "Inventory manager",
    machine_manager: "Machine manager",
  }[role];
}
