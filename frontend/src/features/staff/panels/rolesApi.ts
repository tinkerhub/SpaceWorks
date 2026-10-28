import { staffRequest } from "../../../lib/api";

export type StaffRole = {
  id: number;
  makerspace_id: number;
  name: string;
  slug: string;
  granted_actions: string[];
  legacy_role: string | null;
  is_default: boolean;
  is_protected: boolean;
  member_count: number;
  created_at: string;
  updated_at: string;
};

export type Capability = {
  value: string;
  label: string;
  description: string;
  group: string;
  grantable: boolean;
  lock_reason: string | null;
};

export type StaffMembershipRow = {
  id: number;
  user: { id: number; username: string; email: string; access_status: string };
  makerspace_id: number;
  makerspace_slug: string;
  role: string;
  assigned_role: Pick<StaffRole, "id" | "name" | "slug" | "legacy_role" | "is_default" | "is_protected"> | null;
  created_at: string;
};

export function listRoles(msId: number) {
  return staffRequest<StaffRole[]>(`/admin/makerspaces/${msId}/roles`);
}

export function createRole(msId: number, body: Pick<StaffRole, "name" | "granted_actions">) {
  return staffRequest<StaffRole>(`/admin/makerspaces/${msId}/roles`, { method: "POST", body: JSON.stringify(body) });
}

export function updateRole(msId: number, roleId: number, patch: Partial<Pick<StaffRole, "name" | "granted_actions">>) {
  return staffRequest<StaffRole>(`/admin/makerspaces/${msId}/roles/${roleId}`, { method: "PATCH", body: JSON.stringify(patch) });
}

export function deleteRole(msId: number, roleId: number) {
  return staffRequest<void>(`/admin/makerspaces/${msId}/roles/${roleId}`, { method: "DELETE" });
}

export type MachineScopeOption = {
  id: number;
  label: string;
  is_builtin?: boolean;
  is_active?: boolean;
};

export type RoleMachineScope = {
  machine_type_ids: number[];
  machine_ids: number[];
  available_machine_types: MachineScopeOption[];
  available_machines: MachineScopeOption[];
  /** False when the role is exempt (holds manage_makerspace) or grants no machine authority. */
  scoping_applies: boolean;
};

export function getRoleMachineScope(msId: number, roleId: number) {
  return staffRequest<RoleMachineScope>(`/admin/makerspaces/${msId}/roles/${roleId}/machine-scope`);
}

export function setRoleMachineScope(
  msId: number,
  roleId: number,
  body: { machine_type_ids: number[]; machine_ids: number[] },
) {
  return staffRequest<RoleMachineScope>(`/admin/makerspaces/${msId}/roles/${roleId}/machine-scope`, {
    method: "PUT", body: JSON.stringify(body),
  });
}

export type MemberMachineScope = {
  /** The member's personal types, on top of their role's. */
  machine_type_ids: number[];
  role_machine_type_ids: number[];
  available_machine_types: MachineScopeOption[];
  /** False when personal types would change nothing: exempt, or the role lacks Machines. */
  scoping_applies: boolean;
  role_covers_all: boolean;
};

export function getMemberMachineScope(msId: number, membershipId: number) {
  return staffRequest<MemberMachineScope>(`/admin/makerspaces/${msId}/memberships/${membershipId}/machine-scope`);
}

export function setMemberMachineScope(msId: number, membershipId: number, body: { machine_type_ids: number[] }) {
  return staffRequest<MemberMachineScope>(`/admin/makerspaces/${msId}/memberships/${membershipId}/machine-scope`, {
    method: "PUT", body: JSON.stringify(body),
  });
}

/**
 * The capability catalog. Pass the role being edited: the server then keeps listing
 * actions that role already holds even when their module is switched off, so an edit
 * shows (and preserves) every grant instead of silently hiding some.
 */
export function capabilitiesPath(msId: number, roleId?: number | null) {
  const base = `/admin/makerspaces/${msId}/roles/capabilities`;
  return roleId == null ? base : `${base}?role_id=${roleId}`;
}

export function listCapabilities(msId: number, roleId?: number | null) {
  return staffRequest<Capability[]>(capabilitiesPath(msId, roleId));
}

export function listMemberships(msId: number) {
  return staffRequest<StaffMembershipRow[]>(`/admin/makerspaces/${msId}/memberships`);
}

export function createMembership(msId: number, body: {
  username: string; email?: string; first_name?: string; last_name?: string; password?: string; role_id: number;
}) {
  return staffRequest<StaffMembershipRow>(`/admin/makerspaces/${msId}/memberships`, { method: "POST", body: JSON.stringify(body) });
}

export function assignRole(msId: number, membershipId: number, roleId: number) {
  return staffRequest<StaffMembershipRow>(`/admin/makerspaces/${msId}/memberships/${membershipId}/role`, {
    method: "PATCH", body: JSON.stringify({ role_id: roleId }),
  });
}

// Roles an actor may hand out: superadmins assign anything; everyone else only roles that
// stay within their own action ceiling and never grant manage_makerspace. Mirrors the
// backend's role-assignment ceiling so the UI never offers a choice the server refuses.
export function assignableRolesFor<R extends Pick<StaffRole, "granted_actions">>(
  roles: readonly R[],
  actorActions: readonly string[],
  isSuperadmin: boolean,
): R[] {
  if (isSuperadmin) return [...roles];
  const ceiling = new Set(actorActions.filter((action) => action !== "manage_makerspace"));
  return roles.filter(
    (role) => !role.granted_actions.includes("manage_makerspace") && role.granted_actions.every((action) => ceiling.has(action)),
  );
}

// The grants a role can use on this makerspace. The plain capability catalog omits every
// action of a switched-off module, so a grant outside it is inert here (Machine Manager on a
// space without `machines`). An unloaded catalog keeps them all rather than guessing.
export function liveActions(
  role: Pick<StaffRole, "granted_actions">,
  catalog: readonly Pick<Capability, "value">[] | undefined,
): string[] {
  if (!Array.isArray(catalog)) return role.granted_actions;
  const known = new Set(catalog.map((item) => item.value));
  return role.granted_actions.filter((action) => known.has(action));
}

// True when the role holds manage_makerspace. Falls back to the legacy enum when the row has
// no assigned role or the roles list has not loaded it (yet).
export function roleManagesMakerspace(
  roles: readonly Pick<StaffRole, "id" | "granted_actions">[],
  roleId: number | null | undefined,
  legacyRole?: string | null,
): boolean {
  const role = roleId == null ? undefined : roles.find((item) => item.id === roleId);
  return role ? role.granted_actions.includes("manage_makerspace") : legacyRole === "space_manager";
}

// Users lists staff: memberships whose role grants actions. A community member or a walk-in
// borrower record (a role granting nothing) is not staff -- it belongs to the Members tab,
// which exists only with the `membership` module on -- and offering it "Reset password" or
// "Change role" here would be offering what the backend refuses or never meant. A legacy row
// (no assigned role) is staff unless it is `custom`, the enum a grant-less row mirrors. A role
// missing from the list (created since it loaded) is kept rather than hiding a staff member.
export function isStaffMembership(
  row: Pick<StaffMembershipRow, "role" | "assigned_role">,
  roles: readonly Pick<StaffRole, "id" | "granted_actions">[],
): boolean {
  if (!row.assigned_role) return row.role !== "custom";
  const role = roles.find((item) => item.id === row.assigned_role?.id);
  return role ? role.granted_actions.length > 0 : true;
}
