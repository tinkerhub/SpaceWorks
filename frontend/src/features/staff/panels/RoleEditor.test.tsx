import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { staffRequest } = vi.hoisted(() => ({ staffRequest: vi.fn() }));

vi.mock("../../../lib/api", async () => {
  const actual = await vi.importActual<typeof import("../../../lib/api")>("../../../lib/api");
  return { ...actual, staffRequest };
});
vi.mock("./RoleMachineScopeEditor", () => ({ RoleMachineScopeEditor: () => null }));

import { RoleEditor } from "./RoleEditor";
import type { Capability, StaffRole } from "./rolesApi";

const capability = (value: string, label: string, grantable = true): Capability => ({
  value, label, description: "", group: "Inventory", grantable, lock_reason: null,
});
const capabilities = [
  capability("view_inventory", "View inventory"),
  capability("edit_inventory", "Edit inventory"),
  // Held by the role but not grantable by this actor: it must survive an unrelated edit.
  capability("manage_makerspace", "Manage makerspace", false),
];
const role: StaffRole = {
  id: 5, makerspace_id: 7, name: "Front Desk", slug: "front-desk",
  granted_actions: ["view_inventory", "manage_makerspace"], legacy_role: null, is_default: false,
  is_protected: false, member_count: 2, created_at: "", updated_at: "",
};

function renderEditor() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <RoleEditor msId={7} role={role} capabilities={capabilities} actorActions={["manage_makerspace"]} isSuperadmin={false} onClose={vi.fn()} onSaved={vi.fn()} />
    </QueryClientProvider>,
  );
}

function patchBody() {
  const [, init] = staffRequest.mock.calls[0];
  return JSON.parse(init.body as string);
}

beforeEach(() => {
  staffRequest.mockReset();
  staffRequest.mockResolvedValue(role);
});

describe("RoleEditor sends changed fields only", () => {
  it("does not save an untouched role", () => {
    renderEditor();
    expect(screen.getByRole("button", { name: "Save role" })).toBeDisabled();
  });

  it("sends only the name when only the name changed", async () => {
    renderEditor();
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "Front desk team" } });
    fireEvent.click(screen.getByRole("button", { name: "Save role" }));
    await waitFor(() => expect(staffRequest).toHaveBeenCalledTimes(1));
    expect(staffRequest.mock.calls[0][0]).toBe("/admin/makerspaces/7/roles/5");
    expect(patchBody()).toEqual({ name: "Front desk team" });
  });

  it("sends only the actions when only the actions changed, keeping held non-grantable ones", async () => {
    renderEditor();
    fireEvent.click(screen.getByRole("checkbox", { name: /Edit inventory/ }));
    fireEvent.click(screen.getByRole("button", { name: "Save role" }));
    await waitFor(() => expect(staffRequest).toHaveBeenCalledTimes(1));
    const body = patchBody();
    expect(Object.keys(body)).toEqual(["granted_actions"]);
    expect([...body.granted_actions].sort()).toEqual(["edit_inventory", "manage_makerspace", "view_inventory"]);
  });
});
