import { useMutation, useQueryClient } from "@tanstack/react-query";

import { Card, CardHeader, SettingsRow, useToast } from "../../components/ui";
import { staffRequest } from "../../lib/api";
import { errorText, type Makerspace } from "./panels/shared";
import { SettingSwitch } from "./settingsControls";

export function MakerspaceBookingSettings({ makerspace, settings, loading }: {
  makerspace: Makerspace;
  settings?: Makerspace;
  loading: boolean;
}) {
  const queryClient = useQueryClient();
  const { showToast } = useToast();
  const enabled = settings?.booking_requester_notifications_enabled
    ?? makerspace.booking_requester_notifications_enabled
    ?? false;
  const update = useMutation({
    mutationFn: (next: boolean) => staffRequest<Makerspace>("/admin/makerspaces/" + makerspace.id, {
      method: "PATCH",
      body: JSON.stringify({ booking_requester_notifications_enabled: next }),
    }),
    onSuccess: async (_data, next) => {
      showToast(next ? "Booking emails are on" : "Booking emails are off", { tone: "success" });
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["makerspace-settings", makerspace.id] }),
        queryClient.invalidateQueries({ queryKey: ["staff", "makerspaces"] }),
        queryClient.invalidateQueries({ queryKey: ["bookings", makerspace.id] }),
      ]);
    },
    onError: (error) => showToast(errorText(error, "Couldn't change booking emails"), { tone: "error" }),
  });

  return (
    <Card as="section">
      <CardHeader title="Booking emails" description="What people who book a space hear from you." />
      <SettingsRow
        title="Booking requester emails"
        description="The default for booking submitted, confirmed and rejected emails. Each space may inherit or override this setting."
      >
        <SettingSwitch
          label="Email booking requesters"
          checked={enabled}
          disabled={loading || update.isPending}
          onCheckedChange={(checked) => update.mutate(checked)}
          error={update.error?.message}
        />
      </SettingsRow>
    </Card>
  );
}
