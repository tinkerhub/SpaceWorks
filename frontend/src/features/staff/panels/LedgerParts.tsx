import { ArrowDown, ArrowUp, ArrowUpDown } from "lucide-react";

import { Skeleton, SkeletonRows, Table, TBody, TH, THead } from "../../../components/ui";

export type LedgerSource = "request" | "self_checkout" | "direct_handout";
export type LedgerSourceFilter = "" | "reviewed" | "self_checkout" | "direct";

export type LedgerRow = {
  source: LedgerSource;
  item_name: string;
  container: string | null;
  units: Array<{ asset_tag: string; serial_number: string }>;
  target_label: string | null;
  holder: string;
  quantity: number;
  since: string | null;
  due: string | null;
  makerspace_id: number;
  reference_id: number;
  status: string;
};

export type LedgerResponse = {
  count: number;
  results: LedgerRow[];
};

export type SortKey = "item_name" | "holder" | "quantity" | "since" | "due" | "source" | "makerspace_id";
export type SortDirection = "asc" | "desc";

export const sourceLabels: Record<LedgerSource, string> = {
  request: "Request",
  self_checkout: "Self-checkout",
  direct_handout: "Direct",
};

export function LedgerSkeleton({ aggregate }: { aggregate: boolean }) {
  const cols = aggregate ? 7 : 6;
  return (
    <Table aria-hidden="true" className="min-w-[760px]">
      <THead>
        <tr>
          {Array.from({ length: cols }, (_, index) => (
            <TH key={index}>
              <Skeleton className="h-3 w-20" />
            </TH>
          ))}
        </tr>
      </THead>
      <TBody>
        <SkeletonRows rows={4} cols={cols} />
      </TBody>
    </Table>
  );
}

export function UnitLines({ row }: { row: LedgerRow }) {
  if (row.units.length) {
    return (
      <div className="mt-0.5 flex flex-wrap gap-x-2 gap-y-0.5 text-caption text-ink-muted">
        {row.units.map((unit) => (
          <span className="break-words" key={`${unit.asset_tag}-${unit.serial_number || "no-serial"}`}>
            <span className="font-mono">#{unit.asset_tag}</span>
            {unit.serial_number ? <> · <span className="font-mono">{unit.serial_number}</span></> : null}
          </span>
        ))}
      </div>
    );
  }

  return row.target_label ? <div className="mt-0.5 break-words text-caption text-ink-muted">{row.target_label}</div> : null;
}

export function SortableHeader({
  label,
  sortKey,
  sort,
  onSort,
  align = "left",
}: {
  label: string;
  sortKey: SortKey;
  sort: { key: SortKey; direction: SortDirection };
  onSort: (key: SortKey) => void;
  align?: "left" | "right";
}) {
  const active = sort.key === sortKey;
  const Icon = active ? (sort.direction === "asc" ? ArrowUp : ArrowDown) : ArrowUpDown;
  return (
    <TH
      aria-sort={active ? (sort.direction === "asc" ? "ascending" : "descending") : undefined}
      className={align === "right" ? "text-right" : "text-left"}
    >
      <button
        type="button"
        className={`-mx-1 inline-flex min-h-9 items-center gap-1 rounded-md px-1 font-semibold hover:text-ink focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus ${align === "right" ? "flex-row-reverse" : ""}`}
        onClick={() => onSort(sortKey)}
      >
        {label}
        <Icon aria-hidden="true" className={`size-3.5 ${active ? "text-ink" : "text-ink-disabled"}`} />
      </button>
    </TH>
  );
}

export function ledgerParams({
  page,
  pageSize,
  search,
  source,
  overdueOnly,
  sort,
}: {
  page?: number;
  pageSize?: number;
  search: string;
  source: LedgerSourceFilter;
  overdueOnly: boolean;
  sort: string;
}) {
  const params = new URLSearchParams();
  if (page) params.set("page", String(page));
  if (pageSize) params.set("page_size", String(pageSize));
  const trimmed = search.trim();
  if (trimmed) params.set("search", trimmed);
  if (source) params.set("source", source);
  if (overdueOnly) params.set("overdue", "true");
  params.set("sort", sort);
  return params;
}

export function isOverdue(value: string | null, now: number) {
  return Boolean(value && new Date(value).getTime() < now);
}

export function formatDate(value: string | null) {
  if (!value) return "\u2014";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "\u2014";
  return date.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}
