import type { Key } from "react";
import { useEffect, useMemo, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Download, Plus, QrCode } from "lucide-react";

import { BulkActionToolbar, Button, ConfirmDialog, DataTable, EmptyState, ErrorText, FilterBar, FilterChip, Modal, SegmentedControl, useToast } from "../../../components/ui";
import { downloadStaffFile, staffRequest } from "../../../lib/api";
import { useDebouncedValue } from "../../../lib/useDebouncedValue";
import { moduleEnabled } from "../../../lib/modules";
import { readStorage, writeStorage } from "../../../lib/safeStorage";
import { ImageUploader } from "../ImageUploader";
import { ChainOfCustodyBlock } from "./LoanTimeline";
import { invalidateInventoryViews } from "../queryInvalidation";
import { categoryResults, errorText, Panel, type CategoryListResponse, type Makerspace, useStaffGet } from "./shared";
import { IndividualAssets, LendingHistory, QrHistory } from "./InventoryAssets";
import { inventoryColumns } from "./InventoryColumns";
import { FixShelfDialog, ToBuyDialog } from "./InventoryDialogs";
import { ItemModal, QuantityAdjust } from "./InventoryItemModal";
import {
  adjustPayload,
  defaultToBuyQuantity,
  emptyAdjust,
  emptyForm,
  formFromProduct,
  payloadFromForm,
  type AdjustmentForm,
  type AdminProduct,
  type ItemForm,
} from "./inventoryForm";

const VIEW_OPTIONS = [{ value: "active", label: "Active" }, { value: "archived", label: "Archived" }] as const;

// Every mutation here (create, PATCH, archive, adjust, needs-fix, image, export) is
// EDIT_INVENTORY on the server; the list, QR history and asset list are VIEW_INVENTORY.
// A view-only role therefore gets a read-only panel rather than buttons that 403.
export function Inventory({ makerspace, canViewAudit = false, canUseToBuy = false, canEditInventory = false }: { makerspace: Makerspace; canViewAudit?: boolean; canUseToBuy?: boolean; canEditInventory?: boolean }) {
  const queryClient = useQueryClient();
  const { showToast } = useToast();
  const fail = (fallback: string) => (error: Error) => showToast(errorText(error, fallback), { tone: "error" });
  const showToBuy = canUseToBuy && moduleEnabled(makerspace.enabled_modules, "procurement");
  const containersEnabled = moduleEnabled(makerspace.enabled_modules, "containers");
  const storageKey = `inventory.view.${makerspace.id}`;
  const [search, setSearch] = useState(() => readStorage(storageKey));
  const [selectedIds, setSelectedIds] = useState<Key[]>([]);
  const [form, setForm] = useState<ItemForm>(emptyForm);
  const [adjustForm, setAdjustForm] = useState<AdjustmentForm>(emptyAdjust);
  const [editing, setEditing] = useState<AdminProduct | null>(null);
  const [toBuyTarget, setToBuyTarget] = useState<AdminProduct | null>(null);
  const [toBuyQty, setToBuyQty] = useState("1");
  const [addOpen, setAddOpen] = useState(false);
  const [archiveTarget, setArchiveTarget] = useState<AdminProduct | null>(null);
  const [fixTarget, setFixTarget] = useState<AdminProduct | null>(null);
  const [assetFixTarget, setAssetFixTarget] = useState<AdminProduct | null>(null);
  const [fixQty, setFixQty] = useState("1");
  const [qrConfirm, setQrConfirm] = useState<boolean | null>(null);
  const [bulkQrMessage, setBulkQrMessage] = useState("");
  const [showArchived, setShowArchived] = useState(false);
  const [showLowStock, setShowLowStock] = useState(false);
  const debouncedSearch = useDebouncedValue(search);
  useEffect(() => {
    setSearch(readStorage(`inventory.view.${makerspace.id}`));
    setSelectedIds([]); setForm(emptyForm); setAdjustForm(emptyAdjust); setEditing(null);
    setToBuyTarget(null); setToBuyQty("1"); setAddOpen(false); setArchiveTarget(null);
    setFixTarget(null); setAssetFixTarget(null); setFixQty("1"); setQrConfirm(null);
    setBulkQrMessage(""); setShowArchived(false); setShowLowStock(false);
  }, [makerspace.id]);
  const lowStockParam = showLowStock ? "&low_stock=true" : "";
  const inventoryQuery = `/admin/makerspace/${makerspace.id}/inventory?page_size=1000&archived=${showArchived ? "true" : "false"}&q=${encodeURIComponent(debouncedSearch)}${lowStockParam}`;
  const products = useStaffGet<{ results: AdminProduct[] }>(["inventory", makerspace.id, showArchived ? "archived" : "active", showLowStock ? "low" : "all", debouncedSearch], inventoryQuery);
  const categories = useStaffGet<CategoryListResponse>(["categories", makerspace.id], `/admin/makerspace/${makerspace.id}/categories`);
  const invalidate = () => {
    invalidateInventoryViews(queryClient, makerspace.id, makerspace.slug);
    queryClient.invalidateQueries({ queryKey: ["categories", makerspace.id] });
  };
  const rows = useMemo(() => products.data?.results ?? [], [products.data?.results]);
  // The modal works from the latest fetched row, so counts and the photo refresh after
  // an adjustment or upload instead of showing the snapshot taken when it opened.
  const liveEditing = editing ? rows.find((row) => row.id === editing.id) ?? editing : null;
  const openEdit = (product: AdminProduct) => {
    update.reset();
    adjust.reset();
    setEditing(product);
    setForm(formFromProduct(product));
    setAdjustForm(emptyAdjust);
  };
  const create = useMutation({
    mutationFn: () => staffRequest<AdminProduct>(`/admin/makerspace/${makerspace.id}/inventory`, { method: "POST", body: JSON.stringify(payloadFromForm(form, true)) }),
    // Reopen the just-created item in the edit modal so the user can add a photo.
    // The image uploader needs an existing product id, so it can't live on the add
    // form - this hands off straight into editing instead of forcing a manual re-open.
    onSuccess: (created) => { showToast(`${created.name} added. You can add a photo now.`, { tone: "success" }); setAddOpen(false); invalidate(); openEdit(created); },
    onError: fail("Could not add the item."),
  });
  const update = useMutation({
    mutationFn: () => editing ? staffRequest(`/admin/inventory/${editing.id}`, { method: "PATCH", body: JSON.stringify(payloadFromForm(form, false)) }) : Promise.resolve(),
    onSuccess: () => { showToast("Changes saved", { tone: "success" }); setEditing(null); setAdjustForm(emptyAdjust); invalidate(); },
    onError: fail("Could not save the item."),
  });
  const adjust = useMutation({
    mutationFn: () => editing ? staffRequest(`/admin/inventory/${editing.id}/adjust-quantity`, { method: "POST", body: JSON.stringify(adjustPayload(adjustForm)) }) : Promise.resolve(),
    onSuccess: () => { showToast("Quantities adjusted", { tone: "success" }); setAdjustForm(emptyAdjust); invalidate(); },
    onError: fail("Could not adjust quantities."),
  });
  const unarchive = useMutation({
    mutationFn: (product: AdminProduct) => staffRequest(`/admin/inventory/${product.id}`, { method: "PATCH", body: JSON.stringify({ is_archived: false }) }),
    onSuccess: (_data, product) => { showToast(`${product.name} is back in inventory`, { tone: "success" }); invalidate(); },
    onError: fail("Could not restore the item."),
  });
  const archive = useMutation({
    mutationFn: (product: AdminProduct) => staffRequest(`/admin/inventory/${product.id}`, { method: "PATCH", body: JSON.stringify({ is_archived: true }) }),
    onSuccess: (_data, product) => {
      setArchiveTarget(null);
      invalidate();
      showToast(`${product.name} archived`, { tone: "success", action: { label: "Undo", onClick: () => unarchive.mutate(product) } });
    },
    onError: fail("Could not archive the item."),
  });
  const moveToFix = useMutation({
    mutationFn: () => {
      if (!fixTarget) return Promise.reject(new Error("Select an item first."));
      return staffRequest(`/admin/inventory/${fixTarget.id}/needs-fix`, {
        method: "POST",
        body: JSON.stringify({ action: "shelve", quantity: Number(fixQty) || 1 }),
      });
    },
    onSuccess: () => {
      showToast(`${Number(fixQty) || 1} ${fixTarget?.name ?? "units"} moved to the fix shelf`, { tone: "success" });
      setFixTarget(null);
      setFixQty("1");
      queryClient.invalidateQueries({ queryKey: ["needs-fix-shelf", makerspace.id] });
      invalidate();
    },
    onError: fail("Could not move units to the fix shelf."),
  });
  const bulkQr = useMutation({
    mutationFn: async (enabled: boolean) => {
      const ids = [...selectedIds];
      const results = await Promise.allSettled(
        ids.map((id) =>
          staffRequest(`/admin/inventory/${String(id)}`, {
            method: "PATCH",
            body: JSON.stringify({ public_self_checkout_enabled: enabled }),
          }),
        ),
      );
      return {
        total: ids.length,
        succeeded: results.filter((result) => result.status === "fulfilled").length,
        failed: results.filter((result) => result.status === "rejected").length,
      };
    },
    onSuccess: (result) => {
      const message = `${result.succeeded} of ${result.total} items updated. ${result.failed} failed.`;
      setQrConfirm(null);
      setBulkQrMessage(message);
      showToast(message, { tone: result.failed ? "warning" : "success" });
      invalidate();
    },
    onError: fail("Could not update public QR."),
  });
  // Export the current view: selected rows when any are checked, else every row
  // matching the active filters (archived/search/low-stock).
  const exportInventory = useMutation({
    mutationFn: (format: "csv" | "xlsx") => {
      const base = `/admin/makerspace/${makerspace.id}/inventory/export?format=${format}`;
      const query = selectedIds.length
        ? `${base}&ids=${selectedIds.map((id) => String(id)).join(",")}`
        : `${base}&archived=${showArchived ? "true" : "false"}&q=${encodeURIComponent(debouncedSearch)}${lowStockParam}`;
      return downloadStaffFile(query, `inventory-${makerspace.slug}.${format}`);
    },
    onSuccess: (_data, format) => showToast(`Inventory exported as ${format.toUpperCase()}`, { tone: "success" }),
    onError: fail("Could not export inventory."),
  });
  const toBuy = useMutation({
    mutationFn: () => {
      if (!toBuyTarget) return Promise.reject(new Error("Select an item first."));
      return staffRequest(`/procurement/makerspace/${makerspace.id}/to-buy`, {
        method: "POST",
        body: JSON.stringify({ name: toBuyTarget.name, quantity: Number(toBuyQty) || 1, link: "", estimated_unit_cost: "" }),
      });
    },
    onSuccess: () => {
      showToast(toBuyTarget ? `${toBuyTarget.name} added to To Buy` : "Item added to To Buy", { tone: "success" });
      setToBuyTarget(null);
      setToBuyQty("1");
      queryClient.invalidateQueries({ queryKey: ["procurement", makerspace.id] });
    },
    onError: fail("Could not add to To Buy."),
  });
  const openFix = (product: AdminProduct) => {
    if (product.tracking_mode === "individual") {
      setAssetFixTarget(product);
      return;
    }
    moveToFix.reset();
    setFixTarget(product);
    setFixQty(product.available_quantity > 0 ? "1" : "0");
  };
  const openToBuy = (product: AdminProduct) => {
    toBuy.reset();
    setToBuyTarget(product);
    setToBuyQty(defaultToBuyQuantity(product));
  };
  // Bulk actions and exports act on the selection, so a filter change that hides rows clears it.
  const changeFilter = (apply: () => void) => { setSelectedIds([]); setBulkQrMessage(""); apply(); };
  const categoryRows = categoryResults(categories.data);
  const columns = inventoryColumns({
    canEditInventory,
    showToBuy,
    unarchivePending: unarchive.isPending,
    onOpen: openEdit,
    onFix: openFix,
    onArchive: setArchiveTarget,
    onUnarchive: (product) => unarchive.mutate(product),
    onToBuy: openToBuy,
  });
  const exportLabel = (format: string) => (selectedIds.length ? `Export ${format} (${selectedIds.length})` : `Export ${format}`);
  const filtered = Boolean(debouncedSearch) || showLowStock;
  return (
    <Panel
      title="Inventory"
      description="Everything you lend, with live counts. Open an item to edit it, adjust stock or see its history."
      actions={canEditInventory ? (
        <>
          <Button startIcon={<Download />} disabled={exportInventory.isPending} onClick={() => exportInventory.mutate("csv")}>{exportLabel("CSV")}</Button>
          <Button startIcon={<Download />} disabled={exportInventory.isPending} onClick={() => exportInventory.mutate("xlsx")}>{exportLabel("XLSX")}</Button>
          <Button variant="primary" startIcon={<Plus />} onClick={() => { create.reset(); setForm(emptyForm); setAddOpen(true); }}>Add item</Button>
        </>
      ) : null}
    >
      <div className="grid gap-4">
        <FilterBar
          value={search}
          onChange={(value) => changeFilter(() => setSearch(value))}
          placeholder="Search inventory"
          searchLabel="Search inventory"
          actions={<Button variant="quiet" size="sm" onClick={() => { writeStorage(storageKey, search); showToast("View saved. This search opens by default next time.", { tone: "success" }); }}>Save view</Button>}
        >
          <SegmentedControl ariaLabel="Inventory view" size="sm" options={VIEW_OPTIONS} value={showArchived ? "archived" : "active"} onValueChange={(value) => changeFilter(() => setShowArchived(value === "archived"))} />
          <FilterChip selected={showLowStock} onClick={() => changeFilter(() => setShowLowStock((value) => !value))}>Low stock</FilterChip>
        </FilterBar>
        {canEditInventory ? (
          <BulkActionToolbar
            selectedCount={selectedIds.length}
            onClear={() => setSelectedIds([])}
            actions={(
              <>
                <Button size="sm" startIcon={<QrCode />} disabled={bulkQr.isPending} onClick={() => { setBulkQrMessage(""); setQrConfirm(true); }}>Enable QR</Button>
                <Button size="sm" disabled={bulkQr.isPending} onClick={() => { setBulkQrMessage(""); setQrConfirm(false); }}>Disable QR</Button>
              </>
            )}
          />
        ) : null}
        {products.isError ? (
          <EmptyState tone="error" title="Could not load inventory" description={errorText(products.error, "Refresh the page to try again.")} />
        ) : (
          <DataTable<AdminProduct>
            columns={columns}
            data={rows}
            getRowId={(row) => row.id}
            selectedIds={canEditInventory ? selectedIds : undefined}
            onSelectionChange={canEditInventory ? setSelectedIds : undefined}
            loading={products.isLoading}
            emptyTitle={filtered ? "No items match" : showArchived ? "No archived inventory" : "No active inventory"}
            emptyDescription={filtered ? "Try another search or turn off Low stock." : showArchived ? "Archived items show up here." : canEditInventory ? "Add an item to start lending." : "Nothing has been added yet."}
            skeletonCols={columns.length + (canEditInventory ? 1 : 0)}
          />
        )}
        {bulkQrMessage ? <p role="status" className="text-body-ui text-ink-secondary">{bulkQrMessage}</p> : null}
        {exportInventory.error ? <ErrorText message={errorText(exportInventory.error, "Could not export inventory.")} /> : null}
      </div>
      <ItemModal title="Add item" open={addOpen} onClose={() => setAddOpen(false)} form={form} setForm={setForm} categories={categoryRows} includeQuantities pending={create.isPending} error={create.error?.message} onSubmit={() => create.mutate()} />
      <ItemModal title={liveEditing?.name ?? "Edit item"} open={Boolean(liveEditing)} onClose={() => setEditing(null)} form={form} setForm={setForm} categories={categoryRows} readOnly={!canEditInventory} pending={update.isPending} error={update.error?.message} onSubmit={() => update.mutate()}>
        {liveEditing && canEditInventory ? <div className="border-t border-line pt-5"><ImageUploader endpoint={`/admin/inventory/${liveEditing.id}/image`} currentUrl={liveEditing.image_url} label="Item photo" onChanged={invalidate} /></div> : null}
        {liveEditing && canEditInventory ? <QuantityAdjust product={liveEditing} form={adjustForm} setForm={setAdjustForm} pending={adjust.isPending} error={adjust.error?.message} onSubmit={() => adjust.mutate()} /> : null}
        {liveEditing ? <div className="border-t border-line pt-5"><QrHistory title="Product QR history" queryKey={["product-qr-history", liveEditing.id]} path={`/admin/inventory/${liveEditing.id}/qr-history`} /></div> : null}
        {liveEditing?.tracking_mode === "individual" ? <IndividualAssets productId={liveEditing.id} makerspaceId={makerspace.id} refreshInventory={invalidate} canEdit={canEditInventory} containersEnabled={containersEnabled} /> : null}
        {liveEditing && canViewAudit ? <LendingHistory productId={liveEditing.id} /> : null}
        {liveEditing && canViewAudit ? <ChainOfCustodyBlock productId={liveEditing.id} /> : null}
      </ItemModal>
      {showToBuy ? <ToBuyDialog target={toBuyTarget} quantity={toBuyQty} setQuantity={setToBuyQty} pending={toBuy.isPending} error={toBuy.error?.message} onClose={() => setToBuyTarget(null)} onSubmit={() => toBuy.mutate()} /> : null}
      <FixShelfDialog target={fixTarget} quantity={fixQty} setQuantity={setFixQty} pending={moveToFix.isPending} error={moveToFix.error?.message} onClose={() => setFixTarget(null)} onSubmit={() => moveToFix.mutate()} />
      <Modal open={Boolean(assetFixTarget)} onClose={() => setAssetFixTarget(null)} size="lg" title="Choose an asset to fix" description={assetFixTarget ? `Pick the ${assetFixTarget.name} unit that needs repair.` : undefined} footer={<div className="flex justify-end"><Button onClick={() => setAssetFixTarget(null)}>Close</Button></div>}>
        {assetFixTarget ? <IndividualAssets productId={assetFixTarget.id} makerspaceId={makerspace.id} refreshInventory={invalidate} canEdit={canEditInventory} containersEnabled={containersEnabled} /> : null}
      </Modal>
      <ConfirmDialog open={Boolean(archiveTarget)} title={archiveTarget ? `Archive ${archiveTarget.name}?` : "Archive item?"} message="It disappears from active inventory and the public page. You can bring it back from Archived." confirmLabel="Archive" tone="danger" pending={archive.isPending} onCancel={() => setArchiveTarget(null)} onConfirm={() => { if (archiveTarget) archive.mutate(archiveTarget); }} />
      <ConfirmDialog open={qrConfirm !== null} title={qrConfirm ? "Turn on public QR?" : "Turn off public QR?"} message={`${qrConfirm ? "Enable" : "Disable"} public self-checkout QR for ${selectedIds.length} selected items?`} confirmLabel={qrConfirm ? "Enable" : "Disable"} pending={bulkQr.isPending} onCancel={() => setQrConfirm(null)} onConfirm={() => { if (qrConfirm !== null) bulkQr.mutate(qrConfirm); }} />
    </Panel>
  );
}
