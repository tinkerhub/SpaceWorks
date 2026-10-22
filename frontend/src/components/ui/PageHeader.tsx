import type { ReactNode } from "react";

import { cn } from "../../lib/cn";

type PageHeaderProps = {
  /** Optional muted line above the title (greeting, section name). */
  kicker?: ReactNode;
  title: ReactNode;
  /** One line under the title. */
  description?: ReactNode;
  actions?: ReactNode;
  className?: string;
};

/** Page title pattern: kicker, h1, one-line description, actions on the right. */
export function PageHeader({ kicker, title, description, actions, className }: PageHeaderProps) {
  return (
    <div className={cn("flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between", className)}>
      <div className="min-w-0">
        {kicker ? <p className="mb-1.5 text-body-ui text-ink-muted">{kicker}</p> : null}
        <h1 className="text-h1 text-ink [overflow-wrap:anywhere]">{title}</h1>
        {description ? <p className="mt-2 max-w-[640px] text-body-ui text-ink-secondary">{description}</p> : null}
      </div>
      {actions ? <div className="flex shrink-0 flex-wrap items-center gap-2.5">{actions}</div> : null}
    </div>
  );
}

type SectionHeadingProps = {
  title: ReactNode;
  description?: ReactNode;
  action?: ReactNode;
  as?: "h2" | "h3";
  className?: string;
};

/** Section title (h4 scale) with an optional description and action. */
export function SectionHeading({ title, description, action, as: Heading = "h2", className }: SectionHeadingProps) {
  return (
    <div className={cn("flex flex-wrap items-end justify-between gap-3", className)}>
      <div className="min-w-0">
        <Heading className="text-h4 text-ink">{title}</Heading>
        {description ? <p className="mt-1 text-body-ui text-ink-muted">{description}</p> : null}
      </div>
      {action}
    </div>
  );
}

type SettingsRowProps = { title: ReactNode; description?: ReactNode; children: ReactNode; className?: string };

/** Settings row: label column (title + helper) on the left, fields on the right. Stacks below lg:
 * beside the staff sidebar, a 960-1199px window leaves the field column too narrow. */
export function SettingsRow({ title, description, children, className }: SettingsRowProps) {
  return (
    <div className={cn("grid gap-4 border-b border-line py-6 last:border-b-0 lg:grid-cols-[minmax(0,280px)_minmax(0,1fr)] lg:gap-10", className)}>
      <div>
        <h3 className="font-sans text-label text-ink">{title}</h3>
        {description ? <p className="mt-1 text-caption text-ink-muted">{description}</p> : null}
      </div>
      <div className="min-w-0">{children}</div>
    </div>
  );
}
