import { forwardRef, useId, type ComponentPropsWithoutRef, type ElementRef, type ReactNode } from "react";
import * as RadioGroupPrimitive from "@radix-ui/react-radio-group";

import { cn } from "../../lib/cn";

/** Radio group (arrow keys move, one tab stop). Posts `name` in forms. */
export const RadioGroup = forwardRef<ElementRef<typeof RadioGroupPrimitive.Root>, ComponentPropsWithoutRef<typeof RadioGroupPrimitive.Root>>(
  function RadioGroup({ className, ...props }, ref) {
    return <RadioGroupPrimitive.Root ref={ref} className={cn("flex flex-col gap-2.5", className)} {...props} />;
  },
);

type RadioProps = { value: string; label: ReactNode; description?: ReactNode; id?: string; disabled?: boolean; className?: string };

/** One radio with a label (and optional description) on the right. Use inside RadioGroup. */
export function Radio({ value, label, description, id, disabled, className }: RadioProps) {
  const generatedId = useId();
  const controlId = id ?? generatedId;
  return (
    <div className={cn("flex items-start gap-3", className)}>
      <RadioGroupPrimitive.Item
        id={controlId}
        value={value}
        disabled={disabled}
        aria-describedby={description ? `${controlId}-desc` : undefined}
        className="mt-0.5 inline-flex size-5 shrink-0 items-center justify-center rounded-full border-[1.5px] border-outline bg-canvas hover:border-ink-secondary focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus disabled:cursor-not-allowed disabled:opacity-50 data-[state=checked]:border-accent-ink"
      >
        <RadioGroupPrimitive.Indicator className="block size-2.5 rounded-full bg-accent-ink" />
      </RadioGroupPrimitive.Item>
      <label htmlFor={controlId} className="min-w-0 cursor-pointer select-none text-body-ui text-ink">
        {label}
        {description ? <span id={`${controlId}-desc`} className="block text-caption text-ink-muted">{description}</span> : null}
      </label>
    </div>
  );
}

type OptionCardProps = {
  value: string;
  title: ReactNode;
  description?: ReactNode;
  /** Icon shown in a 32px circle that fills when checked. */
  icon?: ReactNode;
  disabled?: boolean;
  className?: string;
};

/**
 * One choice among a few with consequences (visibility, policy). Use inside RadioGroup.
 * Checked: strong border with a hairline inset and the icon circle fills.
 */
export function OptionCard({ value, title, description, icon, disabled, className }: OptionCardProps) {
  return (
    <RadioGroupPrimitive.Item
      value={value}
      disabled={disabled}
      className={cn(
        "group flex w-full min-w-0 items-start gap-3 rounded-xl border border-line bg-canvas p-4 text-left transition-colors duration-180 ease-standard hover:bg-subtle focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus disabled:cursor-not-allowed disabled:opacity-60 data-[state=checked]:border-accent-ink data-[state=checked]:shadow-[inset_0_0_0_0.5px_rgb(var(--color-accent-ink))]",
        className,
      )}
    >
      {icon ? (
        <span
          aria-hidden="true"
          className="inline-flex size-8 shrink-0 items-center justify-center rounded-full bg-fill text-ink-secondary transition-colors group-data-[state=checked]:bg-primary group-data-[state=checked]:text-on-primary [&_svg]:size-4"
        >
          {icon}
        </span>
      ) : null}
      <span className="min-w-0">
        <span className="block text-label text-ink">{title}</span>
        {description ? <span className="mt-0.5 block text-caption text-ink-muted">{description}</span> : null}
      </span>
    </RadioGroupPrimitive.Item>
  );
}
