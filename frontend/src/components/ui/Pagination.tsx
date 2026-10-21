import { ChevronLeft, ChevronRight } from "lucide-react";

import { Button } from "./Button";

type PaginationProps = {
  page: number;
  totalPages: number;
  onChange: (page: number) => void;
  /** Total row count, shown as context when provided. */
  count?: number;
  pageSize?: number;
  disabled?: boolean;
};

/**
 * Shared prev/next pager for server-paginated staff lists. Renders nothing when
 * everything fits on one page. Pairs with `usePaginatedQuery`.
 */
export function Pagination({ page, totalPages, onChange, count, pageSize, disabled }: PaginationProps) {
  if (totalPages <= 1) {
    return null;
  }

  const rangeLabel =
    count != null && pageSize != null
      ? `${Math.min((page - 1) * pageSize + 1, count)}–${Math.min(page * pageSize, count)} of ${count}`
      : null;

  return (
    <div className="flex flex-wrap items-center justify-end gap-2 text-sm text-ink-muted">
      {rangeLabel ? <span className="mr-auto">{rangeLabel}</span> : null}
      <Button size="sm" startIcon={<ChevronLeft />} disabled={disabled || page <= 1} onClick={() => onChange(Math.max(1, page - 1))}>
        Previous
      </Button>
      <span className="px-1 tabular-nums">
        Page {page} of {totalPages}
      </span>
      <Button size="sm" endIcon={<ChevronRight />} disabled={disabled || page >= totalPages} onClick={() => onChange(Math.min(totalPages, page + 1))}>
        Next
      </Button>
    </div>
  );
}
