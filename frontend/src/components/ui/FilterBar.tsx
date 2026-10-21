import type { ReactNode } from "react";
import { useId } from "react";

import { SearchInput } from "./inputs";

type FilterBarProps = {
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  searchLabel?: string;
  children?: ReactNode;
  actions?: ReactNode;
};

/** Pill search with a clear button, then filters, then actions pushed right. */
export function FilterBar({
  value,
  onChange,
  placeholder = "Search",
  searchLabel = "Search table",
  children,
  actions,
}: FilterBarProps) {
  const searchId = useId();

  return (
    <div className="flex flex-col gap-3 sm:flex-row sm:flex-wrap sm:items-center">
      <label className="sr-only" htmlFor={searchId}>
        {searchLabel}
      </label>
      <div className="min-w-0 flex-1 sm:basis-56">
        <SearchInput
          id={searchId}
          value={value}
          placeholder={placeholder}
          onChange={(event) => onChange(event.target.value)}
          onClear={() => onChange("")}
        />
      </div>
      {children ? <div className="flex min-w-0 flex-wrap items-center gap-2">{children}</div> : null}
      {actions ? <div className="flex min-w-0 flex-wrap items-center gap-2 sm:ml-auto">{actions}</div> : null}
    </div>
  );
}
