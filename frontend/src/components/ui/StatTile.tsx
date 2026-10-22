import type { ReactNode } from "react";
import { Link } from "react-router-dom";

import { cn } from "../../lib/cn";

export type ProgressTone = "accent" | "secondary" | "success" | "warning" | "danger";

const fills: Record<ProgressTone, string> = {
  accent: "bg-accent-ink",
  secondary: "bg-secondary",
  success: "bg-success",
  warning: "bg-warn",
  danger: "bg-danger",
};

type ProgressBarProps = { value: number; max: number; tone?: ProgressTone; label?: string; className?: string };

/** Thin rounded bar. Pass `label` so assistive tech knows what is measured. */
export function ProgressBar({ value, max, tone = "accent", label, className }: ProgressBarProps) {
  const percent = max > 0 ? Math.min(100, Math.max(0, (value / max) * 100)) : 0;
  return (
    <div
      role="progressbar"
      aria-label={label}
      aria-valuemin={0}
      aria-valuemax={max}
      aria-valuenow={Math.min(Math.max(value, 0), max)}
      className={cn("h-1.5 w-full overflow-hidden rounded-full bg-emphasis", className)}
    >
      <div className={cn("h-full rounded-full transition-[width] duration-360 ease-standard", fills[tone])} style={{ width: `${percent}%` }} />
    </div>
  );
}

type StatTileProps = {
  label: ReactNode;
  value: ReactNode;
  hint?: ReactNode;
  progress?: { value: number; max: number; tone?: ProgressTone; label?: string };
  /** `attention` tints the tile for a number that needs someone; `danger` colours the number. */
  tone?: "default" | "attention" | "danger";
  /** Makes the whole tile a link. */
  to?: string;
  className?: string;
};

/** Label over a big number, with an optional hint and progress bar. */
export function StatTile({ label, value, hint, progress, tone = "default", to, className }: StatTileProps) {
  const body = (
    <>
      <span className={cn("block text-sm", tone === "attention" ? "text-warning-fg" : "text-ink-muted")}>{label}</span>
      <span
        className={cn(
          "mt-1 block font-display text-[32px] font-extrabold leading-tight tracking-[-0.02em]",
          tone === "attention" ? "text-warning-fg" : tone === "danger" ? "text-danger-fg" : "text-ink",
        )}
      >
        {value}
      </span>
      {hint ? <span className={cn("mt-0.5 block text-caption", tone === "attention" ? "text-warning-fg" : "text-ink-muted")}>{hint}</span> : null}
      {progress ? <ProgressBar className="mt-2.5" value={progress.value} max={progress.max} tone={progress.tone} label={progress.label} /> : null}
    </>
  );
  const classes = cn(
    "block min-w-0 rounded-lg border p-4",
    tone === "attention" ? "border-transparent bg-warning-bg" : "border-line bg-canvas",
    to && "transition-colors hover:bg-subtle focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus",
    className,
  );
  return to ? <Link to={to} className={classes}>{body}</Link> : <div className={classes}>{body}</div>;
}
