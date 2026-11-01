import {
  ArrowLeftRight,
  BadgeCheck,
  Bell,
  Boxes,
  CalendarClock,
  CalendarDays,
  ChartColumn,
  CircleDot,
  ClipboardCheck,
  Container,
  CreditCard,
  Cpu,
  DatabaseBackup,
  Download,
  HandHelping,
  Inbox,
  KeyRound,
  LayoutDashboard,
  LayoutGrid,
  Mail,
  MailCheck,
  NotebookText,
  PackageCheck,
  Puzzle,
  QrCode,
  ScanLine,
  ScrollText,
  Server,
  Settings,
  ShieldCheck,
  ShoppingCart,
  Tags,
  Truck,
  Upload,
  UserCog,
  Users,
  Wrench,
  type LucideIcon,
} from "lucide-react";

import { TAB_GROUPS, TAB_LABELS } from "../staffAccess";

// One icon per staff tab. Labels, groups and permissions stay in `staffAccess.ts` and
// module gating in `staffTabs.ts`; this map only decides what each row looks like.
const TAB_ICONS: Record<string, LucideIcon> = {
  dashboard: LayoutDashboard,
  notifications: Bell,
  requests: Inbox,
  direct: HandHelping,
  handover: PackageCheck,
  payments: CreditCard,
  ledger: NotebookText,
  transfers: ArrowLeftRight,
  stocktake: ClipboardCheck,
  tobuy: ShoppingCart,
  inventory: Boxes,
  categories: Tags,
  needsfix: Wrench,
  containers: Container,
  bulk: Upload,
  qr: QrCode,
  scanner: ScanLine,
  machines: Cpu,
  events: CalendarDays,
  bookings: CalendarClock,
  members: Users,
  reports: ChartColumn,
  accountability: ShieldCheck,
  warranty: BadgeCheck,
  audit: ScrollText,
  users: UserCog,
  settings: Settings,
  emailtemplates: Mail,
  "email-logs": MailCheck,
  api: KeyRound,
  exports: Download,
  backups: DatabaseBackup,
  migration: Truck,
  modules: Puzzle,
  platform: Server,
};

export function staffTabIcon(tab: string): LucideIcon {
  return TAB_ICONS[tab] ?? CircleDot;
}

export function staffTabLabel(tab: string) {
  return TAB_LABELS[tab] ?? tab;
}

/** Equipment and eligible requests links nested under Machines. */
export type StaffNavSubLink = { label: string; subPath: string; queue?: boolean };

export type StaffNavRow = {
  tab: string;
  label: string;
  icon: LucideIcon;
  /** Set only on rows under a tab with sub-links; "" is that tab's index page. */
  subPath?: string;
};

export type StaffNavGroup = {
  label: string;
  tabs: string[];
  rows: StaffNavRow[];
  /** A one-row group named after its only tab ("Events") needs no heading over it. */
  showHeading: boolean;
};

function tabRows(tab: string, machineTypeLinks: readonly StaffNavSubLink[], collapsed: boolean): StaffNavRow[] {
  if (tab !== "machines" || !machineTypeLinks.length) {
    return [{ tab, label: staffTabLabel(tab), icon: staffTabIcon(tab) }];
  }
  return [
    collapsed ? { tab, label: staffTabLabel(tab), icon: staffTabIcon(tab) }
      : { tab, label: "All machine types", icon: LayoutGrid, subPath: "" },
    ...machineTypeLinks.filter((link) => !collapsed || link.queue).map((link) => ({ tab, label: link.label, icon: link.queue ? Inbox : staffTabIcon(tab), subPath: link.subPath })),
  ];
}

/**
 * The sidebar's groups: `TAB_GROUPS` narrowed to the tabs this actor may open, empties
 * dropped. Machines unfolds into one row per type in `machineTypeLinks` when there are any.
 */
export function staffNavGroups(allowedTabs: readonly string[], machineTypeLinks: readonly StaffNavSubLink[] = [], collapsed = false): StaffNavGroup[] {
  return TAB_GROUPS
    .map((group) => {
      const tabs = group.tabs.filter((tab) => allowedTabs.includes(tab));
      const rows = tabs.flatMap((tab) => tabRows(tab, machineTypeLinks, collapsed));
      return { label: group.label, tabs, rows, showHeading: !(rows.length === 1 && rows[0].label === group.label) };
    })
    .filter((group) => group.tabs.length > 0);
}
