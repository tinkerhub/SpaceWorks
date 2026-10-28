import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { Button, Chip } from "../../../../components/ui";
import {
  isBuiltinPrinterType,
  machineKeys,
  setMachineTypeSettings,
  type EffectiveTypeConfig,
  type MachineType,
  type MachineTypeCapabilityConfig,
  type MachineTypeSettings,
} from "../../machinesApi";
import { CapabilityFields, PricingEditor, meteringUnits } from "./MachineTypeEditors";
import { useNotify } from "./machineUi";
import { effectiveConfig } from "./typeConfig";

/** Only what differs from the built-in is stored; matching values go back to inheriting it. */
function overridesFrom(draft: MachineTypeCapabilityConfig, builtin: EffectiveTypeConfig, builtinConsumables: boolean): MachineTypeSettings {
  const usesConsumables = draft.metering_unit !== "minutes" && draft.uses_consumables !== false;
  return {
    metering_unit: draft.metering_unit === builtin.metering_unit ? null : draft.metering_unit,
    requires_booking: draft.requires_booking === builtin.requires_booking ? null : draft.requires_booking,
    // Against the built-in's RAW switch: the effective one is forced off for a minutes type,
    // so a minutes built-in moved to weight with consumables off would otherwise send null
    // and inherit "on" from the raw config.
    uses_consumables: usesConsumables === builtinConsumables ? null : usesConsumables,
  };
}

/** A built-in type's unit, booking and consumables switch, changed for this makerspace only. */
function BuiltinTypeSettings({ makerspaceId, machineType, showBooking }: { makerspaceId: number; machineType: MachineType; showBooking: boolean }) {
  const queryClient = useQueryClient();
  const notify = useNotify();
  const current = effectiveConfig(machineType);
  // A global type's own capability_config IS the built-in default every makerspace inherits.
  const builtin = effectiveConfig({ capability_config: machineType.capability_config });
  const [draft, setDraft] = useState<MachineTypeCapabilityConfig>(current);
  const printer = isBuiltinPrinterType(machineType);
  const save = useMutation({
    mutationFn: (payload: MachineTypeSettings) => setMachineTypeSettings(makerspaceId, machineType.id, payload),
    onSuccess: async (updated) => {
      if (updated?.effective_config) setDraft(updated.effective_config);
      notify.success(`${machineType.name} settings saved for this makerspace`);
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: machineKeys.types(makerspaceId) }),
        queryClient.invalidateQueries({ queryKey: machineKeys.list(makerspaceId) }),
        queryClient.invalidateQueries({ queryKey: machineKeys.pricing(makerspaceId) }),
      ]);
    },
    onError: (error) => notify.failure("Couldn't save the type settings.", error),
  });
  return (
    <form className="grid items-start gap-4 rounded-lg border border-line bg-subtle p-4 sm:grid-cols-2 md:grid-cols-3" onSubmit={(event) => { event.preventDefault(); save.mutate(overridesFrom(draft, builtin, machineType.capability_config?.uses_consumables !== false)); }}>
      <div className="sm:col-span-full">
        <h4 className="text-label text-ink">Settings</h4>
        <p className="text-caption text-ink-muted">This makerspace only. Other makerspaces keep the built-in settings.</p>
      </div>
      <CapabilityFields config={draft} showBooking={showBooking} showPresets={false} meteringLocked={printer} onChange={setDraft} />
      {save.error instanceof Error ? <p className="text-caption text-danger-fg sm:col-span-full">{save.error.message}</p> : null}
      <div className="flex flex-wrap justify-end gap-2 sm:col-span-full">
        {current.overridden ? (
          <Button type="button" variant="quiet" disabled={save.isPending} onClick={() => save.mutate({ metering_unit: null, requires_booking: null, uses_consumables: null })}>
            Use built-in settings
          </Button>
        ) : null}
        <Button type="submit" loading={save.isPending} loadingLabel="Saving…">Save for this makerspace</Button>
      </div>
    </form>
  );
}

export function BuiltinTypeRow({ makerspaceId, machineType, canConfigure, canEditPricing = canConfigure, currency, paymentsOn = true, showBooking = true }: {
  makerspaceId: number; machineType: MachineType; canConfigure: boolean; canEditPricing?: boolean; currency: string; paymentsOn?: boolean; showBooking?: boolean;
}) {
  const config = effectiveConfig(machineType);
  return (
    <li className="grid gap-4 rounded-lg border border-line bg-canvas p-4">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <span className="min-w-0">
          <h3 className="text-title text-ink">{machineType.icon ? `${machineType.icon} ` : ""}{machineType.name}</h3>
          <span className="text-caption text-ink-muted">
            <span className="font-mono">{machineType.slug}</span> · {meteringUnits.find((unit) => unit.value === config.metering_unit)?.label ?? config.metering_unit} · {config.requires_booking ? "Booking required" : "No booking"} · {config.uses_consumables ? "Uses consumables" : "No consumables"}
          </span>
        </span>
        <Chip size="sm">{config.overridden ? "Built-in · changed for this makerspace" : "Built-in"}</Chip>
      </div>
      {canConfigure ? <BuiltinTypeSettings makerspaceId={makerspaceId} machineType={machineType} showBooking={showBooking} /> : null}
      <PricingEditor makerspaceId={makerspaceId} machineType={machineType} currency={currency} canEdit={canEditPricing} canTogglePayment={canConfigure} paymentsOn={paymentsOn} />
    </li>
  );
}
