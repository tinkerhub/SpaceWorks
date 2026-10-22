import { forwardRef, useId, type ComponentPropsWithoutRef, type ElementRef, type ReactNode } from "react";
import * as SwitchPrimitive from "@radix-ui/react-switch";

import { cn } from "../../lib/cn";

type SwitchRootProps = ComponentPropsWithoutRef<typeof SwitchPrimitive.Root>;

/** On/off switch for settings that apply instantly (role="switch", Space toggles). */
export const Switch = forwardRef<ElementRef<typeof SwitchPrimitive.Root>, SwitchRootProps>(function Switch({ className, ...props }, ref) {
  return (
    <SwitchPrimitive.Root
      ref={ref}
      className={cn(
        "relative inline-flex h-7 w-12 shrink-0 cursor-pointer items-center rounded-full border border-transparent bg-outline/70 transition-colors duration-180 ease-standard focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus disabled:cursor-not-allowed disabled:opacity-50 data-[state=checked]:bg-accent-ink",
        className,
      )}
      {...props}
    >
      <SwitchPrimitive.Thumb className="block size-[22px] translate-x-[2px] rounded-full bg-canvas shadow-segment transition-transform duration-180 ease-standard data-[state=checked]:translate-x-[22px]" />
    </SwitchPrimitive.Root>
  );
});

/** Label + description on the left, switch on the right; the whole row is clickable. */
export function SwitchRow({ label, description, className, id, ...props }: SwitchRootProps & { label: ReactNode; description?: ReactNode }) {
  const generatedId = useId();
  const controlId = id ?? generatedId;
  return (
    <div className={cn("flex items-center justify-between gap-4", className)}>
      <label htmlFor={controlId} className="min-w-0 flex-1 cursor-pointer select-none">
        <span className="block text-label text-ink">{label}</span>
        {description ? <span id={`${controlId}-desc`} className="block text-caption text-ink-muted">{description}</span> : null}
      </label>
      <Switch id={controlId} aria-describedby={description ? `${controlId}-desc` : undefined} {...props} />
    </div>
  );
}
