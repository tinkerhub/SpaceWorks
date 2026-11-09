import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { staffRequest } = vi.hoisted(() => ({ staffRequest: vi.fn() }));
vi.mock("../../../lib/api", async () => {
  const actual = await vi.importActual<typeof import("../../../lib/api")>("../../../lib/api");
  return { ...actual, staffRequest };
});

import { ToastProvider } from "../../../components/ui";
import { RoleEditor } from "./RoleEditor";
import type { Capability, RoleMachineScope, StaffRole } from "./rolesApi";

const capabilities: Capability[] = [
  { value: "view_inventory", label: "View inventory", group: "Inventory" },
  { value: "manage_machines", label: "Manage machines", group: "Machines" },
  { value: "manage_makerspace", label: "Manage makerspace", group: "Makerspace" },
].map((item) => ({ ...item, description: "", grantable: true, lock_reason: null }));
const role: StaffRole = {
  id: 5, makerspace_id: 7, name: "Inventory team", slug: "inventory-team",
  granted_actions: ["view_inventory"], legacy_role: null, is_default: false,
  is_protected: false, member_count: 2, created_at: "", updated_at: "",
};
const scopePath = "/admin/makerspaces/7/roles/5/machine-scope";
const rolePath = "/admin/makerspaces/7/roles/5";
const roleKey = ["staff", "role-machine-scope", 7, 5];
const personalKey = ["staff", "member-machine-scope", 7, 41];
const coworkerKey = ["staff", "member-machine-scope", 7, 42];
const foreignKey = ["staff", "member-machine-scope", 8, 41];

function scope(overrides: Partial<RoleMachineScope> = {}): RoleMachineScope {
  return {
    machine_type_ids: [], machine_ids: [], scoping_applies: true,
    available_machine_types: [{ id: 11, label: "3D Printer", is_builtin: true }],
    available_machines: [{ id: 21, label: "One laser", is_active: true }],
    ...overrides,
  };
}

function harness(initialRole: StaffRole | null) {
  const client = new QueryClient({ defaultOptions: {
    queries: { retry: false, staleTime: Infinity }, mutations: { retry: false },
  } });
  // Inactive personal editors must become stale too; otherwise reopening People
  // after a capability/scope change would show the previous role's authority.
  for (const key of [personalKey, coworkerKey, foreignKey]) client.setQueryData(key, { cached: true });
  const onSaved = vi.fn();
  function view(value: StaffRole | null) {
    return (
      <QueryClientProvider client={client}>
        <ToastProvider>
          <RoleEditor msId={7} role={value} capabilities={capabilities} actorActions={["manage_makerspace"]}
            isSuperadmin onClose={vi.fn()} onSaved={onSaved} />
        </ToastProvider>
      </QueryClientProvider>
    );
  }
  const rendered = render(view(initialRole));
  return { client, onSaved, reopen: (value: StaffRole) => rendered.rerender(view(value)) };
}

beforeEach(() => {
  staffRequest.mockReset();
});

describe("one machine capability and its scope", () => {
  it.each([
    ["Machine Manager", ["manage_machines"]],
    ["Inventory Manager", ["view_inventory"]],
    ["Space Manager", ["view_inventory", "manage_machines", "manage_makerspace"]],
  ])("uses the unified actions in the %s preset", async (preset, expected) => {
    staffRequest.mockResolvedValue(role);
    const { onSaved } = harness(null);
    expect(screen.getAllByRole("checkbox", { name: /Manage machines/ })).toHaveLength(1);
    expect(screen.queryByRole("checkbox", { name: /Manage printing/ })).toBeNull();
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "New team" } });
    fireEvent.click(screen.getByRole("button", { name: preset as string }));
    fireEvent.click(screen.getByRole("button", { name: "Save role" }));
    await waitFor(() => expect(onSaved).toHaveBeenCalledOnce());
    expect(staffRequest).toHaveBeenCalledWith("/admin/makerspaces/7/roles", {
      method: "POST", body: JSON.stringify({ name: "New team", granted_actions: expected }),
    });
  });

  it("enables machines, saves, then reopens a fresh scope and invalidates personal editors", async () => {
    const savedRole = { ...role, granted_actions: ["view_inventory", "manage_machines"] };
    let currentScope = scope({ scoping_applies: false });
    staffRequest.mockImplementation(async (path: string, init?: RequestInit) => {
      if (path === scopePath) return currentScope;
      if (path === rolePath && init?.method === "PATCH") {
        currentScope = scope();
        return savedRole;
      }
      throw new Error(`Unexpected request: ${path}`);
    });
    const { client, onSaved, reopen } = harness(role);
    await screen.findByText(/Makerspace administrators cover every machine/);
    fireEvent.click(screen.getByRole("checkbox", { name: /Manage machines/ }));
    expect(screen.getByText("Save, then choose machine scope")).toBeInTheDocument();
    expect(screen.getByText(/Personal types can be added under Users/)).toHaveTextContent(/only supplement/);
    expect(screen.queryByRole("checkbox", { name: /3D Printer/ })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Save role" }));
    await waitFor(() => expect(onSaved).toHaveBeenCalledOnce());
    expect(staffRequest).toHaveBeenCalledWith(rolePath, {
      method: "PATCH", body: JSON.stringify({ granted_actions: savedRole.granted_actions }),
    });
    expect(client.getQueryState(roleKey)?.isInvalidated).toBe(true);
    expect(client.getQueryState(personalKey)?.isInvalidated).toBe(true);
    expect(client.getQueryState(coworkerKey)?.isInvalidated).toBe(true);
    expect(client.getQueryState(foreignKey)?.isInvalidated).toBe(false);

    reopen(savedRole);
    expect(await screen.findByRole("checkbox", { name: /3D Printer/ })).not.toBeChecked();
    expect(screen.queryByText("Save, then choose machine scope")).toBeNull();
    expect(screen.getByText(/These selections apply to everyone with this role/)).toBeInTheDocument();
    expect(screen.getByText(/People with this role can still manage any personal types/)).toBeInTheDocument();
  });

  it("saves real type and individual-machine checkboxes and refreshes personal scope", async () => {
    let currentScope = scope();
    staffRequest.mockImplementation(async (path: string, init?: RequestInit) => {
      if (path !== scopePath) throw new Error(`Unexpected request: ${path}`);
      if (init?.method === "PUT") {
        currentScope = scope(JSON.parse(init.body as string));
      }
      return currentScope;
    });
    const { client } = harness({ ...role, granted_actions: ["manage_machines"] });
    const printer = await screen.findByRole("checkbox", { name: /3D Printer/ });
    fireEvent.click(printer);
    fireEvent.click(screen.getByRole("checkbox", { name: /One laser/ }));
    fireEvent.click(screen.getByRole("button", { name: "Save machine scope" }));
    await waitFor(() => expect(client.getQueryState(personalKey)?.isInvalidated).toBe(true));
    expect(staffRequest).toHaveBeenCalledWith(scopePath, {
      method: "PUT", body: JSON.stringify({ machine_type_ids: [11], machine_ids: [21] }),
    });
    expect(client.getQueryState(coworkerKey)?.isInvalidated).toBe(true);
    expect(client.getQueryState(foreignKey)?.isInvalidated).toBe(false);
    await waitFor(() => expect(client.getQueryData<RoleMachineScope>(roleKey)?.machine_type_ids).toEqual([11]));
    expect(screen.getByRole("checkbox", { name: /3D Printer/ })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: /One laser/ })).toBeChecked();
  });
});
