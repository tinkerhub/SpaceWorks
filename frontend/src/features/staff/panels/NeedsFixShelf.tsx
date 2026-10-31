import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { Button, Chip, ConfirmDialog, EmptyState, ErrorText, Input, Modal, SkeletonRows, Table, TBody, TD, TH, THead, TR, useToast } from "../../../components/ui";
import { staffRequest } from "../../../lib/api";
import { moduleEnabled } from "../../../lib/modules";
import { invalidateInventoryViews } from "../queryInvalidation";
import { IndividualAssets } from "./InventoryAssets";
import { errorText, Panel, type Makerspace, useStaffGet } from "./shared";

type ShelfItem = {
  id: number;
  name: string;
  tracking_mode: "quantity" | "individual";
  needs_fix_quantity: number;
  available_quantity: number;
  total_quantity: number;
};

type ShelfAction = "repair" | "scrap";

// The to-be-fixed shelf: items with units pulled out for repair (rejected as broken at
// handover). Staff can repair them back into stock or scrap them out of inventory.
export function NeedsFixShelf({ makerspace }: { makerspace: Makerspace }) {
  const queryClient = useQueryClient();
  const { showToast } = useToast();
  const shelf = useStaffGet<{ results: ShelfItem[] }>(
    ["needs-fix-shelf", makerspace.id],
    `/admin/inventory/needs-fix?makerspace=${makerspace.id}`,
  );
  const [qty, setQty] = useState<Record<number, string>>({});
  const [scrapTarget, setScrapTarget] = useState<ShelfItem | null>(null);
  const [assetTarget, setAssetTarget] = useState<ShelfItem | null>(null);
  const assetUnitsEnabled = moduleEnabled(makerspace.enabled_modules, "asset_units");
  const containersEnabled = moduleEnabled(makerspace.enabled_modules, "containers");
  const refreshShelf = () => {
    queryClient.invalidateQueries({ queryKey: ["needs-fix-shelf", makerspace.id] });
    // Repairs return units to available stock, so the public counts change too.
    invalidateInventoryViews(queryClient, makerspace.id, makerspace.slug);
  };

  const act = useMutation({
    mutationFn: ({ item, action, quantity }: { item: ShelfItem; action: ShelfAction; quantity: number }) =>
      staffRequest(`/admin/inventory/${item.id}/needs-fix`, {
        method: "POST",
        body: JSON.stringify({ action, quantity }),
      }),
    onSuccess: (_data, { item, action, quantity }) => {
      showToast(action === "repair" ? `${quantity} ${item.name} back in stock` : `${quantity} ${item.name} scrapped`, { tone: "success" });
      setScrapTarget(null);
      setQty((current) => {
        const next = { ...current };
        delete next[item.id];
        return next;
      });
      refreshShelf();
    },
    onError: (error) => showToast(errorText(error, "Could not update the shelf."), { tone: "error" }),
  });

  const rows = shelf.data?.results ?? [];
  const quantityFor = (item: ShelfItem) => qty[item.id] === undefined ? item.needs_fix_quantity : Number(qty[item.id]);
  const quantityValid = (item: ShelfItem) => {
    const quantity = quantityFor(item);
    return Number.isInteger(quantity) && quantity >= 1 && quantity <= item.needs_fix_quantity;
  };
  const run = (item: ShelfItem, action: ShelfAction) => {
    if (!quantityValid(item)) return;
    act.mutate({ item, action, quantity: quantityFor(item) });
  };

  return (
    <Panel title="To-be-fixed shelf" description="Units rejected as broken at handover. Repair them back into stock, or scrap them out of inventory.">
      <div className="grid gap-4">
        {shelf.error ? <ErrorText message={errorText(shelf.error, "Could not load the shelf.")} /> : null}
        {!shelf.isLoading && !shelf.error && !rows.length ? (
          <EmptyState title="Nothing on the shelf" description="No items are waiting for repair. Units rejected as broken at handover land here." />
        ) : null}
        {shelf.isLoading || rows.length ? (
          <Table label="Items awaiting repair">
            <THead>
              <tr>
                <TH>Item</TH>
                <TH>To fix</TH>
                <TH>Stock</TH>
                <TH>Quantity</TH>
                <TH><span className="sr-only">Actions</span></TH>
              </tr>
            </THead>
            <TBody>
              {shelf.isLoading ? <SkeletonRows rows={3} cols={5} /> : rows.map((item) => (
                <TR key={item.id}>
                  <TD className="font-semibold">{item.name}</TD>
                  <TD><Chip tone="warning" size="sm">{item.needs_fix_quantity} to fix</Chip></TD>
                  <TD className="whitespace-nowrap tabular-nums text-ink-secondary">{item.available_quantity} available · {item.total_quantity} total</TD>
                  <TD>
                    {item.tracking_mode === "individual" ? <span className="text-ink-secondary">Per unit</span> : <Input
                      className="w-24"
                      aria-label={`Quantity for ${item.name}`}
                      type="number"
                      inputMode="numeric"
                      min="1"
                      max={item.needs_fix_quantity}
                      placeholder={String(item.needs_fix_quantity)}
                      value={qty[item.id] ?? String(item.needs_fix_quantity)}
                      aria-invalid={!quantityValid(item) || undefined}
                      onChange={(event) => setQty((current) => ({ ...current, [item.id]: event.target.value }))}
                    />}
                  </TD>
                  <TD>
                    {item.tracking_mode === "individual" ? (
                      <div className="grid justify-items-end gap-2">
                        <Button size="sm" disabled={!assetUnitsEnabled} onClick={() => setAssetTarget(item)}>Manage units</Button>
                        {!assetUnitsEnabled ? <p className="text-caption text-ink-secondary">Unit management is unavailable because the asset units module is disabled.</p> : null}
                      </div>
                    ) : <div className="flex flex-wrap justify-end gap-2">
                      <Button size="sm" variant="success" disabled={act.isPending || !quantityValid(item)} onClick={() => run(item, "repair")}>
                        Move back to inventory
                      </Button>
                      <Button size="sm" variant="danger" disabled={act.isPending || !quantityValid(item)} onClick={() => setScrapTarget(item)}>
                        Scrap…
                      </Button>
                    </div>}
                  </TD>
                </TR>
              ))}
            </TBody>
          </Table>
        ) : null}
        {act.error ? <ErrorText message={errorText(act.error, "Could not update the shelf.")} /> : null}
      </div>
      <Modal
        open={Boolean(assetTarget) && assetUnitsEnabled}
        onClose={() => setAssetTarget(null)}
        title={assetTarget ? `Manage units · ${assetTarget.name}` : "Manage units"}
        size="lg"
        footer={<div className="flex justify-end"><Button onClick={() => setAssetTarget(null)}>Close</Button></div>}
      >
        {assetTarget && assetUnitsEnabled ? (
          <IndividualAssets
            productId={assetTarget.id}
            makerspaceId={makerspace.id}
            refreshInventory={refreshShelf}
            canEdit={true}
            containersEnabled={containersEnabled}
          />
        ) : null}
      </Modal>
      <ConfirmDialog
        open={Boolean(scrapTarget)}
        title={scrapTarget ? `Scrap ${quantityFor(scrapTarget)} ${scrapTarget.name}?` : "Scrap units?"}
        message="Scrapped units are removed from inventory for good. The adjustment is logged."
        confirmLabel="Scrap"
        tone="danger"
        pending={act.isPending}
        onCancel={() => setScrapTarget(null)}
        onConfirm={() => { if (scrapTarget) run(scrapTarget, "scrap"); }}
      />
    </Panel>
  );
}
