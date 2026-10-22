import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { Button, CheckboxField, Chip, Dropdown, Field, Input } from "../../../../components/ui";
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

export const meteringUnits: Array<{ value: MeteringUnit; label: string }> = [
  { value: "weight", label: "Weight (grams)" },
  { value: "volume", label: "Volume (milliliters)" },
  { value: "length", label: "Length (millimeters)" },
  { value: "count", label: "Count" },
  { value: "minutes", label: "Minutes" },
];
export const defaultConfig: MachineTypeCapabilityConfig = { metering_unit: "count", requires_booking: false };

export function configFor(machineType: MachineType): MachineTypeCapabilityConfig {
  const config = machineType.capability_config;
  return config && meteringUnits.some((unit) => unit.value === config.metering_unit)
    ? config
    : defaultConfig;
}

type PresetKey = "accepted_materials" | "accepted_colours";

function withPresetList(config: MachineTypeCapabilityConfig, key: PresetKey, values: string[]) {
  if (values.length) return { ...config, [key]: values };
  const next = { ...config };
  delete next[key];
  return next;
}

/** Metering unit, booking and the material / colour presets: the shared body of both type forms. */
export function CapabilityFields({ config, disabled = false, showBooking = true, onChange }: {
  config: MachineTypeCapabilityConfig;
  disabled?: boolean;
  /** "Requires booking" only means something while the bookings module is on. */
  showBooking?: boolean;
  onChange: (config: MachineTypeCapabilityConfig) => void;
}) {
  return (
    <>
      <Field label="Metering unit">
        <Dropdown value={config.metering_unit} disabled={disabled} onChange={(event) => onChange({ ...config, metering_unit: event.target.value as MeteringUnit })}>
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
    </>
  );
}

export function PricingEditor({ makerspaceId, machineType, currency, canConfigure }: {
  makerspaceId: number; machineType: MachineType; currency: string; canConfigure: boolean;
}) {
  const queryClient = useQueryClient();
  const notify = useNotify();
  const pricing = useQuery({ queryKey: machineKeys.pricing(makerspaceId), queryFn: () => getMachineTypePricing(makerspaceId), enabled: canConfigure });
  const row = pricing.data?.results.find((item) => item.machine_type_id === machineType.id);
  const [rate, setRate] = useState("");
  const [flatFee, setFlatFee] = useState("");
  const [paymentEnabled, setPaymentEnabled] = useState<boolean | null>(null);
  const mutation = useMutation({
    mutationFn: () => setMachineTypePricing(makerspaceId, machineType.id, {
      rate_per_unit: rate || row?.rate_per_unit || "0.00",
      flat_fee: flatFee || row?.flat_fee || "0.00",
      payment_enabled: paymentEnabled ?? row?.payment_enabled ?? false,
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

  if (!canConfigure) return null;
  return (
    <div className="grid gap-3 border-t border-line pt-4">
      <h4 className="text-label text-ink">Pricing</h4>
      <div className="grid gap-3 sm:grid-cols-2 md:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto] md:items-end">
        <Field label={`Rate per unit (${currency})`}>
          <Input type="number" min="0" step="0.01" inputMode="decimal" value={shownRate} onChange={(event) => setRate(event.target.value)} />
        </Field>
        <Field label={`Flat fee (${currency})`}>
          <Input type="number" min="0" step="0.01" inputMode="decimal" value={shownFlatFee} onChange={(event) => setFlatFee(event.target.value)} />
        </Field>
        <Button onClick={() => mutation.mutate()} loading={mutation.isPending} loadingLabel="Saving…">Save pricing</Button>
        <CheckboxField className="sm:col-span-full" label="Enable payment" checked={shownEnabled} onCheckedChange={(checked) => setPaymentEnabled(checked === true)} />
      </div>
      {pricing.isLoading ? <p className="text-caption text-ink-muted" role="status">Loading pricing…</p> : null}
      {pricing.error instanceof Error ? <p className="text-caption text-danger-fg">{pricing.error.message}</p> : null}
      {mutation.error instanceof Error ? <p className="text-caption text-danger-fg">{mutation.error.message}</p> : null}
    </div>
  );
}

export function CustomTypeRow({ makerspaceId, machineType, canConfigure, currency, showPricing = true, showBooking = true }: {
  makerspaceId: number; machineType: MachineType; canConfigure: boolean; currency: string; showPricing?: boolean; showBooking?: boolean;
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
      <PricingEditor makerspaceId={makerspaceId} machineType={machineType} currency={currency} canConfigure={canConfigure && showPricing} />
    </li>
  );
}

export function BuiltinTypeRow({ makerspaceId, machineType, canConfigure, currency, showPricing = true }: {
  makerspaceId: number; machineType: MachineType; canConfigure: boolean; currency: string; showPricing?: boolean;
}) {
  const config = configFor(machineType);
  return (
    <li className="grid gap-4 rounded-lg border border-line bg-canvas p-4">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <span className="min-w-0">
          <h3 className="text-title text-ink">{machineType.icon ? `${machineType.icon} ` : ""}{machineType.name}</h3>
          <span className="text-caption text-ink-muted">
            <span className="font-mono">{machineType.slug}</span> · {meteringUnits.find((unit) => unit.value === config.metering_unit)?.label ?? config.metering_unit} · {config.requires_booking ? "Booking required" : "No booking"}
          </span>
        </span>
        <Chip size="sm">Built-in · settings fixed</Chip>
      </div>
      <PricingEditor makerspaceId={makerspaceId} machineType={machineType} currency={currency} canConfigure={canConfigure && showPricing} />
    </li>
  );
}
