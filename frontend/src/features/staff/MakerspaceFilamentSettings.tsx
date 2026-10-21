import { useEffect, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { Button, Card, CardHeader, Field, Input, SettingsRow, StatusChip, useToast } from "../../components/ui";
import { staffRequest } from "../../lib/api";
import { errorText, type Makerspace } from "./panels/shared";

type Props = {
  makerspace: Makerspace;
  settings?: Makerspace;
  loading: boolean;
};

export function MakerspaceFilamentSettings({ makerspace, settings, loading }: Props) {
  const queryClient = useQueryClient();
  const { showToast } = useToast();
  const currentThreshold =
    settings?.filament_low_stock_threshold_grams ??
    makerspace.filament_low_stock_threshold_grams ??
    "0.00";
  const [thresholdInput, setThresholdInput] = useState(String(currentThreshold));

  useEffect(() => {
    setThresholdInput(String(currentThreshold));
  }, [currentThreshold, makerspace.id]);

  const updateThreshold = useMutation({
    mutationFn: (next: string) =>
      staffRequest<Makerspace>(`/admin/makerspaces/${makerspace.id}`, {
        method: "PATCH",
        body: JSON.stringify({ filament_low_stock_threshold_grams: next || "0" }),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["makerspace-settings", makerspace.id] });
      queryClient.invalidateQueries({ queryKey: ["makerspaces"] });
      queryClient.invalidateQueries({ queryKey: ["staff", "makerspaces"] });
      showToast("Low-stock threshold saved", { tone: "success" });
    },
    onError: (error) => showToast(errorText(error, "Couldn't save the threshold"), { tone: "error" }),
  });

  const normalizedThreshold = thresholdInput.trim() || "0";
  const currentNumber = Number(currentThreshold);
  const nextNumber = Number(normalizedThreshold);
  const invalid = Number.isNaN(nextNumber) || nextNumber < 0;
  const saveDisabled =
    loading || updateThreshold.isPending || invalid || nextNumber === currentNumber;

  return (
    <Card as="section">
      <CardHeader
        title="Filament"
        description="Keep spools stocked without counting by hand."
        action={<StatusChip tone={currentNumber > 0 ? "success" : "neutral"} size="sm">{currentNumber > 0 ? `${currentThreshold} g` : "Off"}</StatusChip>}
      />
      <SettingsRow
        title="Filament low-stock threshold"
        description="Auto-add a printing to-buy item when an active spool reaches this remaining weight. Set 0 to turn it off."
      >
        <form
          className="flex min-w-0 flex-wrap items-start gap-3"
          onSubmit={(event) => {
            event.preventDefault();
            if (!saveDisabled) updateThreshold.mutate(normalizedThreshold);
          }}
        >
          <Field
            label="Threshold (g)"
            className="w-44"
            error={invalid ? "Enter zero or a positive gram value." : updateThreshold.error?.message}
          >
            <Input
              type="number"
              min={0}
              step="0.01"
              value={thresholdInput}
              disabled={loading || updateThreshold.isPending}
              onChange={(event) => setThresholdInput(event.target.value)}
            />
          </Field>
          <Button type="submit" className="sm:mt-[26px]" disabled={saveDisabled} loading={updateThreshold.isPending} loadingLabel="Saving…">
            Save threshold
          </Button>
        </form>
      </SettingsRow>
    </Card>
  );
}
