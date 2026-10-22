import { Button, ErrorText, type ButtonVariant } from "../../../components/ui";

/** Cancel + the dialog's one action, right-aligned (stacked on phones). */
export function ModalActions({
  pending,
  disabled,
  submitLabel = "Save",
  submitVariant = "primary",
  onClose,
  onSubmit,
}: {
  pending: boolean;
  disabled: boolean;
  submitLabel?: string;
  submitVariant?: ButtonVariant;
  onClose: () => void;
  onSubmit: () => void;
}) {
  return (
    <div className="flex flex-col-reverse gap-2.5 sm:flex-row sm:justify-end">
      <Button variant="secondary" disabled={pending} onClick={onClose}>Cancel</Button>
      <Button variant={submitVariant} disabled={disabled} loading={pending} loadingLabel="Saving…" onClick={onSubmit}>{submitLabel}</Button>
    </div>
  );
}

/** The server's message when it is not already shown next to a field. */
export function GeneralError({ error, errors }: { error: unknown; errors: Record<string, string> }) {
  const message = error instanceof Error ? error.message : "";
  if (!message || Object.keys(errors).length) return null;
  return <ErrorText message={message} />;
}

export function validationErrors(error: unknown): Record<string, string> {
  if (!error || !(error instanceof Error)) return {};
  try {
    const parsed = JSON.parse(error.message) as Record<string, unknown>;
    return flattenErrors(parsed);
  } catch {
    return {};
  }
}

function flattenErrors(value: Record<string, unknown>) {
  return Object.fromEntries(
    Object.entries(value).map(([key, item]) => [
      key,
      Array.isArray(item) ? item.join(" ") : typeof item === "string" ? item : JSON.stringify(item),
    ]),
  );
}
