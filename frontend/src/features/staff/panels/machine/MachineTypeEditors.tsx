import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { Button, CheckboxField, Dropdown, Field, Input, SwitchRow } from "../../../../components/ui";
import {
  getMachineTypePricing,
  machineKeys,
  setMachineTypePricing,
  updateMachineType,
  type MachineType,
  type MachineTypeCapabilityConfig,
  type MeteringUnit,
} from "../../machinesApi";
import { CapabilityPresetListEditor } from "./CapabilityPresetListEditor";
import { useNotify } from "./machineUi";
import { configFor, effectiveConfig } from "./typeConfig";

export { configFor } from "./typeConfig";

export const meteringUnits: Array<{ value: MeteringUnit; label: string }> = [
  { value: "weight", label: "Weight (grams)" },
  { value: "volume", label: "Volume (milliliters)" },
  { value: "length", label: "Length (millimeters)" },
  { value: "count", label: "Count" },
  { value: "minutes", label: "Minutes" },
];
/** Starting values of the New machine type form (a choice the manager edits, not a fallback). */
export const defaultConfig: MachineTypeCapabilityConfig = { metering_unit: "count", requires_booking: false, uses_consumables: true };

type PresetKey = "accepted_materials" | "accepted_colours";

function withPresetList(config: MachineTypeCapabilityConfig, key: PresetKey, values: string[]) {
  if (values.length) return { ...config, [key]: values };
  const next = { ...config };
  delete next[key];
  return next;
}

/** Leaving minutes for a stock unit starts with consumables on: that is the stock units' default. */
function withUnit(config: MachineTypeCapabilityConfig, unit: MeteringUnit): MachineTypeCapabilityConfig {
  const leavingMinutes = config.metering_unit === "minutes" && unit !== "minutes";
  return { ...config, metering_unit: unit, uses_consumables: leavingMinutes ? true : config.uses_consumables };
}

/** Metering unit, booking, consumables and the material / colour presets: the shared body of the type forms. */
export function CapabilityFields({ config, disabled = false, showBooking = true, showPresets = true, meteringLocked = false, onChange }: {
  config: MachineTypeCapabilityConfig;
  disabled?: boolean;
  /** "Requires booking" only means something while the bookings module is on. */
  showBooking?: boolean;
  /** Built-in types keep their material and colour presets. */
  showPresets?: boolean;
  /** The 3D printer is always weight-metered and always draws from filament pools. */
  meteringLocked?: boolean;
  onChange: (config: MachineTypeCapabilityConfig) => void;
}) {
  return (
    <>
      <Field label="Metering unit">
        <Dropdown value={config.metering_unit} disabled={disabled || meteringLocked} onChange={(event) => onChange(withUnit(config, event.target.value as MeteringUnit))}>
          {meteringUnits.map((unit) => <option key={unit.value} value={unit.value}>{unit.label}</option>)}
        </Dropdown>
      </Field>
      {showBooking ? (
        <CheckboxField
          className="self-center sm:col-span-2"
          label="Requires booking"
          description="Members book a slot before using this type."
          checked={config.requires_booking}
          disabled={disabled}
          onCheckedChange={(checked) => onChange({ ...config, requires_booking: checked === true })}
        />
      ) : null}
      {/* Time is never drawn from a stock pool, so the switch only exists for stock units. */}
      {config.metering_unit !== "minutes" ? (
        <SwitchRow
          className="rounded-lg border border-line p-3 sm:col-span-full"
          label="Uses consumables"
          description="Jobs draw from stock pools kept in this unit."
          checked={config.uses_consumables !== false}
          disabled={disabled || meteringLocked}
          onCheckedChange={(checked) => onChange({ ...config, uses_consumables: checked })}
        />
      ) : null}
      {showPresets ? (
        <div className="grid gap-3 sm:col-span-full md:grid-cols-2">
          <CapabilityPresetListEditor
            label="Materials"
            singularLabel="Material"
            values={config.accepted_materials ?? []}
            disabled={disabled}
            onChange={(values) => onChange(withPresetList(config, "accepted_materials", values))}
          />
          <CapabilityPresetListEditor
            label="Colours"
            singularLabel="Colour"
            values={config.accepted_colours ?? []}
            disabled={disabled}
            onChange={(values) => onChange(withPresetList(config, "accepted_colours", values))}
          />
        </div>
      ) : null}
    </>
  );
}

// Short unit for the free threshold label: it is in the type's own metering unit.
const FREE_BELOW_UNITS: Record<string, string> = { weight: "g", minutes: "min", volume: "ml", length: "mm", count: "items" };

export function PricingEditor({ makerspaceId, machineType, currency, canEdit, canTogglePayment, paymentsOn }: {
  makerspaceId: number; machineType: MachineType; currency: string;
  /** Machine staff price the types they manage; space managers price every type. */
  canEdit: boolean;
  /** Online payment is a space-manager decision. */
  canTogglePayment: boolean;
  paymentsOn: boolean;
}) {
  const queryClient = useQueryClient();
  const notify = useNotify();
  const pricing = useQuery({ queryKey: machineKeys.pricing(makerspaceId), queryFn: () => getMachineTypePricing(makerspaceId), enabled: canEdit });
  const row = pricing.data?.results.find((item) => item.machine_type_id === machineType.id);
  const [rate, setRate] = useState("");
  const [flatFee, setFlatFee] = useState("");
  const [paymentEnabled, setPaymentEnabled] = useState<boolean | null>(null);
  const [freeBelow, setFreeBelow] = useState("");
  const unit = FREE_BELOW_UNITS[effectiveConfig(machineType).metering_unit] ?? "units";
  // Upper-case for display, and no "(...)" suffix at all until the currency is known.
  const money = currency ? ` (${currency.toUpperCase()})` : "";
  const mutation = useMutation({
    mutationFn: () => setMachineTypePricing(makerspaceId, machineType.id, {
      rate_per_unit: rate || row?.rate_per_unit || "0.00",
      flat_fee: flatFee || row?.flat_fee || "0.00",
      payment_enabled: paymentEnabled ?? row?.payment_enabled ?? false,
      free_below_quantity: freeBelow || row?.free_below_quantity || "0.00",
    }),
    onSuccess: async () => {
      notify.success(`Pricing saved for ${machineType.name}`);
      await queryClient.invalidateQueries({ queryKey: machineKeys.pricing(makerspaceId) });
    },
    onError: (error) => notify.failure("Couldn't save pricing.", error),
  });
  const shownRate = rate || row?.rate_per_unit || "0.00";
  const shownFlatFee = flatFee || row?.flat_fee || "0.00";
  const shownEnabled = paymentEnabled ?? row?.payment_enabled ?? false;
  const shownFreeBelow = freeBelow || row?.free_below_quantity || "0.00";

  // Machine staff only get pricing rows for the types they manage; no row = not theirs, and
  // until the rows load nothing says which types those are.
  if (!canEdit || (!canTogglePayment && !row)) return null;
  return (
    <div className="grid gap-3 border-t border-line pt-4">
      <h4 className="text-label text-ink">Pricing</h4>
      <div className="grid items-start gap-3 sm:grid-cols-2 md:grid-cols-3">
        <Field label={`Rate per unit${money}`}>
          <Input type="number" min="0" step="0.01" inputMode="decimal" value={shownRate} onChange={(event) => setRate(event.target.value)} />
        </Field>
        <Field label={`Flat fee${money}`}>
          <Input type="number" min="0" step="0.01" inputMode="decimal" value={shownFlatFee} onChange={(event) => setFlatFee(event.target.value)} />
        </Field>
        <Field label={`Free below (${unit})`} helperText="Manual usage under this is logged as free.">
          <Input type="number" min="0" step="0.01" inputMode="decimal" value={shownFreeBelow} onChange={(event) => setFreeBelow(event.target.value)} />
        </Field>
        {/* Online charging needs the payments module; the price itself is also what manual usage logs. */}
        {paymentsOn && canTogglePayment ? <CheckboxField className="sm:col-span-full" label="Enable payment" checked={shownEnabled} onCheckedChange={(checked) => setPaymentEnabled(checked === true)} /> : null}
        <div className="flex justify-end sm:col-span-2 md:col-span-3">
          {/* Saving before the stored row loads would overwrite it with the zero placeholders. */}
          <Button onClick={() => mutation.mutate()} loading={mutation.isPending} loadingLabel="Saving…" disabled={!pricing.isSuccess}>Save pricing</Button>
        </div>
      </div>
      {pricing.isLoading ? <p className="text-caption text-ink-muted" role="status">Loading pricing…</p> : null}
      {pricing.error instanceof Error ? <p className="text-caption text-danger-fg">{pricing.error.message}</p> : null}
      {mutation.error instanceof Error ? <p className="text-caption text-danger-fg">{mutation.error.message}</p> : null}
    </div>
  );
}

export function CustomTypeRow({ makerspaceId, machineType, canConfigure, canEditPricing = canConfigure, currency, paymentsOn = true, showBooking = true }: {
  makerspaceId: number; machineType: MachineType; canConfigure: boolean; canEditPricing?: boolean; currency: string; paymentsOn?: boolean; showBooking?: boolean;
}) {
  const queryClient = useQueryClient();
  const notify = useNotify();
  const [name, setName] = useState(machineType.name);
  const [icon, setIcon] = useState(machineType.icon);
  const [config, setConfig] = useState(configFor(machineType));
  const rename = useMutation({
    mutationFn: () => updateMachineType(makerspaceId, machineType.id, { name: name.trim(), icon: icon.trim(), capability_config: config }),
    onSuccess: async () => {
      notify.success(`${name.trim()} saved`);
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: machineKeys.types(makerspaceId) }),
        queryClient.invalidateQueries({ queryKey: machineKeys.list(makerspaceId) }),
      ]);
    },
    onError: (error) => notify.failure("Couldn't save the machine type.", error),
  });
  return (
    <li className="grid gap-4 rounded-lg border border-line bg-canvas p-4">
      <form className="grid gap-4 sm:grid-cols-2 md:grid-cols-3" onSubmit={(event) => { event.preventDefault(); rename.mutate(); }}>
        <div className="flex flex-wrap items-center justify-between gap-2 sm:col-span-full">
          <h3 className="text-title text-ink">{machineType.name}</h3>
          <span className="text-caption text-ink-muted">Slug <span className="font-mono">{machineType.slug}</span> (fixed)</span>
        </div>
        <Field label="Name"><Input value={name} disabled={!canConfigure} onChange={(event) => setName(event.target.value)} required /></Field>
        <Field label="Icon"><Input value={icon} disabled={!canConfigure} onChange={(event) => setIcon(event.target.value)} placeholder="Optional icon" /></Field>
        <CapabilityFields config={config} disabled={!canConfigure} showBooking={showBooking} onChange={setConfig} />
        {rename.error instanceof Error ? <p className="text-caption text-danger-fg sm:col-span-full">{rename.error.message}</p> : null}
        {canConfigure ? (
          <Button className="justify-self-start sm:col-span-full" type="submit" loading={rename.isPending} loadingLabel="Saving…" disabled={!name.trim()}>Save type</Button>
        ) : null}
      </form>
      <PricingEditor makerspaceId={makerspaceId} machineType={machineType} currency={currency} canEdit={canEditPricing} canTogglePayment={canConfigure} paymentsOn={paymentsOn} />
    </li>
  );
}
