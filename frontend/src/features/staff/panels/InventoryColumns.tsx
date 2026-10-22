import { ImageIcon } from "lucide-react";

import { Button, Chip } from "../../../components/ui";
import type { DataTableColumn } from "../../../components/ui";
import { InventoryAvailability } from "./InventoryItemModal";
import type { AdminProduct } from "./inventoryForm";

type ColumnOptions = {
  canEditInventory: boolean;
  showToBuy: boolean;
  unarchivePending: boolean;
  onOpen: (product: AdminProduct) => void;
  onFix: (product: AdminProduct) => void;
  onArchive: (product: AdminProduct) => void;
  onUnarchive: (product: AdminProduct) => void;
  onToBuy: (product: AdminProduct) => void;
};

/** Units that can go to the fix shelf: individual assets may already be damaged. */
function fixableUnits(product: AdminProduct) {
  return product.tracking_mode === "individual" ? product.available_quantity + product.damaged_quantity : product.available_quantity;
}

export function inventoryColumns({ canEditInventory, showToBuy, unarchivePending, onOpen, onFix, onArchive, onUnarchive, onToBuy }: ColumnOptions): DataTableColumn<AdminProduct>[] {
  return [
    { key: "image", header: <span className="sr-only">Photo</span>, render: (product) => (
      <div className="grid size-10 place-items-center overflow-hidden rounded-md border border-line bg-subtle text-ink-muted">
        {product.image_url ? <img src={product.image_url} alt="" className="h-full w-full object-cover" /> : <ImageIcon aria-hidden="true" className="size-4" />}
      </div>
    ) },
    { key: "name", header: "Name", sortable: true, render: (product) => (
      <button type="button" className="rounded-sm text-left font-semibold text-ink underline-offset-4 hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus" onClick={() => onOpen(product)}>
        {product.name}
      </button>
    ) },
    { key: "tracking_mode", header: "Tracking", sortable: true, render: (product) => (
      <span className="inline-flex flex-wrap items-center gap-1.5">
        <Chip size="sm">{product.tracking_mode === "individual" ? "Individual" : "Quantity"}</Chip>
        {product.is_archived ? <Chip size="sm" tone="outline">Archived</Chip> : null}
      </span>
    ) },
    { key: "total_quantity", header: "Total", sortable: true, className: "tabular-nums" },
    { key: "available_quantity", header: "Available", sortable: true, render: (product) => <InventoryAvailability product={product} /> },
    { key: "issued_quantity", header: "Issued", sortable: true, className: "tabular-nums" },
    { key: "damaged_quantity", header: "Damaged", sortable: true, className: "tabular-nums" },
    { key: "lost_quantity", header: "Lost", sortable: true, className: "tabular-nums" },
    { key: "actions", header: <span className="sr-only">Actions</span>, render: (product) => (
      <div className="ml-auto flex w-max flex-wrap justify-end gap-2">
        <Button size="sm" onClick={() => onOpen(product)}>{canEditInventory ? "Edit" : "View"}</Button>
        {canEditInventory && !product.is_archived ? (
          <Button size="sm" variant="warn" disabled={fixableUnits(product) <= 0} onClick={() => onFix(product)}>To Fix</Button>
        ) : null}
        {showToBuy ? <Button size="sm" onClick={() => onToBuy(product)}>To Buy</Button> : null}
        {!canEditInventory ? null : product.is_archived ? (
          <Button size="sm" variant="success" disabled={unarchivePending} onClick={() => onUnarchive(product)}>Back to inventory</Button>
        ) : (
          <Button size="sm" variant="danger-quiet" onClick={() => onArchive(product)}>Archive…</Button>
        )}
      </div>
    ) },
  ];
}
