import { useRef } from "react";
import { ArrowLeftRight, Check, ChevronsUpDown, LogOut, UserRound } from "lucide-react";

import { ThemeIcon, useTheme } from "../../../components/ThemeToggle";
import { Avatar, Menu, MenuContent, MenuItem, MenuLabel, MenuSeparator, MenuTrigger } from "../../../components/ui";
import { cn } from "../../../lib/cn";
import type { Makerspace } from "../panels/shared";

export type StaffAccountMenuProps = {
  username: string;
  roleName?: string;
  activeMakerspaceName?: string;
  /** Listed as a switcher only when the actor can move between several. */
  makerspaces: Makerspace[];
  selected: number | null;
  canSwitchMakerspace: boolean;
  canPickMakerspace: boolean;
  collapsed: boolean;
  onOpenAccount: () => void;
  onPickMakerspace: () => void;
  onSelectMakerspace: (id: number) => void;
  onSignOut: () => void;
};

/** The account card at the foot of the sidebar and its menu: account, mode, makerspace, sign out. */
export function StaffAccountMenu({
  username,
  roleName,
  activeMakerspaceName,
  makerspaces,
  selected,
  canSwitchMakerspace,
  canPickMakerspace,
  collapsed,
  onOpenAccount,
  onPickMakerspace,
  onSelectMakerspace,
  onSignOut,
}: StaffAccountMenuProps) {
  const { theme, toggle } = useTheme();
  const triggerRef = useRef<HTMLButtonElement>(null);
  // The account dialog opens only once the menu has closed and handed focus back to this
  // card, so the dialog restores focus here instead of to a menu item that no longer exists.
  const openAccountOnClose = useRef(false);
  const context = [roleName, activeMakerspaceName].filter(Boolean).join(" · ");

  return (
    <Menu>
      <MenuTrigger
        ref={triggerRef}
        aria-label={`${username}, account menu`}
        className={cn(
          "flex min-h-12 w-full items-center gap-2.5 rounded-md border border-line bg-canvas text-left transition-colors duration-180 ease-standard hover:bg-subtle focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus data-[state=open]:bg-subtle",
          collapsed ? "justify-center p-1.5" : "p-2",
        )}
      >
        <Avatar name={username} size="sm" tone="accent" />
        {collapsed ? null : (
          <>
            <span className="min-w-0 flex-1">
              <span className="block truncate text-sm font-semibold text-ink">{username}</span>
              {context ? <span className="line-clamp-2 block text-caption text-ink-muted [overflow-wrap:anywhere]">{context}</span> : null}
            </span>
            <ChevronsUpDown aria-hidden="true" className="size-4 shrink-0 text-ink-muted" />
          </>
        )}
      </MenuTrigger>
      <MenuContent
        side={collapsed ? "right" : "top"}
        align={collapsed ? "end" : "start"}
        className="min-w-[240px]"
        onCloseAutoFocus={(event) => {
          if (!openAccountOnClose.current) return;
          openAccountOnClose.current = false;
          event.preventDefault();
          triggerRef.current?.focus();
          onOpenAccount();
        }}
      >
        <MenuLabel>{username}</MenuLabel>
        <MenuItem icon={<UserRound />} onSelect={() => { openAccountOnClose.current = true; }}>
          Account
        </MenuItem>
        <MenuItem icon={<ThemeIcon theme={theme} />} onSelect={toggle}>
          {theme === "dark" ? "Light mode" : "Dark mode"}
        </MenuItem>
        {canSwitchMakerspace ? (
          <>
            <MenuSeparator />
            <MenuLabel>Makerspace</MenuLabel>
            {makerspaces.map((makerspace) => (
              <MenuItem
                key={makerspace.id}
                icon={<Check className={makerspace.id === selected ? "opacity-100" : "opacity-0"} />}
                aria-current={makerspace.id === selected ? "true" : undefined}
                onSelect={() => onSelectMakerspace(makerspace.id)}
              >
                {makerspace.name}
              </MenuItem>
            ))}
          </>
        ) : null}
        {canPickMakerspace ? (
          <MenuItem icon={<ArrowLeftRight />} onSelect={onPickMakerspace}>
            Switch makerspace
          </MenuItem>
        ) : null}
        <MenuSeparator />
        <MenuItem icon={<LogOut />} onSelect={onSignOut}>
          Sign out
        </MenuItem>
      </MenuContent>
    </Menu>
  );
}
