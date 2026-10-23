import { forwardRef, type ButtonHTMLAttributes, type ReactNode } from "react";
import { Link, type LinkProps } from "react-router-dom";

import { cn } from "../../lib/cn";

export type IconButtonVariant = "quiet" | "secondary" | "danger" | "primary";
export type IconButtonSize = "sm" | "md";

type IconControlOptions = { variant?: IconButtonVariant; size?: IconButtonSize; className?: string };

export function iconButtonClasses({ variant = "secondary", size = "md", className }: IconControlOptions = {}) {
  return cn(
    "inline-flex shrink-0 items-center justify-center rounded-full transition-colors duration-180 ease-standard focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus disabled:cursor-not-allowed disabled:text-ink-disabled [&_svg]:size-[18px] [&_svg]:shrink-0",
    size === "sm" ? "size-9 pointer-coarse:size-11" : "size-11",
    variant === "quiet" && "text-ink-secondary hover:bg-emphasis hover:text-ink",
    variant === "secondary" && "border border-line-strong bg-canvas text-ink hover:bg-subtle",
    variant === "danger" && "text-danger-fg hover:bg-danger-bg",
    variant === "primary" && "bg-primary text-on-primary hover:bg-accent-bright",
    className,
  );
}

type IconButtonProps = Omit<ButtonHTMLAttributes<HTMLButtonElement>, "aria-label" | "children" | "title"> &
  Omit<IconControlOptions, "className"> & {
    /** Required: icon-only controls must be named for assistive technology. */
    label: string;
    children: ReactNode;
  };

type IconLinkProps = Omit<LinkProps, "aria-label" | "children" | "title"> &
  Omit<IconControlOptions, "className"> & {
    label: string;
    children: ReactNode;
  };

/** Round icon-only button; `label` becomes its accessible name and tooltip. */
export const IconButton = forwardRef<HTMLButtonElement, IconButtonProps>(function IconButton(
  { children, className, label, variant, size, type, ...props },
  ref,
) {
  return (
    <button
      {...props}
      ref={ref}
      aria-label={label}
      className={iconButtonClasses({ variant, size, className })}
      title={label}
      type={type ?? "button"}
    >
      {children}
    </button>
  );
});

export function IconLink({ children, className, label, variant, size, ...props }: IconLinkProps) {
  return (
    <Link {...props} aria-label={label} className={iconButtonClasses({ variant, size, className })} title={label}>
      {children}
    </Link>
  );
}
