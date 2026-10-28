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
 * machines simply gets no machine column rather than an empty picker. With the `machines`
 * module off the machine endpoints refuse, so they are not asked at all.
 */
export function useScopeOptions(makerspaceId: number, enabled = true, machinesOn = true): ScopeOptions {
  const machineTypes = useQuery({
    queryKey: ["machine-types", makerspaceId, "scope"],
    queryFn: () =>
      staffRequest<{ id: number; name: string }[]>(
        `/admin/makerspace/${makerspaceId}/machine-types`,
      ).catch(() => []),
    enabled: enabled && machinesOn,
  });
  const machines = useQuery({
    queryKey: ["machines", makerspaceId, "scope"],
    queryFn: () =>
      staffRequest<{ results?: { id: number; name: string }[] } | { id: number; name: string }[]>(
        `/admin/makerspace/${makerspaceId}/machines`,
      ).catch(() => []),
    enabled: enabled && machinesOn,
  });
  const categories = useQuery({
    queryKey: ["categories", makerspaceId, "scope"],
    queryFn: () => allCategoryPages(makerspaceId).catch(() => []),
    enabled,
  });

  return {
    machineTypes: machinesOn ? unwrap(machineTypes.data) : [],
    machines: machinesOn ? unwrap(machines.data) : [],
    categories: unwrap(categories.data),
  };
}

// Hard stop on the page walk: a server that always returns `next` must not spin forever.
const MAX_CATEGORY_PAGES = 50;

/**
 * Every category, not just page one: the endpoint pages at 24, and a category missing from
 * the picker cannot be ticked at all. Paged with `?page=N` rather than DRF's absolute
 * `next` URL, which `staffRequest` would prefix with the API base (see `getMachines`).
 */
async function allCategoryPages(makerspaceId: number): Promise<ScopeOption[]> {
  type Page = { results?: ScopeOption[]; next?: string | null } | ScopeOption[];
  const path = `/admin/makerspace/${makerspaceId}/categories`;
  const first = await staffRequest<Page>(path);
  if (Array.isArray(first)) return first;
  const results = [...(first.results ?? [])];
  let next = first.next;
  for (let page = 2; next && page <= MAX_CATEGORY_PAGES; page += 1) {
    const response = await staffRequest<Page>(`${path}?page=${page}`);
    if (Array.isArray(response)) break;
    results.push(...(response.results ?? []));
    next = response.next;
  }
  return results;
}

function unwrap(value: unknown): ScopeOption[] {
  if (Array.isArray(value)) return value as ScopeOption[];
  if (value && typeof value === "object" && Array.isArray((value as { results?: unknown }).results)) {
    return (value as { results: ScopeOption[] }).results;
  }
  return [];
}
