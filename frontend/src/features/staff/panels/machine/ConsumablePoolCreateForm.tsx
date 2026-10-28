import { useId, useMemo, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { Button, Dropdown, Field, Input, SwitchRow } from "../../../../components/ui";
import type { PrinterPool } from "../../../../generated/api";
import { staffRequest } from "../../../../lib/api";
import { isBuiltinPrinterType, type MachineType } from "../../machinesApi";
import { PoolColourSelector } from "./PoolColourSelector";
import { poolPath, poolQueryKey, type PoolUnit } from "./servicePools";
import { useNotify } from "./machineUi";
import { typePoolUnit } from "./typeConfig";

const UNIT_NAMES: Record<PoolUnit, string> = { grams: "Grams", milliliters: "Milliliters", millimeters: "Millimeters", count: "Count" };

type Props = {
  makerspaceId: number;
  machineType: MachineType;
  existingPools: PrinterPool[];
};

type PoolDraft = {
  material: string;
  color: string;
  colorHex: string;
  brand: string;
  quantity: string;
  unit: PoolUnit;
  lowThreshold: string;
  isPublic: boolean;
};

const blankPool = (): PoolDraft => ({
  material: "",
  color: "",
  colorHex: "",
  brand: "",
  quantity: "",
  unit: "grams",
  lowThreshold: "",
  isPublic: true,
});

export function ConsumablePoolCreateForm({ makerspaceId, machineType, existingPools }: Props) {
  const queryClient = useQueryClient();
  const notify = useNotify();
  const brandListId = useId();
  const [pool, setPool] = useState(blankPool);
  const printerType = isBuiltinPrinterType(machineType);
  // New stock always belongs to this type and uses its metering unit.
  const derivedUnit = typePoolUnit(machineType);
  const unit = derivedUnit ?? pool.unit;
  const materialPresets = machineType.capability_config?.accepted_materials;
  const brands = useMemo(() => {
    const used = new Map<string, string>();
    existingPools.forEach(({ brand }) => {
      const trimmed = brand?.trim();
      if (trimmed && !used.has(trimmed.toLocaleLowerCase())) used.set(trimmed.toLocaleLowerCase(), trimmed);
    });
    return [...used.values()].sort((left, right) => left.localeCompare(right));
  }, [existingPools]);
  const createPool = useMutation({
    mutationFn: () => staffRequest<PrinterPool>(poolPath(makerspaceId), {
      method: "POST",
      body: JSON.stringify({
        machine_type_id: machineType.id,
        is_public: pool.isPublic,
        material: pool.material.trim(),
        color: pool.color.trim(),
        color_hex: pool.colorHex,
        brand: pool.brand.trim(),
        quantity: pool.quantity,
        unit,
        low_threshold_grams: unit === "grams" && pool.lowThreshold ? pool.lowThreshold : null,
      }),
    }),
    onSuccess: async () => {
      notify.success(`${[pool.brand.trim(), pool.material.trim(), pool.color.trim()].filter(Boolean).join(" ")} added`);
      setPool(blankPool());
      await queryClient.invalidateQueries({ queryKey: poolQueryKey(makerspaceId) });
    },
    onError: (error) => notify.failure(printerType ? "Couldn't add the filament." : "Couldn't add the pool.", error),
  });

  const scopeCopy = `Type-wide: available to every ${machineType.name} machine.`;

  return (
    <form className="grid gap-4" onSubmit={(event) => { event.preventDefault(); createPool.mutate(); }}>
      <div>
        <h4 className="text-title text-ink">{printerType ? "Add filament" : "Create consumable pool"}</h4>
        <p className="mt-0.5 text-caption text-ink-muted">{scopeCopy}</p>
      </div>
      <div className="grid gap-3 sm:grid-cols-2 md:grid-cols-3">
        <Field label="Material">
          {materialPresets ? (
            <Dropdown value={pool.material} onChange={(event) => setPool({ ...pool, material: event.target.value })} required>
              <option value="" disabled>Select material</option>
              {materialPresets.map((material) => <option key={material} value={material}>{material}</option>)}
            </Dropdown>
          ) : (
            <Input value={pool.material} onChange={(event) => setPool({ ...pool, material: event.target.value })} required />
          )}
        </Field>
        <Field label="Brand">
          <Input list={brandListId} value={pool.brand} onChange={(event) => setPool({ ...pool, brand: event.target.value })} />
        </Field>
        <datalist id={brandListId}>{brands.map((brand) => <option key={brand} value={brand} />)}</datalist>
        {derivedUnit ? (
          <div className="grid gap-1.5">
            <span className="text-label text-ink">Unit</span>
            <p className="flex min-h-11 items-center text-body-ui text-ink-secondary">{UNIT_NAMES[derivedUnit]}</p>
          </div>
        ) : (
          <Field label="Unit">
            <Dropdown value={pool.unit} onChange={(event) => setPool({ ...pool, unit: event.target.value as PoolUnit })}>
              <option value="grams">Grams</option>
              <option value="milliliters">Milliliters</option>
              <option value="millimeters">Millimeters</option>
              <option value="count">Count</option>
            </Dropdown>
          </Field>
        )}
        <Field label="Initial quantity">
          <Input type="number" min="0" step="any" inputMode="decimal" value={pool.quantity} onChange={(event) => setPool({ ...pool, quantity: event.target.value })} required />
        </Field>
        {unit === "grams" ? (
          <Field label="Low threshold (grams)">
            <Input type="number" min="0" step="any" inputMode="decimal" value={pool.lowThreshold} onChange={(event) => setPool({ ...pool, lowThreshold: event.target.value })} />
          </Field>
        ) : null}
      </div>
      <PoolColourSelector
        makerspaceId={makerspaceId}
        machineType={machineType}
        existingPools={existingPools}
        value={pool.color}
        valueHex={pool.colorHex}
        onSelect={(color, colorHex) => setPool((current) => ({ ...current, color, colorHex }))}
      />
      <SwitchRow
        className="rounded-lg border border-line p-3"
        label="Visible to requesters"
        description="Requesters can pick this stock when they ask for a job."
        checked={pool.isPublic}
        onCheckedChange={(checked) => setPool((current) => ({ ...current, isPublic: checked }))}
      />
      {createPool.error instanceof Error ? <p className="text-caption text-danger-fg">{createPool.error.message}</p> : null}
      <Button className="justify-self-start" type="submit" loading={createPool.isPending} loadingLabel="Adding…" disabled={!pool.material.trim() || !pool.quantity}>
        {printerType ? "Add filament" : "Add pool"}
      </Button>
    </form>
  );
}
