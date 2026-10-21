import { useState } from "react";

import { Button, ConfirmDialog, Dialog, Dropdown, ErrorText, Field, Input, SectionHeading } from "../../../components/ui";
import { errorText } from "./shared";
import { ProcurementReceipts } from "./ProcurementReceipts";
import {
  draftFromItem,
  isDraftChanged,
  labelStatus,
  statusOptions,
  type RowDraft,
  type ToBuyItem,
  type ToBuyStatus,
} from "./ProcurementPanelRows";

type EditDialogProps = {
  item: ToBuyItem | null;
  savePending: boolean;
  saveError: unknown;
  deletePending: boolean;
  onClose: () => void;
  onSave: (draft: RowDraft) => void;
  onDelete: () => void;
  onMove: () => void;
  onReceiptsChanged: () => void;
};

/** Status, vendor, actual cost and receipts for one To Buy item. */
export function ProcurementEditDialog({ item, ...props }: EditDialogProps) {
  // Keyed by id so the draft starts from the item each time the dialog opens, and a
  // background refetch (after a receipt upload) never wipes unsaved edits.
  return item ? <EditDialogBody key={item.id} item={item} {...props} /> : null;
}

function EditDialogBody({ item, savePending, saveError, deletePending, onClose, onSave, onDelete, onMove, onReceiptsChanged }: EditDialogProps & { item: ToBuyItem }) {
  const [draft, setDraft] = useState<RowDraft>(() => draftFromItem(item));
  const [confirmDelete, setConfirmDelete] = useState(false);
  const movable = item.status === "received" && !item.moved_to_inventory_at;
  const busy = savePending || deletePending;

  return (
    <>
      <Dialog
        open
        onClose={() => { if (!busy) onClose(); }}
        title={item.name}
        description={`${item.kind === "printing" ? "Printing" : "Hardware"} · quantity ${item.quantity}${item.estimated_unit_cost ? ` · estimated ${item.estimated_unit_cost} each` : ""}`}
        size="lg"
        footer={(
          <div className="flex flex-col-reverse gap-2.5 sm:flex-row sm:items-center">
            <Button variant="danger" disabled={busy} onClick={() => setConfirmDelete(true)}>Delete…</Button>
            <div className="flex flex-col-reverse gap-2.5 sm:ml-auto sm:flex-row">
              {movable ? <Button disabled={busy} onClick={onMove}>{item.kind === "printing" ? "Move to printing" : "Move to inventory"}</Button> : null}
              <Button disabled={busy} onClick={onClose}>Cancel</Button>
              <Button variant="primary" loading={savePending} loadingLabel="Saving…" disabled={!isDraftChanged(item, draft)} onClick={() => onSave(draft)}>Save changes</Button>
            </div>
          </div>
        )}
      >
        <div className="grid gap-5">
          <div className="grid gap-4 sm:grid-cols-3">
            <Field label="Status">
              <Dropdown value={draft.status} onChange={(event) => setDraft({ ...draft, status: event.target.value as ToBuyStatus })}>
                {statusOptions.map((status) => <option key={status} value={status}>{labelStatus(status)}</option>)}
              </Dropdown>
            </Field>
            <Field label="Vendor" optional>
              <Input value={draft.vendor_name} onChange={(event) => setDraft({ ...draft, vendor_name: event.target.value })} />
            </Field>
            <Field label="Actual unit cost" optional>
              <Input type="number" min={0} step="0.01" inputMode="decimal" value={draft.actual_unit_cost} onChange={(event) => setDraft({ ...draft, actual_unit_cost: event.target.value })} />
            </Field>
          </div>
          {saveError ? <ErrorText message={errorText(saveError, "Could not update item.")} /> : null}
          <section className="grid gap-3">
            <SectionHeading as="h3" title="Receipts" description="PDF or photos of the invoice." />
            <ProcurementReceipts itemId={item.id} receipts={item.receipts ?? []} onChanged={onReceiptsChanged} />
          </section>
        </div>
      </Dialog>
      <ConfirmDialog
        open={confirmDelete}
        title={`Delete ${item.name}?`}
        message="It comes off the To Buy list. This can't be undone."
        confirmLabel="Delete item"
        tone="danger"
        pending={deletePending}
        onCancel={() => setConfirmDelete(false)}
        onConfirm={onDelete}
      />
    </>
  );
}
