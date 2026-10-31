import { act, fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import {
  authority, calicut, choose, client, deferred, json, kochi, leaves, listCalls,
  mountStaff, noPanel, panelIs, passwordLogin, routeIs, settle, staff, transport,
} from "../../test/staffSelectionHarness";
import { expireStaffAuthSession, getSessionGeneration } from "../../lib/api";

describe("staff chooser and machine console share the current session list", () => {
  it("ignores warmed legacy cache and shares one generation-keyed request across the real session and module hooks", async () => {
    const queryClient = client();
    queryClient.setQueryData(["staff", "makerspaces"], [{ ...kochi, enabled_modules: ["payments"] }]);
    transport.spaces = [{ ...kochi, enabled_modules: ["machines"] }];
    mountStaff("/m/kochi/admin/machines", { queryClient });
    await panelIs(kochi.id, "machines");
    expect(authority().payments).toBe(false);
    expect(listCalls()).toHaveLength(1);
    expect(queryClient.getQueryData(["staff", "makerspaces", getSessionGeneration()])).toEqual(transport.spaces);
    expect(queryClient.getQueryData(["staff", "makerspaces"])).toEqual([{ ...kochi, enabled_modules: ["payments"] }]);
  });

  it("prefix invalidation refreshes both route authorization and the machine module consumer", async () => {
    transport.spaces = [{ ...kochi, enabled_modules: ["machines"] }];
    const { queryClient } = mountStaff("/m/kochi/admin/machines");
    await panelIs(kochi.id, "machines");
    expect(authority().payments).toBe(false);
    transport.spaces = [{ ...kochi, name: "Kochi refreshed", enabled_modules: ["machines", "payments"] }];
    await act(async () => { await queryClient.invalidateQueries({ queryKey: ["staff", "makerspaces"] }); });
    await waitFor(() => expect(authority().payments).toBe(true));
    expect(screen.getAllByText("Kochi refreshed").length).toBeGreaterThan(0);
    expect(listCalls()).toHaveLength(2);
    const currentQueries = queryClient.getQueryCache().findAll({ queryKey: ["staff", "makerspaces", getSessionGeneration()], exact: true });
    expect(currentQueries).toHaveLength(1);
    expect(currentQueries[0].getObserversCount()).toBe(2);
  });

  it("a previous-generation deferred list cannot publish into the new login or either list consumer", async () => {
    const oldList = deferred<Response>();
    transport.routes.set("/admin/makerspaces", () => oldList.promise);
    const { queryClient } = mountStaff("/m/kochi/admin/settings");
    await waitFor(() => expect(listCalls()).toHaveLength(1));
    const oldGeneration = getSessionGeneration();
    noPanel();
    act(() => expireStaffAuthSession());
    transport.routes.delete("/admin/makerspaces");
    transport.user = staff({ username: "new-admin" });
    transport.spaces = [{ ...calicut, enabled_modules: ["machines"] }];
    await passwordLogin();
    await choose("Calicut");
    await panelIs(calicut.id);
    const currentGeneration = getSessionGeneration();
    expect(currentGeneration).toBeGreaterThan(oldGeneration);
    await settle(oldList, json([{ ...kochi, enabled_modules: ["payments"] }]));
    expect(queryClient.getQueryData(["staff", "makerspaces", oldGeneration])).toBeUndefined();
    expect(queryClient.getQueryData(["staff", "makerspaces", currentGeneration])).toEqual(transport.spaces);
    expect(authority().payments).toBe(false);
    expect(leaves.every(({ id, username }) => id === calicut.id && username === "new-admin")).toBe(true);
    await routeIs("/m/calicut/admin/dashboard");
  });
});

describe("staff authorization refresh waits for identity and allowed rows", () => {
  it("removes the stale operational panel until identity AND list finish, then denies a withdrawn explicit target", async () => {
    mountStaff("/m/calicut/admin/settings");
    await panelIs(calicut.id);
    const identity = deferred<Response>();
    const list = deferred<Response>();
    transport.routes.set("/auth/me", () => identity.promise);
    transport.routes.set("/admin/makerspaces", () => list.promise);
    leaves.length = 0;
    fireEvent.click(screen.getByRole("button", { name: "Refresh identity and access" }));
    noPanel();
    await waitFor(() => expect(transport.calls.filter(({ path }) => path === "/auth/me")).toHaveLength(2));
    expect(listCalls()).toHaveLength(1);
    await settle(identity, json(staff({ username: "refreshed-admin" })));
    await waitFor(() => expect(listCalls()).toHaveLength(2));
    noPanel();
    expect(leaves).toEqual([]);
    await settle(list, json([kochi]));
    await screen.findByRole("heading", { name: "Makerspace unavailable" });
    await routeIs("/m/calicut/admin/settings");
    noPanel();
    expect(leaves).toEqual([]);
  });

  it.each(["identity", "list"])("authorization %s refresh errors fail closed and Retry rechecks both before restoring a panel", async (phase) => {
    mountStaff("/m/calicut/admin/settings");
    await panelIs(calicut.id);
    const path = phase === "identity" ? "/auth/me" : "/admin/makerspaces";
    transport.routes.set(path, () => json({ detail: "Temporarily unavailable" }, 503));
    fireEvent.click(screen.getByRole("button", { name: "Refresh identity and access" }));
    await screen.findByText(/Could not check makerspace access\. Retry/);
    noPanel();
    const identityCalls = transport.calls.filter(({ path }) => path === "/auth/me").length;
    transport.routes.delete(path);
    transport.user = staff({ username: "verified-again" });
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    await panelIs(calicut.id, "settings");
    expect(screen.getByTestId("leaf-user")).toHaveTextContent("verified-again");
    expect(transport.calls.filter(({ path }) => path === "/auth/me")).toHaveLength(identityCalls + 1);
  });

  it("withdrawn explicit guest choice becomes unavailable without falling back or staying in a loader", async () => {
    const { queryClient } = mountStaff("/guest-admin", { guestOnly: true });
    await choose("Calicut");
    await panelIs(calicut.id);
    transport.spaces = [kochi];
    await act(async () => { await queryClient.invalidateQueries({ queryKey: ["staff", "makerspaces"] }); });
    await screen.findByRole("heading", { name: "Makerspace unavailable" });
    await routeIs("/guest-admin/dashboard");
    noPanel();
    expect(screen.queryByText("Checking makerspace access…")).not.toBeInTheDocument();
    await choose("Kochi");
    await panelIs(kochi.id);
    await routeIs("/guest-admin/dashboard");
  });
});
