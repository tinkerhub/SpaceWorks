import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ScanLine } from "lucide-react";

import {
  Button, Dropdown, EmptyState, ErrorText, Field, Input, SectionHeading, SegmentedControl, SkeletonRows,
  Table, TBody, TD, TH, THead, TR, useToast,
} from "../../../components/ui";
import QrScanner from "../../../components/ui/QrScanner";
import { staffRequest } from "../../../lib/api";
import { errorText, type Makerspace, useStaffGet } from "./shared";

export type StocktakeRow = { id: number; status: string; notes: string; container: number | null; can_approve: boolean; can_apply: boolean };
type StocktakeLine = {
  id: number;
  product: number | null;
  asset: number | null;
  expected_quantity: number;
  counted_quantity: number;
  variance_quantity: number;
  condition: string;
  container: number | null;
  notes: string;
};
type StocktakeDetail = StocktakeRow & { lines: StocktakeLine[] };
type ProductOption = { id: number; name: string; tracking_mode: string };
export type ContainerOption = { id: number; label: string; location?: string };
type AssetOption = { id: number; asset_tag: string; serial_number: string; status: string };
type StocktakeScanResult = {
  type: "box" | "asset" | "product";
  container_id?: number;
  asset_id?: number;
  product_id?: number;
  label?: string;
  asset_tag?: string;
  name?: string;
};

const CONDITIONS = ["available", "damaged", "lost", "unknown"];
const LINE_COLUMNS = ["Item", "Container", "Expected", "Counted", "Variance", "Condition", "Notes"];
const sentence = (value: string) => value.charAt(0).toUpperCase() + value.slice(1);

// The count step is what moves a stocktake forward and produces the variance the Apply
// step adjusts on - without it a stocktake has zero lines and Apply is a no-op. Records
// a counted quantity per product, then shows expected/counted/variance from the detail.
export function CountSection({ makerspace, stocktakeId }: { makerspace: Makerspace; stocktakeId: number }) {
  const queryClient = useQueryClient();
  const { showToast } = useToast();
  const [mode, setMode] = useState<"product" | "asset">("product");
  const [productId, setProductId] = useState("");
  const [assetId, setAssetId] = useState("");
  const [containerId, setContainerId] = useState("");
  const [counted, setCounted] = useState("0");
  const [condition, setCondition] = useState("available");
  const [notes, setNotes] = useState("");
  const [scanning, setScanning] = useState(false);
  const [scanNote, setScanNote] = useState<{ text: string; ok: boolean } | null>(null);
  const detail = useStaffGet<StocktakeDetail>(["stocktake-detail", stocktakeId], `/admin/stocktakes/${stocktakeId}`);
  const products = useStaffGet<{ results: ProductOption[] }>(["inventory-all", makerspace.id], `/admin/makerspace/${makerspace.id}/inventory?page_size=1000`);
  const containers = useStaffGet<{ results: ContainerOption[] }>(["stocktake-containers", makerspace.id], `/admin/makerspace/${makerspace.id}/containers?page_size=1000`);
  const assets = useStaffGet<{ results: AssetOption[] }>(["stocktake-assets", productId], productId ? `/admin/inventory/${productId}/assets?page_size=1000` : "", Boolean(productId));
  const productName = (id: number | null) => products.data?.results.find((product) => product.id === id)?.name ?? (id ? `#${id}` : "-");
  const assetName = (id: number | null) => assets.data?.results.find((asset) => asset.id === id)?.asset_tag ?? (id ? `Asset #${id}` : "-");
  const containerName = (id: number | null) => containers.data?.results.find((container) => container.id === id)?.label ?? (id ? `Container #${id}` : "-");

  const record = useMutation({
    mutationFn: () => {
      const payload = {
        ...(mode === "asset" ? { asset_id: Number(assetId) } : { product_id: Number(productId) }),
        ...(containerId ? { container_id: Number(containerId) } : {}),
        counted_quantity: Number(counted) || 0,
        condition,
        notes,
      };
      return staffRequest(`/admin/stocktakes/${stocktakeId}/count-lines`, { method: "POST", body: JSON.stringify(payload) });
    },
    onSuccess: () => {
      setProductId("");
      setAssetId("");
      setContainerId("");
      setCounted("0");
      setNotes("");
      setScanNote(null);
      queryClient.invalidateQueries({ queryKey: ["stocktake-detail", stocktakeId] });
      queryClient.invalidateQueries({ queryKey: ["stocktakes", makerspace.id] });
      showToast("Count recorded", { tone: "success" });
    },
    onError: (error) => showToast(errorText(error, "Could not record the count"), { tone: "error" }),
  });
  const handleScan = async (payload: string) => {
    try {
      const result = await staffRequest<StocktakeScanResult>(`/admin/stocktakes/${stocktakeId}/resolve-scan`, {
        method: "POST",
        body: JSON.stringify({ payload }),
      });
      let message = `Scanned ${result.asset_tag || result.name || result.label || payload}`;
      if (result.type === "asset" && result.asset_id && result.product_id) {
        setMode("asset");
        setProductId(String(result.product_id));
        setAssetId(String(result.asset_id));
      } else if (result.type === "product" && result.product_id) {
        const product = await staffRequest<ProductOption>(`/admin/inventory/${result.product_id}`);
        const individual = product.tracking_mode === "individual";
        setMode(individual ? "asset" : "product");
        setProductId(String(result.product_id));
        setAssetId("");
        if (individual) message = `${product.name} is tracked by unit. Scan or select an actual asset to record its count.`;
      } else if (result.type === "box" && result.container_id) {
        setContainerId(String(result.container_id));
      }
      setScanNote({ text: message, ok: true });
    } catch (error) {
      setScanNote({ text: errorText(error, "Unable to resolve scanned QR"), ok: false });
    }
    setScanning(false);
  };
  const lines = detail.data?.lines ?? [];
  const canSave = mode === "asset" ? Boolean(assetId) : Boolean(productId);
  const containerField = (
    <Field label="Line container">
      <Dropdown value={containerId} onChange={(event) => setContainerId(event.target.value)}>
        <option value="">No container</option>
        {containers.data?.results.map((container) => <option key={container.id} value={container.id}>{container.label}</option>)}
      </Dropdown>
    </Field>
  );

  return (
    <div className="grid gap-6">
      <div className="grid gap-4">
        <SegmentedControl
          ariaLabel="Count type"
          value={mode}
          onValueChange={(next) => { setMode(next); setProductId(""); setAssetId(""); }}
          options={[{ value: "product", label: "Product" }, { value: "asset", label: "Asset" }]}
        />
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label={mode === "asset" ? "Product for asset" : "Product"}>
            <Dropdown value={productId} disabled={products.isLoading} onChange={(event) => { setProductId(event.target.value); setAssetId(""); }}>
              <option value="">Select product</option>
              {products.data?.results.filter((product) => mode === "asset" || product.tracking_mode === "quantity").map((product) => <option key={product.id} value={product.id}>{product.name}</option>)}
            </Dropdown>
          </Field>
          {mode === "asset" ? (
            <Field label="Asset">
              <Dropdown value={assetId} disabled={!productId || assets.isLoading} onChange={(event) => setAssetId(event.target.value)}>
                <option value="">Select asset</option>
                {assets.data?.results.map((asset) => <option key={asset.id} value={asset.id}>{asset.asset_tag} ({asset.status})</option>)}
              </Dropdown>
            </Field>
          ) : containerField}
          <Field label="Counted">
            <Input type="number" min="0" inputMode="numeric" value={counted} onChange={(event) => setCounted(event.target.value)} />
          </Field>
          <Field label="Condition">
            <Dropdown value={condition} onChange={(event) => setCondition(event.target.value)}>
              {CONDITIONS.map((value) => <option key={value} value={value}>{sentence(value)}</option>)}
            </Dropdown>
          </Field>
          {mode === "asset" ? containerField : null}
          <Field label="Line notes" optional className={mode === "asset" ? undefined : "sm:col-span-2"}>
            <Input value={notes} onChange={(event) => setNotes(event.target.value)} />
          </Field>
        </div>
        <div className="flex flex-wrap items-center justify-between gap-2.5">
          <Button startIcon={<ScanLine />} onClick={() => setScanning(true)}>Scan QR</Button>
          <Button variant="primary" disabled={!canSave} loading={record.isPending} loadingLabel="Saving…" onClick={() => record.mutate()}>Record count</Button>
        </div>
        {scanNote ? (
          scanNote.ok ? <p role="status" className="text-body-ui text-ink-muted">{scanNote.text}</p> : <ErrorText message={scanNote.text} />
        ) : null}
        {record.isError ? <ErrorText message={record.error.message} /> : null}
      </div>
      {scanning ? <QrScanner onClose={() => setScanning(false)} onScan={handleScan} /> : null}

      <section className="grid gap-3">
        <SectionHeading as="h3" title="Recorded counts" />
        {detail.error instanceof Error ? <ErrorText message={detail.error.message} /> : null}
        {!detail.isLoading && !lines.length ? (
          <EmptyState title="No counts recorded yet" description="Pick an item above, or scan its QR, and record what is on the shelf." />
        ) : (
          <Table label="Recorded counts" className="min-w-[720px]">
            <THead><tr>{LINE_COLUMNS.map((column) => <TH key={column}>{column}</TH>)}</tr></THead>
            <TBody>
              {detail.isLoading ? <SkeletonRows rows={3} cols={LINE_COLUMNS.length} /> : lines.map((line) => (
                <TR key={line.id}>
                  <TD><span className="block max-w-48 break-words">{line.asset ? assetName(line.asset) : productName(line.product)}</span></TD>
                  <TD>{containerName(line.container)}</TD>
                  <TD className="tabular-nums">{line.expected_quantity}</TD>
                  <TD className="tabular-nums">{line.counted_quantity}</TD>
                  <TD className={line.variance_quantity === 0 ? "tabular-nums text-ink-muted" : "font-semibold tabular-nums text-danger-fg"}>{line.variance_quantity}</TD>
                  <TD>{sentence(line.condition)}</TD>
                  <TD><span className="block max-w-56 break-words">{line.notes || "-"}</span></TD>
                </TR>
              ))}
            </TBody>
          </Table>
        )}
      </section>
    </div>
  );
}
