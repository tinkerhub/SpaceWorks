import { accessToken } from "../../test/accessTokens";
import { act, fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import {
  calicut, choose, deferred, json, kochi, leaves, mountStaff, noPanel, panelIs,
  passwordLogin, routeIs, saved, settle, staff, stored, transport, wipeOfflineScopes,
} from "../../test/staffSelectionHarness";
import { expireStaffAuthSession, getAccessToken, getSessionGeneration } from "../../lib/api";

describe("staff interactive login always makes a central global user choose explicitly", () => {
  it.each(["/admin", "/m/calicut/admin/settings"])("password login from %s ignores the saved Kochi hint and opens the central picker", async (path) => {
    transport.restore = false;
    saved(kochi.id);
    mountStaff(path);
    await passwordLogin();
    await screen.findByRole("heading", { name: "Choose a makerspace to operate" });
    await routeIs("/admin");
    expect(stored()).toBeNull();
    expect(leaves).toEqual([]);
    const posted = transport.calls.find(({ path: target }) => target === "/auth/login");
    expect(JSON.parse(String(posted?.init.body))).toMatchObject({ username: "global-admin", surface: "staff" });
    await choose("Calicut");
    await panelIs(calicut.id);
  });

  it("actual LoginPanel social success from SDK and API transports opens the picker instead of a saved or scoped workspace", async () => {
    transport.restore = false;
    saved(kochi.id);
    transport.config = { social_auth: { apple: { enabled: true, service_id: "test-service" } } };
    transport.routes.set("/auth/social/nonce", () => json({ nonce: "nonce" }));
    transport.routes.set("/auth/social/apple", () => json({ access: accessToken("social-login", { surface: "staff", staff_scope: "platform" }), user: transport.user, outcome: "existing" }));
    const signIn = vi.fn().mockResolvedValue({ authorization: { id_token: "sdk-token" } });
    vi.stubGlobal("AppleID", { auth: { init: vi.fn(), signIn } });
    mountStaff("/m/calicut/admin/settings");
    fireEvent.click(await screen.findByRole("button", { name: "Continue with Apple" }));
    await waitFor(() => expect(document.querySelector('script[src*="appleid.auth.js"]')).not.toBeNull());
    fireEvent.load(document.querySelector('script[src*="appleid.auth.js"]')!);
    await screen.findByRole("heading", { name: "Choose a makerspace to operate" });
    await routeIs("/admin");
    noPanel();
    expect(leaves).toEqual([]);
    expect(stored()).toBeNull();
    expect(signIn).toHaveBeenCalledOnce();
    expect(getAccessToken()).toBe(accessToken("social-login", { surface: "staff", staff_scope: "platform" }));
    const completion = transport.calls.find(({ path }) => path === "/auth/social/apple");
    expect(JSON.parse(String(completion?.init.body))).toMatchObject({ id_token: "sdk-token", nonce: "nonce", surface: "staff" });
  });
});

describe("staff auth restoration and logout generations", () => {
  it.each(["refresh", "identity"])("a deferred old restore %s cannot revive its user or selection after logout and a new explicit login", async (stage) => {
    const old = deferred<Response>();
    const path = stage === "refresh" ? "/auth/refresh" : "/auth/me";
    transport.routes.set(path, () => old.promise);
    mountStaff("/m/kochi/admin/settings");
    await waitFor(() => expect(transport.calls.some((call) => call.path === path)).toBe(true));
    act(() => expireStaffAuthSession());
    transport.routes.delete(path);
    transport.user = staff({ username: "new-admin" });
    await passwordLogin();
    await choose("Calicut");
    await panelIs(calicut.id);
    const generation = getSessionGeneration();
    await settle(old, json(stage === "refresh" ? { access: accessToken("old-refresh", { surface: "staff", staff_scope: "platform" }) } : staff({ username: "old-admin" })));
    await routeIs("/m/calicut/admin/dashboard");
    expect(screen.getByTestId("leaf-user")).toHaveTextContent("new-admin");
    expect(getAccessToken()).toBe(accessToken("new-login", { user_id: 2, surface: "staff", staff_scope: "platform" }));
    expect(getSessionGeneration()).toBe(generation);
    expect(stored()).toBe(String(calicut.id));
    expect(leaves.every(({ username }) => username === "new-admin")).toBe(true);
  });

  it.each(["resolve", "reject"])("late logout network and offline cleanup %s cannot clear a newly logged-in user, cache or selection", async (outcome) => {
    const network = deferred<Response>();
    const offline = deferred<void>();
    transport.routes.set("/auth/logout", () => network.promise);
    wipeOfflineScopes.mockReturnValue(offline.promise);
    const { queryClient } = mountStaff("/m/kochi/admin/settings");
    await panelIs(kochi.id);
    const oldGeneration = getSessionGeneration();
    fireEvent.keyDown(screen.getByRole("button", { name: "global-admin, account menu" }), { key: "ArrowDown" });
    fireEvent.click(await screen.findByRole("menuitem", { name: "Sign out" }));
    await screen.findByRole("form", { name: "Staff sign in" });
    noPanel();
    expect(getAccessToken()).toBe("");
    expect(getSessionGeneration()).toBeGreaterThan(oldGeneration);
    expect(stored()).toBeNull();
    expect(wipeOfflineScopes).toHaveBeenCalledWith("staff:");
    transport.user = staff({ username: "new-admin" });
    await passwordLogin();
    await choose("Calicut");
    await panelIs(calicut.id);
    queryClient.setQueryData(["new-session-sentinel"], "survives");
    const newGeneration = getSessionGeneration();
    await act(async () => {
      if (outcome === "reject") {
        network.reject(new TypeError("offline"));
        offline.reject(new Error("offline store unavailable"));
      } else {
        network.resolve(json({}));
        offline.resolve(undefined);
      }
      await Promise.allSettled([network.promise, offline.promise]);
    });
    await panelIs(calicut.id);
    expect(screen.getByTestId("leaf-user")).toHaveTextContent("new-admin");
    expect(queryClient.getQueryData(["new-session-sentinel"])).toBe("survives");
    expect(getSessionGeneration()).toBe(newGeneration);
    expect(getAccessToken()).toBe(accessToken("new-login", { user_id: 2, surface: "staff", staff_scope: "platform" }));
    expect(stored()).toBe(String(calicut.id));
  });
});
