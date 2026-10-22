import type { ReactNode } from "react";

import { Button, ErrorText, Field, Input, Modal } from "../../../components/ui";
import type { AdminProduct } from "./inventoryForm";

function DialogActions({ pending, onCancel, confirm }: { pending: boolean; onCancel: () => void; confirm: ReactNode }) {
  return (
    <div className="flex flex-col-reverse gap-2.5 sm:flex-row sm:justify-end">
      <Button disabled={pending} onClick={onCancel}>Cancel</Button>
      {confirm}
    </div>
  );
}

export function ToBuyDialog({ target, quantity, setQuantity, pending, error, onClose, onSubmit }: {
  target: AdminProduct | null; quantity: string; setQuantity: (value: string) => void; pending: boolean; error?: string; onClose: () => void; onSubmit: () => void;
}) {
  const valid = Number(quantity) >= 1;
  return (
    <Modal
      open={Boolean(target)}
      onClose={onClose}
      size="sm"
      title="Add to To Buy"
      description={target ? `${target.name} goes on the procurement list.` : undefined}
      footer={<DialogActions pending={pending} onCancel={onClose} confirm={<Button variant="primary" loading={pending} disabled={!valid} onClick={onSubmit}>Add to To Buy</Button>} />}
    >
      <div className="grid gap-4">
        <Field label="Quantity" helperText="Suggested from the low-stock threshold."><Input type="number" min="1" inputMode="numeric" value={quantity} onChange={(e) => setQuantity(e.target.value)} /></Field>
        <ErrorText message={error} />
      </div>
    </Modal>
  );
}

export function FixShelfDialog({ target, quantity, setQuantity, pending, error, onClose, onSubmit }: {
  target: AdminProduct | null; quantity: string; setQuantity: (value: string) => void; pending: boolean; error?: string; onClose: () => void; onSubmit: () => void;
}) {
  const available = target?.available_quantity ?? 0;
  const amount = Number(quantity);
  const valid = Boolean(target) && Number.isInteger(amount) && amount >= 1 && amount <= available;
  return (
    <Modal
      open={Boolean(target)}
      onClose={onClose}
      size="sm"
      title="Move to fix shelf"
      description={target ? `Take units of ${target.name} out of circulation for repair.` : undefined}
      footer={<DialogActions pending={pending} onCancel={onClose} confirm={<Button variant="primary" loading={pending} disabled={!valid} onClick={onSubmit}>Move to fix shelf</Button>} />}
    >
      <div className="grid gap-4">
        <Field label="Quantity" helperText={`${available} available`} error={quantity && !valid ? `Enter a whole number from 1 to ${available}.` : undefined}>
          <Input type="number" min="1" max={available || 1} inputMode="numeric" value={quantity} onChange={(e) => setQuantity(e.target.value)} />
        </Field>
        <ErrorText message={error} />
      </div>
    </Modal>
  );
}
