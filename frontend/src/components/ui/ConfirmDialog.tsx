import { useEffect, useId, useState, type ReactNode } from "react";

import { Button } from "./Button";
import { controlClasses } from "./Field";
import { Modal } from "./Modal";

type ConfirmDialogProps = {
  open: boolean;
  title: ReactNode;
  message?: ReactNode;
  confirmLabel?: string;
  cancelLabel?: string;
  /** `danger` (or `destructive`) styles the confirm button as a destructive action. */
  tone?: "danger" | "default";
  destructive?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
  /** Disables both buttons and shows a spinner on confirm. `loading` is an alias. */
  pending?: boolean;
  loading?: boolean;
  /** Require typing this exact text (e.g. a name) before confirm unlocks. */
  confirmText?: string;
  /** Extra content between the message and the actions (a summary, a checkbox). */
  children?: ReactNode;
};

/**
 * Confirmation for consequential actions. Destructive confirmations use the danger
 * button; pass `confirmText` for type-to-confirm. Escape, the backdrop and Cancel all
 * cancel, except while the action is pending.
 */
export function ConfirmDialog({
  open,
  title,
  message,
  confirmLabel = "Confirm",
  cancelLabel = "Cancel",
  tone = "default",
  destructive,
  onConfirm,
  onCancel,
  pending = false,
  loading = false,
  confirmText,
  children,
}: ConfirmDialogProps) {
  const [typed, setTyped] = useState("");
  const inputId = useId();
  const busy = pending || loading;
  const danger = destructive ?? tone === "danger";
  const locked = Boolean(confirmText) && typed.trim() !== confirmText;

  // A reopened dialog never starts unlocked.
  useEffect(() => {
    if (!open) setTyped("");
  }, [open]);

  const cancel = () => {
    if (!busy) onCancel();
  };

  return (
    <Modal
      open={open}
      onClose={cancel}
      title={title}
      size="sm"
      role="alertdialog"
      hideClose
      footer={(
        <div className="flex flex-col-reverse gap-2.5 sm:flex-row sm:justify-end">
          <Button variant="secondary" disabled={busy} onClick={cancel}>
            {cancelLabel}
          </Button>
          <Button variant={danger ? "danger" : "primary"} loading={busy} disabled={locked} onClick={onConfirm}>
            {confirmLabel}
          </Button>
        </div>
      )}
    >
      <div className="grid gap-3.5">
        {message ? <p className="text-body-ui text-ink-secondary">{message}</p> : null}
        {children}
        {confirmText ? (
          <div className="grid gap-1.5">
            <label htmlFor={inputId} className="text-label text-ink">
              Type <span className="font-mono">{confirmText}</span> to confirm
            </label>
            <input id={inputId} className={controlClasses} value={typed} autoComplete="off" onChange={(event) => setTyped(event.target.value)} />
          </div>
        ) : null}
      </div>
    </Modal>
  );
}
