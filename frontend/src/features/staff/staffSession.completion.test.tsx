import { act, fireEvent, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { getAccessToken, getSessionGeneration, setAccessToken } from "../../lib/apiSession";
import { LogoutIncompleteError } from "../../lib/apiSession";
import { accessToken } from "../../test/accessTokens";
import { enter } from "../../test/authOwnership";
import {
  calicut, choose, deferred, json, kochi, mountStaff, noPanel, panelIs,
  passwordLogin, routeIs, settle, staff, stored, transport, wipeOfflineScopes,
} from "../../test/staffSelectionHarness";
import { staffMeKey } from "./paymentsApi";

const restored = () => accessToken("completion-staff", { surface: "staff", staff_scope: "platform" });
const signedIn = () => accessToken("completion-new-staff", { surface: "staff", staff_scope: "platform" });
const warning = new LogoutIncompleteError().message;
beforeEach(() => {
  setAccessToken(restored());
  transport.routes.set("/auth/refresh", () => json({ access: restored() }));
  transport.routes.set("/auth/login", () => json({ access: signedIn(), user: transport.user, surface: "staff" }));
});

async function signOut() {
  fireEvent.keyDown(screen.getByRole("button", { name: "global-admin, account menu" }), { key: "ArrowDown" });
  fireEvent.click(await screen.findByRole("menuitem", { name: "Sign out" }));
  await screen.findByRole("form", { name: "Staff sign in" });
}

describe("staff logout completion notices", () => {
  it("shows a current failed logout in the real LoginPanel after local identity and token cleanup", async () => {
    const network = deferred<Response>();
    transport.routes.set("/auth/logout", () => network.promise);
    const { queryClient } = mountStaff("/m/kochi/admin/settings");
    await panelIs(kochi.id);
    const epoch = getSessionGeneration();
    await signOut();
    expect(getAccessToken()).toBe("");
    expect(getSessionGeneration()).toBe(epoch + 1);
    expect(queryClient.getQueryData(staffMeKey)).toBeUndefined();
    expect(stored()).toBeNull();
    noPanel();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(wipeOfflineScopes).toHaveBeenCalledWith("staff:");
    await act(async () => { network.reject(new TypeError("offline")); await Promise.allSettled([network.promise]); });
    expect(await screen.findByRole("alert")).toHaveTextContent(warning);
    expect(screen.getByRole("form", { name: "Staff sign in" })).toBeInTheDocument();
    expect(getAccessToken()).toBe("");
    expect(queryClient.getQueryData(staffMeKey)).toBeUndefined();
    noPanel();
  });

  it("a new password submit invalidates an old logout warning in the same act before any new token is installed", async () => {
    const network = deferred<Response>();
    const login = deferred<Response>();
    transport.routes.set("/auth/logout", () => network.promise);
    transport.routes.set("/auth/login", () => login.promise);
    const { queryClient } = mountStaff("/m/kochi/admin/settings");
    await panelIs(kochi.id);
    await signOut();
    const signedOutEpoch = getSessionGeneration();
    enter("Username", "new-admin"); enter("Password", "new-password");
    await act(async () => {
      fireEvent.submit(screen.getByRole("form", { name: "Staff sign in" }));
      network.reject(new TypeError("old logout failed"));
      await Promise.allSettled([network.promise]);
    });
    await waitFor(() => expect(transport.calls.filter(({ path }) => path === "/auth/login")).toHaveLength(1));
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Signing in…" })).toBeDisabled();
    expect(screen.getByLabelText("Password")).toHaveValue("new-password");
    expect(getAccessToken()).toBe("");
    expect(getSessionGeneration()).toBe(signedOutEpoch);
    expect(queryClient.getQueryData(staffMeKey)).toBeUndefined();
    noPanel();
    await settle(login, json({ access: signedIn(), surface: "staff", user: staff({ username: "new-admin" }) }));
    await choose("Calicut");
    await panelIs(calicut.id);
    expect(screen.getByTestId("leaf-user")).toHaveTextContent("new-admin");
    expect(screen.queryByText(warning)).not.toBeInTheDocument();
  });

  it("a late failed logout cannot publish a warning or clear a completed new login's cache and selection", async () => {
    const network = deferred<Response>();
    transport.routes.set("/auth/logout", () => network.promise);
    const { queryClient } = mountStaff("/m/kochi/admin/settings");
    await panelIs(kochi.id);
    await signOut();
    transport.user = staff({ username: "new-admin" });
    await passwordLogin();
    await choose("Calicut");
    await panelIs(calicut.id);
    queryClient.setQueryData(["new-private-cache"], { owner: "new-admin" });
    const clear = vi.spyOn(queryClient, "clear");
    const epoch = getSessionGeneration();
    await act(async () => { network.reject(new TypeError("offline")); await Promise.allSettled([network.promise]); });
    expect(screen.queryByText(warning)).not.toBeInTheDocument();
    expect(screen.queryByRole("form", { name: "Staff sign in" })).not.toBeInTheDocument();
    expect(queryClient.getQueryData(["new-private-cache"])).toEqual({ owner: "new-admin" });
    expect(queryClient.getQueryData(staffMeKey)).toMatchObject({ username: "new-admin" });
    expect(clear).not.toHaveBeenCalled();
    expect(getAccessToken()).toBe(signedIn());
    expect(getSessionGeneration()).toBe(epoch);
    expect(stored()).toBe(String(calicut.id));
    await routeIs("/m/calicut/admin/dashboard");
    expect(screen.getByTestId("leaf-user")).toHaveTextContent("new-admin");
    clear.mockRestore();
  });
});
