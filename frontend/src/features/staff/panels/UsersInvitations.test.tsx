import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { StaffAuthUser } from "../../../lib/api";
import type { Makerspace } from "./shared";
import { Users } from "./Users";

const { staffRequest } = vi.hoisted(() => ({ staffRequest: vi.fn() }));
vi.mock("../../../lib/api", async () => {
  const actual = await vi.importActual<typeof import("../../../lib/api")>("../../../lib/api");
  return { ...actual, staffRequest };
});

const roles = [
  { id: 4, makerspace_id: 1, name: "Inventory Manager", slug: "inventory_manager", granted_actions: ["edit_inventory"], legacy_role: "inventory_manager", is_default: true, is_protected: true, member_count: 0, created_at: "", updated_at: "" },
];
const invitations = [
  { id: 40, kind: "invite", state: "invited", invite_email: "ready@x.io", user: { id: 50, username: "ready" }, assigned_role: { id: 4, name: "Inventory Manager" }, created_at: "" },
  { id: 41, kind: "invite", state: "invited", invite_email: "later@x.io", user: null, assigned_role: { id: 4, name: "Inventory Manager" }, created_at: "" },
];

const user: StaffAuthUser = {
  username: "boss", email_verified: false, role: "space_manager", is_superuser: false, must_change_password: false,
  makerspaces: [{
    id: 1, slug: "lab", role: "space_manager", role_id: null, role_name: "Space Manager", role_slug: "space_manager", source: "membership",
    actions: ["manage_makerspace", "edit_inventory"], can_configure_machine_types: true, is_machine_only: false,
    can_refer: false, can_verify: false, verified_at: null, referrals_enabled: false,
  }],
};

function renderUsers(modules: string[]) {
  const space = { id: 1, name: "Lab", slug: "lab", public_code: "LAB1", enabled_modules: modules } as unknown as Makerspace;
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <Users makerspaces={[space]} isSuperadmin={false} currentUser={user} onAuthRefresh={vi.fn()} />
    </QueryClientProvider>,
  );
}

// Radix tabs activate on mouse down.
const openTab = (name: string) => fireEvent.mouseDown(screen.getByRole("tab", { name }), { button: 0 });

describe("Users staff invitations", () => {
  beforeEach(() => {
    staffRequest.mockReset();
    staffRequest.mockImplementation((url: string) => {
      if (url.endsWith("/roles")) return Promise.resolve(roles);
      if (url.endsWith("/memberships")) return Promise.resolve([]);
      if (url.startsWith("/admin/membership-requests?")) return Promise.resolve({ count: 2, next: null, previous: null, results: invitations });
      return Promise.resolve({});
    });
  });

  it("is absent when member accounts are off: nobody could sign in to claim one", async () => {
    renderUsers(["staff_admin"]);
    expect(await screen.findByRole("tab", { name: "People" })).toBeInTheDocument();
    expect(screen.queryByRole("tab", { name: "Invitations" })).not.toBeInTheDocument();
  });

  it("is absent when membership is on: the Members tab owns invitations then", async () => {
    renderUsers(["staff_admin", "membership", "member_accounts"]);
    expect(await screen.findByRole("tab", { name: "People" })).toBeInTheDocument();
    expect(screen.queryByRole("tab", { name: "Invitations" })).not.toBeInTheDocument();
  });

  it("lists open staff invitations and approves one with the role it was sent with", async () => {
    renderUsers(["staff_admin", "member_accounts"]);
    await screen.findByRole("tab", { name: "Invitations" });
    openTab("Invitations");

    expect(await screen.findByText("Ready to approve")).toBeInTheDocument();
    expect(screen.getByText("Waiting for them to sign in")).toBeInTheDocument();
    const approve = screen.getAllByRole("button", { name: "Approve" });
    expect(approve).toHaveLength(1);
    fireEvent.click(approve[0]);
    await waitFor(() => expect(staffRequest).toHaveBeenCalledWith(
      "/admin/membership-requests/40/approve",
      { method: "POST", body: JSON.stringify({ role_id: 4 }) },
    ));
    expect(staffRequest).toHaveBeenCalledWith("/admin/membership-requests?makerspace_id=1&state=invited");
  });
});

describe("Users people list", () => {
  it("lists staff only: a walk-in or community member (a role granting nothing) is not staff", async () => {
    const memberRole = { ...roles[0], id: 9, name: "Member", slug: "member", granted_actions: [], legacy_role: null };
    const membership = (id: number, username: string, assigned: { id: number; name: string } | null, legacy: string) => ({
      id, user: { id: id + 100, username, email: "", access_status: "active" }, makerspace_id: 1, makerspace_slug: "lab", role: legacy,
      assigned_role: assigned ? { ...assigned, slug: "", legacy_role: null, is_default: true, is_protected: true } : null, created_at: "",
    });
    staffRequest.mockImplementation((url: string) => {
      if (url.endsWith("/roles")) return Promise.resolve([...roles, memberRole]);
      if (url.endsWith("/memberships")) return Promise.resolve([
        membership(1, "keeper", { id: 4, name: "Inventory Manager" }, "inventory_manager"),
        membership(2, "walkin_ravi", { id: 9, name: "Member" }, "custom"),
      ]);
      return Promise.resolve({});
    });
    renderUsers(["staff_admin"]);

    expect(await screen.findAllByText("keeper")).not.toHaveLength(0);
    await waitFor(() => expect(screen.queryByText("walkin_ravi")).not.toBeInTheDocument());
  });
});
