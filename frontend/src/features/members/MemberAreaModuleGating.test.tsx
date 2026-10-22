import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { memberRequest, staffRequest, bootstrapTenant, refreshAccessToken } = vi.hoisted(() => ({
  memberRequest: vi.fn(),
  staffRequest: vi.fn(),
  bootstrapTenant: vi.fn(),
  refreshAccessToken: vi.fn(),
}));

vi.mock("../../lib/api", async () => {
  const actual = await vi.importActual<typeof import("../../lib/api")>("../../lib/api");
  return { ...actual, memberRequest, staffRequest, bootstrapTenant, refreshAccessToken };
});

import { MemberArea } from "./MemberArea";

// `member_accounts` is on throughout: without it the member area is a 404 (see
// MemberAreaAccountsOff.test.tsx), and these pin what survives the OTHER modules.
const CORE = ["public_inventory", "request_workflow", "staff_admin", "scanner", "qr_management", "evidence_uploads", "member_accounts"];

const membership = {
  makerspace: { slug: "forge", name: "Forge" }, membership_status: "active", role: "member",
  waiver_acceptance_required: false, can_refer: true, can_verify: false, verified_at: null, referrals_enabled: true,
};

function routeMember(modules: string[]) {
  bootstrapTenant.mockResolvedValue({
    makerspace: { id: 1, name: "Forge", slug: "forge", membership_policy: "request", geofence_enabled: false },
    modules,
  });
  memberRequest.mockImplementation((path: string) => {
    if (path === "/memberships/me") return Promise.resolve({ memberships: [membership], requests: [] });
    if (path === "/memberships/invitations") return Promise.resolve({ invitations: [] });
    if (path === "/auth/me") return Promise.resolve({ email_verified: true });
    if (path.endsWith("/payments")) return Promise.resolve([{ id: 9, subject_label: "Laser time", status: "paid", checkout_url: null }]);
    if (path === "/member/archived-payments") return Promise.resolve([]);
    if (path.endsWith("/activity")) return Promise.resolve({ currently_checked_in: false, accountability: { waiver_acceptance_required: false }, active_hardware_loans: [], recent_presence_sessions: [] });
    if (path.endsWith("/waiver")) return Promise.resolve({ has_waiver: false });
    if (path.endsWith("/presence-sessions/current")) return Promise.resolve({ active: false, session: null });
    return Promise.resolve({});
  });
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={["/m/forge/member"]}>
        <Routes><Route path="/m/:slug/member" element={<MemberArea />} /></Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  for (const mock of [memberRequest, staffRequest, bootstrapTenant, refreshAccessToken]) mock.mockReset();
  refreshAccessToken.mockResolvedValue(undefined);
  staffRequest.mockResolvedValue([]);
});

describe("member area with only the core modules", () => {
  it("keeps payments, the membership card and invitations but drops membership and events sections", async () => {
    routeMember(CORE);

    expect(await screen.findByText("Laser time")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Membership" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Pending invitations" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Refer someone" })).not.toBeInTheDocument();
    expect(memberRequest).not.toHaveBeenCalledWith("/member/makerspaces/1/activity");
    // Profile, directory and partner events fetch through staffRequest; none may mount.
    expect(staffRequest).not.toHaveBeenCalled();
  });

  it("mounts the membership and events sections when those modules are on", async () => {
    // Never settles: this test only asserts which sections mount and fetch.
    staffRequest.mockReturnValue(new Promise(() => {}));
    routeMember([...CORE, "membership", "events"]);

    expect(await screen.findByRole("heading", { name: "Refer someone" })).toBeInTheDocument();
    await waitFor(() => expect(memberRequest).toHaveBeenCalledWith("/member/makerspaces/1/activity"));
    expect(staffRequest).toHaveBeenCalledWith("/member/makerspaces/1/collaborative-events/");
    expect(staffRequest).toHaveBeenCalledWith("/member/makerspaces/1/profile");
  });
});
