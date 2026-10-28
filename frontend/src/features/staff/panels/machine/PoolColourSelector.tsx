import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { Check, Plus } from "lucide-react";

import { Button, Field, Input } from "../../../../components/ui";
import type { PrinterPool } from "../../../../generated/api";
import { staffRequest, type StaffAuthUser } from "../../../../lib/api";
import { machineKeys, updateMachineType, type MachineType } from "../../machinesApi";
import { PoolColourSwatchControl } from "./PoolColourSwatchControl";
import { useNotify } from "./machineUi";
import { configFor } from "./typeConfig";

type Props = {
  makerspaceId: number;
  machineType?: MachineType;
  existingPools: PrinterPool[];
  value: string;
  valueHex: string;
  onSelect: (name: string, hex: string) => void;
};

const commonColourHex: Record<string, string> = {
  black: "#000000",
  white: "#ffffff",
  red: "#dc2626",
  blue: "#2563eb",
  green: "#16a34a",
  gray: "#6b7280",
  grey: "#6b7280",
  yellow: "#eab308",
  orange: "#ea580c",
  purple: "#9333ea",
  pink: "#db2777",
  clear: "#f8fafc",
  natural: "#e7dcc8",
  "clear/natural": "#f1f5f9",
  silver: "#c0c0c0",
  gold: "#d4af37",
};

const normaliseName = (name: string) => name.trim().toLocaleLowerCase();
const validHex = (value: string | undefined) => /^#[0-9a-f]{6}$/i.test(value?.trim() ?? "");

function latestPoolHexes(pools: PrinterPool[]) {
  const result = new Map<string, string>();
  [...pools]
    .sort((left, right) => right.created_at.localeCompare(left.created_at) || right.id - left.id)
    .forEach((pool) => {
      const name = normaliseName(pool.color ?? "");
      if (name && !result.has(name) && validHex(pool.color_hex)) {
        result.set(name, pool.color_hex!.trim().toLowerCase());
      }
    });
  return result;
}

export function PoolColourSelector({ makerspaceId, machineType, existingPools, value, valueHex, onSelect }: Props) {
  const queryClient = useQueryClient();
  const notify = useNotify();
  const [addingCustom, setAddingCustom] = useState(false);
  const [customName, setCustomName] = useState("");
  const [customHex, setCustomHex] = useState("#000000");
  const [customError, setCustomError] = useState("");
  const [addedColours, setAddedColours] = useState<Array<{ name: string; hex: string }>>([]);
  const configuredColours = machineType?.capability_config?.accepted_colours ?? [];
  const colourNames = useMemo(() => {
    const names = new Map<string, string>();
    [...configuredColours, ...addedColours.map(({ name }) => name)].forEach((name) => {
      if (!names.has(normaliseName(name))) names.set(normaliseName(name), name);
    });
    return [...names.values()];
  }, [addedColours, configuredColours]);
  const poolHexes = useMemo(() => latestPoolHexes(existingPools), [existingPools]);
  const localHexes = useMemo(
    () => new Map(addedColours.map(({ name, hex }) => [normaliseName(name), hex])),
    [addedColours],
  );
  const currentUser = useQuery({
    queryKey: ["staff", "me"],
    queryFn: () => staffRequest<StaffAuthUser>("/auth/me"),
    enabled: Boolean(machineType),
  });
  const canConfigure = Boolean(
    currentUser.data?.is_superuser ||
    currentUser.data?.makerspaces?.find(({ id }) => id === makerspaceId)?.can_configure_machine_types,
  );
  const appendColour = useMutation({
    mutationFn: ({ name }: { name: string; hex: string }) => {
      if (!machineType) throw new Error("A machine type is required.");
      const capabilityConfig = configFor(machineType);
      return updateMachineType(makerspaceId, machineType.id, {
        name: machineType.name,
        icon: machineType.icon,
        capability_config: { ...capabilityConfig, accepted_colours: [...colourNames, name] },
      });
    },
    onSuccess: async (_updatedType, custom) => {
      notify.success(`${custom.name} added to the colour presets`);
      setAddedColours((current) => [...current, custom]);
      onSelect(custom.name, custom.hex);
      setCustomName("");
      setCustomHex("#000000");
      setCustomError("");
      setAddingCustom(false);
      await queryClient.invalidateQueries({ queryKey: machineKeys.types(makerspaceId) });
    },
    onError: (error) => notify.failure("Couldn't save the custom colour.", error),
  });

  const confirmCustom = () => {
    const name = customName.trim();
    if (!name) {
      setCustomError("Colour name cannot be blank.");
      return;
    }
    if (colourNames.some((colour) => normaliseName(colour) === normaliseName(name))) {
      setCustomError("Colour name already exists.");
      return;
    }
    setCustomError("");
    appendColour.mutate({ name, hex: customHex });
  };

  const hexFor = (name: string) => {
    const key = normaliseName(name);
    return poolHexes.get(key) ?? commonColourHex[key] ?? localHexes.get(key) ?? "";
  };

  return (
    <div className="grid gap-3">
      {configuredColours.length ? (
        <fieldset className="grid min-w-0 gap-2">
          <legend className="mb-1.5 text-label text-ink">Colour</legend>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 md:grid-cols-4">
            {colourNames.map((name) => {
              const hex = hexFor(name);
              const selected = normaliseName(value) === normaliseName(name);
              return (
                <button
                  aria-pressed={selected}
                  className={`grid min-h-11 overflow-hidden rounded-md bg-canvas text-left transition-colors duration-180 ease-standard hover:bg-subtle focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus ${selected ? "border-[1.5px] border-accent-ink" : "border border-line"}`}
                  key={normaliseName(name)}
                  type="button"
                  onClick={() => onSelect(name, hex)}
                >
                  {hex ? <span aria-hidden="true" className="h-9 border-b border-line" style={{ backgroundColor: hex }} /> : null}
                  <span className={`flex min-h-11 items-center justify-between gap-2 px-3 py-1 text-sm font-semibold text-ink ${hex ? "" : "bg-fill"}`}>
                    <span>{name}</span>
                    {selected ? <Check aria-hidden="true" className="size-4 text-accent-ink" /> : null}
                  </span>
                </button>
              );
            })}
          </div>
        </fieldset>
      ) : (
        <Field label="Colour">
          <Input value={value} onChange={(event) => onSelect(event.target.value, valueHex)} placeholder="e.g. Signal red" />
        </Field>
      )}

      {!configuredColours.length ? (
        <PoolColourSwatchControl value={valueHex} onChange={(hex) => onSelect(value, hex)} />
      ) : null}

      {canConfigure && machineType ? (
        addingCustom ? (
          <fieldset className="grid min-w-0 gap-3 rounded-lg border border-line bg-subtle p-4">
            <legend className="px-1 text-label text-ink">Add custom colour</legend>
            <Field label="Custom colour name">
              <Input
                aria-describedby={customError ? "custom-colour-error" : undefined}
                aria-invalid={customError ? true : undefined}
                value={customName}
                onChange={(event) => { setCustomName(event.target.value); setCustomError(""); appendColour.reset(); }}
              />
            </Field>
            <PoolColourSwatchControl legend="Custom colour swatch" value={customHex} onChange={setCustomHex} />
            {customError ? <p className="text-caption text-danger-fg" id="custom-colour-error" role="alert">{customError}</p> : null}
            {appendColour.error instanceof Error ? <p className="text-caption text-danger-fg" role="alert">{appendColour.error.message}</p> : null}
            <div className="flex flex-wrap gap-2">
              <Button loading={appendColour.isPending} loadingLabel="Saving…" onClick={confirmCustom}>Save custom colour</Button>
              <Button variant="quiet" onClick={() => { setAddingCustom(false); setCustomError(""); appendColour.reset(); }}>Cancel</Button>
            </div>
          </fieldset>
        ) : (
          <Button className="justify-self-start" size="sm" startIcon={<Plus />} onClick={() => setAddingCustom(true)}>
            Add a custom colour
          </Button>
        )
      ) : null}
    </div>
  );
}
