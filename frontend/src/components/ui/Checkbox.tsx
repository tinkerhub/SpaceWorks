import { forwardRef, useId, type ComponentPropsWithoutRef, type ElementRef, type ReactNode } from "react";
import * as CheckboxPrimitive from "@radix-ui/react-checkbox";
import { Check, Minus } from "lucide-react";

import { cn } from "../../lib/cn";

type CheckboxRootProps = ComponentPropsWithoutRef<typeof CheckboxPrimitive.Root>;

/** 20px checkbox; checked and indeterminate fill with the primary colour. Posts `name`/`value` in forms. */
export const Checkbox = forwardRef<ElementRef<typeof CheckboxPrimitive.Root>, CheckboxRootProps>(function Checkbox({ className, ...props }, ref) {
  return (
    <CheckboxPrimitive.Root
      ref={ref}
      className={cn(
        "peer relative inline-flex size-5 shrink-0 items-center pointer-coarse:after:absolute pointer-coarse:after:-inset-3 pointer-coarse:after:content-[''] justify-center rounded-[6px] border-[1.5px] border-outline bg-canvas transition-colors duration-120 ease-standard hover:border-ink-secondary focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus disabled:cursor-not-allowed disabled:opacity-50 data-[state=checked]:border-accent-ink data-[state=checked]:bg-primary data-[state=checked]:text-on-primary data-[state=indeterminate]:border-accent-ink data-[state=indeterminate]:bg-primary data-[state=indeterminate]:text-on-primary",
        className,
      )}
      {...props}
    >
      <CheckboxPrimitive.Indicator className="flex items-center justify-center">
        {props.checked === "indeterminate" ? <Minus aria-hidden="true" className="size-3.5" strokeWidth={3} /> : <Check aria-hidden="true" className="size-3.5" strokeWidth={3} />}
      </CheckboxPrimitive.Indicator>
    </CheckboxPrimitive.Root>
  );
});

type LabelledCheckboxProps = CheckboxRootProps & { label: ReactNode; description?: ReactNode };

/** Checkbox with its label (and optional description) on the right; the whole row is clickable. */
export function CheckboxField({ label, description, className, id, ...props }: LabelledCheckboxProps) {
  const generatedId = useId();
  const controlId = id ?? generatedId;
  return (
    <div className={cn("flex items-start gap-3", className)}>
      <Checkbox id={controlId} aria-describedby={description ? `${controlId}-desc` : undefined} className="mt-0.5" {...props} />
      <label htmlFor={controlId} className="min-w-0 cursor-pointer select-none text-body-ui text-ink">
        {label}
        {description ? <span id={`${controlId}-desc`} className="block text-caption text-ink-muted">{description}</span> : null}
      </label>
    </div>
  );
}

/** Bordered option with a description; selected gets a 1.5px strong border (scopes, audiences). */
export function CheckboxCard({ label, description, className, id, ...props }: LabelledCheckboxProps) {
  const generatedId = useId();
  const controlId = id ?? generatedId;
  return (
    <label
      htmlFor={controlId}
      className={cn(
        "flex cursor-pointer items-start gap-3 rounded-lg border border-line bg-canvas p-4 transition-colors duration-180 ease-standard hover:bg-subtle has-[[data-state=checked]]:border-[1.5px] has-[[data-state=checked]]:border-accent-ink has-[:disabled]:cursor-not-allowed has-[:disabled]:opacity-60",
        className,
      )}
    >
      <Checkbox id={controlId} aria-describedby={description ? `${controlId}-desc` : undefined} className="mt-0.5" {...props} />
      <span className="min-w-0">
        <span className="block text-label text-ink">{label}</span>
        {description ? <span id={`${controlId}-desc`} className="block text-caption text-ink-muted">{description}</span> : null}
      </span>
    </label>
  );
}
