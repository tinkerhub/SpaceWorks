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
    fireEvent.click(await screen.findByRole("button", { name: "Edit" }));

    const dialog = await screen.findByRole("dialog", { name: "Edit Events crew" });
    const offModule = await within(dialog).findByRole("checkbox", { name: /Manage events/ });
    expect(offModule).toHaveAttribute("aria-checked", "true");
    expect(requestedPaths()).toContain("/admin/makerspaces/7/roles/capabilities?role_id=5");
  });

  it("creates a new role from the plain catalog", async () => {
    renderManager();
    await screen.findByRole("button", { name: "Edit" });
    fireEvent.click(screen.getAllByRole("button", { name: "New role" })[0]);

    const dialog = await screen.findByRole("dialog", { name: "New role" });
    expect(within(dialog).getByRole("checkbox", { name: /View inventory/ })).toBeInTheDocument();
    expect(within(dialog).queryByRole("checkbox", { name: /Manage events/ })).not.toBeInTheDocument();
    expect(requestedPaths().some((path) => path.includes("role_id="))).toBe(false);
  });
});
