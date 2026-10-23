import type { Key, ReactNode } from "react";
import { useEffect, useMemo, useRef, useState } from "react";
import { ArrowDown, ArrowUp, ArrowUpDown } from "lucide-react";

import { EmptyState } from "./EmptyState";
import { SkeletonRows } from "./Skeleton";
import { Spinner } from "./Spinner";

export type DataTableColumn<T> = {
  key: Extract<keyof T, string> | string; header: ReactNode; render?: (row: T) => ReactNode; sortable?: boolean; className?: string;
};

// A 16px checkbox inside a 44px hit area (WCAG 2.5.5); the negative margin keeps the cell size.
const checkHit = "-m-3.5 inline-flex cursor-pointer p-3.5";

type SortState = { key: string; direction: "asc" | "desc" };

type DataTableProps<T> = {
  columns: DataTableColumn<T>[]; data: T[]; getRowId?: (row: T) => Key; selectedIds?: Key[];
  onSelectionChange?: (ids: Key[]) => void; loading?: boolean; emptyTitle?: string; emptyDescription?: string; emptyAction?: ReactNode;
  skeletonCols?: number;
};

export function DataTable<T>({
  columns,
  data,
  getRowId = defaultGetRowId,
  selectedIds,
  onSelectionChange,
  loading = false,
  emptyTitle = "No records",
  emptyDescription,
  emptyAction,
  skeletonCols,
}: DataTableProps<T>) {
  const [sort, setSort] = useState<SortState | null>(null);
  const selectedSet = useMemo(() => new Set(selectedIds ?? []), [selectedIds]);
  const visibleIds = useMemo(() => data.map(getRowId), [data, getRowId]);
  const selectionEnabled = Boolean(selectedIds && onSelectionChange);
  const allSelected = visibleIds.length > 0 && visibleIds.every((id) => selectedSet.has(id));
  const someSelected = visibleIds.some((id) => selectedSet.has(id));
  const selectAllRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (selectAllRef.current) selectAllRef.current.indeterminate = someSelected && !allSelected;
  }, [allSelected, someSelected]);

  const sortedData = useMemo(() => {
    if (!sort) return data;
    return [...data].sort((a, b) => compareValues(getCellValue(a, sort.key), getCellValue(b, sort.key), sort.direction));
  }, [data, sort]);

  const toggleSort = (column: DataTableColumn<T>) => {
    if (!column.sortable) return;
    setSort((current) => ({
      key: column.key,
      direction: current?.key === column.key && current.direction === "asc" ? "desc" : "asc",
    }));
  };
  const changeRow = (id: Key, checked: boolean) => {
    const next = new Set(selectedSet);
    checked ? next.add(id) : next.delete(id);
    onSelectionChange?.([...next]);
  };
  const changeAll = (checked: boolean) => {
    const next = new Set(selectedSet);
    visibleIds.forEach((id) => (checked ? next.add(id) : next.delete(id)));
    onSelectionChange?.([...next]);
  };

  if (!loading && !data.length) return <EmptyState title={emptyTitle} description={emptyDescription} action={emptyAction} />;

  return (
    <div className="sw-scroll-x relative w-full min-w-0 overflow-x-auto rounded-lg border border-line">
      <table className="w-full min-w-[640px] border-collapse text-left text-body-ui" aria-busy={loading}>
        <thead className="bg-subtle text-[13px] text-ink-muted">
          <tr className="border-b border-line">
            {selectionEnabled ? (
              <th className="w-10 px-4 py-3" scope="col">
                <label className={checkHit}>
                  <input ref={selectAllRef} type="checkbox" className="size-4 cursor-pointer accent-accent" aria-label="Select all rows" checked={allSelected} onChange={(event) => changeAll(event.target.checked)} />
                </label>
              </th>
            ) : null}
            {columns.map((column) => (
              <th
                key={column.key}
                className={`whitespace-nowrap px-4 py-3 font-semibold ${column.className ?? ""}`}
                aria-sort={sort?.key === column.key ? ariaSort(sort.direction) : undefined}
                scope="col"
              >
                {column.sortable ? (
                  <button type="button" className="-mx-1 inline-flex min-h-9 pointer-coarse:min-h-11 items-center gap-1 rounded-md px-1 font-semibold hover:text-ink focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus" onClick={() => toggleSort(column)}>
                    {column.header}
                    <SortIcon direction={sort?.key === column.key ? sort.direction : null} />
                  </button>
                ) : column.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {loading && skeletonCols ? (
            <SkeletonRows rows={6} cols={skeletonCols} />
          ) : loading ? (
            <tr>
              <td className="px-4 py-8 text-center" colSpan={columns.length + (selectionEnabled ? 1 : 0)}>
                <Spinner />
              </td>
            </tr>
          ) : (
            sortedData.map((row) => {
              const id = getRowId(row);
              return (
                <tr key={id} className="border-b border-emphasis transition-colors last:border-b-0 hover:bg-subtle/60">
                  {selectionEnabled ? (
                    <td className="px-4 py-3">
                      <label className={checkHit}>
                        <input type="checkbox" className="size-4 cursor-pointer accent-accent" aria-label={`Select row ${String(id)}`} checked={selectedSet.has(id)} onChange={(event) => changeRow(id, event.target.checked)} />
                      </label>
                    </td>
                  ) : null}
                  {columns.map((column) => (
                    <td key={column.key} className={`px-4 py-3 align-middle text-ink ${column.className ?? ""}`}>
                      {column.render ? column.render(row) : String(getCellValue(row, column.key) ?? "")}
                    </td>
                  ))}
                </tr>
              );
            })
          )}
        </tbody>
      </table>
    </div>
  );
}

function SortIcon({ direction }: { direction: "asc" | "desc" | null }) {
  const Icon = direction === "asc" ? ArrowUp : direction === "desc" ? ArrowDown : ArrowUpDown;
  return <Icon aria-hidden="true" className={`size-3.5 ${direction ? "text-ink" : "text-ink-disabled"}`} />;
}

function defaultGetRowId<T>(row: T): Key {
  return (row as { id: Key }).id;
}

function getCellValue<T>(row: T, key: string) {
  return (row as Record<string, unknown>)[key];
}

function ariaSort(direction: "asc" | "desc") {
  return direction === "asc" ? "ascending" : "descending";
}

function compareValues(left: unknown, right: unknown, direction: "asc" | "desc") {
  const order = direction === "asc" ? 1 : -1;
  if (left == null && right == null) return 0;
  if (left == null) return -1 * order;
  if (right == null) return 1 * order;
  if (typeof left === "number" && typeof right === "number") return (left - right) * order;
  return String(left).localeCompare(String(right), undefined, { numeric: true, sensitivity: "base" }) * order;
}
