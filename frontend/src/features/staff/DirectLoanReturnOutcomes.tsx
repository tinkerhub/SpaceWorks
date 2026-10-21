import { Dropdown, Field, Input } from "../../components/ui";
import type { DirectLoanReturnItem } from "./DirectLoanList";

export type AssetOutcome = "returned" | "damaged" | "missing";
// Quantity buckets per item (non-individual): default everything to "returned".
export type QtyState = Record<number, { returned: number; damaged: number; missing: number }>;
// Per-asset outcome for individual-tracked items.
export type AssetState = Record<number, Record<number, AssetOutcome>>;

const BUCKETS = [
  { key: "returned", label: "Returned" },
  { key: "damaged", label: "Damaged" },
  { key: "missing", label: "Missing" },
] as const;

/** How each outstanding unit came back: per-asset outcome, or returned/damaged/missing counts. */
export function DirectLoanReturnOutcomes({
  items,
  qtyState,
  assetState,
  disabled,
  fullyResolved,
  onQtyChange,
  onAssetChange,
}: {
  items: DirectLoanReturnItem[];
  qtyState: QtyState;
  assetState: AssetState;
  disabled: boolean;
  fullyResolved: boolean;
  onQtyChange: (itemId: number, key: "returned" | "damaged" | "missing", value: string) => void;
  onAssetChange: (itemId: number, assetId: number, outcome: AssetOutcome) => void;
}) {
  if (!items.length) return null;
  return (
    <fieldset className="grid gap-3">
      <legend className="mb-2 text-label text-ink">Return outcomes</legend>
      {items.map((item) =>
        item.tracking_mode === "individual" ? (
          <div key={item.item_id} className="grid gap-3 rounded-lg border border-line p-3">
            <p className="text-label text-ink">{item.product_name}</p>
            {item.assets.map((asset) => (
              <Field key={asset.asset_id} label={<span className="font-mono">{asset.asset_tag}</span>}>
                <Dropdown
                  value={(assetState[item.item_id] ?? {})[asset.asset_id] ?? "returned"}
                  disabled={disabled}
                  onChange={(event) => onAssetChange(item.item_id, asset.asset_id, event.target.value as AssetOutcome)}
                >
                  <option value="returned">Returned</option>
                  <option value="damaged">Damaged</option>
                  <option value="missing">Missing</option>
                </Dropdown>
              </Field>
            ))}
          </div>
        ) : (
          <div key={item.item_id} className="grid gap-3 rounded-lg border border-line p-3">
            <p className="text-label text-ink">
              {item.product_name} <span className="font-normal text-ink-muted">· {item.remaining_quantity} out</span>
            </p>
            <div className="grid gap-3 sm:grid-cols-3">
              {BUCKETS.map((bucket) => (
                <Field key={bucket.key} label={bucket.label}>
                  <Input
                    type="number"
                    min="0"
                    max={item.remaining_quantity}
                    value={(qtyState[item.item_id] ?? { returned: 0, damaged: 0, missing: 0 })[bucket.key]}
                    disabled={disabled}
                    onChange={(event) => onQtyChange(item.item_id, bucket.key, event.target.value)}
                  />
                </Field>
              ))}
            </div>
          </div>
        ),
      )}
      {!fullyResolved ? <p className="text-caption text-warning-fg">Resolve every outstanding unit before submitting.</p> : null}
    </fieldset>
  );
}
