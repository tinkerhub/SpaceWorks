import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import type { UseQueryResult } from "@tanstack/react-query";
import { Download, Plus } from "lucide-react";

import {
  Button,
  EmptyState,
  ErrorText,
  FilterChip,
  Skeleton,
  StatTile,
  Table,
  TBody,
  TH,
  THead,
  useToast,
} from "../../../components/ui";
import { downloadStaffFile, staffRequest } from "../../../lib/api";
import {
  groupProcurementRows,
  ProcurementRow,
  itemTotal,
  labelStatus,
  statusOptions,
  type RowDraft,
  type ToBuyItem,
  type ToBuyStatus,
} from "./ProcurementPanelRows";
import {
  procurementMachineTypeOptions,
  procurementMachineTypeRequired,
  type ProcurementMachineTypeOptions,
} from "./ProcurementPanelTypes";
import { emptyProcurementForm, ProcurementCreateDialog, type ProcurementForm } from "./ProcurementCreateDialog";
import { ProcurementEditDialog } from "./ProcurementEditDialog";
import { ProcurementMoveModal } from "./ProcurementMoveModal";
import { errorText, Panel, type Makerspace, useStaffGet } from "./shared";
import { formatMoney, useMakerspaceCurrency, withCurrency } from "../paymentsApi";

type StatusFilter = "all" | ToBuyStatus;
type UpdateVariables = { id: number; payload: { status: ToBuyStatus; vendor_name: string; actual_unit_cost: number | null } };

const HEADERS = ["Item", "Qty", "Est. unit", "Actual unit", "Vendor", "Purchaser", "Ordered", "Received", "Receipts", "Status", "Moved"];
const COST_HEADERS = new Set(["Est. unit", "Actual unit"]);

type ProcurementPanelProps = {
  makerspace: Makerspace;
  canChooseKind?: boolean;
};

export function ProcurementPanel({
  makerspace,
  canChooseKind = false,
}: ProcurementPanelProps) {
  const queryClient = useQueryClient();
  const { showToast } = useToast();
  const [form, setForm] = useState<ProcurementForm>(emptyProcurementForm);
  const [createOpen, setCreateOpen] = useState(false);
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("requested");
  const [moveTarget, setMoveTarget] = useState<ToBuyItem | null>(null);
  const [editId, setEditId] = useState<number | null>(null);
  const currency = useMakerspaceCurrency(makerspace.id);
  const base = `/procurement/makerspace/${makerspace.id}/to-buy`;
  const statusParam = statusFilter === "all" ? "" : `&status=${statusFilter}`;
  const queryKey = ["procurement", makerspace.id, statusFilter];
  const items = useStaffGet<ToBuyItem[]>(queryKey, `${base}?limit=200${statusParam}`);
  const machineTypes = useStaffGet<ProcurementMachineTypeOptions>(
    ["procurement-machine-types", makerspace.id, form.kind],
    `${base}/machine-types?kind=${form.kind}`,
  );
  const typeOptions = procurementMachineTypeOptions(machineTypes.data);
  // Server-derived, and it already accounts for the stream, so it needs no local
  // `createsPrintingByDefault` qualifier.
  const requiresMachineType = procurementMachineTypeRequired(machineTypes.data);
  const invalidate = () => void Promise.all([
    queryClient.invalidateQueries({ queryKey: ["procurement", makerspace.id] }),
    queryClient.invalidateQueries({ queryKey: ["operations-report"] }),
  ]);

  const create = useMutation({
    mutationFn: () => {
      const path = canChooseKind ? `${base}?kind=${form.kind}` : base;
      return staffRequest(path, {
        method: "POST",
        body: JSON.stringify({
          name: form.name,
          quantity: Number(form.quantity) || 1,
          link: form.link,
          estimated_unit_cost: form.estimated_unit_cost ? Number(form.estimated_unit_cost) : null,
          vendor_name: form.vendor_name,
          actual_unit_cost: form.actual_unit_cost ? Number(form.actual_unit_cost) : null,
          machine_type: form.machine_type ? Number(form.machine_type) : null,
        }),
      });
    },
    onSuccess: () => {
      showToast(`${form.name.trim()} added to To Buy.`, { tone: "success" });
      setForm(emptyProcurementForm);
      setCreateOpen(false);
      invalidate();
    },
    onError: (error) => showToast(errorText(error, "Could not add item."), { tone: "error" }),
  });

  const update = useMutation({
    mutationFn: (vars: UpdateVariables) =>
      staffRequest(`/procurement/to-buy/${vars.id}`, {
        method: "PATCH",
        body: JSON.stringify(vars.payload),
      }),
    onSuccess: () => {
      setEditId(null);
      showToast("Item updated.", { tone: "success" });
      invalidate();
    },
    onError: (error) => showToast(errorText(error, "Could not update item."), { tone: "error" }),
  });

  const remove = useMutation({
    mutationFn: (id: number) => staffRequest(`/procurement/to-buy/${id}`, { method: "DELETE" }),
    onSuccess: () => {
      setEditId(null);
      showToast("Item deleted.", { tone: "success" });
      invalidate();
    },
    onError: (error) => showToast(errorText(error, "Could not delete item."), { tone: "error" }),
  });

  const exportToBuy = useMutation({
    mutationFn: (format: "csv" | "xlsx") => {
      const params = new URLSearchParams({ format });
      if (statusFilter !== "all") params.set("status", statusFilter);
      return downloadStaffFile(`${base}/export?${params.toString()}`, `to-buy-${makerspace.slug}.${format}`);
    },
    onSuccess: (_result, format) => showToast(`To Buy list exported as ${format.toUpperCase()}.`, { tone: "success" }),
    onError: (error) => showToast(errorText(error, "Could not export list."), { tone: "error" }),
  });

  const rows = items.data ?? [];
  const editing = rows.find((item) => item.id === editId) ?? null;
  const visibleEstimatedTotal = rows.reduce((sum, item) => sum + itemTotal(item, "estimated"), 0);
  const openBudget = rows.filter((item) => !["received", "cancelled"].includes(item.status)).reduce((sum, item) => sum + itemTotal(item, "estimated"), 0);
  const receivedTotal = rows.filter((item) => item.status === "received").reduce((sum, item) => sum + itemTotal(item, "actual"), 0);
  const openCreate = () => {
    create.reset();
    setCreateOpen(true);
  };
  const saveDraft = (id: number, draft: RowDraft) => update.mutate({
    id,
    payload: { status: draft.status, vendor_name: draft.vendor_name, actual_unit_cost: draft.actual_unit_cost ? Number(draft.actual_unit_cost) : null },
  });

  return (
    <Panel
      title="To Buy"
      description={`Shopping list for ${makerspace.name}: requested, approved, ordered and received purchases, with receipts.`}
      actions={(
        <>
          <Button size="sm" startIcon={<Download />} disabled={exportToBuy.isPending} onClick={() => exportToBuy.mutate("csv")}>Export CSV</Button>
          <Button size="sm" startIcon={<Download />} disabled={exportToBuy.isPending} onClick={() => exportToBuy.mutate("xlsx")}>Export XLSX</Button>
          <Button variant="primary" startIcon={<Plus />} onClick={openCreate}>Add item</Button>
        </>
      )}
    >
      <div className="grid gap-5">
        <div className="grid gap-3 sm:grid-cols-3">
          <StatTile label="Visible estimated total" value={formatAmount(visibleEstimatedTotal, currency)} hint="Everything in this view" />
          <StatTile label="Open budget" value={formatAmount(openBudget, currency)} hint="Not yet received or cancelled" />
          <StatTile label="Received actual total" value={formatAmount(receivedTotal, currency)} hint="Actual cost where known" />
        </div>
        <div role="group" aria-label="Status" className="flex flex-wrap items-center gap-2">
          {(["all", ...statusOptions] as StatusFilter[]).map((status) => (
            <FilterChip key={status} selected={statusFilter === status} onClick={() => setStatusFilter(status)}>
              {status === "all" ? "All" : labelStatus(status)}
            </FilterChip>
          ))}
          {items.isFetching && !items.isLoading ? <span role="status" className="text-caption text-ink-muted">Refreshing…</span> : null}
        </div>
        <ProcurementTable
          rows={rows}
          items={items}
          filtered={statusFilter !== "all"}
          makerspaceSlug={makerspace.slug}
          currency={currency}
          onEdit={(item) => { update.reset(); setEditId(item.id); }}
          onMove={setMoveTarget}
          onAdd={openCreate}
        />
      </div>
      <ProcurementCreateDialog
        open={createOpen}
        onClose={() => setCreateOpen(false)}
        form={form}
        setForm={setForm}
        canChooseKind={canChooseKind}
        requiresMachineType={requiresMachineType}
        typeOptions={typeOptions}
        typesLoading={machineTypes.isLoading}
        currency={currency}
        pending={create.isPending}
        error={create.error}
        onSubmit={() => create.mutate()}
      />
      <ProcurementEditDialog
        item={editing}
        currency={currency}
        savePending={update.isPending}
        saveError={update.error}
        deletePending={remove.isPending}
        onClose={() => setEditId(null)}
        onSave={(draft) => { if (editing) saveDraft(editing.id, draft); }}
        onDelete={() => { if (editing) remove.mutate(editing.id); }}
        onMove={() => { setMoveTarget(editing); setEditId(null); }}
        onReceiptsChanged={invalidate}
      />
      <ProcurementMoveModal item={moveTarget} makerspace={makerspace} onClose={() => setMoveTarget(null)} onMoved={invalidate} />
    </Panel>
  );
}

function ProcurementTable({ rows, items, filtered, makerspaceSlug, currency, onEdit, onMove, onAdd }: {
  rows: ToBuyItem[];
  items: UseQueryResult<ToBuyItem[], Error>;
  filtered: boolean;
  makerspaceSlug: string;
  currency: string;
  onEdit: (item: ToBuyItem) => void;
  onMove: (item: ToBuyItem) => void;
  onAdd: () => void;
}) {
  if (items.isLoading) {
    return (
      <div className="grid gap-2" aria-busy="true">
        {Array.from({ length: 4 }, (_, index) => <Skeleton key={index} className="h-12 w-full" />)}
      </div>
    );
  }
  if (items.error) return <ErrorText message={errorText(items.error, "Unable to load list.")} />;
  if (!rows.length) {
    return (
      <EmptyState
        title={filtered ? "Nothing with this status" : "Nothing on the list yet"}
        description={filtered ? "Pick another status above, or add what the space needs." : "Add what the space needs to buy, then track it through to received."}
        action={<Button variant="primary" startIcon={<Plus />} onClick={onAdd}>Add item</Button>}
      />
    );
  }
  return (
    <Table label="To Buy items" className="min-w-[1080px]" containerClassName="max-h-[36rem] overflow-y-auto">
      <THead className="sticky top-0 z-[1]">
        <tr>
          {HEADERS.map((header) => <TH key={header}>{COST_HEADERS.has(header) ? withCurrency(header, currency) : header}</TH>)}
          <TH><span className="sr-only">Actions</span></TH>
        </tr>
      </THead>
      <TBody>
        {groupProcurementRows(rows).map((group) => (
          <GroupRows key={group.key} label={group.label} rows={group.rows} makerspaceSlug={makerspaceSlug} onEdit={onEdit} onMove={onMove} />
        ))}
      </TBody>
    </Table>
  );
}

function GroupRows({ label, rows, makerspaceSlug, onEdit, onMove }: { label: string; rows: ToBuyItem[]; makerspaceSlug: string; onEdit: (item: ToBuyItem) => void; onMove: (item: ToBuyItem) => void }) {
  return <>
    <tr className="bg-subtle"><th scope="rowgroup" className="border-b border-line px-4 py-2 text-left text-label text-ink-secondary" colSpan={HEADERS.length + 1}>{label}</th></tr>
    {rows.map((item) => <ProcurementRow key={item.id} item={item} makerspaceSlug={makerspaceSlug} onEdit={() => onEdit(item)} onMove={() => onMove(item)} />)}
  </>;
}

function formatAmount(value: number, currency: string) {
  if (currency) return formatMoney(value.toFixed(2), currency);
  return value.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}
