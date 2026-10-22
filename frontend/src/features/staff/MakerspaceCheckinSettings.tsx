import { useEffect, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { Button, Callout, Card, CardHeader, Dropdown, Field, Input, SettingsRow, useToast } from "../../components/ui";
import { staffRequest } from "../../lib/api";
import { StructuredApiError } from "../../lib/apiErrors";
import { errorText, type Makerspace, useStaffGet } from "./panels/shared";

type Mode = "disabled" | "checked_in" | "anyone";

export type CheckinSettings = {
  public_request_mode: Mode;
  request_access: string;
  membership_installed: boolean;
  checkin_space_id: number | null;
  checkin_api_url: string;
  checkin_required_purpose: string;
  checkin_provider_name: string;
  deployment: { api_url: string; required_purpose: string; provider_name: string };
  effective: { api_url_source: "makerspace" | "deployment" | ""; required_purpose: string; provider_name: string };
};

export type CheckinTestResult = { ok: boolean; rows: number; space_rows: number | null; code: string; reason: string };

type Form = { mode: Mode; url: string; purpose: string; provider: string; spaceId: string };

const MODE_LABELS: Record<Mode, string> = {
  disabled: "An account is required",
  checked_in: "Anyone checked in (verified against your check-in roster)",
  anyone: "Anyone, no account needed",
};

function formFrom(data: CheckinSettings): Form {
  return {
    mode: data.public_request_mode,
    url: data.checkin_api_url,
    purpose: data.checkin_required_purpose,
    provider: data.checkin_provider_name,
    spaceId: data.checkin_space_id === null ? "" : String(data.checkin_space_id),
  };
}

function fieldError(error: unknown, field: string) {
  if (!(error instanceof StructuredApiError)) return undefined;
  const value = error.body[field];
  return Array.isArray(value) ? value.join(" ") : typeof value === "string" ? value : undefined;
}

/**
 * Who may submit borrow requests, and -- in check-in mode -- which roster admits them.
 * Blank roster fields fall back to the deployment's settings, shown as placeholders.
 * Hidden from staff who cannot change it unless the makerspace already runs check-in.
 */
export function MakerspaceCheckinSettings({ makerspace, canManageMakerspace }: { makerspace: Makerspace; canManageMakerspace: boolean }) {
  const queryClient = useQueryClient();
  const { showToast } = useToast();
  const path = `/admin/makerspaces/${makerspace.id}/checkin-settings`;
  const settings = useStaffGet<CheckinSettings>(["checkin-settings", makerspace.id], path);
  const [form, setForm] = useState<Form | null>(null);
  const set = (patch: Partial<Form>) => setForm((current) => (current ? { ...current, ...patch } : current));

  useEffect(() => {
    if (settings.data) setForm(formFrom(settings.data));
  }, [settings.data]);

  const save = useMutation({
    mutationFn: (values: Form) =>
      staffRequest<CheckinSettings>(path, {
        method: "PATCH",
        body: JSON.stringify(
          values.mode === "checked_in"
            ? {
                public_request_mode: values.mode,
                checkin_api_url: values.url.trim(),
                checkin_required_purpose: values.purpose.trim(),
                checkin_provider_name: values.provider.trim(),
                checkin_space_id: values.spaceId.trim() ? Number(values.spaceId) : null,
              }
            : { public_request_mode: values.mode },
        ),
      }),
    onSuccess: (data) => {
      queryClient.setQueryData(["checkin-settings", makerspace.id], data);
      queryClient.invalidateQueries({ queryKey: ["makerspace-settings", makerspace.id] });
      showToast("Check-in settings saved", { tone: "success" });
    },
    onError: (error) => showToast(errorText(error, "Couldn't save the check-in settings"), { tone: "error" }),
  });

  const test = useMutation({
    mutationFn: (url: string) =>
      staffRequest<CheckinTestResult>(`${path}/test`, { method: "POST", body: JSON.stringify({ checkin_api_url: url.trim() }) }),
    onError: (error) => showToast(errorText(error, "Couldn't test the roster"), { tone: "error" }),
  });

  const data = settings.data;
  if (!data || !form) return null;
  if (!canManageMakerspace && data.public_request_mode !== "checked_in") return null;

  const readOnly = !canManageMakerspace;
  const busy = save.isPending;
  const checkedIn = form.mode === "checked_in";
  const deployment = data.deployment;

  return (
    <Card as="section">
      <CardHeader
        title="Check-in"
        description="Let people borrow by checking in at your space, verified against your check-in system's live roster."
      />
      <form
        onSubmit={(event) => {
          event.preventDefault();
          save.mutate(form);
        }}
      >
        <fieldset disabled={readOnly || busy} className="grid min-w-0 gap-0">
          <SettingsRow title="Who can submit borrow requests" description={data.membership_installed ? "Only active members can, while the membership module is on." : "Check-in needs no member accounts."}>
            <Field label="Who can submit borrow requests" hideLabel error={fieldError(save.error, "public_request_mode")}>
              <Dropdown value={form.mode} disabled={readOnly || busy || data.membership_installed} onChange={(event) => set({ mode: event.target.value as Mode })}>
                {(Object.keys(MODE_LABELS) as Mode[]).map((mode) => (
                  <option key={mode} value={mode}>{MODE_LABELS[mode]}</option>
                ))}
              </Dropdown>
            </Field>
          </SettingsRow>
          {checkedIn ? (
            <SettingsRow title="Roster" description="Leave a field blank to use this server's default, shown in grey.">
              <div className="grid min-w-0 gap-4 sm:grid-cols-2">
                <Field label="Roster URL" className="sm:col-span-2" helperText="Public https:// address that lists who is checked in now." error={fieldError(save.error, "checkin_api_url")}>
                  <Input type="url" inputMode="url" maxLength={500} value={form.url} placeholder={deployment.api_url || "https://"} onChange={(event) => set({ url: event.target.value })} />
                </Field>
                <Field label="Required purpose" error={fieldError(save.error, "checkin_required_purpose")}>
                  <Input maxLength={200} value={form.purpose} placeholder={deployment.required_purpose} onChange={(event) => set({ purpose: event.target.value })} />
                </Field>
                <Field label="Check-in system name" helperText="Shown to borrowers." error={fieldError(save.error, "checkin_provider_name")}>
                  <Input maxLength={100} value={form.provider} placeholder={deployment.provider_name} onChange={(event) => set({ provider: event.target.value })} />
                </Field>
                <Field label="Upstream space ID" helperText="This space's number in the check-in system." error={fieldError(save.error, "checkin_space_id")}>
                  <Input type="number" min={1} inputMode="numeric" value={form.spaceId} onChange={(event) => set({ spaceId: event.target.value })} />
                </Field>
              </div>
            </SettingsRow>
          ) : null}
        </fieldset>
        {checkedIn && !readOnly ? (
          <div className="grid gap-2 pt-2">
            <div>
              <Button type="button" variant="secondary" size="sm" loading={test.isPending} loadingLabel="Testing…" onClick={() => test.mutate(form.url)}>
                Test connection
              </Button>
            </div>
            {test.data && !test.isPending ? (
              test.data.ok ? (
                <Callout tone="success" role="status">
                  Read {test.data.rows} {test.data.rows === 1 ? "person" : "people"} checked in
                  {test.data.space_rows === null ? "." : `, ${test.data.space_rows} at this space ID.`}
                </Callout>
              ) : (
                <Callout tone="danger" role="alert" title="Roster not read">{test.data.reason}</Callout>
              )
            ) : null}
          </div>
        ) : null}
        {readOnly ? (
          <p className="pt-2 text-caption text-ink-muted">Only staff who manage this makerspace can change this.</p>
        ) : (
          <div className="pt-4">
            <Button type="submit" loading={busy} loadingLabel="Saving…">Save check-in settings</Button>
          </div>
        )}
      </form>
    </Card>
  );
}
