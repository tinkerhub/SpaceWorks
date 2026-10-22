import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { memberRequest, staffRequest, bootstrapTenant, refreshAccessToken, logout } = vi.hoisted(() => ({
  memberRequest: vi.fn(),
  staffRequest: vi.fn(),
  bootstrapTenant: vi.fn(),
  refreshAccessToken: vi.fn(),
  logout: vi.fn(),
}));
vi.mock("../../lib/api", async () => {
  const actual = await vi.importActual<typeof import("../../lib/api")>("../../lib/api");
  return { ...actual, memberRequest, staffRequest, bootstrapTenant, refreshAccessToken, logout };
});

import { ToastProvider } from "../../components/ui";
import { MemberAccountSection } from "./MemberAccountSection";
import { MemberArea } from "./MemberArea";

const membership = {
  makerspace: { slug: "forge", name: "Forge" }, membership_status: "active", role: "member",
  waiver_acceptance_required: false, can_refer: false, can_verify: false, verified_at: null, referrals_enabled: false,
};

function client() {
  return new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
}

function renderArea(mustChange: () => boolean) {
  bootstrapTenant.mockResolvedValue({
    makerspace: { id: 1, name: "Forge", slug: "forge", membership_policy: "request", geofence_enabled: false },
    modules: ["member_accounts"],
  });
  memberRequest.mockImplementation((path: string, init?: RequestInit) => {
    if (path === "/auth/change-password") return Promise.resolve({ detail: "Password updated." });
    if (path === "/memberships/me") return Promise.resolve({ memberships: [membership], requests: [] });
    if (path === "/memberships/invitations") return Promise.resolve({ invitations: [] });
    if (path === "/auth/me") return Promise.resolve({ username: "maker", email_verified: true, must_change_password: mustChange() });
    if (path.endsWith("/waiver")) return Promise.resolve({ has_waiver: false });
    if (path.endsWith("/presence-sessions/current")) return Promise.resolve({ active: false, session: null });
    if (path.endsWith("/payments") || path === "/member/archived-payments") return Promise.resolve([]);
    return Promise.reject(new Error(`Unexpected ${init?.method ?? "GET"} ${path}`));
  });
  return render(
    <QueryClientProvider client={client()}>
      <MemoryRouter initialEntries={["/m/forge/member"]}>
        <Routes><Route path="/m/:slug/member" element={<MemberArea />} /></Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  for (const mock of [memberRequest, staffRequest, bootstrapTenant, refreshAccessToken, logout]) mock.mockReset();
  refreshAccessToken.mockResolvedValue(false);
  staffRequest.mockResolvedValue([]);
});

describe("member must-change-password gate", () => {
  it("replaces the whole member area until the password is rotated", async () => {
    let mustChange = true;
    renderArea(() => mustChange);

    expect(await screen.findByRole("heading", { level: 1, name: "Set a new password" })).toBeInTheDocument();
    expect(screen.getByText("maker")).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Pending invitations" })).not.toBeInTheDocument();
    expect(screen.queryByRole("tab")).not.toBeInTheDocument();

    mustChange = false;
    fireEvent.change(screen.getByLabelText("Current password"), { target: { value: "temporary-pass" } });
    fireEvent.change(screen.getByLabelText("New password"), { target: { value: "my-own-pass-123" } });
    fireEvent.change(screen.getByLabelText("Confirm new password"), { target: { value: "my-own-pass-123" } });
    fireEvent.click(screen.getByRole("button", { name: "Save new password" }));

    expect(await screen.findByRole("heading", { name: "Pending invitations" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Set a new password" })).not.toBeInTheDocument();
    expect(memberRequest).toHaveBeenCalledWith("/auth/change-password", expect.objectContaining({ method: "POST", credentials: "include" }));
  });

  it("shows the account tab with password and sign-out once the flag is clear", async () => {
    renderArea(() => false);

    fireEvent.mouseDown(await screen.findByRole("tab", { name: "Account" }));
    expect(screen.getByRole("heading", { name: "Password" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Sign out" })).toBeInTheDocument();
  });
});

describe("member sign out", () => {
  function renderSection(onSignedOut = vi.fn()) {
    render(
      <QueryClientProvider client={client()}>
        <ToastProvider>
          <MemberAccountSection username="maker" onSignedOut={onSignedOut} />
        </ToastProvider>
      </QueryClientProvider>,
    );
    return onSignedOut;
  }

  it("resets the view and confirms when the server ends the session", async () => {
    logout.mockResolvedValue(undefined);
    const onSignedOut = renderSection();
    fireEvent.click(screen.getByRole("button", { name: "Sign out" }));

    await waitFor(() => expect(onSignedOut).toHaveBeenCalledTimes(1));
    expect(screen.getByRole("status")).toHaveTextContent("Signed out");
  });

  it("still resets the view and says so when the server cannot confirm the logout", async () => {
    logout.mockRejectedValue(new Error("You are signed out on this device, but the server did not confirm it."));
    const onSignedOut = renderSection();
    fireEvent.click(screen.getByRole("button", { name: "Sign out" }));

    await waitFor(() => expect(onSignedOut).toHaveBeenCalledTimes(1));
    expect(screen.getByRole("status")).toHaveTextContent("the server did not confirm it");
  });
});
