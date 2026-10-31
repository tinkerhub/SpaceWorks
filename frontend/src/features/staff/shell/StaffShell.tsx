import { useEffect, useLayoutEffect, useRef, useState, type ReactNode } from "react";
import * as DialogPrimitive from "@radix-ui/react-dialog";
import { Menu as MenuIcon, X } from "lucide-react";

import { SkipLink } from "../../../components/SkipLink";
import { SpaceWorksLogo } from "../../../components/SpaceWorksLogo";
import { Button, IconButton } from "../../../components/ui";
import { cn } from "../../../lib/cn";
import { useMediaQuery } from "../../../lib/useMediaQuery";
import type { StaffAuthUser } from "../../../lib/api";
import { AccountDialog } from "../AccountDialog";
import { useUnreadNotifications } from "../useUnreadNotifications";
import { StaffSidebar, type StaffSidebarProps } from "./StaffSidebar";
import { useSidebarCollapsed } from "./useSidebarCollapsed";

export type StaffShellProps = {
  nav: Omit<StaffSidebarProps["nav"], "activeMakerspaceId" | "unreadCount" | "onNavigate">;
  account: Omit<StaffSidebarProps["account"], "onOpenAccount">;
  activeMakerspaceId?: number;
  publicPath: string | null;
  /** Shown in the mobile top bar, where the sidebar is folded away. */
  workspaceName: string;
  user: StaffAuthUser;
  onPasswordChanged: () => void;
  onSelectTab: (tab: string) => void;
  children: ReactNode;
};

/**
 * Staff console chrome: a 224px sidebar that folds to a 68px icon rail on desktop, and a
 * top bar whose menu button opens the same sidebar as a sheet below the md breakpoint.
 */
export function StaffShell({
  nav,
  account,
  activeMakerspaceId,
  publicPath,
  workspaceName,
  user,
  onPasswordChanged,
  onSelectTab,
  children,
}: StaffShellProps) {
  const { collapsed, toggle } = useSidebarCollapsed();
  const [sheetOpen, setSheetOpen] = useState(false);
  const [accountOpen, setAccountOpen] = useState(false);
  const desktop = useMediaQuery("(min-width: 60rem)");
  const desktopRef = useRef(desktop);
  desktopRef.current = desktop;
  const mainRef = useRef<HTMLElement>(null);
  const menuButtonRef = useRef<HTMLButtonElement>(null);
  // Set when "Account" is chosen inside the sheet: the dialog waits until the sheet has
  // closed, because a modal sheet keeps focus and pointer events to itself while it is open.
  const accountAfterSheet = useRef(false);
  const handoffFrame = useRef<number | null>(null);
  const mounted = useRef(false);
  function cancelAccountHandoff() {
    accountAfterSheet.current = false;
    if (handoffFrame.current !== null) cancelAnimationFrame(handoffFrame.current);
    handoffFrame.current = null;
  }
  useLayoutEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; cancelAccountHandoff(); };
  }, []);
  useEffect(() => {
    if (desktop) {
      cancelAccountHandoff();
      setSheetOpen(false);
    }
  }, [desktop]);
  // One request for the whole shell, shared by the rail and the sheet.
  const unreadCount = useUnreadNotifications(
    activeMakerspaceId,
    Boolean(activeMakerspaceId) && nav.allowedTabs.includes("notifications"),
  );

  const sidebar = (inSheet: boolean) => (
    <StaffSidebar
      nav={{
        ...nav,
        activeMakerspaceId,
        unreadCount,
        onNavigate: (tab) => {
          cancelAccountHandoff();
          onSelectTab(tab);
          if (inSheet) setSheetOpen(false);
        },
      }}
      account={{
        ...account,
        onSignOut: () => { cancelAccountHandoff(); account.onSignOut(); },
        onOpenAccount: () => {
          cancelAccountHandoff();
          if (!inSheet) {
            setAccountOpen(true);
            return;
          }
          accountAfterSheet.current = true;
          setSheetOpen(false);
        },
        onPickMakerspace: () => {
          cancelAccountHandoff();
          if (inSheet) setSheetOpen(false);
          account.onPickMakerspace();
        },
        onSelectMakerspace: (id) => {
          cancelAccountHandoff();
          if (inSheet) setSheetOpen(false);
          account.onSelectMakerspace(id);
        },
      }}
      publicPath={publicPath}
      collapsed={inSheet ? false : collapsed}
      onToggleCollapsed={inSheet ? undefined : toggle}
    />
  );

  return (
    <div className="flex min-h-screen min-w-0 flex-col bg-subtle text-ink md:flex-row">
      <SkipLink />
      <aside
        aria-label="Staff console"
        className={cn(
          "sticky top-0 hidden h-dvh shrink-0 overflow-y-auto overflow-x-hidden border-r border-line bg-subtle transition-[width] duration-240 ease-standard motion-reduce:transition-none md:block",
          collapsed ? "w-[68px]" : "w-[224px]",
        )}
      >
        {sidebar(false)}
      </aside>

      <div className="sticky top-0 z-40 flex h-14 items-center gap-3 border-b border-line bg-subtle/95 px-4 backdrop-blur-md md:hidden">
        <SpaceWorksLogo size={26} className="shrink-0 text-ink" />
        <p className="min-w-0 flex-1 truncate font-semibold text-ink">{workspaceName}</p>
        {account.canPickMakerspace ? (
          <Button variant="secondary" size="sm" onClick={() => { cancelAccountHandoff(); account.onPickMakerspace(); }}>Switch makerspace</Button>
        ) : null}
        <DialogPrimitive.Root open={!desktop && sheetOpen} onOpenChange={(open) => { cancelAccountHandoff(); setSheetOpen(open); }}>
          <DialogPrimitive.Trigger asChild>
            <IconButton ref={menuButtonRef} label="Open navigation menu" variant="quiet">
              <MenuIcon />
            </IconButton>
          </DialogPrimitive.Trigger>
          {!desktop ? <DialogPrimitive.Portal>
            <DialogPrimitive.Overlay className="sw-overlay-in fixed inset-0 z-50 bg-overlay md:hidden" />
            <DialogPrimitive.Content
              className="sw-drawer-in fixed inset-y-0 left-0 z-50 w-[min(280px,86vw)] overflow-y-auto border-r border-line bg-subtle shadow-float md:hidden"
              onCloseAutoFocus={(event) => {
                if (!mounted.current) { event.preventDefault(); return; }
                if (desktopRef.current) {
                  cancelAccountHandoff();
                  event.preventDefault();
                  requestAnimationFrame(() => mainRef.current?.focus());
                  return;
                }
                if (!accountAfterSheet.current) return;
                accountAfterSheet.current = false;
                event.preventDefault();
                // Radix's closing focus scopes must finish before the custom modal captures focus.
                handoffFrame.current = requestAnimationFrame(() => {
                  handoffFrame.current = null;
                  if (mounted.current && !desktopRef.current) {
                    menuButtonRef.current?.focus();
                    setAccountOpen(true);
                  }
                });
              }}
            >
              <DialogPrimitive.Title className="sr-only">Navigation</DialogPrimitive.Title>
              <DialogPrimitive.Description className="sr-only">Staff console sections and your account</DialogPrimitive.Description>
              <DialogPrimitive.Close asChild>
                <IconButton label="Close navigation menu" size="sm" variant="quiet" className="absolute right-3 top-3 z-10">
                  <X />
                </IconButton>
              </DialogPrimitive.Close>
              {sidebar(true)}
            </DialogPrimitive.Content>
          </DialogPrimitive.Portal> : null}
        </DialogPrimitive.Root>
      </div>

      <main ref={mainRef} id="main-content" tabIndex={-1} className="min-w-0 flex-1 px-4 py-6 sm:px-6 md:px-10 md:py-8">
        <div className="mx-auto w-full max-w-[1200px]">{children}</div>
      </main>

      <AccountDialog
        open={accountOpen}
        onClose={() => { cancelAccountHandoff(); setAccountOpen(false); }}
        onPasswordChanged={onPasswordChanged}
        onSignOut={() => { cancelAccountHandoff(); account.onSignOut(); }}
        user={user}
      />
    </div>
  );
}
