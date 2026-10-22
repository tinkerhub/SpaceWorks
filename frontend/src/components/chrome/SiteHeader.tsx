import { useState, type ReactNode } from "react";
import { Link, useLocation } from "react-router-dom";
import * as DialogPrimitive from "@radix-ui/react-dialog";
import { Menu as MenuIcon, X } from "lucide-react";

import { cn } from "../../lib/cn";
import { ThemeToggle } from "../ThemeToggle";
import { IconButton, buttonClasses } from "../ui";

export type SiteNavLink = {
  to: string;
  label: string;
  /** Match only the exact path (a site's home), not everything below it. */
  exact?: boolean;
};

export type SiteAction = {
  to: string;
  label: string;
  variant: "primary" | "secondary" | "quiet";
};

type SiteHeaderProps = {
  /** The lockup on the left; it should link home. */
  brand: ReactNode;
  links: SiteNavLink[];
  actions: SiteAction[];
  /** Extra controls beside the theme toggle (e.g. a stats icon link). */
  extra?: ReactNode;
};

const trimSlash = (path: string) => path.replace(/\/+$/, "") || "/";

function isActive(pathname: string, link: SiteNavLink) {
  const current = trimSlash(pathname);
  const path = trimSlash(link.to);
  if (link.exact || path === "/") return current === path;
  return current === path || current.startsWith(`${path}/`);
}

/**
 * Public site header: brand, section links (active = muted pill) and the actions on the
 * right. Below md the links and actions move into a menu sheet.
 */
export function SiteHeader({ brand, links, actions, extra }: SiteHeaderProps) {
  const { pathname } = useLocation();
  const [menuOpen, setMenuOpen] = useState(false);

  return (
    <header className="sticky top-0 z-40 border-b border-line bg-canvas/90 backdrop-blur-md">
      <nav aria-label="Main navigation" className="mx-auto flex min-h-16 max-w-[var(--sw-chrome-max,1200px)] items-center gap-3 px-4 py-2 sm:px-6 md:gap-6">
        <div className="min-w-0 shrink">{brand}</div>
        <ul className="hidden items-center gap-1 md:flex">
          {links.map((link) => (
            <li key={link.to}>
              <Link
                to={link.to}
                aria-current={isActive(pathname, link) ? "page" : undefined}
                className={cn(
                  "inline-flex min-h-9 items-center whitespace-nowrap rounded-full px-3.5 pointer-coarse:min-h-11 text-label text-ink-secondary transition-colors duration-180 ease-standard hover:text-ink focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus",
                  isActive(pathname, link) && "bg-fill font-semibold text-ink",
                )}
              >
                {link.label}
              </Link>
            </li>
          ))}
        </ul>
        <div className="ml-auto flex shrink-0 items-center gap-1.5">
          {extra}
          <ThemeToggle variant="icon" />
          <div className="hidden items-center gap-2 md:flex">
            {actions.map((action) => (
              <Link key={action.to + action.label} to={action.to} className={buttonClasses({ variant: action.variant, size: "sm" })}>
                {action.label}
              </Link>
            ))}
          </div>
          <DialogPrimitive.Root open={menuOpen} onOpenChange={setMenuOpen}>
            <DialogPrimitive.Trigger asChild>
              <IconButton label="Open navigation menu" variant="quiet" className="md:hidden">
                <MenuIcon />
              </IconButton>
            </DialogPrimitive.Trigger>
            <DialogPrimitive.Portal>
              <DialogPrimitive.Overlay className="sw-overlay-in fixed inset-0 z-50 bg-overlay md:hidden" />
              <DialogPrimitive.Content className="sw-dialog-in fixed inset-x-0 top-0 z-50 max-h-dvh overflow-y-auto rounded-b-2xl border-b border-line bg-canvas p-4 shadow-float md:hidden">
                <DialogPrimitive.Title className="sr-only">Navigation</DialogPrimitive.Title>
                <DialogPrimitive.Description className="sr-only">Site sections and sign-in links</DialogPrimitive.Description>
                <div className="mb-3 flex items-center justify-between gap-3">
                  <div className="min-w-0">{brand}</div>
                  <DialogPrimitive.Close asChild>
                    <IconButton label="Close navigation menu" variant="quiet">
                      <X />
                    </IconButton>
                  </DialogPrimitive.Close>
                </div>
                <ul className="flex flex-col">
                  {links.map((link) => (
                    <li key={link.to}>
                      <Link
                        to={link.to}
                        onClick={() => setMenuOpen(false)}
                        aria-current={isActive(pathname, link) ? "page" : undefined}
                        className={cn(
                          "flex min-h-12 items-center rounded-md px-3 text-body font-medium text-ink focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-focus",
                          isActive(pathname, link) && "bg-emphasis font-semibold",
                        )}
                      >
                        {link.label}
                      </Link>
                    </li>
                  ))}
                </ul>
                {actions.length > 0 ? (
                  <div className="mt-3 flex flex-col gap-2 border-t border-line pt-3">
                    {actions.map((action) => (
                      <Link
                        key={action.to + action.label}
                        to={action.to}
                        onClick={() => setMenuOpen(false)}
                        className={buttonClasses({ variant: action.variant === "quiet" ? "secondary" : action.variant, fullWidth: true })}
                      >
                        {action.label}
                      </Link>
                    ))}
                  </div>
                ) : null}
              </DialogPrimitive.Content>
            </DialogPrimitive.Portal>
          </DialogPrimitive.Root>
        </div>
      </nav>
    </header>
  );
}
