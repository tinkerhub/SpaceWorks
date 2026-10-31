import type { StaffAuthUser } from "../../lib/api";
import type { Makerspace } from "./panels/shared";
import { getStaffAccess } from "./staffAccess";
import { filterTabsByEnabledModules, staffBasePath, staffMakerspaceSlugFromPath, staffTabPath, tabFromStaffPath } from "./staffTabs";

export type StaffSelection =
  | { kind: "loading" | "error" | "picker" | "unavailable" }
  | { kind: "selected"; makerspace: Makerspace };

export function isGlobalStaffAdmin(user: StaffAuthUser) {
  return user.is_superuser || user.role === "superadmin";
}

export function canManagePlatform(user: StaffAuthUser, singleTenantLocked = false) {
  const context = user.staff_context;
  return !singleTenantLocked && !user.must_change_password && isGlobalStaffAdmin(user) && context?.scope_kind === "platform" &&
    context.makerspace_id === null && context.can_manage_platform === true;
}

export function hasOperationalOverride(user: StaffAuthUser, space?: Makerspace) {
  return isGlobalStaffAdmin(user) && space?.superadmin_access_enabled === true;
}

/** A stored id is a hint. A scoped route always wins, even when it has no match. */
export function resolveStaffSelection({
  spaces, loading, error, pathname, guestOnly, lockedId, globalAdmin, hint, explicitId, picker,
}: {
  spaces: Makerspace[];
  loading: boolean;
  error: boolean;
  pathname: string;
  guestOnly: boolean;
  lockedId: number | null;
  globalAdmin: boolean;
  hint: number | null;
  explicitId: number | null;
  picker: boolean;
}): StaffSelection {
  if (error) return { kind: "error" };
  if (loading) return { kind: "loading" };
  if (lockedId !== null) {
    const makerspace = spaces.find((space) => space.id === lockedId);
    return makerspace ? { kind: "selected", makerspace } : { kind: "unavailable" };
  }
  const slug = staffMakerspaceSlugFromPath(pathname, guestOnly);
  if (slug) {
    const makerspace = spaces.find((space) => space.slug === slug);
    return makerspace ? { kind: "selected", makerspace } : { kind: "unavailable" };
  }
  const atBase = pathname.replace(/\/+$/, "") === staffBasePath(guestOnly);
  if (atBase && (globalAdmin || picker)) return { kind: "picker" };
  if (explicitId !== null) {
    const makerspace = spaces.find((space) => space.id === explicitId);
    return makerspace ? { kind: "selected", makerspace } : { kind: "unavailable" };
  }
  const makerspace = spaces.find((space) => space.id === hint) ?? (!globalAdmin ? spaces[0] : undefined);
  return makerspace ? { kind: "selected", makerspace } : { kind: "picker" };
}

/** Carry a tab only when this target grants it; machine type ids never cross spaces. */
export function staffChoicePath(space: Makerspace, user: StaffAuthUser, guestOnly: boolean, pathname: string) {
  const membership = user.makerspaces.find((item) => item.id === space.id);
  const access = getStaffAccess(membership?.actions ?? [], hasOperationalOverride(user, space), false, membership?.is_machine_only);
  const tabs = filterTabsByEnabledModules(access.allowedTabs, space);
  // Global settings are not a target-space preference. Enter the allowed default.
  const routeHint = tabFromStaffPath(pathname, guestOnly);
  const hint = routeHint === "platform" ? "" : routeHint;
  const tab = tabs.includes(hint) ? hint : tabs.includes(access.defaultTab) ? access.defaultTab : tabs[0] ?? "";
  return staffTabPath(tab, guestOnly, guestOnly ? undefined : space.slug);
}
