import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { staffRequest } = vi.hoisted(() => ({ staffRequest: vi.fn() }));

vi.mock("../../../lib/api", async () => {
  const actual = await vi.importActual<typeof import("../../../lib/api")>("../../../lib/api");
  return { ...actual, staffRequest };
});
vi.mock("./RoleMachineScopeEditor", () => ({ RoleMachineScopeEditor: () => null }));

import { RoleManager } from "./RoleManager";
import { capabilitiesPath, type Capability, type StaffRole } from "./rolesApi";

const capability = (value: string, label: string, group = "Inventory"): Capability => ({
  value, label, description: "", group, grantable: true, lock_reason: null,
});
// The plain catalog omits actions of switched-off modules ...
const plainCatalog = [capability("view_inventory", "View inventory")];
// ... the role-scoped one keeps the off-module action this role already holds.
const roleCatalog = [...plainCatalog, capability("manage_events", "Manage events", "Events")];
const role: StaffRole = {
  id: 5, makerspace_id: 7, name: "Events crew", slug: "events-crew",
  granted_actions: ["view_inventory", "manage_events"], legacy_role: null, is_default: false,
  is_protected: false, member_count: 1, created_at: "", updated_at: "",
};

function renderManager() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <RoleManager msId={7} actorActions={["manage_makerspace"]} isSuperadmin={false} onRolesChanged={vi.fn()} />
    </QueryClientProvider>,
  );
}

const requestedPaths = () => staffRequest.mock.calls.map(([path]) => path as string);

beforeEach(() => {
  staffRequest.mockReset();
  staffRequest.mockImplementation((path: string) => {
    if (path === "/admin/makerspaces/7/roles") return Promise.resolve([role]);
    if (path === "/admin/makerspaces/7/roles/capabilities") return Promise.resolve(plainCatalog);
    if (path === "/admin/makerspaces/7/roles/capabilities?role_id=5") return Promise.resolve(roleCatalog);
    return Promise.resolve({});
  });
});

describe("capabilitiesPath", () => {
  it("adds role_id only for an existing role", () => {
    expect(capabilitiesPath(7)).toBe("/admin/makerspaces/7/roles/capabilities");
    expect(capabilitiesPath(7, null)).toBe("/admin/makerspaces/7/roles/capabilities");
    expect(capabilitiesPath(7, 5)).toBe("/admin/makerspaces/7/roles/capabilities?role_id=5");
  });
});

describe("RoleManager capability catalog", () => {
  it("edits an existing role against its role-scoped catalog, keeping off-module grants visible", async () => {
    renderManager();
    expect(await screen.findByText("Events crew", { exact: true })).toBeVisible();
    const edit = within(screen.getByRole("table")).getByRole("button", { name: "Edit" });
    expect(edit).toHaveRole("button");
    expect(edit).toHaveAccessibleName("Edit");
    expect(edit).toBeVisible();
    fireEvent.click(edit);

    const dialog = await screen.findByRole("dialog", { name: "Edit Events crew" });
    expect(await within(dialog).findByText("Manage events", { exact: true })).toBeVisible();
    const offModule = within(dialog).getByRole("checkbox", { name: /Manage events/ });
    expect(offModule).toBeVisible();
    expect(offModule).toHaveAttribute("aria-checked", "true");
    expect(requestedPaths()).toContain("/admin/makerspaces/7/roles/capabilities?role_id=5");
  });

  it("creates a new role from the plain catalog", async () => {
    renderManager();
    expect(await screen.findByText("Events crew", { exact: true })).toBeVisible();
    fireEvent.click(screen.getAllByRole("button", { name: "New role" })[0]);

    const dialog = await screen.findByRole("dialog", { name: "New role" });
    expect(within(dialog).getByRole("checkbox", { name: /View inventory/ })).toBeInTheDocument();
    expect(within(dialog).queryByRole("checkbox", { name: /Manage events/ })).not.toBeInTheDocument();
    expect(requestedPaths().some((path) => path.includes("role_id="))).toBe(false);
  });
});

describe("RoleManager on a space without some modules", () => {
  const defaults = (overrides: Partial<StaffRole>): StaffRole => ({ ...role, is_default: true, is_protected: true, member_count: 0, ...overrides });
  const machineManager = defaults({ id: 8, name: "Machine Manager", slug: "machine_manager", granted_actions: ["manage_machines"] });
  const member = defaults({ id: 9, name: "Member", slug: "member", granted_actions: [] });

  function renderWith(roles: StaffRole[], membershipOn: boolean) {
    staffRequest.mockImplementation((path: string) => {
      if (path === "/admin/makerspaces/7/roles") return Promise.resolve(roles);
      if (path === "/admin/makerspaces/7/roles/capabilities") return Promise.resolve(plainCatalog);
      return Promise.resolve({});
    });
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <RoleManager msId={7} actorActions={["manage_makerspace"]} isSuperadmin={false} membershipOn={membershipOn} onRolesChanged={vi.fn()} />
      </QueryClientProvider>,
    );
  }

  it("lists only grants the installed modules offer, never a raw action key", async () => {
    renderWith([role], false);
    expect(await screen.findByText("View inventory")).toBeVisible();
    expect(screen.queryByText(/manage_events/)).toBeNull();
  });

  it("hides unused defaults that describe only switched-off modules", async () => {
    renderWith([role, machineManager, member], false);
    expect(await screen.findByText("Events crew")).toBeVisible();
    expect(screen.queryByText("Machine Manager")).toBeNull();
    expect(screen.queryByText("Member")).toBeNull();
  });

  it("keeps such a default while someone still holds it, and Member with membership on", async () => {
    renderWith([{ ...machineManager, member_count: 1 }, member], true);
    expect(await screen.findByText("Machine Manager")).toBeVisible();
    expect(screen.getByText("Member")).toBeVisible();
  });
});
