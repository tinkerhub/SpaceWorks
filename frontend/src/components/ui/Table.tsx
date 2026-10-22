import type { HTMLAttributes, TdHTMLAttributes, ThHTMLAttributes } from "react";

import { cn } from "../../lib/cn";

type TableProps = HTMLAttributes<HTMLTableElement> & {
  /** Names the scroll region; also makes it keyboard-scrollable. */
  label?: string;
  /** Classes for the rounded scroll container. */
  containerClassName?: string;
};

/** Rounded, bordered table that scrolls inside its own box on small screens. */
export function Table({ className, containerClassName, children, label, ...props }: TableProps) {
  return (
    <div
      className={cn("w-full min-w-0 overflow-x-auto rounded-lg border border-line bg-canvas", containerClassName)}
      role={label ? "region" : undefined}
      aria-label={label}
      tabIndex={label ? 0 : undefined}
    >
      <table className={cn("w-full border-collapse text-left text-body-ui", className)} {...props}>
        {children}
      </table>
    </div>
  );
}

export function THead({ className, ...props }: HTMLAttributes<HTMLTableSectionElement>) {
  return <thead className={cn("bg-subtle", className)} {...props} />;
}

export function TBody({ className, ...props }: HTMLAttributes<HTMLTableSectionElement>) {
  return <tbody className={cn("[&>tr:last-child>td]:border-b-0", className)} {...props} />;
}

export function TR({ className, ...props }: HTMLAttributes<HTMLTableRowElement>) {
  return <tr className={cn("transition-colors hover:bg-subtle/60", className)} {...props} />;
}

export function TH({ className, scope = "col", ...props }: ThHTMLAttributes<HTMLTableCellElement>) {
  return <th scope={scope} className={cn("whitespace-nowrap border-b border-line px-4 py-3 text-[13px] font-semibold text-ink-muted", className)} {...props} />;
}

export function TD({ className, ...props }: TdHTMLAttributes<HTMLTableCellElement>) {
  return <td className={cn("border-b border-emphasis px-4 py-3 align-middle text-ink", className)} {...props} />;
}
