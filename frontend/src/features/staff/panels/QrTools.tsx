import { useEffect, useMemo, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Plus, QrCode as QrIcon } from "lucide-react";

import { Button, Callout, Card, CardHeader, Chip, Dropdown, EmptyState, ErrorText, Field, Input, useToast } from "../../../components/ui";
import { staffRequest } from "../../../lib/api";
import { moduleEnabled } from "../../../lib/modules";
import { errorText, Panel, type Makerspace, type Product, useStaffGet } from "./shared";
import { BatchLabels, NewBatchDialog, type Batch, type BatchDetail } from "./QrToolsBatch";
import { invalidateInventoryViews, invalidateQrViews } from "../queryInvalidation";

type ListResponse<T> = { results: T[] };
type QrCode = { id: number; payload: string; target_type: string; target_id: number };
type AssetRow = { id: number; asset_tag: string; serial_number: string; status: string; box_label: string | null; qr_code_id: number | null; qr_payload: string | null };

export function QrTools({ makerspace }: { makerspace: Makerspace }) {
  const queryClient = useQueryClient();
  const { showToast } = useToast();
  const [batchId, setBatchId] = useState("");
  const [productId, setProductId] = useState("");
  const [assetId, setAssetId] = useState("");
  const [assetCount, setAssetCount] = useState("50");
  const [assetPrefix, setAssetPrefix] = useState("");
  const [batchModalOpen, setBatchModalOpen] = useState(false);
  const batches = useStaffGet<ListResponse<Batch>>(["qr-batches", makerspace.id], `/admin/makerspace/${makerspace.id}/qr-print-batches`);
  const products = useStaffGet<ListResponse<Product>>(["inventory", makerspace.id], `/admin/makerspace/${makerspace.id}/inventory?page_size=1000`);
  const activeBatchId = Number(batchId) || 0;
  const selectedProductId = Number(productId) || 0;
  const batch = useStaffGet<BatchDetail>(["qr-batch", activeBatchId], `/admin/qr-print-batches/${activeBatchId}`, Boolean(activeBatchId));

  useEffect(() => {
    if (!batchId && batches.data?.results?.length) {
      setBatchId(String(batches.data.results[0].id));
    }
  }, [batchId, batches.data?.results]);

  const productOptions = useMemo(() => products.data?.results?.filter((product) => !product.is_archived) ?? [], [products.data?.results]);
  const selectedProduct = useMemo(() => productOptions.find((product) => product.id === selectedProductId), [selectedProductId, productOptions]);
  const selectedIsIndividual = selectedProduct?.tracking_mode === "individual";
  const assets = useStaffGet<ListResponse<AssetRow>>(
    ["inventory-assets", selectedProductId],
    `/admin/inventory/${selectedProductId}/assets`,
    Boolean(selectedIsIndividual && selectedProductId),
  );

  const refreshBatch = () => {
    queryClient.invalidateQueries({ queryKey: ["qr-batches", makerspace.id] });
    if (activeBatchId) queryClient.invalidateQueries({ queryKey: ["qr-batch", activeBatchId] });
  };
  const failed = (fallback: string) => (error: Error) => showToast(errorText(error, fallback), { tone: "error" });
  const createBatch = useMutation({
    mutationFn: (title: string) =>
      staffRequest<Batch>(`/admin/makerspace/${makerspace.id}/qr-print-batches`, { method: "POST", body: JSON.stringify({ title }) }),
    onSuccess: (created) => {
      setBatchId(String(created.id));
      setBatchModalOpen(false);
      refreshBatch();
      showToast("Print batch created", { tone: "success" });
    },
    onError: failed("Could not create the print batch"),
  });
  const addItem = async (qrCodeId: number, labelText: string) => {
    await staffRequest(`/admin/qr-print-batches/${activeBatchId}/items`, {
      method: "POST",
      body: JSON.stringify({ qr_code_id: qrCodeId, label_text: labelText }),
    });
  };
  const addProduct = useMutation({
    mutationFn: async () => {
      if (!selectedProduct) throw new Error("Choose an inventory item.");
      if (selectedProduct.tracking_mode === "individual") throw new Error("Generate unit QRs for individual inventory.");
      const qr = await staffRequest<QrCode>("/admin/qr/tools", {
        method: "POST",
        body: JSON.stringify({ makerspace_id: makerspace.id, product_id: selectedProduct.id }),
      });
      await addItem(qr.id, selectedProduct.name);
    },
    onSuccess: () => {
      // /qr/tools may mint the item's QR for the first time, so QR views are stale too.
      invalidateQrViews(queryClient, makerspace.id);
      refreshBatch();
      showToast("Item QR added to the batch", { tone: "success" });
    },
    onError: failed("Could not add the item QR"),
  });
  const reprintAsset = useMutation({
    mutationFn: async () => {
      const asset = assets.data?.results?.find((item) => item.id === Number(assetId));
      if (!asset) throw new Error("Choose an existing unit.");
      const qr = await staffRequest<QrCode>(`/admin/assets/${asset.id}/qr`, { method: "POST", body: JSON.stringify({}) });
      await addItem(qr.id, asset.asset_tag);
    },
    onSuccess: () => {
      invalidateInventoryViews(queryClient, makerspace.id);
      invalidateQrViews(queryClient, makerspace.id);
      queryClient.invalidateQueries({ queryKey: ["inventory-assets", selectedProductId] });
      refreshBatch();
      showToast("Unit QR added to the batch", { tone: "success" });
    },
    onError: failed("Could not reprint the unit QR"),
  });
  const generateAssets = useMutation({
    mutationFn: () => {
      if (!selectedProduct) return Promise.reject(new Error("Choose an inventory item."));
      return staffRequest(`/admin/products/${selectedProduct.id}/assets/generate`, {
        method: "POST",
        body: JSON.stringify({ count: Number(assetCount), name_prefix: assetPrefix.trim() || selectedProduct.name, print_batch_id: activeBatchId }),
      });
    },
    onSuccess: () => {
      invalidateInventoryViews(queryClient, makerspace.id);
      invalidateQrViews(queryClient, makerspace.id);
      queryClient.invalidateQueries({ queryKey: ["inventory-assets", selectedProductId] });
      refreshBatch();
      showToast("Unit QRs generated", { tone: "success" });
    },
    onError: failed("Could not generate unit QRs"),
  });
  const hasBatch = Boolean(activeBatchId);
  // Both unit-QR endpoints (`assets/generate` and the per-asset reprint) are guarded by
  // `asset_units` on the backend, so offering the controls without it produces a form
  // whose only outcome is a 404. Fails closed: an unloaded list enables nothing.
  const assetUnitsEnabled = moduleEnabled(makerspace.enabled_modules, "asset_units");
  const count = Number(assetCount);
  const assetOptions = assets.data?.results ?? [];
  const canGenerateAssets = hasBatch && Boolean(selectedProduct) && selectedIsIndividual && Number.isInteger(count) && count > 0 && count <= 200;
  const canReprintAsset = hasBatch && selectedIsIndividual && Boolean(assetId);
  const canAddItemQr = hasBatch && Boolean(selectedProduct) && !selectedIsIndividual;
  const selectProduct = (nextId: string) => {
    setProductId(nextId);
    setAssetId("");
    const product = productOptions.find((item) => item.id === Number(nextId));
    setAssetPrefix(product?.name ?? "");
  };
  const noBatches = !batches.isLoading && !batches.error && !batches.data?.results?.length;
  const openNewBatch = () => { createBatch.reset(); setBatchModalOpen(true); };

  return (
    <Panel
      title="QR tools"
      description={`Collect QR labels for ${makerspace.name} into a print batch, then download them together.`}
      actions={<Button variant="primary" startIcon={<Plus />} onClick={openNewBatch}>New batch</Button>}
    >
      <div className="grid gap-5">
        {noBatches ? (
          <EmptyState title="No print batches yet" description="Create a batch first; labels you add are collected in it." action={<Button onClick={openNewBatch}>New batch</Button>} />
        ) : (
          <Card as="section">
            <Field label="Print batch">
              <Dropdown value={batchId} disabled={batches.isLoading} onChange={(event) => setBatchId(event.target.value)}>
                <option value="">Select a print batch</option>
                {batches.data?.results?.map((item) => <option key={item.id} value={item.id}>{item.title}</option>)}
              </Dropdown>
            </Field>
            {batches.isError ? <ErrorText message={batches.error.message} /> : null}
          </Card>
        )}

        <Card as="section">
          <CardHeader title="Inventory QR" description="Add an item's QR, or generate and reprint unit QRs for individually tracked items." />
          <div className="grid gap-4">
            <Field label="Inventory item" helperText={hasBatch ? undefined : "Choose or create a print batch first."}>
              <Dropdown value={productId} disabled={!hasBatch || products.isLoading} onChange={(event) => selectProduct(event.target.value)}>
                <option value="">Choose an inventory item</option>
                {productOptions.map((product) => (
                  <option key={product.id} value={product.id}>{product.name} · {product.tracking_mode} · {product.available_quantity} available</option>
                ))}
              </Dropdown>
            </Field>
            {selectedProduct ? (
              <div><Chip tone="neutral" size="sm">{selectedIsIndividual ? "Individually tracked" : "Tracked by quantity"}</Chip></div>
            ) : null}
            {selectedIsIndividual && !assetUnitsEnabled ? (
              <Callout tone="info">Unit QR generation needs the Asset units module.</Callout>
            ) : null}
            {selectedIsIndividual && assetUnitsEnabled ? (
              <div className="grid gap-4">
                <div className="grid items-end gap-3 sm:grid-cols-[120px_minmax(0,1fr)_auto]">
                  <Field label="Unit count"><Input inputMode="numeric" value={assetCount} onChange={(event) => setAssetCount(event.target.value)} /></Field>
                  <Field label="Label prefix"><Input value={assetPrefix} onChange={(event) => setAssetPrefix(event.target.value)} /></Field>
                  <Button variant="primary" startIcon={<QrIcon />} disabled={!canGenerateAssets} loading={generateAssets.isPending} loadingLabel="Generating…" onClick={() => generateAssets.mutate()}>
                    Generate missing/new unit QRs
                  </Button>
                </div>
                <div className="grid items-end gap-3 border-t border-line pt-4 sm:grid-cols-[minmax(0,1fr)_auto]">
                  <Field label="Existing unit to reprint">
                    <Dropdown value={assetId} disabled={!hasBatch || assets.isLoading} onChange={(event) => setAssetId(event.target.value)}>
                      <option value="">Choose a unit</option>
                      {assetOptions.map((asset) => (
                        <option key={asset.id} value={asset.id}>{asset.asset_tag} · {asset.status} · {asset.qr_code_id ? `QR #${asset.qr_code_id}` : "no QR linked"}</option>
                      ))}
                    </Dropdown>
                  </Field>
                  <Button disabled={!canReprintAsset} loading={reprintAsset.isPending} loadingLabel="Adding…" onClick={() => reprintAsset.mutate()}>Reprint unit QR</Button>
                </div>
                {assets.isLoading ? <p role="status" className="text-body-ui text-ink-muted">Loading units…</p> : null}
                {assets.isError ? <ErrorText message={assets.error.message} /> : null}
                {!assets.isLoading && selectedProduct && !assetOptions.length ? <p className="text-body-ui text-ink-muted">No individual units yet.</p> : null}
              </div>
            ) : null}
            {!selectedIsIndividual ? (
              <div>
                <Button startIcon={<QrIcon />} disabled={!canAddItemQr} loading={addProduct.isPending} loadingLabel="Adding…" onClick={() => addProduct.mutate()}>
                  Add/reprint item QR
                </Button>
              </div>
            ) : null}
            {addProduct.isError ? <ErrorText message={addProduct.error.message} /> : null}
            {reprintAsset.isError ? <ErrorText message={reprintAsset.error.message} /> : null}
            {generateAssets.isError ? <ErrorText message={generateAssets.error.message} /> : null}
          </div>
        </Card>

        {hasBatch ? <BatchLabels batchId={activeBatchId} batch={batch.data} loading={batch.isLoading} error={batch.error} /> : null}
      </div>

      <NewBatchDialog
        open={batchModalOpen}
        pending={createBatch.isPending}
        error={createBatch.error?.message}
        onClose={() => setBatchModalOpen(false)}
        onCreate={(title) => createBatch.mutate(title)}
      />
    </Panel>
  );
}
