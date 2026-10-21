import { useQuery } from "@tanstack/react-query";

import { CheckboxField } from "../../components/ui";
import { staffRequest } from "../../lib/api";
import type { DestinationScope } from "./notificationDestinationTypes";

type ScopeOption = { id: number; name: string };

export type ScopeOptions = {
  machineTypes: ScopeOption[];
  machines: ScopeOption[];
  categories: ScopeOption[];
};

/** Machine type / machine / category checkboxes that narrow a room or recipient rule. */
export function ScopePicker({
  onChange,
  options,
  scopeRequired = false,
  scope,
}: {
  onChange: (scope: DestinationScope) => void;
  options: ScopeOptions;
  scopeRequired?: boolean;
  scope: DestinationScope;
}) {
  const groups = [
    { key: "machine_type_ids" as const, label: "Machine types", items: options.machineTypes },
    { key: "machine_ids" as const, label: "Machines", items: options.machines },
    { key: "category_ids" as const, label: "Categories", items: options.categories },
  ].filter((group) => group.items.length > 0);

  if (groups.length === 0) return null;

  return (
    <fieldset className="grid min-w-0 gap-3">
      <legend className="text-caption text-ink-muted">
        {scopeRequired
          ? "Required: choose at least one machine or machine type"
          : "Limit to (leave everything unticked to receive all alerts)"}
      </legend>
      <div className="grid gap-4 sm:grid-cols-3">
        {groups.map((group) => (
          <div key={group.key} className="min-w-0">
            <p className="text-label text-ink">{group.label}</p>
            <div className="mt-2 grid max-h-40 gap-2 overflow-y-auto pr-1">
              {group.items.map((item) => (
                <CheckboxField
                  key={item.id}
                  label={item.name}
                  checked={scope[group.key].includes(item.id)}
                  onCheckedChange={(checked) =>
                    onChange({
                      ...scope,
                      [group.key]: checked === true
                        ? [...scope[group.key], item.id]
                        : scope[group.key].filter((id) => id !== item.id),
                    })
                  }
                />
              ))}
            </div>
          </div>
        ))}
      </div>
    </fieldset>
  );
}

/**
 * Scope targets a room or rule can name. Each list is optional — a makerspace with no
 * machines simply gets no machine column rather than an empty picker.
 */
export function useScopeOptions(makerspaceId: number, enabled = true): ScopeOptions {
  const machineTypes = useQuery({
    queryKey: ["machine-types", makerspaceId, "scope"],
    queryFn: () =>
      staffRequest<{ id: number; name: string }[]>(
        `/admin/makerspace/${makerspaceId}/machine-types`,
      ).catch(() => []),
    enabled,
  });
  const machines = useQuery({
    queryKey: ["machines", makerspaceId, "scope"],
    queryFn: () =>
      staffRequest<{ results?: { id: number; name: string }[] } | { id: number; name: string }[]>(
        `/admin/makerspace/${makerspaceId}/machines`,
      ).catch(() => []),
    enabled,
  });
  const categories = useQuery({
    queryKey: ["categories", makerspaceId, "scope"],
    queryFn: () =>
      staffRequest<{ results?: { id: number; name: string }[] } | { id: number; name: string }[]>(
        `/admin/makerspace/${makerspaceId}/categories`,
      ).catch(() => []),
    enabled,
  });

  return {
    machineTypes: unwrap(machineTypes.data),
    machines: unwrap(machines.data),
    categories: unwrap(categories.data),
  };
}

function unwrap(value: unknown): ScopeOption[] {
  if (Array.isArray(value)) return value as ScopeOption[];
  if (value && typeof value === "object" && Array.isArray((value as { results?: unknown }).results)) {
    return (value as { results: ScopeOption[] }).results;
  }
  return [];
}
