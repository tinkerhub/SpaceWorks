import { Button, Chip, StatusChip, TD, TR, type StatusTone } from "../../../components/ui";
import type { ToBuyReceipt } from "./ProcurementReceipts";

export type Kind = "hardware" | "printing";
export type ToBuyStatus = "requested" | "approved" | "ordered" | "received" | "cancelled";

export type ToBuyItem = {
  id: number;
  kind: Kind;
  machine_type: number | null;
  machine_type_name: string | null;
  name: string;
  quantity: number;
  link: string;
  status: ToBuyStatus;
  estimated_unit_cost: string | null;
  vendor_name: string;
  actual_unit_cost: string | null;
  purchaser_username: string | null;
  ordered_at: string | null;
  received_at: string | null;
  moved_to_inventory_at: string | null;
  resulting_product: number | null;
  resulting_pool: number | null;
  resulting_machine: number | null;
  source_pool: number | null;
  created_by_username: string | null;
  receipts: ToBuyReceipt[];
};

export type RowDraft = {
  status: ToBuyStatus;
  vendor_name: string;
  actual_unit_cost: string;
};

export const statusOptions: ToBuyStatus[] = ["requested", "approved", "ordered", "received", "cancelled"];

export type ProcurementGroup = {
  key: string;
  label: string;
  rows: ToBuyItem[];
};

export function groupProcurementRows(rows: ToBuyItem[]): ProcurementGroup[] {
  const groups = new Map<string, ProcurementGroup>();
  for (const item of rows) {
    const key = item.machine_type === null ? "unassigned" : `type-${item.machine_type}`;
    const label = item.machine_type_name ?? "Unassigned";
    const group = groups.get(key) ?? { key, label, rows: [] };
    group.rows.push(item);
    groups.set(key, group);
  }
  return [...groups.values()].sort((left, right) => {
    if (left.key === "unassigned") return 1;
    if (right.key === "unassigned") return -1;
    return left.label.localeCompare(right.label);
  });
}

const statusTones: Record<ToBuyStatus, StatusTone> = {
  requested: "warning",
  approved: "info",
  ordered: "info",
  received: "success",
  cancelled: "neutral",
};

export function ProcurementStatus({ status }: { status: ToBuyStatus }) {
  return <StatusChip tone={statusTones[status]} size="sm">{labelStatus(status)}</StatusChip>;
}

/** One read-only list row; editing happens in the item dialog. */
export function ProcurementRow({ item, makerspaceSlug, onEdit, onMove }: {
  item: ToBuyItem;
  makerspaceSlug: string;
  onEdit: () => void;
  onMove: () => void;
}) {
  const movable = item.status === "received" && !item.moved_to_inventory_at;
  return (
    <TR>
      <TD className="align-top">
        <button type="button" className="block max-w-56 break-words text-left font-semibold text-ink underline-offset-4 hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus" onClick={onEdit}>
          {item.name}
        </button>
        <span className="mt-1 flex flex-wrap items-center gap-1.5">
          <Chip size="sm">{item.kind === "printing" ? "Printing" : "Hardware"}</Chip>
          {item.source_pool ? <Chip size="sm" tone="warning">Auto · low stock</Chip> : null}
          <ItemLink link={item.link} />
        </span>
      </TD>
      <TD className="text-right tabular-nums">{item.quantity}</TD>
      <TD className="text-right tabular-nums text-ink-secondary">{item.estimated_unit_cost ?? "—"}</TD>
      <TD className="text-right tabular-nums text-ink-secondary">{item.actual_unit_cost ?? "—"}</TD>
      <TD><span className="block max-w-36 break-words text-ink-secondary">{item.vendor_name || "—"}</span></TD>
      <TD><span className="block max-w-36 break-words text-ink-secondary">{item.purchaser_username ?? "—"}</span></TD>
      <TD className="whitespace-nowrap text-caption text-ink-muted">{formatDateTime(item.ordered_at)}</TD>
      <TD className="whitespace-nowrap text-caption text-ink-muted">{formatDateTime(item.received_at)}</TD>
      <TD className="tabular-nums text-ink-secondary">{item.receipts?.length ?? 0}</TD>
      <TD><ProcurementStatus status={item.status} /></TD>
      <TD className="text-caption text-ink-muted"><MoveState item={item} makerspaceSlug={makerspaceSlug} /></TD>
      <TD className="text-right">
        <div className="flex justify-end gap-2">
          {movable ? <Button size="sm" onClick={onMove}>Move</Button> : null}
          <Button size="sm" onClick={onEdit}>Edit</Button>
        </div>
      </TD>
    </TR>
  );
}

function MoveState({ item, makerspaceSlug }: { item: ToBuyItem; makerspaceSlug: string }) {
  if (!item.moved_to_inventory_at) return <>—</>;
  if (item.resulting_product) {
    return <a className="font-semibold text-accent-ink underline underline-offset-4" href={`/m/${makerspaceSlug}/admin/inventory`}>Inventory #{item.resulting_product}</a>;
  }
  if (item.resulting_pool) return <>Pool #{item.resulting_pool}</>;
  if (item.resulting_machine) return <>Machine #{item.resulting_machine}</>;
  return <>Moved</>;
}

function ItemLink({ link }: { link: string }) {
  const href = safeHref(link);
  if (href) return <a className="text-caption font-semibold text-accent-ink underline underline-offset-4" href={href} target="_blank" rel="noreferrer">Link<span className="sr-only"> (opens in a new tab)</span></a>;
  if (link) return <span className="block max-w-56 break-all text-caption text-ink-muted" title={link}>{link}</span>;
  return null;
}

function safeHref(link: string): string | null {
  return /^https?:\/\//i.test(link) ? link : null;
}

export function draftFromItem(item: ToBuyItem): RowDraft {
  return {
    status: item.status,
    vendor_name: item.vendor_name ?? "",
    actual_unit_cost: item.actual_unit_cost ?? "",
  };
}

export function isDraftChanged(item: ToBuyItem, draft: RowDraft) {
  return item.status !== draft.status || (item.vendor_name ?? "") !== draft.vendor_name || (item.actual_unit_cost ?? "") !== draft.actual_unit_cost;
}

export function itemTotal(item: ToBuyItem, mode: "estimated" | "actual") {
  const raw = mode === "actual" ? item.actual_unit_cost ?? item.estimated_unit_cost : item.estimated_unit_cost;
  const unitCost = Number(raw ?? 0);
  return Number.isFinite(unitCost) ? unitCost * item.quantity : 0;
}

export function labelStatus(status: ToBuyStatus) {
  return status.charAt(0).toUpperCase() + status.slice(1).replace("_", " ");
}

function formatDateTime(value: string | null) {
  if (!value) return "—";
  return new Date(value).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}
