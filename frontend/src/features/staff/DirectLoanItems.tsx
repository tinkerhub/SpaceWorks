import { useState, type Dispatch, type SetStateAction } from "react";
import { Plus, QrCode, ScanLine, Trash2, X } from "lucide-react";

import { Button, Dropdown, ErrorText, Field, IconButton, Input, SectionHeading, Textarea } from "../../components/ui";
import QrScanner from "../../components/ui/QrScanner";
import { staffRequest } from "../../lib/api";
import {
  labelForTarget,
  type ContainerOption,
  type LineDraft,
  type ProductOption,
  type QrResolveResponse,
  type ScannedPayload,
} from "./DirectLoanTypes";
import { isQrNotRecognised, qrResolveErrorText } from "./evidenceUi";

type DirectLoanItemsProps = {
  products: ProductOption[];
  productsLoading: boolean;
  /** `null` when the `containers` module is off: no container picker at all. */
  containers: ContainerOption[] | null;
  containersLoading: boolean;
  containerId: string;
  onContainerChange: (containerId: string) => void;
  lines: LineDraft[];
  setLines: Dispatch<SetStateAction<LineDraft[]>>;
  scanned: ScannedPayload[];
  setScanned: Dispatch<SetStateAction<ScannedPayload[]>>;
  qrPayloads: string;
  onQrPayloadsChange: (value: string) => void;
};

/**
 * What goes out: an optional container, counted items, and scanned unit/item QR codes.
 * The parent remounts this (key) after each issue, which also clears scanner state.
 */
export function DirectLoanItems(props: DirectLoanItemsProps) {
  const { products, productsLoading, containers, containersLoading, containerId, onContainerChange, lines, setLines, scanned, setScanned, qrPayloads, onQrPayloadsChange } = props;
  const [scanner, setScanner] = useState<"items" | "container" | null>(null);
  const [containerScanError, setContainerScanError] = useState("");
  const [itemScanError, setItemScanError] = useState("");
  const productById = new Map(products.map((product) => [product.id, product]));

  const addLine = () => setLines((rows) => [...rows, { key: Math.max(0, ...rows.map((row) => row.key)) + 1, productId: "", quantity: "1" }]);
  const updateLine = (key: number, patch: Partial<LineDraft>) =>
    setLines((rows) => rows.map((line) => (line.key === key ? { ...line, ...patch } : line)));
  const removeLine = (key: number) => setLines((rows) => rows.filter((line) => line.key !== key));

  const handleScan = async (payload: string) => {
    const cleanPayload = payload.trim();
    if (!cleanPayload || scanned.some((item) => item.payload === cleanPayload)) return;
    let label = cleanPayload;
    try {
      const result = await staffRequest<QrResolveResponse>("/admin/qr/resolve", { method: "POST", body: JSON.stringify({ payload: cleanPayload }) });
      label = labelForTarget(result.target, cleanPayload);
    } catch (error) {
      // 403 and 404 both mean "not a code of this site" (see isQrNotRecognised): say so
      // and leave it out. Any other failure keeps the code as typed for the server to judge.
      if (isQrNotRecognised(error)) {
        setItemScanError(qrResolveErrorText(error));
        return;
      }
      label = cleanPayload;
    }
    setItemScanError("");
    setScanned((items) => (items.some((item) => item.payload === cleanPayload) ? items : [...items, { payload: cleanPayload, label }]));
  };

  const handleContainerScan = async (payload: string) => {
    try {
      const result = await staffRequest<QrResolveResponse>("/admin/qr/resolve", { method: "POST", body: JSON.stringify({ payload }) });
      const target = result.target;
      if (target.type !== "box") {
        setContainerScanError("That QR code isn't a container. Scan the label on the container.");
        return;
      }
      if (!containers?.some((container) => container.id === target.id)) {
        setContainerScanError("That container isn't available for handout (inactive or not found).");
        return;
      }
      onContainerChange(String(target.id));
      setContainerScanError("");
    } catch (error) {
      setContainerScanError(qrResolveErrorText(error, "Could not read that QR code. Try again or pick the container from the list."));
    } finally {
      setScanner(null);
    }
  };

  return (
    <div className="grid gap-6">
      {containers ? <div className="grid gap-2">
        <div className="flex flex-col gap-2 sm:flex-row sm:items-end">
          <Field label="Container" optional className="min-w-0 flex-1">
            <Dropdown id="direct-loan-container" value={containerId} disabled={containersLoading} onChange={(event) => onContainerChange(event.target.value)}>
              <option value="">No container</option>
              {containers.map((container) => (
                <option key={container.id} value={container.id}>{container.label}</option>
              ))}
            </Dropdown>
          </Field>
          <Button startIcon={<ScanLine />} onClick={() => { setContainerScanError(""); setScanner("container"); }}>
            Scan container
          </Button>
        </div>
        <ErrorText message={containerScanError} />
      </div> : null}

      <div className="grid gap-3">
        <SectionHeading as="h3" title="Items" action={<Button size="sm" startIcon={<Plus />} onClick={addLine}>Add item</Button>} />
        {lines.length === 0 ? <p className="text-body-ui text-ink-muted">No counted items. Add one, or scan QR codes below.</p> : null}
        {lines.map((line) => {
          const product = productById.get(Number(line.productId));
          const individual = product?.tracking_mode === "individual";
          return (
            <div key={line.key} className="grid gap-2 sm:grid-cols-[minmax(0,1fr)_120px_auto] sm:items-start">
              <Dropdown aria-label="Product" value={line.productId} disabled={productsLoading} onChange={(event) => updateLine(line.key, { productId: event.target.value })}>
                <option value="">Inventory item</option>
                {products.map((option) => (
                  <option key={option.id} value={option.id}>
                    {option.name} · {option.available_quantity} available{option.storage_location ? ` · Shelf ${option.storage_location}` : ""}
                  </option>
                ))}
              </Dropdown>
              <Input aria-label="Quantity" min={1} inputMode="numeric" type="number" value={line.quantity} disabled={individual} onChange={(event) => updateLine(line.key, { quantity: event.target.value })} />
              <IconButton label="Remove item" variant="quiet" onClick={() => removeLine(line.key)}>
                <Trash2 />
              </IconButton>
              {product ? (
                <p className="text-caption text-ink-muted sm:col-span-3">
                  {individual ? "Tracked per unit. Scan each unit's QR code below instead of entering a quantity." : "Counted by quantity."}
                </p>
              ) : null}
            </div>
          );
        })}
      </div>

      <div className="grid gap-3">
        <SectionHeading as="h3" title="QR codes" action={<Button size="sm" startIcon={<QrCode />} onClick={() => { setItemScanError(""); setScanner("items"); }}>Scan QR</Button>} />
        <ErrorText message={itemScanError} />
        {scanned.length ? (
          <ul className="flex flex-wrap gap-2" aria-label="Scanned QR codes">
            {scanned.map((item) => (
              <li key={item.payload} className="inline-flex min-w-0 max-w-full items-center gap-1 rounded-full bg-fill py-0.5 pl-3 pr-0.5 text-sm font-semibold text-ink-secondary">
                <span className="min-w-0 [overflow-wrap:anywhere]">{item.label}</span>
                <IconButton label={`Remove ${item.label}`} variant="quiet" size="sm" onClick={() => setScanned((items) => items.filter((entry) => entry.payload !== item.payload))}>
                  <X />
                </IconButton>
              </li>
            ))}
          </ul>
        ) : null}
        <Field label="QR payloads" optional helperText="For codes you can't scan: paste one per line.">
          <Textarea className="font-mono text-sm" rows={3} placeholder="One QR payload per line" value={qrPayloads} onChange={(event) => onQrPayloadsChange(event.target.value)} />
        </Field>
      </div>

      {scanner === "items" ? <QrScanner onScan={handleScan} onClose={() => setScanner(null)} /> : null}
      {scanner === "container" ? <QrScanner onScan={handleContainerScan} onClose={() => setScanner(null)} /> : null}
    </div>
  );
}
