import type { ReactNode } from "react";

import { SkipLink } from "../SkipLink";
import { SpaceWorksBadge } from "../SpaceWorksLogo";

type AuthLayoutProps = {
  /** Kicker over the title, e.g. "Space Manager desk". */
  kicker?: ReactNode;
  title: ReactNode;
  description?: ReactNode;
  children: ReactNode;
};

// The four tiles of the Space Works mark, enlarged: sky, yellow, green, pink.
const TILES = ["bg-accent", "bg-warn", "bg-success", "bg-secondary"] as const;

/**
 * Sign-in layout: the form on the left, a brand panel in the Space Works colours on the
 * right. Below md the panel drops away and the form is the whole page.
 */
export function AuthLayout({ kicker, title, description, children }: AuthLayoutProps) {
  return (
    <div className="grid min-h-dvh min-w-0 bg-canvas text-ink md:grid-cols-2 2xl:grid-cols-[minmax(0,1fr)_880px]">
      <SkipLink />
      <div className="flex min-w-0 flex-col px-4 py-5 sm:px-8 sm:py-6">
        <header>
          <SpaceWorksBadge />
        </header>
        <main id="main-content" tabIndex={-1} className="flex flex-1 items-center justify-center py-10">
          <div className="flex w-full max-w-[400px] flex-col gap-6">
            <div className="flex flex-col gap-2">
              {kicker ? <p className="text-overline text-accent-ink">{kicker}</p> : null}
              <h1 className="text-h1 text-ink">{title}</h1>
              {description ? <p className="text-body-ui text-ink-secondary">{description}</p> : null}
            </div>
            {children}
          </div>
        </main>
      </div>

      <aside aria-hidden="true" className="relative hidden p-4 md:block">
        <div className="relative flex h-full min-h-[520px] flex-col justify-between overflow-hidden rounded-3xl bg-accent/25 p-12">
          <div aria-hidden="true" className="absolute -right-16 -top-16 size-64 rounded-full bg-secondary/40" />
          <p className="relative max-w-[440px] font-display text-[40px] font-extrabold leading-[1.02] tracking-[-0.03em] text-ink">
            Every tool, every handover,
            <br />
            accounted for.
          </p>
          <div className="relative grid grid-cols-2 gap-3 self-end">
            {TILES.map((tile) => (
              <span key={tile} className={`block size-20 rounded-2xl ${tile}`} />
            ))}
          </div>
        </div>
      </aside>
    </div>
  );
}
