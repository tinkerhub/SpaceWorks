import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { MembersPanel } from "./MembersPanel";

const { staffRequest } = vi.hoisted(() => ({ staffRequest: vi.fn() }));
vi.mock("../../lib/api", async () => {
  const actual = await vi.importActual<typeof import("../../lib/api")>("../../lib/api");
  return { ...actual, staffRequest };
});

const roster = {
  count: 1,
  next: null,
  previous: null,
  results: [{
    id: 7,
    status: "active",
    user: { id: 9, username: "walkin", email: "", display_name: "Walk In" },
    assigned_role: { id: 1, name: "Member", slug: "member" },
    can_refer: false,
    can_verify: false,
    verified_at: null,
    activated_at: null,
    revoked_at: null,
    revocation_reason: "",
    waiver_accepted_at: null,
    waiver_version_accepted: null,
    waiver_current: false,
    waiver_required: true,
    payment: null,
  }],
};

function renderPanel(actorActions: string[] = ["manage_makerspace"], isSuperadmin = false, currentUsername = "me") {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MembersPanel makerspaceId={3} actorActions={actorActions} isSuperadmin={isSuperadmin} currentUsername={currentUsername} />
    </QueryClientProvider>,
  );
}

const roles = [
  { id: 1, name: "Member", granted_actions: [], legacy_role: null },
  { id: 2, name: "Space Manager", granted_actions: ["manage_makerspace", "issue_hardware"], legacy_role: "space_manager" },
  { id: 3, name: "Printing", granted_actions: ["manage_printing"], legacy_role: null },
  { id: 4, name: "Inventory Manager", granted_actions: ["edit_inventory"], legacy_role: "inventory_manager" },
];

// Legacy memberships carry no assigned role; the staff list holds their legacy enum.
const legacyRow = (id: number, username: string) => ({ ...roster.results[0], id, user: { id: id + 100, username, email: "", display_name: "" }, assigned_role: null, waiver_required: false });
const staffList = [{ id: 20, role: "space_manager" }, { id: 21, role: "inventory_manager" }];

function mockApi(rows: unknown[], requests: unknown[] = []) {
  staffRequest.mockImplementation((url: string) => {
    if (url.startsWith("/admin/memberships?")) return Promise.resolve({ ...roster, count: rows.length, results: rows });
    if (url.startsWith("/admin/membership-requests?")) return Promise.resolve({ count: requests.length, next: null, previous: null, results: requests });
    if (url.includes("presence-sessions")) return Promise.resolve([]);
    if (url.endsWith("/roles")) return Promise.resolve(roles);
    if (url.endsWith("/memberships")) return Promise.resolve(staffList);
    return Promise.resolve({});
  });
}

// Radix tabs activate on mouse down; inactive panels are unmounted.
function openTab(name: string) {
  fireEvent.mouseDown(screen.getByRole("tab", { name }), { button: 0 });
}

// The listbox renders its options only while open; read them, then close it again.
async function listedOptions(name: string) {
  fireEvent.click(await screen.findByRole("combobox", { name }));
  const names = screen.getAllByRole("option").map((option) => option.textContent);
  fireEvent.keyDown(screen.getByRole("listbox"), { key: "Escape" });
  await waitFor(() => expect(screen.queryByRole("listbox")).not.toBeInTheDocument());
  return names;
}

describe("MembersPanel", () => {
  beforeEach(() => {
    staffRequest.mockReset();
    mockApi(roster.results);
  });

  it("offers waiver, referral and verification controls (the tab renders only with membership on)", async () => {
    renderPanel();

    expect(await screen.findByText("Record witnessed acceptance")).toBeInTheDocument();
    expect(screen.getByText("Can refer")).toBeInTheDocument();

    fireEvent.click(screen.getByText("Record witnessed acceptance"));
    await waitFor(() => expect(staffRequest).toHaveBeenCalledWith(
      "/admin/memberships/7/waiver/witness",
      { method: "POST", body: JSON.stringify({}) },
    ));

    openTab("Waiver");
    expect(screen.getByRole("button", { name: "Publish waiver" })).toBeInTheDocument();
  });

  it("offers only assignable roles and hides Revoke on a manage_makerspace row for a Space Manager", async () => {
    const managerRow = { ...roster.results[0], id: 8, user: { id: 10, username: "boss", email: "", display_name: "Boss" }, assigned_role: { id: 2, name: "Space Manager", slug: "space-manager" } };
    mockApi([roster.results[0], managerRow]);
    renderPanel(["manage_makerspace", "issue_hardware"]);

    expect(await listedOptions("Role for Walk In")).toEqual(["Member"]);
    expect(screen.queryByRole("combobox", { name: "Role for Boss" })).not.toBeInTheDocument();
    expect(screen.getByText("Managed by a platform admin")).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: /^Revoke/ })).toHaveLength(1);
    openTab("Requests");
    expect(await listedOptions("Invite role")).toEqual(["Member"]);
  });

  it("shows the actor's own row read-only, with no Revoke", async () => {
    mockApi([legacyRow(20, "me"), legacyRow(21, "stock")]);
    renderPanel(["manage_makerspace", "edit_inventory"]);

    expect(await screen.findByText("You")).toBeInTheDocument();
    expect(screen.getByText("Space Manager")).toBeInTheDocument();
    expect(screen.queryByRole("combobox", { name: "Role for me" })).not.toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: /^Revoke/ })).toHaveLength(1);
  });

  it("resolves a legacy row's role instead of rendering an empty select", async () => {
    mockApi([legacyRow(20, "boss"), legacyRow(21, "stock")]);
    renderPanel(["manage_makerspace", "edit_inventory"]);

    // The legacy space manager is read-only for a non-superadmin...
    expect(await screen.findByText("Managed by a platform admin")).toBeInTheDocument();
    expect(screen.queryByRole("combobox", { name: "Role for boss" })).not.toBeInTheDocument();
    // ...and the legacy inventory manager's select shows the role it holds.
    expect(await screen.findByRole("combobox", { name: "Role for stock" })).toHaveTextContent("Inventory Manager");
  });

  it("approves a claimed staff invitation with the role it was sent with", async () => {
    const claimed = { id: 40, kind: "invite", state: "invited", invite_email: "new@x.io", user: { id: 50, username: "newbie" }, assigned_role: { id: 4, name: "Inventory Manager" }, created_at: "2026-10-01T00:00:00Z" };
    const unclaimed = { ...claimed, id: 41, invite_email: "later@x.io", user: null };
    mockApi(roster.results, [claimed, unclaimed]);
    renderPanel(["manage_makerspace", "edit_inventory"]);

    openTab("Requests");
    const approve = await screen.findAllByRole("button", { name: "Approve" });
    expect(approve).toHaveLength(1);
    expect(screen.getAllByRole("button", { name: "Revoke" })).toHaveLength(2);
    fireEvent.click(approve[0]);
    await waitFor(() => expect(staffRequest).toHaveBeenCalledWith(
      "/admin/membership-requests/40/approve",
      { method: "POST", body: JSON.stringify({ role_id: 4 }) },
    ));
  });
});
