import { CheckboxField, Dropdown, Field, Input, SegmentedControl, Textarea } from "../../../components/ui";
import type { Product } from "./shared";

type PrinterOption = { id: number; name: string };

export type ContainerOption = { id: number; label: string };
export type HardwareMode = "create" | "topup";
export type PrintingTarget = "spool" | "printer";

export type HardwareForm = {
  mode: HardwareMode;
  quantity: string;
  productId: string;
  name: string;
  description: string;
  category: string;
  box: string;
  trackingMode: "quantity" | "individual";
  isPublic: boolean;
  publicAvailabilityMode: "exact_count" | "status_only" | "hidden";
  showPublicCount: boolean;
  publicSelfCheckoutEnabled: boolean;
};

export type PrintingForm = {
  target: PrintingTarget;
  printerId: string;
  material: string;
  color: string;
  brand: string;
  initialWeight: string;
  remainingWeight: string;
  printerName: string;
  printerModel: string;
  printerStatus: "active" | "maintenance" | "offline";
};

export function HardwareMoveForm({ form, setForm, products, categories, containers }: {
  form: HardwareForm;
  setForm: (form: HardwareForm) => void;
  products: Product[];
  categories: { id: number; name: string }[];
  containers: ContainerOption[];
}) {
  return (
    <div className="grid gap-4">
      <SegmentedControl<HardwareMode>
        ariaLabel="Move as"
        value={form.mode}
        onValueChange={(mode) => setForm({ ...form, mode })}
        options={[{ value: "create", label: "Create item" }, { value: "topup", label: "Top up" }]}
        className="w-max"
      />
      <Field label="Quantity"><Input type="number" min="1" value={form.quantity} onChange={(e) => setForm({ ...form, quantity: e.target.value })} /></Field>
      {form.mode === "topup" ? (
        <Field label="Existing product">
          <Dropdown value={form.productId} onChange={(e) => setForm({ ...form, productId: e.target.value })}>
            <option value="" disabled>Select product</option>
            {products.map((product) => <option key={product.id} value={String(product.id)}>{product.name} ({product.available_quantity} available)</option>)}
          </Dropdown>
        </Field>
      ) : (
        <>
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Name"><Input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></Field>
            <Field label="Tracking mode">
              <Dropdown value={form.trackingMode} onChange={(e) => setForm({ ...form, trackingMode: e.target.value as HardwareForm["trackingMode"] })}>
                <option value="quantity">Quantity</option>
                <option value="individual">Individual</option>
              </Dropdown>
            </Field>
          </div>
          <Field label="Description" optional><Textarea rows={3} value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} /></Field>
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Category">
              <Dropdown value={form.category} onChange={(e) => setForm({ ...form, category: e.target.value })}>
                <option value="">Uncategorized</option>
                {categories.map((category) => <option key={category.id} value={String(category.id)}>{category.name}</option>)}
              </Dropdown>
            </Field>
            <Field label="Container">
              <Dropdown value={form.box} onChange={(e) => setForm({ ...form, box: e.target.value })}>
                <option value="">No container</option>
                {containers.map((container) => <option key={container.id} value={String(container.id)}>{container.label}</option>)}
              </Dropdown>
            </Field>
          </div>
          <Field label="Public visibility">
            <Dropdown value={form.publicAvailabilityMode} onChange={(e) => setForm({ ...form, publicAvailabilityMode: e.target.value as HardwareForm["publicAvailabilityMode"] })}>
              <option value="status_only">Status only</option>
              <option value="exact_count">Exact count</option>
              <option value="hidden">Hidden</option>
            </Dropdown>
          </Field>
          <div className="grid gap-3 sm:grid-cols-3">
            <CheckboxField label="Public" checked={form.isPublic} onCheckedChange={(value) => setForm({ ...form, isPublic: value === true })} />
            <CheckboxField label="Show count" checked={form.showPublicCount} onCheckedChange={(value) => setForm({ ...form, showPublicCount: value === true })} />
            <CheckboxField label="Self checkout" checked={form.publicSelfCheckoutEnabled} onCheckedChange={(value) => setForm({ ...form, publicSelfCheckoutEnabled: value === true })} />
          </div>
        </>
      )}
    </div>
  );
}

export function PrintingMoveForm({ form, setForm, printers }: { form: PrintingForm; setForm: (form: PrintingForm) => void; printers: PrinterOption[] }) {
  return (
    <div className="grid gap-4">
      <SegmentedControl<PrintingTarget>
        ariaLabel="Move as"
        value={form.target}
        onValueChange={(target) => setForm({ ...form, target })}
        options={[{ value: "spool", label: "Spool" }, { value: "printer", label: "Printer" }]}
        className="w-max"
      />
      {form.target === "spool" ? (
        <>
          <Field label="Printer">
            <Dropdown value={form.printerId} onChange={(e) => setForm({ ...form, printerId: e.target.value })}>
              <option value="">Unassigned printer</option>
              {printers.map((printer) => <option key={printer.id} value={String(printer.id)}>{printer.name}</option>)}
            </Dropdown>
          </Field>
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Material"><Input value={form.material} onChange={(e) => setForm({ ...form, material: e.target.value })} /></Field>
            <Field label="Brand" optional><Input value={form.brand} onChange={(e) => setForm({ ...form, brand: e.target.value })} /></Field>
          </div>
          <Field label="Color" optional><Input value={form.color} onChange={(event) => setForm({ ...form, color: event.target.value })} /></Field>
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Initial weight (g)"><Input type="number" min="0" step="0.01" value={form.initialWeight} onChange={(e) => setForm({ ...form, initialWeight: e.target.value, remainingWeight: form.remainingWeight || e.target.value })} /></Field>
            <Field label="Remaining weight (g)"><Input type="number" min="0" step="0.01" value={form.remainingWeight} onChange={(e) => setForm({ ...form, remainingWeight: e.target.value })} /></Field>
          </div>
        </>
      ) : (
        <>
          <Field label="Printer name"><Input value={form.printerName} onChange={(e) => setForm({ ...form, printerName: e.target.value })} /></Field>
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Model" optional><Input value={form.printerModel} onChange={(e) => setForm({ ...form, printerModel: e.target.value })} /></Field>
            <Field label="Status">
              <Dropdown value={form.printerStatus} onChange={(e) => setForm({ ...form, printerStatus: e.target.value as PrintingForm["printerStatus"] })}>
                <option value="active">Active</option>
                <option value="maintenance">Maintenance</option>
                <option value="offline">Offline</option>
              </Dropdown>
            </Field>
          </div>
        </>
      )}
    </div>
  );
}
