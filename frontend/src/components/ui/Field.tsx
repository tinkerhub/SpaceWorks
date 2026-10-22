import { cloneElement, isValidElement, useId, type ReactElement, type ReactNode } from "react";
import { AlertCircle } from "lucide-react";

import { cn } from "../../lib/cn";

/** Shared look for text inputs, textareas and select triggers (label above, 12px radius). */
export const controlClasses =
  "block min-h-11 w-full min-w-0 rounded-md border border-line-strong bg-canvas px-3.5 py-2.5 text-base leading-snug text-ink placeholder:text-ink-muted transition-colors duration-180 ease-standard hover:border-outline focus:border-focus focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus disabled:cursor-not-allowed disabled:border-line disabled:bg-subtle disabled:text-ink-muted aria-[invalid=true]:border-danger-fg";

/** Read-only text fields read as values, not inputs. Not part of controlClasses: a button is :read-only too. */
export const readOnlyClasses = "read-only:border-line read-only:bg-subtle";

/** Controls Field may wire with `id` / `aria-*` directly. Anything else is wrapped in a <label>. */
const WIRABLE_INTRINSICS = new Set(["input", "select", "textarea"]);

type FieldControlProps = Record<string, unknown> & { id?: string; "aria-describedby"?: string; required?: boolean };

/** Mark a component that forwards `id`, `aria-invalid` and `aria-describedby` to its control. */
export function markFieldControl<T extends object>(component: T): T {
  (component as T & { fieldControl?: boolean }).fieldControl = true;
  return component;
}

function isWirable(node: ReactNode): node is ReactElement<FieldControlProps> {
  if (!isValidElement(node)) return false;
  if (typeof node.type === "string") return WIRABLE_INTRINSICS.has(node.type);
  return Boolean((node.type as { fieldControl?: boolean }).fieldControl);
}

export type FieldProps = {
  label: ReactNode;
  /** Shown under the control in muted text. `hint` is the older name. */
  helperText?: ReactNode;
  hint?: ReactNode;
  error?: ReactNode;
  /** Adds a muted "Optional" after the label. */
  optional?: boolean;
  /** Visually hide the label but keep it for assistive technology. */
  hideLabel?: boolean;
  required?: boolean;
  id?: string;
  className?: string;
  children: ReactNode;
};

/**
 * Label above, control, then helper or error text. A single input/select/textarea (or a
 * primitive marked with `markFieldControl`) gets `id`, `aria-invalid` and
 * `aria-describedby` wired to the text below it. Any other content is wrapped in the
 * label element so it stays labelled.
 */
export function Field({ label, helperText, hint, error, optional, hideLabel, required, id, className, children }: FieldProps) {
  const generatedId = useId();
  const helper = helperText ?? hint;
  const hasError = error !== undefined && error !== null && error !== false && error !== "";
  const labelText = (
    <span className={cn("text-label text-ink", hideLabel && "sr-only")}>
      {label}
      {optional ? <span className="ml-1.5 font-normal text-ink-muted">Optional</span> : null}
    </span>
  );

  if (!isWirable(children)) {
    return (
      <label className={cn("grid min-w-0 grid-cols-[minmax(0,1fr)] content-start gap-1.5", className)}>
        {labelText}
        {children}
        <FieldMessage error={hasError ? error : undefined} helper={helper} />
      </label>
    );
  }

  const controlId = id ?? children.props.id ?? generatedId;
  const messageId = hasError || helper ? `${controlId}-description` : undefined;
  const control = cloneElement(children, {
    id: controlId,
    "aria-invalid": hasError ? true : children.props["aria-invalid"],
    "aria-describedby": [children.props["aria-describedby"], messageId].filter(Boolean).join(" ") || undefined,
    required: required ?? children.props.required,
  });
  return (
    <div className={cn("grid min-w-0 grid-cols-[minmax(0,1fr)] content-start gap-1.5", className)}>
      <label htmlFor={controlId} className="min-w-0">{labelText}</label>
      {control}
      <FieldMessage id={messageId} error={hasError ? error : undefined} helper={helper} />
    </div>
  );
}

function FieldMessage({ id, error, helper }: { id?: string; error?: ReactNode; helper?: ReactNode }) {
  if (error) {
    return (
      <span id={id} className="flex items-start gap-1.5 text-caption text-danger-fg">
        <AlertCircle aria-hidden="true" className="mt-px size-4 shrink-0" />
        <span className="min-w-0">{error}</span>
      </span>
    );
  }
  return helper ? <span id={id} className="text-caption text-ink-muted">{helper}</span> : null;
}
