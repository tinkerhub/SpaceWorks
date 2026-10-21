import { Link } from "react-router-dom";
import { ArrowUpRight, PanelLeftClose, PanelLeftOpen } from "lucide-react";

import { SpaceWorksLogo } from "../../../components/SpaceWorksLogo";
import { IconButton } from "../../../components/ui";
import { cn } from "../../../lib/cn";
import { StaffAccountMenu, type StaffAccountMenuProps } from "./StaffAccountMenu";
import { RailTip, StaffSidebarNav, type StaffNavProps } from "./StaffSidebarNav";

export type StaffSidebarProps = {
  nav: Omit<StaffNavProps, "collapsed">;
  account: Omit<StaffAccountMenuProps, "collapsed">;
  publicPath: string | null;
  collapsed?: boolean;
  onToggleCollapsed?: () => void;
};

/** Sidebar contents, shared by the desktop rail and the mobile menu sheet. */
export function StaffSidebar({ nav, account, publicPath, collapsed = false, onToggleCollapsed }: StaffSidebarProps) {
  return (
    <div className={cn("flex min-h-full flex-col gap-5 py-3.5", collapsed ? "px-2.5" : "px-3")}>
      <div className={cn("flex items-center gap-2 pt-1", collapsed ? "flex-col" : "justify-between pl-2")}>
        <Link
          to="/"
          aria-label="Open makerspace listing"
          className="inline-flex min-w-0 items-center rounded-md text-ink focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus"
        >
          <SpaceWorksLogo size={collapsed ? 28 : 24} withWordmark={!collapsed} />
        </Link>
        {onToggleCollapsed ? (
          <IconButton
            label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
            size="sm"
            variant="quiet"
            onClick={onToggleCollapsed}
            aria-expanded={!collapsed}
          >
            {collapsed ? <PanelLeftOpen /> : <PanelLeftClose />}
          </IconButton>
        ) : null}
      </div>

      <StaffSidebarNav {...nav} collapsed={collapsed} />

      <div className="mt-auto flex flex-col gap-2 pt-2">
        {publicPath ? (
          <RailTip collapsed={collapsed} label="Public inventory">
            <Link
              to={publicPath}
              aria-label={collapsed ? "Public inventory" : undefined}
              className={cn(
                "inline-flex min-h-9 items-center gap-1 rounded-md text-sm font-medium text-ink-secondary underline-offset-4 hover:text-ink focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus",
                collapsed ? "justify-center hover:bg-emphasis" : "px-3 hover:underline",
              )}
            >
              {collapsed ? null : "Public inventory"}
              <ArrowUpRight aria-hidden="true" className="size-4" />
            </Link>
          </RailTip>
        ) : null}
        <StaffAccountMenu {...account} collapsed={collapsed} />
      </div>
    </div>
  );
}
