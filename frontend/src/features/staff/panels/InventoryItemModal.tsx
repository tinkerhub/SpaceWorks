import type { ReactNode } from "react";

import { Button, CheckboxField, Dropdown, ErrorText, Field, Input, Metric, Modal, SectionHeading, Textarea } from "../../../components/ui";
import { StatusWord, type Category } from "./shared";
import type { AdjustmentForm, AdminProduct, ItemForm } from "./inventoryForm";

// `readOnly` is for roles holding VIEW_INVENTORY without EDIT_INVENTORY: the product PATCH
// is EDIT_INVENTORY on the server, so they see the details with no Save to fail on.
export function ItemModal({ title, open, onClose, form, setForm, categories, includeQuantities = false, readOnly = false, pending, error, onSubmit, children }: {
  title: string; open: boolean; onClose: () => void; form: ItemForm; setForm: (updater: (current: ItemForm) => ItemForm) => void; categories: Category[];
  includeQuantities?: boolean; readOnly?: boolean; pending: boolean; error?: string; onSubmit: () => void; children?: ReactNode;
}) {
  const set = <K extends keyof ItemForm>(key: K, value: ItemForm[K]) => setForm((current) => ({ ...current, [key]: value }));
  return (
    <Modal
      open={open}
      onClose={onClose}
      title={title}
      description={readOnly ? "You can view this item. Editing needs the edit inventory permission." : undefined}
      size="lg"
      footer={(
        <div className="flex flex-col-reverse gap-2.5 sm:flex-row sm:justify-end">
          <Button variant="secondary" disabled={pending} onClick={onClose}>{readOnly ? "Close" : "Cancel"}</Button>
          {readOnly ? null : <Button variant="primary" loading={pending} disabled={!form.name.trim()} onClick={onSubmit}>Save</Button>}
        </div>
      )}
    >
      <div className="grid gap-5">
        <fieldset className="grid min-w-0 gap-4" disabled={readOnly}>
          <Field label="Name"><Input placeholder="e.g. Soldering iron" value={form.name} onChange={(e) => set("name", e.target.value)} /></Field>
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Tracking mode" helperText="Individual tracks each unit by its own tag and QR.">
              <Dropdown value={form.tracking_mode} disabled={readOnly} onChange={(e) => set("tracking_mode", e.target.value)}>
                <option value="quantity">Quantity</option>
                <option value="individual">Individual</option>
              </Dropdown>
            </Field>
            <Field label="Category">
              <Dropdown value={form.category} disabled={readOnly} onChange={(e) => set("category", e.target.value)}>
                <option value="">Uncategorized</option>
                {categories.map((category) => <option key={category.id} value={String(category.id)}>{category.name}</option>)}
              </Dropdown>
            </Field>
          </div>
          <Field label="Description" optional><Textarea rows={3} placeholder="Notes for staff and borrowers" value={form.description} onChange={(e) => set("description", e.target.value)} /></Field>
          <Field label="Storage location" optional helperText="Staff only. Never shown on the public page."><Input placeholder="e.g. Shelf B3" value={form.storage_location} onChange={(e) => set("storage_location", e.target.value)} /></Field>
          {includeQuantities ? (
            <div className="grid gap-4 sm:grid-cols-2">
              <Field label="Total quantity"><Input type="number" min="0" inputMode="numeric" value={form.total_quantity} onChange={(e) => set("total_quantity", e.target.value)} /></Field>
              <Field label="Available quantity"><Input type="number" min="0" inputMode="numeric" value={form.available_quantity} onChange={(e) => set("available_quantity", e.target.value)} /></Field>
            </div>
          ) : null}
          <div className="grid gap-3 rounded-lg border border-line p-4">
            <SectionHeading as="h3" title="Public page" description="What members see on the public inventory." />
            <div className="grid gap-3 sm:grid-cols-3">
              <CheckboxField label="Public" checked={form.is_public} disabled={readOnly} onCheckedChange={(checked) => set("is_public", checked === true)} />
              <CheckboxField label="Self checkout" checked={form.public_self_checkout_enabled} disabled={readOnly} onCheckedChange={(checked) => set("public_self_checkout_enabled", checked === true)} />
              <CheckboxField label="Show count" checked={form.show_public_count} disabled={readOnly} onCheckedChange={(checked) => set("show_public_count", checked === true)} />
            </div>
            <Field label="Public visibility">
              <Dropdown value={form.public_availability_mode} disabled={readOnly} onChange={(e) => set("public_availability_mode", e.target.value)}>
                <option value="status_only">Status only</option>
                <option value="exact_count">Exact count</option>
                <option value="hidden">Hidden</option>
              </Dropdown>
            </Field>
          </div>
        </fieldset>
        {includeQuantities ? <p className="text-caption text-ink-muted">You can add a photo after saving. The item opens for editing so you can upload one.</p> : null}
        <ErrorText message={error} />
        {children}
      </div>
    </Modal>
  );
}

export function QuantityAdjust({ product, form, setForm, pending, error, onSubmit }: { product: AdminProduct; form: AdjustmentForm; setForm: (updater: (current: AdjustmentForm) => AdjustmentForm) => void; pending: boolean; error?: string; onSubmit: () => void }) {
  const set = (key: keyof AdjustmentForm, value: string) => setForm((current) => ({ ...current, [key]: value }));
  return (
    <section className="grid gap-4 border-t border-line pt-5">
      <SectionHeading as="h3" title="Adjust quantities" description="Use positive or negative numbers. Every adjustment is logged with its reason." />
      <div className="grid gap-2 sm:grid-cols-3">
        <Metric label="Available" value={product.available_quantity} />
        <Metric label="Damaged" value={product.damaged_quantity} />
        <Metric label="Lost" value={product.lost_quantity} danger={product.lost_quantity > 0} />
      </div>
      <div className="grid gap-4 sm:grid-cols-3">
        <Field label="Change available"><Input type="number" inputMode="numeric" value={form.delta_available} onChange={(e) => set("delta_available", e.target.value)} /></Field>
        <Field label="Change damaged"><Input type="number" inputMode="numeric" value={form.delta_damaged} onChange={(e) => set("delta_damaged", e.target.value)} /></Field>
        <Field label="Change lost"><Input type="number" inputMode="numeric" value={form.delta_lost} onChange={(e) => set("delta_lost", e.target.value)} /></Field>
      </div>
      <Field label="Adjustment reason"><Input placeholder="e.g. Recount after stocktake" value={form.reason} onChange={(e) => set("reason", e.target.value)} /></Field>
      <ErrorText message={error} />
      <div className="flex justify-end">
        <Button variant="secondary" loading={pending} disabled={!form.reason.trim()} onClick={onSubmit}>Apply adjustment</Button>
      </div>
    </section>
  );
}

export function InventoryAvailability({ product }: { product: AdminProduct }) {
  const isLowStock = product.available_quantity <= Math.ceil(product.total_quantity * 0.2);
  const badge = product.available_quantity <= 0
    ? <StatusWord status="unavailable" label="Unavailable" tone="danger" />
    : isLowStock
      ? <StatusWord status="limited" label="Limited" tone="warning" />
      : <StatusWord status="available" label="Available" tone="success" />;
  return <span className="inline-flex items-center gap-2"><span className="inline-block w-8 font-semibold tabular-nums text-ink">{product.available_quantity}</span>{badge}</span>;
}
