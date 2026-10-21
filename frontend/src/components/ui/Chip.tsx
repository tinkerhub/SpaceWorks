import type { ReactNode } from "react";
import { AlertTriangle, CheckCircle2, Circle, Info, XCircle } from "lucide-react";

import { cn } from "../../lib/cn";

/**
 * Soft status/label tones. Every fill pairs with its own foreground in both themes;
 * `accent`/`secondary` are the brand pastels for distributing a repeating set
 * (categories, machine types) by a STABLE property, never by render order.
 */
export type ChipTone = "neutral" | "success" | "warning" | "danger" | "info" | "accent" | "secondary" | "outline";

export const chipToneClasses: Record<ChipTone, string> = {
  neutral: "bg-fill text-ink-secondary",
  success: "bg-success-bg text-success-fg",
  warning: "bg-warning-bg text-warning-fg",
  danger: "bg-danger-bg text-danger-fg",
  info: "bg-info-bg text-info-fg",
  accent: "bg-accent text-on-accent",
  secondary: "bg-secondary text-on-secondary",
  outline: "border border-line-strong bg-canvas text-ink-secondary",
};

type ChipProps = {
  tone?: ChipTone;
  icon?: ReactNode;
  size?: "sm" | "md";
  className?: string;
  children: ReactNode;
};

/** Pill label, sentence case. One word where possible. */
export function Chip({ tone = "neutral", icon, size = "md", className, children }: ChipProps) {
  return (
    <span
      className={cn(
        "inline-flex min-w-0 max-w-full items-center gap-1 rounded-full font-semibold leading-snug whitespace-nowrap [&_svg]:size-3.5 [&_svg]:shrink-0",
        size === "sm" ? "px-2 py-0.5 text-xs" : "px-2.5 py-0.5 text-[13px]",
        chipToneClasses[tone],
        className,
      )}
    >
      {icon ? <span aria-hidden="true" className="inline-flex">{icon}</span> : null}
      <span className="min-w-0 truncate">{children}</span>
    </span>
  );
}

export type StatusTone = "success" | "warning" | "danger" | "info" | "neutral";

const statusIcons: Record<StatusTone, ReactNode> = {
  success: <CheckCircle2 />,
  warning: <AlertTriangle />,
  danger: <XCircle />,
  info: <Info />,
  neutral: <Circle />,
};

/** Status is never colour alone: a word plus a matching icon on a soft fill. */
export function StatusChip({ tone, children, size = "md", showIcon = true, className }: {
  tone: StatusTone;
  children: ReactNode;
  size?: "sm" | "md";
  showIcon?: boolean;
  className?: string;
}) {
  return (
    <Chip tone={tone} size={size} icon={showIcon ? statusIcons[tone] : undefined} className={className}>
      {children}
    </Chip>
  );
}
