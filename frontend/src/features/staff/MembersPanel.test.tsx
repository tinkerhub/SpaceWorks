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

function renderPanel(actorActions: string[] = ["manage_makerspace"], isSuperadmin = false) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MembersPanel makerspaceId={3} membershipEnabled={false} actorActions={actorActions} isSuperadmin={isSuperadmin} />
    </QueryClientProvider>,
  );
}

const roles = [
  { id: 1, name: "Member", granted_actions: [] },
  { id: 2, name: "Space Manager", granted_actions: ["manage_makerspace", "issue_hardware"] },
  { id: 3, name: "Printing", granted_actions: ["manage_printing"] },
];

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

describe("MembersPanel waiver controls", () => {
  beforeEach(() => {
    staffRequest.mockReset();
    staffRequest.mockImplementation((url: string) => {
      if (url.startsWith("/admin/memberships?")) return Promise.resolve(roster);
      if (url.includes("presence-sessions")) return Promise.resolve([]);
      if (url.endsWith("/roles")) return Promise.resolve(roles);
      return Promise.resolve({});
    });
  });

  it("keeps core waiver controls available when community membership is disabled", async () => {
    renderPanel();

    expect(await screen.findByText("Record witnessed acceptance")).toBeInTheDocument();
    expect(screen.queryByText("Can refer")).not.toBeInTheDocument();

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
    staffRequest.mockImplementation((url: string) => {
      if (url.startsWith("/admin/memberships?")) return Promise.resolve({ ...roster, count: 2, results: [roster.results[0], managerRow] });
      if (url.includes("presence-sessions")) return Promise.resolve([]);
      if (url.endsWith("/roles")) return Promise.resolve(roles);
      return Promise.resolve({});
    });
    renderPanel(["manage_makerspace", "issue_hardware"]);

    expect(await listedOptions("Role for Walk In")).toEqual(["Member"]);
    expect(screen.queryByRole("combobox", { name: "Role for Boss" })).not.toBeInTheDocument();
    expect(screen.getByText("Managed by a platform admin")).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: /^Revoke/ })).toHaveLength(1);
    openTab("Invitations");
    expect(await listedOptions("Invite role")).toEqual(["Member"]);
  });
});
