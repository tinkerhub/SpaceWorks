import { useEffect, useId, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { ChevronDown } from "lucide-react";

import { Tooltip } from "../../../components/ui";
import { cn } from "../../../lib/cn";
import { staffTabPath } from "../staffTabs";
import { staffNavGroups, staffTabIcon, staffTabLabel, type StaffNavGroup } from "./staffNavItems";
import { useNavGroupsCollapsed } from "./useNavGroupsCollapsed";

export type StaffNavProps = {
  activeMakerspaceSlug?: string;
  activeTab: string;
  allowedTabs: readonly string[];
  collapsed: boolean;
  guestOnly: boolean;
  singleTenantLocked: boolean;
  unreadCount: number;
  onNavigate: (tab: string) => void;
};

/** Shows the label as a tooltip only on the icon rail, where the text is hidden. */
export function RailTip({ collapsed, label, children }: { collapsed: boolean; label: string; children: ReactNode }) {
  return collapsed ? <Tooltip content={label} side="right">{children}</Tooltip> : <>{children}</>;
}

function UnreadBadge({ count, collapsed }: { count: number; collapsed: boolean }) {
  if (count <= 0) return null;
  // The link's accessible name already carries the count, so the badge is visual only.
  return collapsed ? (
    <span aria-hidden="true" className="absolute right-2 top-2 size-2 rounded-full bg-danger" />
  ) : (
    <span aria-hidden="true" className="shrink-0 rounded-full bg-danger-bg px-[7px] text-xs font-bold leading-5 text-danger-fg">
      {count > 99 ? "99+" : count}
    </span>
  );
}

type NavGroupProps = { group: StaffNavGroup; props: StaffNavProps; open: boolean; onToggle: () => void };

function NavGroup({ group, props, open, onToggle }: NavGroupProps) {
  const headingId = useId();
  const listId = useId();
  const { activeMakerspaceSlug, activeTab, collapsed, guestOnly, singleTenantLocked, unreadCount, onNavigate } = props;
  // The icon rail has no headings, so every group stays open there.
  const heading = group.showHeading && !collapsed;
  const expanded = !heading || open;
  return (
    <div role="group" aria-labelledby={heading ? headingId : undefined} aria-label={heading ? undefined : group.label}>
      {heading ? (
        <button
          id={headingId}
          type="button"
          aria-expanded={expanded}
          aria-controls={listId}
          onClick={onToggle}
          className="flex w-full min-h-8 pointer-coarse:min-h-11 items-center justify-between gap-2 rounded-md px-3 pb-1 text-left text-overline text-ink-muted transition-colors duration-180 ease-standard hover:text-ink focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus"
        >
          {group.label}
          <ChevronDown aria-hidden="true" className={cn("size-3.5 shrink-0 transition-transform duration-180 ease-standard motion-reduce:transition-none", !expanded && "-rotate-90")} />
        </button>
      ) : null}
      <ul id={listId} hidden={!expanded} className="flex flex-col gap-0.5">
        {group.tabs.map((tab) => {
          const Icon = staffTabIcon(tab);
          const label = staffTabLabel(tab);
          const active = tab === activeTab;
          const unread = tab === "notifications" ? unreadCount : 0;
          // The visible label leads the accessible name; the unread count is folded in after it.
          const accessibleName = unread > 0 ? `${label}, ${unread} unread` : collapsed ? label : undefined;
          return (
            <li key={tab}>
              <RailTip collapsed={collapsed} label={label}>
                <Link
                  to={staffTabPath(tab, guestOnly, activeMakerspaceSlug, singleTenantLocked)}
                  onClick={() => onNavigate(tab)}
                  aria-current={active ? "page" : undefined}
                  aria-label={accessibleName}
                  className={cn(
                    "relative flex min-h-10 pointer-coarse:min-h-11 items-center gap-2.5 rounded-md border border-transparent text-[15px] text-ink-secondary transition-colors duration-180 ease-standard hover:bg-emphasis hover:text-ink focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus [&_svg]:size-[18px] [&_svg]:shrink-0",
                    collapsed ? "justify-center px-0" : "px-3",
                    active && "border-line bg-canvas font-semibold text-ink shadow-segment hover:bg-canvas",
                  )}
                >
                  <Icon aria-hidden="true" className={active ? "text-accent-ink" : undefined} />
                  {collapsed ? null : <span className="min-w-0 flex-1 truncate">{label}</span>}
                  <UnreadBadge count={unread} collapsed={collapsed} />
                </Link>
              </RailTip>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

/** The staff console's section list: every tab this actor's role and modules allow, grouped. */
export function StaffSidebarNav(props: StaffNavProps) {
  const groups = staffNavGroups(props.allowedTabs);
  const { collapsed: closedGroups, setGroupOpen } = useNavGroupsCollapsed();
  const activeGroup = groups.find((group) => group.tabs.includes(props.activeTab))?.label;
  // Landing on a tab inside a folded group (a link, a refresh) opens that group.
  useEffect(() => {
    if (activeGroup) setGroupOpen(activeGroup, true);
  }, [activeGroup, setGroupOpen]);
  return (
    <nav aria-label="Staff sections" className={cn("flex flex-col", props.collapsed ? "gap-2" : "gap-4")}>
      {groups.map((group, index) => (
        <div key={group.label} className={cn(props.collapsed && index > 0 && "border-t border-line pt-2")}>
          <NavGroup
            group={group}
            props={props}
            open={!closedGroups.has(group.label)}
            onToggle={() => setGroupOpen(group.label, closedGroups.has(group.label))}
          />
        </div>
      ))}
    </nav>
  );
}
