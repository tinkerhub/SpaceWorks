import { useMutation, useQueryClient } from "@tanstack/react-query";

import { Card, CardHeader, SettingsRow, useToast } from "../../components/ui";
import { staffRequest } from "../../lib/api";
import { moduleEnabled } from "../../lib/modules";
import { errorText, type Makerspace } from "./panels/shared";
import { SettingSwitch } from "./settingsControls";

type Props = {
  makerspace: Makerspace;
  settings?: Makerspace;
  loading: boolean;
};

export function MakerspacePublicStatsSettings({ makerspace, settings, loading }: Props) {
  const queryClient = useQueryClient();
  const { showToast } = useToast();
  const publicStatsEnabled = settings?.public_stats_enabled ?? makerspace.public_stats_enabled ?? false;
  const showHolderNames =
    settings?.public_stats_show_holder_names ?? makerspace.public_stats_show_holder_names ?? false;

  const invalidateSettings = () => {
    queryClient.invalidateQueries({ queryKey: ["makerspace-settings", makerspace.id] });
    queryClient.invalidateQueries({ queryKey: ["makerspaces"] });
    queryClient.invalidateQueries({ queryKey: ["staff", "makerspaces"] });
  };
  const updatePublicStats = useMutation({
    mutationFn: (next: boolean) =>
      staffRequest<Makerspace>(`/admin/makerspaces/${makerspace.id}`, {
        method: "PATCH",
        body: JSON.stringify({ public_stats_enabled: next }),
      }),
    onSuccess: (_data, next) => {
      invalidateSettings();
      showToast(next ? "Public stats page published" : "Public stats page hidden", { tone: "success" });
    },
    onError: (error) => showToast(errorText(error, "Couldn't change the public stats page"), { tone: "error" }),
  });
  const updateHolderNames = useMutation({
    mutationFn: (next: boolean) =>
      staffRequest<Makerspace>(`/admin/makerspaces/${makerspace.id}`, {
        method: "PATCH",
        body: JSON.stringify({ public_stats_show_holder_names: next }),
      }),
    onSuccess: (_data, next) => {
      invalidateSettings();
      showToast(next ? "Borrower names are public" : "Borrower names are hidden", { tone: "success" });
    },
    onError: (error) => showToast(errorText(error, "Couldn't change borrower names"), { tone: "error" }),
  });

  return (
    <Card as="section">
      <CardHeader
        title="Public stats"
        description={`A public activity page with ${moduleEnabled(settings?.enabled_modules ?? makerspace.enabled_modules, "printing") ? "print hours, " : ""}popular hardware and current loans.`}
      />
      <SettingsRow
        title="Public stats page"
        description={
          <>
            Published at <code className="font-mono">/m/{makerspace.slug}/stats</code>. When off, the page and its API
            return 404 and the link is hidden. Borrower names are controlled separately below.
          </>
        }
      >
        <SettingSwitch
          label="Publish public stats"
          checked={publicStatsEnabled}
          disabled={loading || updatePublicStats.isPending}
          onCheckedChange={(checked) => updatePublicStats.mutate(checked)}
          error={updatePublicStats.error?.message}
        />
      </SettingsRow>
      <SettingsRow
        title="Public borrower names"
        description="When on, each current loan publishes the borrower's name on the unauthenticated public stats page. When off, every borrower is shown as “Borrower”."
      >
        <SettingSwitch
          label="Publish borrower names publicly"
          checked={showHolderNames}
          warnWhenOn
          disabled={loading || updateHolderNames.isPending}
          onCheckedChange={(checked) => updateHolderNames.mutate(checked)}
          error={updateHolderNames.error?.message}
        />
      </SettingsRow>
    </Card>
  );
}
