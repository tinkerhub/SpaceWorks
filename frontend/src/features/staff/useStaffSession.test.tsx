import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

const { logout, refreshAccessToken, staffRequest, wipeOfflineScopes } = vi.hoisted(() => ({
  logout: vi.fn(),
  refreshAccessToken: vi.fn(),
  staffRequest: vi.fn(),
  wipeOfflineScopes: vi.fn(),
}));
vi.mock("../../lib/api", async () => {
  const actual = await vi.importActual<typeof import("../../lib/api")>("../../lib/api");
  return { ...actual, logout, refreshAccessToken, staffRequest };
});
vi.mock("../../lib/tenant", () => ({
  useTenant: () => ({ mode: "central", makerspaceId: null, bootstrap: null }),
}));
vi.mock("./eventCheckInOfflineStore", () => ({ wipeOfflineScopes }));

import type { StaffAuthUser } from "../../lib/api";
import { useStaffSession } from "./useStaffSession";

const user: StaffAuthUser = {
  username: "space-manager",
  email_verified: true,
  role: "staff",
  is_superuser: false,
  must_change_password: false,
  makerspaces: [],
};

describe("useStaffSession signOut", () => {
  it("clears the local session even when the logout request fails", async () => {
    refreshAccessToken.mockResolvedValue(false);
    staffRequest.mockResolvedValue([]);
    wipeOfflineScopes.mockResolvedValue(undefined);
    logout.mockRejectedValue(new TypeError("Failed to fetch"));
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={client}>
        <MemoryRouter initialEntries={["/admin"]}>{children}</MemoryRouter>
      </QueryClientProvider>
    );
    const { result } = renderHook(() => useStaffSession(false), { wrapper });
    await waitFor(() => expect(result.current.restoring).toBe(false));

    act(() => result.current.setUser(user));
    expect(result.current.user).toEqual(user);

    await act(() => result.current.signOut());

    expect(logout).toHaveBeenCalledTimes(1);
    expect(wipeOfflineScopes).toHaveBeenCalledWith("staff:");
    expect(result.current.user).toBeNull();
    expect(result.current.selected).toBeNull();
  });
});
