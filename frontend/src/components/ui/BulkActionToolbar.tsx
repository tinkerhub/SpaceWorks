import type { ReactNode } from "react";

import { Button } from "./Button";

type BulkActionToolbarProps = {
  selectedCount: number;
  onClear: () => void;
  actions?: ReactNode;
  clearLabel?: string;
};

/** Appears while rows are selected: count, bulk actions, and a quiet clear. */
export function BulkActionToolbar({
  selectedCount,
  onClear,
  actions,
  clearLabel = "Clear",
}: BulkActionToolbarProps) {
  if (selectedCount <= 0) return null;

  return (
    <div className="flex min-w-0 flex-wrap items-center gap-2 rounded-lg bg-info-bg px-4 py-2.5 text-sm text-info-fg">
      <span className="font-semibold">{selectedCount} selected</span>
      {actions ? <div className="flex min-w-0 flex-wrap items-center gap-2">{actions}</div> : null}
      <Button variant="quiet" size="sm" className="ml-0 text-info-fg sm:ml-auto" onClick={onClear}>
        {clearLabel}
      </Button>
    </div>
  );
}
