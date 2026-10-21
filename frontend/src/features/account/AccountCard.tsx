import { useId, type ReactNode } from "react";

import { cn } from "../../lib/cn";

type AccountCardProps = {
  title: ReactNode;
  /** One line under the title. */
  description?: ReactNode;
  /** Actions on the right; they stack under the title on phones. */
  action?: ReactNode;
  tone?: "default" | "danger";
  className?: string;
  children?: ReactNode;
};

/**
 * The one card for account pages: a titled section (h2 + one-line description), optional
 * actions on the right and its body below. One topic per card; never nest them.
 */
export function AccountCard({ title, description, action, tone = "default", className, children }: AccountCardProps) {
  const titleId = useId();
  return (
    <section
      aria-labelledby={titleId}
      className={cn(
        "min-w-0 rounded-2xl border bg-canvas p-5 [overflow-wrap:anywhere] sm:p-6",
        tone === "danger" ? "border-[1.5px] border-danger-border" : "border-line",
        className,
      )}
    >
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <h2 id={titleId} className={cn("text-h4", tone === "danger" ? "text-danger-fg" : "text-ink")}>{title}</h2>
          {description ? <p className="mt-1 text-body-ui text-ink-muted">{description}</p> : null}
        </div>
        {action ? <div className="flex shrink-0 flex-wrap items-center gap-2">{action}</div> : null}
      </div>
      {children ? <div className="mt-5">{children}</div> : null}
    </section>
  );
}
