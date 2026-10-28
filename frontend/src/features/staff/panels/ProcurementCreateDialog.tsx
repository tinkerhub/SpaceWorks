import { Button, Dialog, Dropdown, ErrorText, Field, Input } from "../../../components/ui";
import { errorText } from "./shared";
import { withCurrency } from "../paymentsApi";
import type { Kind } from "./ProcurementPanelRows";
import type { ProcurementMachineTypeOption } from "./ProcurementPanelTypes";

export type ProcurementForm = {
  name: string;
  quantity: string;
  link: string;
  estimated_unit_cost: string;
  vendor_name: string;
  actual_unit_cost: string;
  kind: Kind;
  machine_type: string;
};

export const emptyProcurementForm: ProcurementForm = {
  name: "",
  quantity: "1",
  link: "",
  estimated_unit_cost: "",
  vendor_name: "",
  actual_unit_cost: "",
  kind: "hardware",
  machine_type: "",
};

export function canSubmitProcurement(form: ProcurementForm, requiresMachineType: boolean) {
  return Boolean(form.name.trim()) && (!requiresMachineType || Boolean(form.machine_type));
}

/** "Add item" dialog for the To Buy list. */
export function ProcurementCreateDialog({
  open,
  onClose,
  form,
  setForm,
  canChooseKind,
  requiresMachineType,
  typeOptions,
  typesLoading,
  pending,
  error,
  onSubmit,
  currency,
}: {
  open: boolean;
  onClose: () => void;
  form: ProcurementForm;
  setForm: (form: ProcurementForm) => void;
  canChooseKind: boolean;
  requiresMachineType: boolean;
  typeOptions: ProcurementMachineTypeOption[];
  typesLoading: boolean;
  pending: boolean;
  error: unknown;
  onSubmit: () => void;
  /** Upper-case makerspace currency, or "" when unknown. */
  currency: string;
}) {
  const formId = "procurement-create-form";
  const ready = canSubmitProcurement(form, requiresMachineType);
  const noTypes = requiresMachineType && !typesLoading && !typeOptions.length;

  return (
    <Dialog
      open={open}
      onClose={() => { if (!pending) onClose(); }}
      title="Add to To Buy"
      description="Anything the space needs to buy. Costs are optional and can be filled in later."
      size="lg"
      footer={(
        <div className="flex flex-col-reverse gap-2.5 sm:flex-row sm:justify-end">
          <Button disabled={pending} onClick={onClose}>Cancel</Button>
          <Button variant="primary" type="submit" form={formId} loading={pending} loadingLabel="Adding…" disabled={!ready}>Add item</Button>
        </div>
      )}
    >
      <form
        id={formId}
        className="grid gap-4 sm:grid-cols-2"
        onSubmit={(event) => {
          event.preventDefault();
          if (ready && !pending) onSubmit();
        }}
      >
        <Field label="Item name" className="sm:col-span-2">
          <Input value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })} />
        </Field>
        {canChooseKind ? (
          <Field label="Kind">
            {/* A different stream has different machine types, so a picked type is dropped. */}
            <Dropdown value={form.kind} onChange={(event) => setForm({ ...form, kind: event.target.value as Kind, machine_type: "" })}>
              <option value="hardware">Hardware</option>
              <option value="printing">Printing</option>
            </Dropdown>
          </Field>
        ) : null}
        <Field label="Quantity">
          <Input type="number" min={1} value={form.quantity} onChange={(event) => setForm({ ...form, quantity: event.target.value })} />
        </Field>
        <Field label="Machine type" optional={!requiresMachineType} error={noTypes ? "No machine types are linked to your role." : undefined}>
          <Dropdown value={form.machine_type} required={requiresMachineType} onChange={(event) => setForm({ ...form, machine_type: event.target.value })}>
            <option value="">{requiresMachineType ? "Select a type" : "Unassigned"}</option>
            {typeOptions.map((machineType) => (
              <option key={machineType.id} value={String(machineType.id)}>{machineType.name}</option>
            ))}
          </Dropdown>
        </Field>
        <Field label="Link" optional className="sm:col-span-2">
          <Input inputMode="url" placeholder="https://" value={form.link} onChange={(event) => setForm({ ...form, link: event.target.value })} />
        </Field>
        <Field label={withCurrency("Estimated unit cost", currency)} optional>
          <Input type="number" min={0} step="0.01" inputMode="decimal" value={form.estimated_unit_cost} onChange={(event) => setForm({ ...form, estimated_unit_cost: event.target.value })} />
        </Field>
        <Field label="Vendor" optional>
          <Input value={form.vendor_name} onChange={(event) => setForm({ ...form, vendor_name: event.target.value })} />
        </Field>
        <Field label={withCurrency("Actual unit cost", currency)} optional>
          <Input type="number" min={0} step="0.01" inputMode="decimal" value={form.actual_unit_cost} onChange={(event) => setForm({ ...form, actual_unit_cost: event.target.value })} />
        </Field>
        {error ? <div className="sm:col-span-2"><ErrorText message={errorText(error, "Could not add item.")} /></div> : null}
      </form>
    </Dialog>
  );
}
