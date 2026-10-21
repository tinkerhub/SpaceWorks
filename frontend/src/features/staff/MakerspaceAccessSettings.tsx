import { useMutation, useQueryClient } from "@tanstack/react-query";

import { Card, CardHeader, Dropdown, Field, SettingsRow, useToast } from "../../components/ui";
import { staffRequest } from "../../lib/api";
import { errorText, type Makerspace } from "./panels/shared";
import { SettingSwitch } from "./settingsControls";

type Props = { makerspace: Makerspace; settings?: Makerspace; loading: boolean };
type PrintLookupPolicy = Makerspace["public_print_status_lookup_policy"];

/** One-field PATCH on the makerspace row, refreshing every query that carries it. */
function useMakerspacePatch<T>(makerspaceId: number, field: string, success: (value: T) => string, failure: string) {
  const queryClient = useQueryClient();
  const { showToast } = useToast();
  return useMutation({
    mutationFn: (next: T) =>
      staffRequest<Makerspace>(`/admin/makerspaces/${makerspaceId}`, {
        method: "PATCH",
        body: JSON.stringify({ [field]: next }),
      }),
    onSuccess: (_data, next) => {
      queryClient.invalidateQueries({ queryKey: ["makerspace-settings", makerspaceId] });
      queryClient.invalidateQueries({ queryKey: ["makerspaces"] });
      queryClient.invalidateQueries({ queryKey: ["staff", "makerspaces"] });
      showToast(success(next), { tone: "success" });
    },
    onError: (error) => showToast(errorText(error, failure), { tone: "error" }),
  });
}

export function MakerspaceSuperadminAccessSettings({ makerspace, settings, loading, isSuperadmin }: Props & { isSuperadmin: boolean }) {
  const enabled = settings?.superadmin_access_enabled ?? makerspace.superadmin_access_enabled ?? true;
  const update = useMakerspacePatch<boolean>(
    makerspace.id,
    "superadmin_access_enabled",
    (next) => (next ? "Superadmin access is on" : "Superadmin access is off"),
    "Couldn't change superadmin access",
  );
  // Once a makerspace admin turns it off, only they can turn it back on.
  const reEnableBlocked = isSuperadmin && !enabled;
  return (
    <Card as="section">
      <CardHeader title="Access" description="Who outside this makerspace can see it." />
      <SettingsRow
        title="Superadmin access"
        description="When off, this makerspace is hidden from the superadmin's reports, dashboards, audit, and admin lists. It does not revoke the superadmin's platform/database access. Only the makerspace admin can turn it back on."
      >
        <SettingSwitch
          label="Allow superadmin access"
          checked={enabled}
          disabled={loading || update.isPending || reEnableBlocked}
          onCheckedChange={(checked) => update.mutate(checked)}
          error={update.error?.message}
        />
        {reEnableBlocked ? <p className="mt-2 text-caption text-ink-muted">Re-enable is controlled by the makerspace admin.</p> : null}
      </SettingsRow>
    </Card>
  );
}

export function MakerspaceStaffNotificationSettings({ makerspace, settings, loading }: Props) {
  const enabled = settings?.staff_notifications_enabled ?? makerspace.staff_notifications_enabled ?? true;
  const update = useMakerspacePatch<boolean>(
    makerspace.id,
    "staff_notifications_enabled",
    (next) => (next ? "Staff emails are on" : "Staff emails are off"),
    "Couldn't change staff emails",
  );
  return (
    <Card as="section">
      <CardHeader title="Staff email notifications" description="Email this makerspace's managers when hardware and print request statuses change." />
      <SettingsRow title="Staff emails" description="Managers get an email for each status change. Channels below cover chat and push.">
        <SettingSwitch
          label="Send staff emails"
          checked={enabled}
          disabled={loading || update.isPending}
          onCheckedChange={(checked) => update.mutate(checked)}
          error={update.error?.message}
        />
      </SettingsRow>
    </Card>
  );
}

export function MakerspacePrintStatusSettings({ makerspace, settings, loading }: Props) {
  const policy = settings?.public_print_status_lookup_policy ?? makerspace.public_print_status_lookup_policy ?? "email_unverified";
  const update = useMakerspacePatch<PrintLookupPolicy>(
    makerspace.id,
    "public_print_status_lookup_policy",
    (next) => `Print status recovery set to ${statusLookupLabel(next).toLowerCase()}`,
    "Couldn't change print status recovery",
  );
  return (
    <Card as="section">
      <CardHeader title="Public print status recovery" description="Controls whether public print requests can be recovered from an email address when the status link is lost." />
      <SettingsRow title="Lookup policy" description="Token only means the status link is the only way back in.">
        <Field label="Public print status lookup policy" hideLabel error={update.error?.message} className="max-w-xs">
          <Dropdown
            value={policy}
            disabled={loading || update.isPending}
            onChange={(event) => update.mutate(event.target.value as PrintLookupPolicy)}
          >
            <option value="token_only">Token only</option>
            <option value="email_unverified">Email lookup</option>
          </Dropdown>
        </Field>
      </SettingsRow>
    </Card>
  );
}

function statusLookupLabel(policy: PrintLookupPolicy) {
  return { token_only: "Token only", email_unverified: "Email lookup" }[policy ?? "email_unverified"];
}
