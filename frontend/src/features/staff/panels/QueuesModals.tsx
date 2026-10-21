import { useEffect, useRef, useState } from "react";

import { ErrorText, Field, Input, Modal, Textarea } from "../../../components/ui";
import { FormFooter, submitForm } from "./QueuesModalShared";
import type { FormModalProps, RejectRequestValues, ReturnDueValues } from "./QueuesModalTypes";

export type {
  AssignIssueValues,
  IssueReject,
  RejectRequestValues,
  ReturnDueValues,
  ReturnRequestValues,
} from "./QueuesModalTypes";
export { AssignIssueModal } from "./QueuesAssignIssueModal";
export { ReturnRequestModal } from "./QueuesReturnRequestModal";

export function ReturnDueModal({
  row,
  open,
  pending,
  error,
  defaultValue,
  onClose,
  onSubmit,
}: FormModalProps<ReturnDueValues> & { defaultValue: string }) {
  const [returnDueAt, setReturnDueAt] = useState(defaultValue);
  // The suggested date is recomputed on every parent render (it is "now + loan days"),
  // so it is read only when the dialog opens. Re-seeding on every new value would wipe
  // what the person typed as soon as the clock ticked over a minute and anything re-rendered.
  const defaultRef = useRef(defaultValue);
  defaultRef.current = defaultValue;

  useEffect(() => {
    if (open) setReturnDueAt(defaultRef.current);
  }, [open, row?.id]);

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={row ? `Set due for request #${row.id}` : "Set due"}
      description="Return reminders and overdue flags use this time."
      footer={<FormFooter formId="return-due-form" pending={pending} submitLabel="Save due date" onCancel={onClose} />}
    >
      <form id="return-due-form" className="grid gap-4" onSubmit={(event) => submitForm(event, () => onSubmit({ returnDueAt }))}>
        <Field label="Return due date and time" helperText="Leave empty to clear the due time.">
          <Input type="datetime-local" value={returnDueAt} disabled={pending} onChange={(event) => setReturnDueAt(event.target.value)} />
        </Field>
        <ErrorText message={error} />
      </form>
    </Modal>
  );
}

export function RejectRequestModal({ row, open, pending, error, onClose, onSubmit }: FormModalProps<RejectRequestValues>) {
  const [reason, setReason] = useState("");
  const [validationError, setValidationError] = useState("");

  useEffect(() => {
    if (open) {
      setReason("");
      setValidationError("");
    }
  }, [open]);

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={row ? `Reject request #${row.id}?` : "Reject request?"}
      description="The requester sees this reason. This can't be undone."
      footer={<FormFooter formId="reject-request-form" pending={pending} submitLabel="Reject request" onCancel={onClose} tone="danger" />}
    >
      <form id="reject-request-form" className="grid gap-4" onSubmit={(event) => submitForm(event, submitReject)}>
        <Field label="Reason" error={validationError || undefined}>
          <Textarea value={reason} disabled={pending} onChange={(event) => { setReason(event.target.value); setValidationError(""); }} />
        </Field>
        <ErrorText message={error} />
      </form>
    </Modal>
  );

  function submitReject() {
    if (!reason.trim()) return setValidationError("Reason is required.");
    setValidationError("");
    onSubmit({ reason: reason.trim() });
  }
}
