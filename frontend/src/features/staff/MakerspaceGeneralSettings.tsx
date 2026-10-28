import { useEffect, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { Button, Card, CardHeader, Field, Input, SettingsRow, useToast } from "../../components/ui";
import { staffRequest } from "../../lib/api";
import { errorText, type Makerspace } from "./panels/shared";
import { SettingSwitch } from "./settingsControls";

type Props = {
  makerspace: Makerspace;
  settings?: Makerspace;
  loading: boolean;
};

export function MakerspaceGeneralSettings({ makerspace, settings, loading }: Props) {
  const queryClient = useQueryClient();
  const { showToast } = useToast();
  const currentDefaultLoanDays = settings?.default_loan_days ?? makerspace.default_loan_days ?? 7;
  const publicInventoryEnabled =
    settings?.public_inventory_enabled ?? makerspace.public_inventory_enabled ?? true;
  const [defaultLoanDays, setDefaultLoanDays] = useState(String(currentDefaultLoanDays));

  useEffect(() => {
    setDefaultLoanDays(String(currentDefaultLoanDays));
  }, [currentDefaultLoanDays, makerspace.id]);

  const refreshSettings = () => {
    queryClient.invalidateQueries({ queryKey: ["makerspace-settings", makerspace.id] });
    queryClient.invalidateQueries({ queryKey: ["makerspaces"] });
    queryClient.invalidateQueries({ queryKey: ["staff", "makerspaces"] });
  };

  const updateDefaultLoanDays = useMutation({
    mutationFn: (value: string) =>
      staffRequest<Makerspace>(`/admin/makerspaces/${makerspace.id}`, {
        method: "PATCH",
        body: JSON.stringify({ default_loan_days: Number(value) || 7 }),
      }),
    onSuccess: () => {
      refreshSettings();
      showToast("Default loan days saved", { tone: "success" });
    },
    onError: (error) => showToast(errorText(error, "Couldn't save the default loan days"), { tone: "error" }),
  });

  const updatePublicInventory = useMutation({
    mutationFn: (next: boolean) =>
      staffRequest<Makerspace>(`/admin/makerspaces/${makerspace.id}`, {
        method: "PATCH",
        body: JSON.stringify({ public_inventory_enabled: next }),
      }),
    onSuccess: (_data, next) => {
      refreshSettings();
      showToast(next ? "Public inventory is on" : "Public inventory is off", { tone: "success" });
    },
    onError: (error) => showToast(errorText(error, "Couldn't change public inventory"), { tone: "error" }),
  });

  return (
    <Card as="section">
      <CardHeader title="General" description="Loan defaults and what the public can browse." />
      <SettingsRow title="Default loan days" description="Default return window applied when a hardware request is issued.">
        <form
          className="flex min-w-0 flex-wrap items-start gap-3"
          onSubmit={(event) => {
            event.preventDefault();
            updateDefaultLoanDays.mutate(defaultLoanDays);
          }}
        >
          <Field label="Default loan days" hideLabel error={updateDefaultLoanDays.error?.message} className="w-40">
            <Input
              id="default-loan-days"
              type="number"
              min="1"
              value={defaultLoanDays}
              disabled={loading || updateDefaultLoanDays.isPending}
              onChange={(event) => setDefaultLoanDays(event.target.value)}
            />
          </Field>
          <Button type="submit" disabled={loading} loading={updateDefaultLoanDays.isPending} loadingLabel="Saving…">
            Save default days
          </Button>
        </form>
      </SettingsRow>
      <SettingsRow
        title="Public inventory"
        description="When off, the public inventory catalog is hidden. This does not delete any inventory data."
      >
        <SettingSwitch
          label="Show public inventory"
          checked={publicInventoryEnabled}
          disabled={loading || updatePublicInventory.isPending}
          onCheckedChange={(checked) => updatePublicInventory.mutate(checked)}
          error={updatePublicInventory.error?.message}
        />
      </SettingsRow>
    </Card>
  );
}
