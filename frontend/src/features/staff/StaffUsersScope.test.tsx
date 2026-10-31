import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { getSessionGeneration } from "../../lib/api";
import {
  alpha, chooseRole, createdSpace, demo, fillStaff, managerUser, openAddStaff,
  renderUsersScope, rolesFor, spaces, superadminUser, usersScopeTransport,
} from "../../test/staffUsersScopeHarness";
import { staffMakerspacesKey } from "./useStaffMakerspaces";

const { staffRequest } = vi.hoisted(() => ({
  staffRequest: vi.fn<(path: string, options?: RequestInit) => Promise<unknown>>(),
}));
vi.mock("../../lib/api", async () => {
  const actual = await vi.importActual<typeof import("../../lib/api")>("../../lib/api");
  return { ...actual, staffRequest };
});

function expectTenantReads(id: number) {
  for (const suffix of ["memberships", "roles", "roles/capabilities"]) {
    expect(staffRequest).toHaveBeenCalledWith(`/admin/makerspaces/${id}/${suffix}`);
  }
}
function expectNoTenantRequests(id: number) {
  expect(staffRequest.mock.calls.some(([path]) => path.startsWith(`/admin/makerspaces/${id}/`))).toBe(false);
}
const writes = () => staffRequest.mock.calls.filter(([, options]) => options?.method && options.method !== "GET");
const openTab = (name: string) => fireEvent.mouseDown(screen.getByRole("tab", { name }), { button: 0 });

describe("Users follows the StaffTabContent active makerspace", () => {
  beforeEach(() => { staffRequest.mockReset().mockImplementation(usersScopeTransport); });

  it("reads Demo staff, roles and capabilities despite Alpha being first, with no second makerspace chooser", async () => {
    renderUsersScope();
    const staff = await screen.findByRole("region", { name: "Staff" });
    expect(await within(staff).findByRole("row", { name: /demo_keeper/ })).toBeInTheDocument();
    expect(within(staff).getByRole("row", { name: /demo_auditor/ })).toBeInTheDocument();
    expect(within(staff).getAllByText("Demo")).toHaveLength(2);
    expect(screen.queryByText("alpha_keeper")).not.toBeInTheDocument();
    expect(screen.queryByRole("combobox", { name: "Makerspace" })).not.toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole("button", { name: "Add staff" })).toBeEnabled());

    openTab("Roles");
    const roles = await screen.findByRole("tabpanel", { name: "Roles" });
    expect(await within(roles).findByText("Demo Inventory")).toBeInTheDocument();
    expect(within(roles).getByText("Demo Auditor")).toBeInTheDocument();
    expect(await within(roles).findByText("Edit inventory")).toBeInTheDocument();
    expect(within(roles).getByText("View audit log")).toBeInTheDocument();
    expect(within(roles).queryByText("Alpha Inventory")).not.toBeInTheDocument();
    expectTenantReads(7);
    expect(staffRequest.mock.calls.every(([path]) => path.startsWith("/admin/makerspaces/7/"))).toBe(true);
    expectNoTenantRequests(1);
  });

  it("adds staff to Demo through the real modal and refreshes the actor's authority", async () => {
    const { onAuthRefresh } = renderUsersScope();
    const dialog = await openAddStaff();
    const fields = within(dialog);
    expect(fields.getByLabelText("Makerspace")).toHaveValue("Demo");
    expect(fields.getByLabelText("Makerspace")).toHaveAttribute("readonly");
    expect(dialog).toHaveAccessibleDescription("They'll join Demo with the role you pick.");
    fillStaff(dialog);
    await chooseRole(fields.getByRole("combobox", { name: "Role" }), "Demo Inventory");
    fireEvent.click(fields.getByRole("button", { name: "Add staff" }));

    await screen.findByText("Staff member added");
    expect(writes()).toHaveLength(1);
    const [path, options] = writes()[0];
    expect(path).toBe("/admin/makerspaces/7/memberships");
    expect(options?.method).toBe("POST");
    expect(JSON.parse(String(options?.body))).toEqual({
      username: "demo.new", email: "demo.new@example.org", first_name: "New", last_name: "Keeper",
      password: " secret-Demo-42! ", role_id: rolesFor(demo)[0].id,
    });
    expect(onAuthRefresh).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("dialog", { name: "Add staff" })).not.toBeInTheDocument();
    expectNoTenantRequests(1);
  });

  it("remounts Users on an active-space change, clearing drafts, filters and descendant role targets", async () => {
    const view = renderUsersScope();
    await screen.findByRole("row", { name: /demo_keeper/ });
    await chooseRole(screen.getByRole("combobox", { name: "Role" }), "Demo Inventory");
    expect(screen.queryByText("demo_auditor")).not.toBeInTheDocument();
    const draft = await openAddStaff();
    fillStaff(draft);
    await chooseRole(within(draft).getByRole("combobox", { name: "Role" }), "Demo Auditor");

    // Same unkeyed StaffTabContent and exact same all-makerspaces array; only active changes.
    view.rerenderScope({ activeMakerspace: alpha });
    expect(await screen.findByRole("row", { name: /alpha_keeper/ })).toBeInTheDocument();
    expect(screen.getByRole("row", { name: /alpha_auditor/ })).toBeInTheDocument();
    expect(screen.queryByText("demo_keeper")).not.toBeInTheDocument();
    expect(screen.queryByText("demo_auditor")).not.toBeInTheDocument();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "Role" })).toHaveTextContent("All roles");
    expectTenantReads(1);

    const fresh = await openAddStaff();
    const fields = within(fresh);
    expect(fields.getByLabelText("Makerspace")).toHaveValue("Alpha");
    for (const label of [/^Username$/, /^Email/, /^First name/, /^Last name/, /^Password$/]) {
      expect(fields.getByLabelText(label)).toHaveValue("");
    }
    expect(fields.getByRole("combobox", { name: "Role" })).toHaveTextContent("Select a role");
    await chooseRole(fields.getByRole("combobox", { name: "Role" }), "Alpha Inventory");
    expect(fields.queryByText("Demo Auditor")).not.toBeInTheDocument();
    fireEvent.click(fields.getByRole("button", { name: "Cancel" }));

    const alphaRow = screen.getByRole("row", { name: /alpha_keeper/ });
    fireEvent.click(within(alphaRow).getByRole("button", { name: "Change role" }));
    const roleDialog = await screen.findByRole("dialog", { name: "Change role for alpha_keeper" });
    await chooseRole(within(roleDialog).getByRole("combobox", { name: "Role" }), "Alpha Auditor");
    view.rerenderScope({ activeMakerspace: demo });
    expect(await screen.findByRole("row", { name: /demo_keeper/ })).toBeInTheDocument();
    expect(screen.getByRole("row", { name: /demo_auditor/ })).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.queryByText("alpha_keeper")).not.toBeInTheDocument();
    const demoRow = screen.getByRole("row", { name: /demo_keeper/ });
    fireEvent.click(within(demoRow).getByRole("button", { name: "Change role" }));
    const newRoleDialog = await screen.findByRole("dialog", { name: "Change role for demo_keeper" });
    expect(within(newRoleDialog).getByRole("combobox", { name: "Role" })).toHaveTextContent("Demo Inventory");
    expect(writes()).toHaveLength(0);
  });

  it("creates a global makerspace without switching Demo, invalidates list generations, and hides creation from managers", async () => {
    const view = renderUsersScope({ isSuperadmin: true, currentUser: superadminUser });
    await screen.findByRole("row", { name: /demo_keeper/ });
    const prefix = ["staff", "makerspaces"];
    const sessionKey = staffMakerspacesKey(getSessionGeneration());
    view.client.setQueryData(prefix, spaces);
    view.client.setQueryData(sessionKey, spaces);
    view.client.setQueryData(["staff", "unrelated"], "unchanged");
    expect(view.client.getQueryState(sessionKey)?.isInvalidated).toBe(false);
    fireEvent.click(screen.getByRole("button", { name: "Create makerspace" }));
    const dialog = await screen.findByRole("dialog", { name: "Create makerspace" });
    const fields = within(dialog);
    for (const [label, value] of [
      [/^Name$/, " Workshop "], [/^Public code$/, "work"], [/^Slug$/, " workshop "], [/^Location/, " Kochi "],
    ] as const) fireEvent.change(fields.getByLabelText(label), { target: { value } });
    fireEvent.click(fields.getByRole("checkbox", { name: /^Superadmin can access this makerspace/ }));
    fireEvent.click(fields.getByRole("button", { name: "Create makerspace" }));

    await screen.findByText("Makerspace created");
    expect(writes()).toHaveLength(1);
    const [path, options] = writes()[0];
    expect(path).toBe("/admin/makerspaces");
    expect(options?.method).toBe("POST");
    expect(JSON.parse(String(options?.body))).toEqual({
      name: "Workshop", public_code: "WORK", slug: "workshop", location: "Kochi", superadmin_access_enabled: false,
    });
    expect(view.client.getQueryState(prefix)?.isInvalidated).toBe(true);
    expect(view.client.getQueryState(sessionKey)?.isInvalidated).toBe(true);
    expect(view.client.getQueryState(["staff", "unrelated"])?.isInvalidated).toBe(false);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.getByRole("row", { name: /demo_keeper/ })).toBeInTheDocument();
    const add = await openAddStaff();
    expect(within(add).getByLabelText("Makerspace")).toHaveValue("Demo");
    fireEvent.click(within(add).getByRole("button", { name: "Cancel" }));
    expectNoTenantRequests(1);
    expectNoTenantRequests(createdSpace.id);
    expect(view.onAuthRefresh).not.toHaveBeenCalled();

    view.rerenderScope({ isSuperadmin: false, currentUser: managerUser });
    expect(screen.queryByRole("button", { name: "Create makerspace" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Add staff" })).toBeEnabled();
  });

  it("keeps Users unmounted and sends no requests when makerspace management is denied", async () => {
    const view = renderUsersScope({ canManageMakerspace: false });
    await act(async () => {});
    expect(screen.queryByRole("heading", { name: "Users" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Add staff" })).not.toBeInTheDocument();
    expect(screen.queryByRole("tab", { name: "People" })).not.toBeInTheDocument();
    expect(view.client.getQueryCache().getAll()).toHaveLength(0);
    expect(staffRequest).not.toHaveBeenCalled();
  });
});
