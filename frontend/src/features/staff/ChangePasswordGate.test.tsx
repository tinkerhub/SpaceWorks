import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { staffRequest, useStaffSession } = vi.hoisted(() => ({ staffRequest: vi.fn(), useStaffSession: vi.fn() }));
vi.mock("../../lib/api", async () => {
  const actual = await vi.importActual<typeof import("../../lib/api")>("../../lib/api");
  return { ...actual, staffRequest };
});
vi.mock("./useStaffSession", () => ({ useStaffSession }));
vi.mock("./StaffWorkspace", () => ({ StaffWorkspace: () => <p>console-rendered</p> }));

import type { StaffAuthUser } from "../../lib/api";
import { StaffApp } from "./StaffApp";

const user: StaffAuthUser = {
  username: "space-manager",
  email_verified: true,
  role: "staff",
  is_superuser: false,
  must_change_password: true,
  makerspaces: [{ id: 3, name: "Forge", slug: "forge", role: "space_manager", actions: [] } as unknown as StaffAuthUser["makerspaces"][number]],
};

function session(overrides: Record<string, unknown> = {}) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return {
    activeMakerspace: { id: 3, name: "Forge", slug: "forge" },
    chooseMakerspace: vi.fn(),
    login: { error: null, isPending: false, mutate: vi.fn() },
    makerspaces: { data: [{ id: 3, name: "Forge", slug: "forge" }], isLoading: false },
    queryClient,
    recovery: { data: undefined },
    refreshAuthUser: vi.fn(),
    restoring: false,
    routeMakerspace: undefined,
    routeMakerspaceSlug: undefined,
    selected: 3,
    setTab: vi.fn(),
    setUser: vi.fn(),
    signOut: vi.fn().mockResolvedValue(undefined),
    singleTenantLocked: false,
    socialLoginSucceeded: vi.fn(),
    tenant: { bootstrap: null },
    user,
    ...overrides,
  };
}

function renderApp(value: ReturnType<typeof session>) {
  useStaffSession.mockReturnValue(value);
  return render(
    <QueryClientProvider client={value.queryClient}>
      <MemoryRouter>
        <StaffApp />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function fill(current: string, next: string) {
  fireEvent.change(screen.getByLabelText("Current password"), { target: { value: current } });
  fireEvent.change(screen.getByLabelText("New password"), { target: { value: next } });
  fireEvent.change(screen.getByLabelText("Confirm new password"), { target: { value: next } });
}

beforeEach(() => {
  staffRequest.mockReset();
  useStaffSession.mockReset();
});

describe("staff must-change-password gate", () => {
  it("blocks the console until the password is rotated", async () => {
    const value = session();
    renderApp(value);

    expect(screen.getByRole("heading", { level: 1, name: "Set a new password" })).toBeInTheDocument();
    expect(screen.getByText("space-manager")).toBeInTheDocument();
    expect(screen.queryByText("console-rendered")).not.toBeInTheDocument();

    // A rejected change keeps the gate closed.
    staffRequest.mockRejectedValueOnce(new Error("Current password is incorrect."));
    fill("wrong-password", "new-password-123");
    fireEvent.click(screen.getByRole("button", { name: "Save new password" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Current password is incorrect.");
    expect(value.setUser).not.toHaveBeenCalled();

    staffRequest.mockResolvedValueOnce({ detail: "Password updated." });
    fill("old-password", "new-password-123");
    fireEvent.click(screen.getByRole("button", { name: "Save new password" }));

    await waitFor(() => expect(value.setUser).toHaveBeenCalledWith({ ...user, must_change_password: false }));
    expect(staffRequest).toHaveBeenLastCalledWith("/auth/change-password", expect.objectContaining({ method: "POST", credentials: "include" }));
  });

  it("opens the console once the flag is cleared", () => {
    renderApp(session({ user: { ...user, must_change_password: false } }));
    expect(screen.getByText("console-rendered")).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Set a new password" })).not.toBeInTheDocument();
  });

  it("can sign out from the gate without changing the password", () => {
    const value = session();
    renderApp(value);
    fireEvent.click(screen.getByRole("button", { name: "Sign out" }));
    expect(value.signOut).toHaveBeenCalledTimes(1);
    expect(staffRequest).not.toHaveBeenCalled();
  });
});
