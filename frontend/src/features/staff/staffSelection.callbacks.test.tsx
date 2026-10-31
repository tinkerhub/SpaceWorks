import { accessToken } from "../../test/accessTokens";
import { QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import {
  calicut, client, deferred, json, kochi, leaves, mountStaff, panelIs, saved,
  settle, staff, stored, transport,
} from "../../test/staffSelectionHarness";
import { getAccessToken, getSessionGeneration } from "../../lib/api";
import { TenantProvider } from "../../lib/tenant";
import { useStaffSession } from "./useStaffSession";

function hookSession() {
  const queryClient = client();
  const wrapper = ({ children }: { children: ReactNode }) => <QueryClientProvider client={queryClient}>
    <TenantProvider><MemoryRouter initialEntries={["/admin"]}>{children}</MemoryRouter></TenantProvider>
  </QueryClientProvider>;
  return { ...renderHook(() => useStaffSession(false), { wrapper }), queryClient };
}

describe("staff chooser invalid and expired callbacks", () => {
  it("the real session hook rejects an unknown choice without selecting or persisting that id", async () => {
    saved(kochi.id);
    const { result } = hookSession();
    await waitFor(() => expect(result.current.selection.kind).toBe("picker"));
    const before = stored();
    act(() => result.current.chooseMakerspace(999999));
    expect(result.current.selection.kind).toBe("picker");
    expect(result.current.selected).toBeNull();
    expect(stored()).toBe(before);
    expect(stored()).not.toBe("999999");
  });

  it("a retained old-generation chooser callback cannot change a new login selection", async () => {
    const { result } = hookSession();
    await waitFor(() => expect(result.current.selection.kind).toBe("picker"));
    const oldChoose = result.current.chooseMakerspace;
    await act(async () => { await result.current.signOut(); });
    act(() => result.current.login.mutate({ username: "new-admin", password: "password" }));
    await waitFor(() => expect(result.current.user).not.toBeNull());
    await waitFor(() => expect(result.current.makerspaces.isSuccess).toBe(true));
    act(() => result.current.chooseMakerspace(calicut.id));
    await waitFor(() => expect(result.current.selected).toBe(calicut.id));
    act(() => oldChoose(kochi.id));
    expect(result.current.selected).toBe(calicut.id);
    expect(stored()).toBe(String(calicut.id));
  });

  it("late password login completion and retained social/choice callbacks after unmount cannot hydrate cache or token", async () => {
    transport.restore = false;
    const login = deferred<Response>();
    transport.routes.set("/auth/login", () => login.promise);
    const { result, unmount, queryClient } = hookSession();
    await waitFor(() => expect(result.current.restoring).toBe(false));
    const oldSocial = result.current.socialLoginSucceeded;
    const oldChoose = result.current.chooseMakerspace;
    act(() => result.current.login.mutate({ username: "old-admin", password: "password" }));
    await waitFor(() => expect(transport.calls.some(({ path }) => path === "/auth/login")).toBe(true));
    const generation = getSessionGeneration();
    const token = getAccessToken();
    unmount();
    await settle(login, json({ access: accessToken("late-login", { surface: "staff", staff_scope: "platform" }), user: staff(), surface: "staff" }));
    act(() => {
      oldSocial({ access: accessToken("late-social", { surface: "staff", staff_scope: "platform" }), user: { ...staff() }, outcome: "existing" });
      oldChoose(kochi.id);
    });
    expect(getSessionGeneration()).toBe(generation);
    expect(getAccessToken()).toBe(token);
    expect(queryClient.getQueryData(["staff", "me"])).toBeUndefined();
    expect(stored()).toBeNull();
  });

  it("a retained authorized picker callback after unmount cannot clear the persisted current selection", async () => {
    const { result, unmount } = hookSession();
    await waitFor(() => expect(result.current.selection.kind).toBe("picker"));
    act(() => result.current.chooseMakerspace(calicut.id));
    await waitFor(() => expect(result.current.selected).toBe(calicut.id));
    const oldChoose = result.current.chooseMakerspace;
    expect(stored()).toBe(String(calicut.id));
    unmount();
    act(() => oldChoose(null));
    expect(stored()).toBe(String(calicut.id));
  });

  it("StrictMode restore ignores the disposed effect and renders only the exact explicit space", async () => {
    saved(kochi.id);
    mountStaff("/m/calicut/admin/settings", { strict: true });
    await panelIs(calicut.id, "settings");
    expect(leaves.length).toBeGreaterThan(0);
    expect(leaves.every(({ id }) => id === calicut.id)).toBe(true);
    expect(screen.queryByText("Restoring session…")).not.toBeInTheDocument();
  });
});
