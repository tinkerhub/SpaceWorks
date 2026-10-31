import { useContext, useState } from "react";

import { Button, ErrorText, Field, Modal, Textarea } from "../../../components/ui";
import { QueueFormEditContext } from "./QueuesModalShared";
import type { FormModalProps } from "./QueuesModalTypes";

export function CancelRequestModal({ row, open, pending, error, onClose, onSubmit }: FormModalProps<{ reason: string }>) {
  const canEdit = useContext(QueueFormEditContext);
  const [reason, setReason] = useState("");
  const [validationError, setValidationError] = useState("");

  function submitCancel() {
    if (pending || !canEdit()) return;
    const clean = reason.trim();
    if (!clean) return setValidationError("Reason is required.");
    if (clean.length > 500) return setValidationError("Reason must be 500 characters or fewer.");
    setValidationError("");
    onSubmit({ reason: clean });
  }

  return (
    <Modal
      open={open}
      onClose={onClose}
      hideClose={pending}
      role="alertdialog"
      size="sm"
      title={row ? `Cancel request #${row.id}?` : "Cancel request?"}
      description="This releases the reserved stock and closes the request without a handover. This can't be undone."
      footer={
        <div className="flex flex-col-reverse gap-2.5 sm:flex-row sm:justify-end">
          <Button variant="secondary" disabled={pending} onClick={onClose}>Go back</Button>
          <Button variant="danger" type="submit" form="cancel-request-form" disabled={pending} loading={pending} loadingLabel="Cancelling…">Cancel request</Button>
        </div>
      }
    >
      <form id="cancel-request-form" className="grid gap-4" onSubmit={(event) => { event.preventDefault(); submitCancel(); }}>
        <Field label="Reason" required helperText="Required. Up to 500 characters. Visible to staff only." error={validationError || undefined}>
          <Textarea value={reason} maxLength={500} disabled={pending} onChange={(event) => {
            if (pending || !canEdit()) return;
            setReason(event.target.value);
            setValidationError("");
          }} />
        </Field>
        <ErrorText message={error} />
      </form>
    </Modal>
  );
}
