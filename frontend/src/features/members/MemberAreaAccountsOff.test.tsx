/**
 * With `member_accounts` off a makerspace has staff accounts only, so its member area is a
 * 404 like every other off-module page: no sign-in, no membership card, no presence, no
 * invitations, and no member API calls. A FAILED bootstrap still falls through to the
 * archived-payments recovery link (MemberAreaArchivedLink.test.tsx pins that half).
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { memberRequest, staffRequest, bootstrapTenant, refreshAccessToken, publicV1Request } = vi.hoisted(() => ({
  memberRequest: vi.fn(),
  staffRequest: vi.fn(),
  bootstrapTenant: vi.fn(),
  refreshAccessToken: vi.fn(),
  publicV1Request: vi.fn(),
}));

vi.mock("../../lib/api", async () => {
  const actual = await vi.importActual<typeof import("../../lib/api")>("../../lib/api");
  return { ...actual, memberRequest, staffRequest, bootstrapTenant, refreshAccessToken, publicV1Request };
});

vi.mock("../../components/NotFoundPage", () => ({
  NotFoundPage: () => <h1>Page not found</h1>,
}));

import { StructuredApiError } from "../../lib/api";
import { MemberArea } from "./MemberArea";

const CHECKIN_SITE = [
  "public_inventory", "request_workflow", "staff_admin", "scanner", "qr_management", "evidence_uploads",
  "printing", "machines", "machine_service",
];

function renderArea(path = "/m/forge/member") {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/m/:slug/member" element={<MemberArea />} />
          <Route path="/member" element={<MemberArea />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  for (const mock of [memberRequest, staffRequest, bootstrapTenant, refreshAccessToken, publicV1Request]) mock.mockReset();
  refreshAccessToken.mockResolvedValue(undefined);
  publicV1Request.mockResolvedValue({});
  memberRequest.mockResolvedValue({ memberships: [], requests: [] });
  staffRequest.mockResolvedValue([]);
});

describe("member area with member accounts off", () => {
  it("is a not-found page and calls no member API", async () => {
    bootstrapTenant.mockResolvedValue({
      makerspace: { id: 1, name: "Forge", slug: "forge", membership_policy: "request" },
      modules: CHECKIN_SITE,
    });
    renderArea();

    expect(await screen.findByRole("heading", { name: "Page not found" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Sign in" })).not.toBeInTheDocument();
    expect(screen.queryByText(/archived payments|closed makerspace/i)).not.toBeInTheDocument();
    expect(memberRequest).not.toHaveBeenCalled();
    expect(staffRequest).not.toHaveBeenCalled();
  });

  it("renders the member area once member accounts are on", async () => {
    bootstrapTenant.mockResolvedValue({
      makerspace: { id: 1, name: "Forge", slug: "forge", membership_policy: "request" },
      modules: [...CHECKIN_SITE, "member_accounts"],
    });
    renderArea();

    await waitFor(() => expect(memberRequest).toHaveBeenCalledWith("/memberships/me"));
    expect(screen.queryByRole("heading", { name: "Page not found" })).not.toBeInTheDocument();
  });

  it("offers no member sign-in on a failed bootstrap when the deployment has none", async () => {
    // Central `/member`: no tenant resolves, so the archived-payments link must survive,
    // but the deployment-wide switch says member accounts do not exist.
    bootstrapTenant.mockRejectedValue(new Error("Makerspace not found."));
    publicV1Request.mockResolvedValue({ member_accounts: { enabled: false } });
    memberRequest.mockRejectedValue(new StructuredApiError(401, { detail: "Authentication required." }));
    renderArea("/member");

    expect(await screen.findByRole("link", { name: "View archived payments" })).toBeInTheDocument();
    await waitFor(() => expect(publicV1Request).toHaveBeenCalledWith("/config"));
    expect(screen.queryByRole("button", { name: "Sign in" })).not.toBeInTheDocument();
  });

  it("shows a signed-in staff account no member surfaces when the deployment has none", async () => {
    bootstrapTenant.mockRejectedValue(new Error("Makerspace not found."));
    publicV1Request.mockResolvedValue({ member_accounts: { enabled: false } });
    memberRequest.mockImplementation((path: string) => {
      if (path === "/memberships/me") return Promise.resolve({ memberships: [], requests: [] });
      if (path === "/memberships/invitations") return Promise.resolve({ invitations: [] });
      if (path === "/auth/me") return Promise.resolve({ username: "ogshan", email_verified: false, must_change_password: false });
      if (path === "/member/archived-payments") return Promise.resolve([]);
      return Promise.resolve({});
    });
    renderArea("/member");

    expect(await screen.findByText("Signed in as ogshan")).toBeInTheDocument();
    await waitFor(() => expect(publicV1Request).toHaveBeenCalledWith("/config"));
    expect(screen.queryByText(/email not verified/i)).not.toBeInTheDocument();
    expect(screen.queryByRole("tab", { name: "Account" })).not.toBeInTheDocument();
    expect(screen.queryByText("Overview")).not.toBeInTheDocument();
  });
});
