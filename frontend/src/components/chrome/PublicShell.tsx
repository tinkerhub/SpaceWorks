import type { ReactNode } from "react";

import { cn } from "../../lib/cn";
import { SiteFooter } from "../SiteFooter";
import { SkipLink } from "../SkipLink";

/**
 * Public page frame: skip link, the site header passed in, the page's <main> landmark
 * (the skip-link target) and the shared footer. Headers stay outside <main>.
 */
export function PublicShell({ header, children }: { header: ReactNode; children: ReactNode }) {
  return (
    <div className="flex min-h-screen min-w-0 flex-col bg-bg text-ink">
      <SkipLink />
      {header}
      <main id="main-content" tabIndex={-1} className="flex min-w-0 flex-1 flex-col outline-none">
        {children}
      </main>
      <SiteFooter />
    </div>
  );
}

const WIDTHS = {
  sm: "max-w-[640px]",
  md: "max-w-[880px]",
  lg: "max-w-[1200px]",
  xl: "max-w-[1440px]",
} as const;

/** Centred page column with the public gutter (16px phones, 24px from sm). */
export function PublicContainer({ width = "lg", className, children }: {
  width?: keyof typeof WIDTHS;
  className?: string;
  children: ReactNode;
}) {
  return <div className={cn("mx-auto w-full min-w-0 px-4 py-8 sm:px-6 sm:py-10", WIDTHS[width], className)}>{children}</div>;
}
