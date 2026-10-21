import type { ReactNode } from "react";
import { AlertTriangle, CheckCircle2, Info, XCircle } from "lucide-react";

import { cn } from "../../lib/cn";

export type CalloutTone = "warning" | "info" | "success" | "danger";

const calloutTones: Record<CalloutTone, { classes: string; icon: ReactNode }> = {
  warning: { classes: "bg-warning-bg text-warning-fg", icon: <AlertTriangle /> },
  info: { classes: "bg-info-bg text-info-fg", icon: <Info /> },
  success: { classes: "bg-success-bg text-success-fg", icon: <CheckCircle2 /> },
  danger: { classes: "bg-danger-bg text-danger-fg", icon: <XCircle /> },
};

type CalloutProps = {
  tone?: CalloutTone;
  /** Bold first sentence. */
  title?: ReactNode;
  children?: ReactNode;
  /** One action, shown on the right. */
  action?: ReactNode;
  role?: "alert" | "status";
  className?: string;
};

/** Tinted banner with an icon and one action. One per page at most. */
export function Callout({ tone = "info", title, children, action, role, className }: CalloutProps) {
  const { classes, icon } = calloutTones[tone];
  return (
    <div role={role} className={cn("flex flex-col gap-3 rounded-lg px-4 py-3.5 sm:flex-row sm:items-center", classes, className)}>
      <span aria-hidden="true" className="hidden shrink-0 sm:inline-flex [&_svg]:size-5">{icon}</span>
      <div className="min-w-0 flex-1 text-body-ui">
        {title ? <p className="font-semibold">{title}</p> : null}
        {children ? <div className={cn(title && "opacity-90")}>{children}</div> : null}
      </div>
      {action ? <div className="flex shrink-0 items-center gap-2">{action}</div> : null}
    </div>
  );
}

type DangerZoneProps = {
  title: ReactNode;
  description?: ReactNode;
  /** Usually a `danger` Button ending in "…" that opens a ConfirmDialog. */
  action?: ReactNode;
  className?: string;
  children?: ReactNode;
};

/** Outlined card for destructive settings, placed at the bottom of a settings page. */
export function DangerZone({ title, description, action, className, children }: DangerZoneProps) {
  return (
    <section className={cn("rounded-lg border-[1.5px] border-danger-border bg-canvas p-5", className)}>
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="min-w-0">
          <h3 className="font-sans text-label text-danger-fg">{title}</h3>
          {description ? <p className="mt-1 text-body-ui text-ink-secondary">{description}</p> : null}
        </div>
        {action ? <div className="shrink-0">{action}</div> : null}
      </div>
      {children}
    </section>
  );
}
