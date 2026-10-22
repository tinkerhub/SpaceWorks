import type { ReactNode } from "react";

import { cn } from "../../lib/cn";

type EmptyStateProps = {
  title: ReactNode;
  /** One or two sentences, ideally the next step. `children` works too. */
  description?: ReactNode;
  children?: ReactNode;
  /** The next step as a button or link. */
  action?: ReactNode;
  /** A small icon above the title. Defaults to the quiet SpaceWorks mark. */
  icon?: ReactNode;
  /** `error` swaps the mark for the danger tone. */
  tone?: "empty" | "error";
  className?: string;
};

/** Three dots in the brand colours, resting. Decorative. */
function EmptyMark({ tone }: { tone: "empty" | "error" }) {
  const dots = tone === "error" ? ["bg-danger", "bg-danger/60", "bg-danger/30"] : ["bg-accent", "bg-secondary", "bg-line-strong"];
  return (
    <span aria-hidden="true" className="mb-1 inline-flex items-end gap-1.5">
      {dots.map((dot) => (
        <span key={dot} className={cn("block size-2.5 rounded-full", dot)} />
      ))}
    </span>
  );
}

/** Dashed card with a title and the next step. Never leave a list blank. */
export function EmptyState({ title, description, children, action, icon, tone = "empty", className }: EmptyStateProps) {
  return (
    <div
      className={cn(
        "flex min-h-32 flex-col items-center justify-center gap-2 rounded-lg border-[1.5px] border-dashed border-line-strong bg-canvas px-6 py-8 text-center",
        className,
      )}
    >
      {icon ? <span aria-hidden="true" className="text-ink-muted [&_svg]:size-7">{icon}</span> : <EmptyMark tone={tone} />}
      <h3 className="font-sans text-label text-ink">{title}</h3>
      {description ? <p className="max-w-md text-body-ui text-ink-muted">{description}</p> : null}
      {children ? <div className="max-w-md text-body-ui text-ink-muted">{children}</div> : null}
      {action ? <div className="mt-2 flex flex-wrap justify-center gap-2">{action}</div> : null}
    </div>
  );
}
