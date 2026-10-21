import { useMemo } from "react";

import { CheckboxCard } from "../../components/ui";
import type { ApiClientScopeOption } from "./apiClientsApi";

/** Scopes grouped into fieldsets, one checkbox card per scope; locked scopes explain why. */
export function ApiClientScopePicker({
  options,
  selected,
  onChange,
  disabled = false,
}: {
  options: ApiClientScopeOption[];
  selected: readonly string[];
  onChange: (scopes: string[]) => void;
  disabled?: boolean;
}) {
  const checked = useMemo(() => new Set(selected), [selected]);
  const grouped = useMemo(() => {
    const groups = new Map<string, ApiClientScopeOption[]>();
    options.forEach((option) => {
      groups.set(option.group, [...(groups.get(option.group) ?? []), option]);
    });
    return groups;
  }, [options]);

  const toggle = (value: string, grantable: boolean) => {
    if (disabled || !grantable) return;
    const next = new Set(checked);
    if (next.has(value)) next.delete(value); else next.add(value);
    onChange(options.filter((option) => next.has(option.value)).map((option) => option.value));
  };

  return (
    <div className="grid gap-4" aria-label="API client scopes">
      {Array.from(grouped.entries()).map(([group, groupOptions]) => (
        <fieldset key={group} className="grid min-w-0 gap-2">
          <legend className="mb-2 text-label text-ink-secondary">{group}</legend>
          <div className="grid gap-2 sm:grid-cols-2">
            {groupOptions.map((option) => (
              <CheckboxCard
                key={option.value}
                label={option.label}
                description={(
                  <>
                    {option.description}
                    {!option.grantable ? (
                      <span className="mt-1 block text-danger-fg">
                        {option.lock_reason ?? "This scope cannot be granted here."}
                      </span>
                    ) : null}
                  </>
                )}
                checked={checked.has(option.value)}
                disabled={disabled || !option.grantable}
                onCheckedChange={() => toggle(option.value, option.grantable)}
              />
            ))}
          </div>
        </fieldset>
      ))}
    </div>
  );
}
