import { forwardRef, type ButtonHTMLAttributes, type ReactNode } from "react";
import { Slot } from "@radix-ui/react-slot";

import { cn } from "../../lib/cn";
import { Spinner } from "./Spinner";

export type ButtonVariant = "primary" | "secondary" | "quiet" | "danger" | "danger-quiet" | "inverse" | "success" | "warn";
export type ButtonSize = "sm" | "md" | "lg";

const base =
  "relative inline-flex min-w-0 max-w-full select-none items-center justify-center gap-2 whitespace-nowrap rounded-full font-semibold transition-[background-color,border-color,color,box-shadow,transform] duration-180 ease-standard focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus enabled:active:scale-[0.98] disabled:cursor-not-allowed aria-disabled:pointer-events-none motion-reduce:enabled:active:scale-100";

const variants: Record<ButtonVariant, string> = {
  primary: "bg-primary text-on-primary hover:bg-accent-bright disabled:bg-emphasis disabled:text-ink-muted",
  secondary: "border border-line-strong bg-canvas text-ink hover:bg-subtle disabled:text-ink-muted disabled:hover:bg-canvas",
  quiet: "text-ink-secondary underline-offset-4 hover:text-ink hover:underline disabled:text-ink-disabled disabled:no-underline",
  danger: "border-[1.5px] border-danger-fg bg-canvas text-danger-fg hover:bg-danger-bg disabled:border-line-strong disabled:text-ink-muted disabled:hover:bg-canvas",
  "danger-quiet": "text-danger-fg underline-offset-4 hover:underline disabled:text-ink-disabled disabled:no-underline",
  inverse: "bg-canvas text-ink hover:bg-subtle disabled:bg-emphasis disabled:text-ink-muted",
  success: "bg-success-bg text-success-fg hover:bg-success/45 disabled:bg-emphasis disabled:text-ink-muted",
  warn: "bg-warning-bg text-warning-fg hover:bg-warn/50 disabled:bg-emphasis disabled:text-ink-muted",
};

const sizes: Record<ButtonSize, string> = {
  sm: "min-h-9 px-3.5 py-1.5 text-sm",
  md: "min-h-11 px-[18px] py-2.5 text-[15px]",
  lg: "min-h-[52px] px-6 py-3.5 text-[17px]",
};

const quietSizes: Record<ButtonSize, string> = {
  sm: "min-h-9 px-1.5 text-sm",
  md: "min-h-11 px-2 text-[15px]",
  lg: "min-h-[52px] px-2.5 text-[17px]",
};

export type ButtonClassOptions = { variant?: ButtonVariant; size?: ButtonSize; fullWidth?: boolean; className?: string };

/** Button look for elements that are not a <Button> (e.g. a react-router <Link>). */
export function buttonClasses({ variant = "secondary", size = "md", fullWidth = false, className }: ButtonClassOptions = {}) {
  const quiet = variant === "quiet" || variant === "danger-quiet";
  return cn(base, variants[variant], quiet ? quietSizes[size] : sizes[size], fullWidth && "w-full", className);
}

export type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: ButtonVariant;
  size?: ButtonSize;
  fullWidth?: boolean;
  /** Shows a spinner, disables the button and keeps its width. */
  loading?: boolean;
  /** Label shown while loading, e.g. "Saving…". Defaults to the children. */
  loadingLabel?: ReactNode;
  startIcon?: ReactNode;
  endIcon?: ReactNode;
  /** Render the single child element (e.g. a <Link>) with button styling. */
  asChild?: boolean;
};

/** Pill button. One `primary` per view; destructive actions use `danger` and confirm first. */
export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = "secondary", size = "md", fullWidth, loading = false, loadingLabel, startIcon, endIcon, asChild = false, className, children, disabled, type, ...props },
  ref,
) {
  const classes = buttonClasses({ variant, size, fullWidth, className });
  if (asChild) {
    return (
      <Slot ref={ref} className={classes} {...props}>
        {children}
      </Slot>
    );
  }
  const icon = (node: ReactNode) => (node ? <span aria-hidden="true" className="inline-flex shrink-0 [&>svg]:size-[18px]">{node}</span> : null);
  return (
    <button ref={ref} type={type ?? "button"} className={classes} disabled={disabled || loading} aria-busy={loading || undefined} {...props}>
      {/* The idle label stays in layout (transparent) while loading, so the width holds and,
          without a loadingLabel, it remains the accessible name next to aria-busy. */}
      <span className={loading ? "inline-flex items-center gap-2 opacity-0" : "contents"} aria-hidden={loading && loadingLabel ? true : undefined}>
        {icon(startIcon)}
        {children}
        {icon(endIcon)}
      </span>
      {loading ? (
        <span className="absolute inset-0 inline-flex items-center justify-center gap-2 px-3">
          <Spinner decorative className="size-4" />
          {loadingLabel ? <span className="truncate">{loadingLabel}</span> : null}
        </span>
      ) : null}
    </button>
  );
});
