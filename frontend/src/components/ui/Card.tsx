import type { HTMLAttributes, ReactNode } from "react";

import { cn } from "../../lib/cn";

type CardProps = HTMLAttributes<HTMLElement> & {
  padding?: "none" | "sm" | "md" | "lg";
  as?: "div" | "section" | "article";
};

/** Flat card: canvas fill, 1px line, 16px radius, no shadow. Don't nest more than two. */
export function Card({ children, className, padding = "md", as: Component = "div", ...props }: CardProps) {
  return (
    <Component
      className={cn(
        "min-w-0 rounded-lg border border-line bg-canvas [overflow-wrap:anywhere]",
        padding === "sm" && "p-3",
        padding === "md" && "p-4 sm:p-5",
        padding === "lg" && "p-6 sm:p-8",
        className,
      )}
      {...props}
    >
      {children}
    </Component>
  );
}

type CardHeaderProps = {
  title: ReactNode;
  description?: ReactNode;
  action?: ReactNode;
  titleAs?: "h2" | "h3" | "h4";
  className?: string;
};

/** Card title (+ one-line description) with optional actions on the right. */
export function CardHeader({ title, description, action, titleAs: Title = "h2", className }: CardHeaderProps) {
  return (
    <div className={cn("mb-4 flex flex-wrap items-start justify-between gap-3", className)}>
      <div className="min-w-0">
        <Title className="font-sans text-title text-ink">{title}</Title>
        {description ? <p className="mt-1 max-w-[70ch] text-body-ui text-ink-muted">{description}</p> : null}
      </div>
      {action ? <div className="flex max-w-full shrink-0 flex-wrap items-center gap-2">{action}</div> : null}
    </div>
  );
}
