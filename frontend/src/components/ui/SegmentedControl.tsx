import { forwardRef, type ButtonHTMLAttributes, type ReactNode } from "react";
import * as ToggleGroupPrimitive from "@radix-ui/react-toggle-group";

import { cn } from "../../lib/cn";

export type SegmentedOption<T extends string> = { value: T; label: ReactNode; icon?: ReactNode; ariaLabel?: string; disabled?: boolean };

type SegmentedControlProps<T extends string> = {
  value: T;
  onValueChange: (value: T) => void;
  options: ReadonlyArray<SegmentedOption<T>>;
  /** Names the group for assistive technology. */
  ariaLabel: string;
  size?: "sm" | "md";
  className?: string;
};

/** Pill track with 2–4 segments for switching views (List / Calendar). One segment is always on. */
export function SegmentedControl<T extends string>({ value, onValueChange, options, ariaLabel, size = "md", className }: SegmentedControlProps<T>) {
  return (
    <ToggleGroupPrimitive.Root
      type="single"
      value={value}
      onValueChange={(next) => next && onValueChange(next as T)}
      aria-label={ariaLabel}
      className={cn("inline-flex max-w-full rounded-full bg-fill p-1", className)}
    >
      {options.map((option) => (
        <ToggleGroupPrimitive.Item
          key={option.value}
          value={option.value}
          disabled={option.disabled}
          aria-label={option.ariaLabel}
          className={cn(
            "inline-flex min-w-0 items-center justify-center gap-1.5 rounded-full font-semibold text-muted transition-[background-color,color,box-shadow] duration-180 ease-standard hover:text-ink focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus disabled:cursor-not-allowed disabled:opacity-50 data-[state=on]:bg-canvas data-[state=on]:text-ink data-[state=on]:shadow-segment [&_svg]:size-4",
            size === "sm" ? "min-h-8 px-3 text-[13px]" : "min-h-9 px-4 text-sm",
          )}
        >
          {option.icon ? <span aria-hidden="true" className="inline-flex">{option.icon}</span> : null}
          {option.label}
        </ToggleGroupPrimitive.Item>
      ))}
    </ToggleGroupPrimitive.Root>
  );
}

type FilterChipProps = ButtonHTMLAttributes<HTMLButtonElement> & { selected: boolean };

/** Toggle chip for filters (aria-pressed). Selected: strong fill. */
export const FilterChip = forwardRef<HTMLButtonElement, FilterChipProps>(function FilterChip({ selected, className, children, type, ...props }, ref) {
  return (
    <button
      ref={ref}
      type={type ?? "button"}
      aria-pressed={selected}
      className={cn(
        "inline-flex min-h-9 items-center gap-1.5 rounded-full border px-3.5 text-sm font-semibold transition-colors duration-180 ease-standard focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus disabled:cursor-not-allowed disabled:opacity-50 [&_svg]:size-4",
        selected ? "border-[1.5px] border-accent-ink bg-primary text-on-primary" : "border-line-strong bg-canvas text-ink-secondary hover:bg-subtle hover:text-ink",
        className,
      )}
      {...props}
    >
      {children}
    </button>
  );
});
