import { render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { assignableRolesFor, isStaffMembership, type StaffMembershipRow, type StaffRole } from "./rolesApi";
import { UsersTable } from "./UsersTable";

function role(id: number, name: string, granted_actions: string[], legacy_role: string | null = null): StaffRole {
  return {
    id, makerspace_id: 1, name, slug: name.toLowerCase().replace(/ /g, "-"), granted_actions, legacy_role,
    is_default: true, is_protected: true, member_count: 1, created_at: "", updated_at: "",
  };
}

const spaceManagerRole = role(1, "Space Manager", ["manage_makerspace", "issue_hardware"], "space_manager");
const inventoryRole = role(2, "Inventory Manager", ["issue_hardware"], "inventory_manager");
const roles = [spaceManagerRole, inventoryRole];

function row(id: number, username: string, assigned: StaffRole | null, legacy = "inventory_manager"): StaffMembershipRow {
  return {
    id,
    user: { id: id + 100, username, email: "", access_status: "restricted" },
    makerspace_id: 1,
    makerspace_slug: "lab",
    role: legacy,
    assigned_role: assigned
      ? { id: assigned.id, name: assigned.name, slug: assigned.slug, legacy_role: assigned.legacy_role, is_default: true, is_protected: true }
      : null,
    created_at: "",
  };
}

const rows = [
  row(1, "me", spaceManagerRole, "space_manager"),
  row(2, "other-manager", spaceManagerRole, "space_manager"),
  row(3, "legacy-manager", null, "space_manager"),
  row(4, "stock-keeper", inventoryRole),
];

function renderTable(isSuperadmin: boolean) {
  const actorActions = ["manage_makerspace", "issue_hardware"];
  render(
    <UsersTable
      rows={rows}
      makerspaceNames={new Map([[1, "Lab"]])}
      loading={false}
      assignableRoles={assignableRolesFor(roles, actorActions, isSuperadmin)}
      roles={roles}
      currentUsername="me"
      isSuperadmin={isSuperadmin}
      onRestrict={vi.fn()}
      onRestore={vi.fn()}
      onResetPassword={vi.fn()}
      onRevoke={vi.fn()}
      onChangeRole={vi.fn()}
    />,
  );
}

// The avatar repeats the name for assistive tech, so take the first match.
const rowFor = (username: string) => screen.getAllByText(username)[0].closest("tr") as HTMLElement;
const actionNames = (username: string) =>
  within(rowFor(username)).queryAllByRole("button").map((button) => button.textContent);

describe("UsersTable action visibility", () => {
  it("hides actions a Space Manager cannot perform", () => {
    renderTable(false);

    expect(actionNames("me")).toEqual([]);
    expect(within(rowFor("me")).getByText("You")).toBeInTheDocument();
    for (const username of ["other-manager", "legacy-manager"]) {
      expect(actionNames(username)).toEqual([]);
      expect(within(rowFor(username)).getByText("Managed by a platform admin")).toBeInTheDocument();
    }
    expect(actionNames("stock-keeper")).toEqual(["Change role", "Reset password", "Revoke…"]);
    expect(screen.queryByRole("button", { name: /^Restrict/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^Restore/ })).not.toBeInTheDocument();
  });

  it("keeps every action for a superadmin on other rows, none on their own", () => {
    renderTable(true);

    expect(actionNames("me")).toEqual([]);
    expect(within(rowFor("me")).getByText("You")).toBeInTheDocument();
    expect(actionNames("other-manager")).toEqual(["Change role", "Restrict…", "Reset password", "Restore", "Revoke…"]);
    expect(actionNames("stock-keeper")).toEqual(["Change role", "Restrict…", "Reset password", "Restore", "Revoke…"]);
  });

  it("offers Restore only on a row whose access is not active", () => {
    rows[3] = { ...rows[3], user: { ...rows[3].user, access_status: "active" } };
    try {
      renderTable(true);
      expect(actionNames("stock-keeper")).toEqual(["Change role", "Restrict…", "Reset password", "Revoke…"]);
      expect(actionNames("other-manager")).toContain("Restore");
    } finally {
      rows[3] = row(4, "stock-keeper", inventoryRole);
    }
  });

  it("shows a role as text, never a select, on every row", () => {
    renderTable(false);

    expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
    expect(within(rowFor("legacy-manager")).getByText("Space Manager")).toBeInTheDocument();
  });
});

describe("assignableRolesFor", () => {
  it("excludes manage_makerspace roles and roles above the actor's ceiling", () => {
    const wide = role(3, "Wide", ["issue_hardware", "manage_printing"]);
    expect(assignableRolesFor([...roles, wide], ["manage_makerspace", "issue_hardware"], false)).toEqual([inventoryRole]);
    expect(assignableRolesFor([...roles, wide], [], true)).toHaveLength(3);
  });
});

describe("isStaffMembership", () => {
  const memberRole = role(5, "Member", []);
  it("keeps roles that grant actions and legacy staff rows, drops grant-less rows", () => {
    expect(isStaffMembership(row(1, "a", inventoryRole), [...roles, memberRole])).toBe(true);
    expect(isStaffMembership(row(2, "b", null, "machine_manager"), roles)).toBe(true);
    expect(isStaffMembership(row(3, "walk-in", memberRole, "custom"), [...roles, memberRole])).toBe(false);
    expect(isStaffMembership(row(4, "c", null, "custom"), roles)).toBe(false);
  });
});
