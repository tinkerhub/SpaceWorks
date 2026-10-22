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

export type StaffNavGroup = {
  label: string;
  tabs: string[];
  /** A one-tab group named after its only tab ("Machines") needs no heading over it. */
  showHeading: boolean;
};

/** The sidebar's groups: `TAB_GROUPS` narrowed to the tabs this actor may open, empties dropped. */
export function staffNavGroups(allowedTabs: readonly string[]): StaffNavGroup[] {
  return TAB_GROUPS
    .map((group) => {
      const tabs = group.tabs.filter((tab) => allowedTabs.includes(tab));
      return { label: group.label, tabs, showHeading: !(tabs.length === 1 && staffTabLabel(tabs[0]) === group.label) };
    })
    .filter((group) => group.tabs.length > 0);
}
