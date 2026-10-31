import type { ComponentProps } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { expect, onTestFinished, vi } from "vitest";

import { ToastProvider } from "../components/ui";
import type { StaffAuthUser } from "../lib/api";
import type { Capability, StaffMembershipRow, StaffRole } from "../features/staff/panels/rolesApi";
import type { Makerspace } from "../features/staff/panels/shared";
import { StaffTabContent } from "../features/staff/StaffTabContent";

function space(id: number, name: string, public_code: string): Makerspace {
  return {
    id, name, slug: name.toLowerCase(), public_code, location: "Kochi",
    telegram_group_chat_id: "", frontend_domain: null, hidden_from_central_directory: false,
    enabled_modules: ["staff_admin", "public_inventory", "reports"],
  };
}

export const alpha = space(1, "Alpha", "ALPH");
export const demo = space(7, "Demo", "DEMO");
export const spaces = [alpha, demo]; // Intentionally NOT active-first.
export const createdSpace = space(11, "Workshop", "WORK");
const timestamp = "2026-10-30T09:00:00Z";

export function rolesFor(makerspace: Makerspace): StaffRole[] {
  return [
    { suffix: 1, label: "Inventory", action: "edit_inventory" },
    { suffix: 2, label: "Auditor", action: "view_audit" },
  ].map(({ suffix, label, action }) => ({
    id: makerspace.id * 100 + suffix, makerspace_id: makerspace.id,
    name: `${makerspace.name} ${label}`, slug: `${makerspace.slug}_${label.toLowerCase()}`,
    granted_actions: [action], legacy_role: null, is_default: false, is_protected: false,
    member_count: 1, created_at: timestamp, updated_at: timestamp,
  }));
}

export function membershipsFor(makerspace: Makerspace): StaffMembershipRow[] {
  return rolesFor(makerspace).map((role, index) => ({
    id: makerspace.id * 1000 + index, makerspace_id: makerspace.id, makerspace_slug: makerspace.slug,
    user: {
      id: makerspace.id * 1000 + index + 100,
      username: `${makerspace.slug}_${index ? "auditor" : "keeper"}`,
      email: `${makerspace.slug}.${index}@example.org`, access_status: "active",
    },
    role: "custom", assigned_role: role, created_at: timestamp,
  }));
}

const capabilities: Capability[] = [
  { value: "edit_inventory", label: "Edit inventory", description: "Manage stock", group: "Inventory", grantable: true, lock_reason: null },
  { value: "view_audit", label: "View audit log", description: "Read audit history", group: "Administration", grantable: true, lock_reason: null },
];

export const managerUser: StaffAuthUser = {
  username: "manager", email_verified: true, role: "space_manager", is_superuser: false, must_change_password: false,
  makerspaces: spaces.map((makerspace) => ({
    id: makerspace.id, slug: makerspace.slug, role: "space_manager", role_id: makerspace.id * 100 + 9,
    role_name: "Space Manager", role_slug: "space_manager", source: "membership",
    actions: ["manage_makerspace", "edit_inventory", "view_audit"], can_configure_machine_types: false,
    is_machine_only: false, can_refer: false, can_verify: false, verified_at: null, referrals_enabled: false, currency: "inr",
  })),
};
export const superadminUser: StaffAuthUser = {
  ...managerUser, username: "root", role: "superadmin", is_superuser: true, makerspaces: [],
};

// Only the external transport is replaced. Unknown paths fail instead of receiving a
// permissive {} response that could conceal an accidental tenant or descendant request.
export async function usersScopeTransport(path: string, options: RequestInit = {}): Promise<unknown> {
  const method = options.method ?? "GET";
  if (method === "POST" && path === "/admin/makerspaces") {
    return { ...createdSpace, superadmin_access_enabled: false };
  }
  if (method === "POST" && path === "/admin/makerspaces/7/memberships") {
    const body = JSON.parse(String(options.body));
    return {
      ...membershipsFor(demo)[0], id: 7999,
      assigned_role: rolesFor(demo).find((role) => role.id === body.role_id),
      user: { id: 8999, access_status: "active", username: body.username, email: body.email },
    };
  }
  for (const makerspace of spaces) {
    const base = `/admin/makerspaces/${makerspace.id}`;
    if (method === "GET" && path === `${base}/memberships`) return membershipsFor(makerspace);
    if (method === "GET" && path === `${base}/roles`) return rolesFor(makerspace);
    if (method === "GET" && path === `${base}/roles/capabilities`) return capabilities;
  }
  throw new Error(`Unexpected Users request: ${method} ${path}`);
}

type Props = ComponentProps<typeof StaffTabContent>;
export function renderUsersScope(overrides: Partial<Props> = {}) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity }, mutations: { retry: false } } });
  const onAuthRefresh = vi.fn();
  let props: Props = {
    activeMakerspace: demo, activeTab: "users", makerspaces: spaces, currentUser: managerUser,
    isSuperadmin: false, guestOnly: false, onAuthRefresh,
    printingOnly: false, canChooseToBuyKind: false, canEditInventory: true, canIssueDirectLoan: false,
    canReturnRequest: false, canReviewRequests: false, canCollectServiceRequests: false, canUseToBuy: false,
    canManageQr: false, canManageMakerspace: true, canManageMachines: false, isMachineOnly: false,
    canConfigureMachineTypes: false, canManageEvents: false, canManageBookings: false,
    canSeeHardware: true, canSeePrinting: false, canViewAudit: true, ...overrides,
  };
  const ui = () => (
    <QueryClientProvider client={client}>
      <MemoryRouter><ToastProvider><StaffTabContent {...props} /></ToastProvider></MemoryRouter>
    </QueryClientProvider>
  );
  const view = render(ui());
  onTestFinished(() => { view.unmount(); client.clear(); });
  return {
    ...view, client, onAuthRefresh,
    // No key or unmount here: production's Users key must perform the tenant reset.
    rerenderScope(changes: Partial<Props>) { props = { ...props, ...changes }; view.rerender(ui()); },
  };
}

export async function openAddStaff() {
  const add = await screen.findByRole("button", { name: "Add staff" });
  await waitFor(() => expect(add).toBeEnabled());
  fireEvent.click(add);
  return screen.findByRole("dialog", { name: "Add staff" });
}

export async function chooseRole(trigger: HTMLElement, name: string) {
  // Exercise the real Radix trigger/listbox, including Dropdown's native change bridge.
  fireEvent.keyDown(trigger, { key: "ArrowDown", code: "ArrowDown" });
  fireEvent.click(await screen.findByRole("option", { name }));
  await waitFor(() => expect(trigger).toHaveTextContent(name));
}

export function fillStaff(dialog: HTMLElement) {
  const fields = within(dialog);
  for (const [label, value] of [
    [/^Username$/, " demo.new "], [/^Email/, "demo.new@example.org"],
    [/^First name/, " New "], [/^Last name/, " Keeper "], [/^Password$/, " secret-Demo-42! "],
  ] as const) {
    fireEvent.change(fields.getByLabelText(label), { target: { value } });
  }
}
